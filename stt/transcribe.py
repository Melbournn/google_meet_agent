"""
the STT fallback (primary transcript comes from Google at capture), reads a WAV, fills segments[] via store.
"""

import sys
import threading
import time
from shared.config import settings
from shared.schema import Segment, Person
from shared import store


TICKS_PER_MS = 10_000  # Azure SDK offsets/durations are in 100-ns ticks


def _speech_config():
    import azure.cognitiveservices.speech as speechsdk
    key = settings.require("speech_key")
    region = settings.require("speech_region")
    cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    # Request word-level timing so segment boundaries are meaningful.
    cfg.request_word_level_timestamps()
    lang = settings.stt_language
    if lang.lower() != "auto":
        cfg.speech_recognition_language = lang
    return cfg


def _auto_detect_config():
    import azure.cognitiveservices.speech as speechsdk
    if settings.stt_language.lower() != "auto":
        return None
    cands = [c.strip() for c in settings.stt_language_candidates.split(",") if c.strip()]
    return speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=cands)


def _run_continuous(recognizer, collect):
    """Drive a recognizer/transcriber to completion, invoking collect(evt)."""
    done = threading.Event()

    def _stop(_evt):
        done.set()

    # ConversationTranscriber raises .transcribed; SpeechRecognizer raises .recognized.
    if hasattr(recognizer, "transcribed"):
        recognizer.transcribed.connect(collect)
        recognizer.session_stopped.connect(_stop)
        recognizer.canceled.connect(_stop)
        recognizer.start_transcribing_async().get()
        done.wait()
        recognizer.stop_transcribing_async().get()
    else:
        recognizer.recognized.connect(collect)
        recognizer.session_stopped.connect(_stop)
        recognizer.canceled.connect(_stop)
        recognizer.start_continuous_recognition_async().get()
        done.wait()
        recognizer.stop_continuous_recognition_async().get()


def _segment(text, offset_ticks, duration_ticks, name, person_id) -> Segment:
    return Segment(
        speaker = Person(name = name, id = person_id),
        startMs = int(offset_ticks // TICKS_PER_MS),
        endMs = int((offset_ticks + duration_ticks) // TICKS_PER_MS),
        text = text,
    )


def transcribe_mixed(wav_path):
    """Diarize + transcribe a single mixed WAV. Speakers are generic ids."""
    import azure.cognitiveservices.speech as speechsdk
    cfg = _speech_config()
    audio = speechsdk.audio.AudioConfig(filename=str(wav_path))
    auto = _auto_detect_config()
    if auto is not None:
        transcriber = speechsdk.transcription.ConversationTranscriber(
            speech_config=cfg, audio_config=audio, auto_detect_source_language_config=auto)
    else:
        transcriber = speechsdk.transcription.ConversationTranscriber(
            speech_config=cfg, audio_config=audio)

    segments = []

    def collect(evt):
        r = evt.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            speaker = getattr(r, "speaker_id", None) or "Unknown"
            segments.append(_segment(r.text, r.offset, r.duration, speaker, None))

    _run_continuous(transcriber, collect)
    return segments


def transcribe_one_speaker(wav_path, name, person_id):
    """Transcribe a single-speaker WAV; every segment is attributed to that speaker."""
    import azure.cognitiveservices.speech as speechsdk
    cfg = _speech_config()
    audio = speechsdk.audio.AudioConfig(filename=str(wav_path))
    auto = _auto_detect_config()
    if auto is not None:
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=cfg, audio_config=audio, auto_detect_source_language_config=auto)
    else:
        recognizer = speechsdk.SpeechRecognizer(speech_config=cfg, audio_config=audio)

    segments = []

    def collect(evt):
        r = evt.result
        if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
            segments.append(_segment(r.text, r.offset, r.duration, name, person_id))

    _run_continuous(recognizer, collect)
    return segments


def process_meeting(meeting_id:str) -> None:
    record = store.load_record(meeting_id)
    if record.segments:
        print(f"[{meeting_id}] already has segments; skipping"); return
    participants = {p.id: p.name for p in record.participants if p.id}

    # Per-speaker WAVs = any *.wav whose stem is not the callId (the mixed file).
    meeting_dir = store.meeting_dir(meeting_id)
    per_speaker = [w for w in meeting_dir.glob("*.wav") if w.stem != meeting_id]
    mixed = meeting_dir / f"{meeting_id}.wav"

    segments = []
    if per_speaker:
        print(f"[{meeting_id}] per-speaker mode: {len(per_speaker)} stream(s)")
        for wav in per_speaker:
            pid = wav.stem
            name = participants.get(pid, pid)
            print(f"  - {wav.name} -> {name}")
            segments.extend(transcribe_one_speaker(wav, name, pid))
    elif mixed.exists() and mixed.stat().st_size > 44:  # 44 = empty WAV header
        print(f"[{meeting_id}] mixed mode (diarized): {mixed.name} ({mixed.stat().st_size} bytes)")
        segments = transcribe_mixed(mixed)
    else:
        print(f"[{meeting_id}] SKIP: no audio (mixed WAV is empty/header-only)")
        return

    segments.sort(key=lambda s: s.startMs)
    record.segments = segments
    if settings.stt_language.lower() != "auto":
        record.language = settings.stt_language

    store.save_record(record)
    print(f"[{meeting_id}] wrote {len(segments)} segment(s)")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)

    if args[0] == "--all":
        for meeting_id in store.list_meetings():
            process_meeting(meeting_id)
    else:
        process_meeting(args[0])


if __name__ == "__main__":
    start = time.time()
    main()
    print(f"done in {time.time() - start:.1f}s")
