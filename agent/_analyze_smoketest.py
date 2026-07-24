"""
Dev smoketest for agent/analyze.py — no Azure, no creds.

Injects a FAKE OpenAI client whose chat.completions.create returns a canned
JSON string, then verifies analyze_meeting:
  - maps the JSON into Summary / ActionItem / Analysis objects,
  - attaches LOCALLY-computed talk-time (not the LLM's),
  - saves via store,
  - is idempotent (second run skips because summary now exists).

Run:  python -m agent._analyze_smoketest
"""

import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from shared import config

_tmp_root = Path(tempfile.mkdtemp(prefix="gma_agent_test_"))
config.settings.recordings_root = str(_tmp_root)

from shared.schema import Person, Participant, Segment, MeetingRecord
from shared import store
from agent import analyze

CANNED = {
    "summary": {"tldr": "Краткое содержание", "narrative": "Подробный разбор встречи"},
    "actionItems": [
        {"title": "Подготовить отчёт", "owner": "Алмаз", "due": "2026-07-01", "sourceStartMs": 0},
    ],
    "analysis": {
        "topics": ["Планирование"],
        "decisions": ["Запустить проект"],
        "sentiment": "позитивный",
        "followUps": ["Созвон в пятницу"],
        # NOTE: deliberately includes a WRONG talkTime the LLM "hallucinated" —
        # our code must ignore it and compute locally. Analysis has no such key
        # in the prompt, but even if present we override it.
    },
}


# ---- fake OpenAI client -------------------------------------------------------
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def create(self, **kwargs):
        return _Resp(json.dumps(CANNED))


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class _FakeClient:
    def __init__(self):
        self.chat = _Chat()


def _record():
    return MeetingRecord(
        meetingId="mtg-1",
        joinUrl="https://meet.google.com/x",
        organizer=Person(),
        participants=[Participant(name="Алмаз", id="u1"), Participant(name="Борис", id="u2")],
        startedAt=datetime.datetime(2026, 6, 28, 9, 0, 0),
        endedAt=datetime.datetime(2026, 6, 28, 9, 42, 0),
        language="ru",
        segments=[
            Segment(speaker=Person(name="Алмаз"), startMs=0, endMs=3000, text="Привет"),
            Segment(speaker=Person(name="Борис"), startMs=3000, endMs=5000, text="Давай"),
        ],
    )


def check(label, passed):
    print(f"{'PASS' if passed else 'FAIL'}: {label}")
    return passed


def main():
    try:
        store.save_record(_record())
        analyze.analyze_meeting("mtg-1", _FakeClient(), "fake-model")
        rec = store.load_record("mtg-1")

        results = [
            check("summary mapped to Summary", rec.summary is not None and rec.summary.tldr == "Краткое содержание"),
            check("actionItems mapped to ActionItem", len(rec.actionItems) == 1 and rec.actionItems[0].title == "Подготовить отчёт"),
            check("due parsed to date", str(rec.actionItems[0].due) == "2026-07-01"),
            check("analysis mapped", rec.analysis is not None and rec.analysis.topics == ["Планирование"]),
            check("talk-time computed LOCALLY", rec.analysis.talkTimeSeconds == {"Алмаз": 3.0, "Борис": 2.0}),
        ]

        # Idempotency: second run should skip (summary now exists).
        before = rec.summary.tldr
        analyze.analyze_meeting("mtg-1", _FakeClient(), "fake-model")
        rec2 = store.load_record("mtg-1")
        results.append(check("second run is idempotent (skips)", rec2.summary.tldr == before))

        print()
        print("ALL PASS" if all(results) else "SOME CHECKS FAILED")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
