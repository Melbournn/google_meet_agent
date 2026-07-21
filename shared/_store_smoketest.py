"""
Dev smoketest for shared/store.py — NOT part of the pipeline.

Proves the disk drop-box end to end, against a throwaway temp recordings root
(so it never touches your real ./recordings):
  1. list_meetings() on an empty-but-existing root returns [] (not None).
  2. save_record() writes {root}/{id}/{id}.json.
  3. load_record() round-trips the record unchanged (UTF-8 intact).
  4. list_meetings() finds the saved id.

Run:  python -m shared._store_smoketest
"""

import datetime
import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Point the shared settings at a throwaway temp dir BEFORE using the store,
# so we don't pollute the real ./recordings. store.py reads the same singleton.
from shared import config

_tmp_root = Path(tempfile.mkdtemp(prefix="gma_store_test_"))
config.settings.recordings_root = str(_tmp_root)

from shared import store
from shared.schema import Person, Participant, MeetingRecord


def check(label, fn):
    try:
        fn()
        print(f"PASS: {label}")
        return True
    except Exception as e:
        print(f"FAIL: {label}\n      {type(e).__name__}: {e}")
        return False


def fresh_record():
    return MeetingRecord(
        meetingId="abc-123",
        joinUrl="https://meet.google.com/abc-defg-hij",
        organizer=Person(name="Алмаз", id="u1"),
        participants=[Participant(name="Алмаз", id="u1")],
        startedAt=datetime.datetime(2026, 6, 28, 9, 0, 0),
        endedAt=datetime.datetime(2026, 6, 28, 9, 42, 0),
        language="ru",
    )


def empty_root_returns_list():
    # Root exists (mkdtemp created it) but has no meetings yet.
    result = store.list_meetings()
    assert result == [], f"expected [] on empty root, got {result!r}"


def save_writes_file():
    store.save_record(fresh_record())
    expected = _tmp_root / "abc-123" / "abc-123.json"
    assert expected.exists(), f"file not written at {expected}"


def load_roundtrips():
    loaded = store.load_record("abc-123")
    assert loaded == fresh_record(), "loaded record != original"


def list_finds_it():
    ids = store.list_meetings()
    assert ids == ["abc-123"], f"expected ['abc-123'], got {ids!r}"


def main():
    try:
        results = [
            check("list_meetings() on empty root returns [] (not None)", empty_root_returns_list),
            check("save_record() writes {root}/{id}/{id}.json", save_writes_file),
            check("load_record() round-trips the record", load_roundtrips),
            check("list_meetings() finds the saved id", list_finds_it),
        ]
        print()
        print("ALL PASS" if all(results) else "SOME CHECKS FAILED")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
