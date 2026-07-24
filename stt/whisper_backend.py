"""
faster-whisper STT backend -- open-source, self-hosted, free. The only STT backend;
exposes transcribe_one_speaker() and transcribe_mixed() for process_meeting().

Language strategy for trilingual (ru/kk/en) meetings:
  * WHISPER_MODEL (default large-v3) is the base multilingual model -- strong ru/en,
    decent kk. It handles code-switching within one recording best.
  * If WHISPER_KK_MODEL is set (e.g. abilmansplus/whisper-turbo-ksc2, MIT-licensed),
    audio detected as Kazakh is re-transcribed with that specialist model. Kazakh-only
    fine-tunes can regress on ru/en, so we route to it ONLY for kk, never as the base.

Diarization: faster-whisper does not diarize. The per-speaker WAV path needs none
(one stream == one speaker). The mixed path uses WhisperX + pyannote when HF_TOKEN
is set (accept the pyannote/speaker-diarization terms on HuggingFace first); without
a token it falls back to a single "Unknown" speaker with a warning.
"""

from shared.config import settings
from shared.schema import Segment, Person


_models = {}  # name -> WhisperModel, loaded once per process


def _resolve_device():
    device = settings.whisper_device.lower()
    compute = settings.whisper_compute_type.lower()
    if device == "auto":
        import ctranslate2  # installed as a faster-whisper dependency
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def _load(name):
    if name not in _models:
        from faster_whisper import WhisperModel
        device, compute = _resolve_device()
        print(f"[whisper] loading '{name}' on {device} ({compute}) ...")
        _models[name] = WhisperModel(name, device=device, compute_type=compute)
    return _models[name]


def _whisper_lang(bcp47):
    """BCP-47 tag ('ru-RU') -> Whisper 2-letter code ('ru'); 'auto' -> None (detect)."""
    if not bcp47 or bcp47.lower() == "auto":
        return None
    return bcp47.split("-")[0].lower()


def _transcribe(wav_path):
    """Run faster-whisper with kk routing. Yields (start_s, end_s, text) tuples."""
    forced = _whisper_lang(settings.stt_language)
    base = _load(settings.whisper_model)

    seg_iter, info = base.transcribe(
        str(wav_path), language=forced, word_timestamps=True, vad_filter=True)

    # Route Kazakh to the specialist model when one is configured. When language is
    # forced we already know it; when auto, info.language is the detected code.
    detected = forced or info.language
    if settings.whisper_kk_model and detected == "kk":
        kk = _load(settings.whisper_kk_model)
        print(f"[whisper] {wav_path.name}: kk detected -> {settings.whisper_kk_model}")
        seg_iter, info = kk.transcribe(
            str(wav_path), language="kk", word_timestamps=True, vad_filter=True)

    for s in seg_iter:
        text = (s.text or "").strip()
        if text:
            yield s.start, s.end, text


def _segment(start_s, end_s, text, name, person_id) -> Segment:
    return Segment(
        speaker=Person(name=name, id=person_id),
        startMs=int(round(start_s * 1000)),
        endMs=int(round(end_s * 1000)),
        text=text,
    )


def transcribe_one_speaker(wav_path, name, person_id):
    """Transcribe a single-speaker WAV; every segment is attributed to that speaker."""
    return [_segment(a, b, t, name, person_id) for a, b, t in _transcribe(wav_path)]


def transcribe_mixed(wav_path):
    """Transcribe a mixed WAV. With HF_TOKEN set, WhisperX + pyannote diarizes and
    each segment gets a speaker label (SPEAKER_00, ...); otherwise every segment is
    attributed to 'Unknown'."""
    if not settings.hf_token:
        print("[whisper] WARNING: mixed audio, no HF_TOKEN -> no diarization, speakers 'Unknown'")
        return [_segment(a, b, t, "Unknown", None) for a, b, t in _transcribe(wav_path)]
    return _transcribe_diarized(wav_path)


def _transcribe_diarized(wav_path):
    """WhisperX pipeline: transcribe -> word-align -> pyannote diarize -> assign speakers.
    Uses WHISPER_MODEL as the base (kk routing does not apply to the mixed path)."""
    import whisperx
    device, compute = _resolve_device()
    lang = _whisper_lang(settings.stt_language)  # may be None (auto-detect)

    model = whisperx.load_model(settings.whisper_model, device, compute_type=compute, language=lang)
    audio = whisperx.load_audio(str(wav_path))
    result = model.transcribe(audio, language=lang)
    lang_code = result.get("language") or lang or "en"

    # Word-level alignment sharpens timestamps and is what lets speakers be assigned
    # per word. Alignment models are per-language and may not exist (e.g. kk) -> skip.
    try:
        model_a, metadata = whisperx.load_align_model(language_code=lang_code, device=device)
        result = whisperx.align(result["segments"], model_a, metadata, audio, device,
                                return_char_alignments=False)
    except Exception as e:
        print(f"[whisper] alignment skipped for '{lang_code}' ({e}); using segment-level times")

    try:
        from whisperx.diarize import DiarizationPipeline
    except ImportError:  # older whisperx exposes it at top level
        from whisperx import DiarizationPipeline
    diarize = DiarizationPipeline(use_auth_token=settings.hf_token, device=device)
    result = whisperx.assign_word_speakers(diarize(audio), result)

    segments = []
    for s in result.get("segments", []):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        speaker = s.get("speaker") or "Unknown"
        segments.append(_segment(s.get("start") or 0.0, s.get("end") or 0.0, text, speaker, None))
    return segments
