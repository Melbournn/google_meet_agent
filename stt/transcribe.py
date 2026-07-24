"""
STT fallback (primary transcript comes from Google at capture). Reads a meeting's
WAV(s) and fills segments[] via store, using the faster-whisper backend
(stt/whisper_backend.py). Open-source, self-hosted, free -- no Azure.

Usage:
    python -m stt.transcribe <meetingId>
    python -m stt.transcribe --all
"""

import sys
import time
from shared.config import settings
from shared import store
from stt import whisper_backend


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
            segments.extend(whisper_backend.transcribe_one_speaker(wav, name, pid))
    elif mixed.exists() and mixed.stat().st_size > 44:  # 44 = empty WAV header
        print(f"[{meeting_id}] mixed mode: {mixed.name} ({mixed.stat().st_size} bytes)")
        segments = whisper_backend.transcribe_mixed(mixed)
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
