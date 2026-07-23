"""
Dev smoketest for stt/transcribe.py orchestration — no Azure, no audio.

Verifies the two non-transcribing paths of process_meeting against a throwaway
recordings root:
  1. A record that ALREADY has segments is skipped (prefer-Google-transcript).
  2. A record with NO segments and NO audio is skipped with a clear message
     (and is left untouched — still empty).

The actual Azure transcription path needs SPEECH_KEY + a real WAV and is not
exercised here.

Run:  python -m stt._transcribe_smoketest
"""

import datetime
import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from shared import config

_tmp_root = Path(tempfile.mkdtemp(prefix="gma_stt_test_"))
config.settings.recordings_root = str(_tmp_root)

from shared.schema import Person, Participant, Segment, MeetingRecord
from shared import store
from stt import transcribe


def _base(meeting_id, segments):
    return MeetingRecord(
        meetingId=meeting_id,
        joinUrl="https://meet.google.com/x",
        organizer=Person(),
        participants=[Participant(name="Алмаз", id="u1")],
        startedAt=datetime.datetime(2026, 6, 28, 9, 0, 0),
        endedAt=datetime.datetime(2026, 6, 28, 9, 42, 0),
        language="ru",
        segments=segments,
    )


def check(label, passed):
    print(f"{'PASS' if passed else 'FAIL'}: {label}")
    return passed


def main():
    try:
        # 1. Already-transcribed record -> skipped, untouched.
        already = _base("has-segs", [Segment(speaker=Person(name="Алмаз"), startMs=0, endMs=1000, text="Привет")])
        store.save_record(already)
        transcribe.process_meeting("has-segs")
        after = store.load_record("has-segs")
        r1 = check("record with segments is left untouched", len(after.segments) == 1 and after.segments[0].text == "Привет")

        # 2. No segments + no audio -> skipped, stays empty.
        empty = _base("no-audio", [])
        store.save_record(empty)
        transcribe.process_meeting("no-audio")
        after2 = store.load_record("no-audio")
        r2 = check("record with no audio stays empty (no crash)", after2.segments == [])

        print()
        print("ALL PASS" if (r1 and r2) else "SOME CHECKS FAILED")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
