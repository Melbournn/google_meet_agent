"""
Dev smoketest for capture/run.py — no live Google call.

Uses a fake CaptureSource that returns one record, against a throwaway temp
recordings root, and verifies: the record is saved to disk, run reports 1,
the checkpoint file is written, and a second run (checkpoint set) is idempotent.

Run:  python -m capture._run_smoketest
"""

import datetime
import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Point settings at a throwaway root BEFORE importing modules that read it.
from shared import config

_tmp_root = Path(tempfile.mkdtemp(prefix="gma_run_test_"))
config.settings.recordings_root = str(_tmp_root)

from capture.base import CaptureSource
from shared.schema import Person, Participant, MeetingRecord
from shared import store
import capture.run as run

# run.py computed its checkpoint path at import from the (default) root; repoint it.
run._CHECKPOINT = _tmp_root / ".capture_checkpoint"


def _record():
    return MeetingRecord(
        meetingId="abc-123",
        joinUrl="https://meet.google.com/abc-defg-hij",
        organizer=Person(),
        participants=[Participant(name="Алмаз", id="u1")],
        startedAt=datetime.datetime(2026, 6, 28, 9, 0, 0),
        endedAt=datetime.datetime(2026, 6, 28, 9, 42, 0),
        language="ru",
    )


class _FakeSource(CaptureSource):
    def __init__(self, records):
        self._records = records
        self.calls = []

    def fetch_finished_meetings(self, since=None):
        self.calls.append(since)
        return self._records


def check(label, passed):
    print(f"{'PASS' if passed else 'FAIL'}: {label}")
    return passed


def main():
    try:
        src = _FakeSource([_record()])
        n1 = run.run_once(source=src)

        results = [
            check("first run saved 1 meeting", n1 == 1),
            check("first run had no checkpoint (since=None)", src.calls[0] is None),
            check("record written to disk", (_tmp_root / "abc-123" / "abc-123.json").exists()),
            check("record loads back", store.load_record("abc-123").meetingId == "abc-123"),
            check("checkpoint file written", run._CHECKPOINT.exists()),
        ]

        # Second run: checkpoint now set -> source should be called WITH a since.
        src2 = _FakeSource([])  # nothing new
        run.run_once(source=src2)
        results.append(check("second run passes checkpoint as since", src2.calls[0] is not None))

        print()
        print("ALL PASS" if all(results) else "SOME CHECKS FAILED")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
