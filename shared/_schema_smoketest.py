"""
Dev smoketest for shared/schema.py — NOT part of the pipeline.

Proves three things about the frozen §4 contract:
  1. A fresh capture-stage record (no transcript/summary/analysis yet) is valid.
  2. A record survives a to_json -> from_json round-trip unchanged.
  3. Russian text is preserved as real UTF-8 (not escaped to \\uXXXX).

Run:  python -m shared._schema_smoketest
"""

import datetime
import sys

# Windows consoles default to a legacy codepage (cp1251 here) that can't render
# Cyrillic; force UTF-8 so the eyeball check below shows real text, not "?????".
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from shared.schema import (
    Person,
    Participant,
    Segment,
    Summary,
    ActionItem,
    Analysis,
    MeetingRecord,
    to_json,
    from_json,
)


def check(label, fn):
    """Run a check, print PASS/FAIL, never abort the whole suite on one failure."""
    try:
        fn()
        print(f"PASS: {label}")
        return True
    except Exception as e:
        print(f"FAIL: {label}\n      {type(e).__name__}: {e}")
        return False


def fresh_capture_record():
    """What the CAPTURE stage produces: everything EXCEPT segments/summary/actionItems/analysis."""
    rec = MeetingRecord(
        meetingId="abc-123",
        joinUrl="https://meet.google.com/abc-defg-hij",
        organizer=Person(name="Алмаз", id="u1"),
        participants=[Participant(name="Алмаз", id="u1")],
        startedAt=datetime.datetime(2026, 6, 28, 9, 0, 0),
        endedAt=datetime.datetime(2026, 6, 28, 9, 42, 0),
        language="ru",
    )
    # The four downstream-owned fields must be safely empty on a fresh record.
    assert rec.segments == [], "segments should default to an empty list"
    assert rec.actionItems == [], "actionItems should default to an empty list"
    assert rec.summary is None, "summary should default to None"
    assert rec.analysis is None, "analysis should default to None"
    return rec


def roundtrip_fresh():
    rec = fresh_capture_record()
    assert from_json(to_json(rec)) == rec, "round-trip changed the record"


def russian_utf8():
    """A fully-filled record with Russian text; prove UTF-8 survives serialization."""
    rec = MeetingRecord(
        meetingId="ru-1",
        joinUrl="https://meet.google.com/xxx-yyyy-zzz",
        organizer=Person(name="Алмаз", id="u1"),
        participants=[Participant(name="Алмаз", id="u1"), Participant(name="Борис", id="u2")],
        startedAt=datetime.datetime(2026, 6, 28, 9, 0, 0),
        endedAt=datetime.datetime(2026, 6, 28, 9, 42, 0),
        language="ru",
        segments=[
            Segment(speaker=Person(name="Алмаз", id="u1"), startMs=0, endMs=1500, text="Привет, коллеги"),
            Segment(speaker=Person(name="Борис", id="u2"), startMs=1600, endMs=3000, text="Давайте начнём"),
        ],
        summary=Summary(tldr="Краткое содержание встречи", narrative="Подробный разбор обсуждения"),
        actionItems=[
            ActionItem(title="Подготовить отчёт", owner="Алмаз", due=datetime.date(2026, 7, 1), sourceStartMs=0),
        ],
        analysis=Analysis(
            topics=["Планирование"],
            decisions=["Запустить проект"],
            sentiment="позитивный",
            followUps=["Созвон в пятницу"],
            talkTimeSeconds={"Алмаз": 1.5, "Борис": 1.4},
        ),
    )
    js = to_json(rec)
    assert "Привет" in js, "cyrillic text not found in JSON output"
    assert "\\u04" not in js, "cyrillic got escaped to \\uXXXX (UTF-8 not preserved)"
    assert from_json(js) == rec, "round-trip changed the filled record"
    print("---- sample JSON (eyeball the Cyrillic) ----")
    print(js)


def main():
    results = [
        check("fresh capture-stage record constructs with correct defaults", fresh_capture_record),
        check("fresh record round-trips (to_json -> from_json)", roundtrip_fresh),
        check("Russian text survives round-trip as real UTF-8", russian_utf8),
    ]
    print()
    print("ALL PASS" if all(results) else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
