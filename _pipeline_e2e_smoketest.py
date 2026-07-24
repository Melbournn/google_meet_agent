"""
End-to-end pipeline smoketest — no live Google/Azure.

Chains the whole build scope on ONE meeting, with fakes at the two external
boundaries (Meet API + LLM):

    capture (fake Meet client) -> store -> [STT skipped: segments present]
                                        -> agent (fake LLM client) -> store

Then asserts the final {meetingId}.json holds a complete record: metadata,
participants, segments (from the Google transcript), summary, actionItems, and
analysis with LOCALLY-computed talk-time.

Run:  python -m _pipeline_e2e_smoketest
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

_tmp_root = Path(tempfile.mkdtemp(prefix="gma_e2e_"))
config.settings.recordings_root = str(_tmp_root)

from shared import store
import capture.run as run
from capture.meet_rest_source import MeetRestSource
from agent import analyze
import stt.transcribe as transcribe

# --- fake Meet API data + client (from the capture smoketest) ------------------
CONFERENCE = {"name": "conferenceRecords/abc123", "startTime": "2026-06-28T09:00:00Z",
              "endTime": "2026-06-28T09:42:00Z", "space": "spaces/xyz"}
SPACE = {"name": "spaces/xyz", "meetingUri": "https://meet.google.com/abc-defg-hij"}
PARTICIPANTS = [
    {"name": "conferenceRecords/abc123/participants/p1", "signedinUser": {"user": "users/1", "displayName": "Алмаз"}},
    {"name": "conferenceRecords/abc123/participants/p2", "anonymousUser": {"displayName": "Guest"}},
]
TRANSCRIPTS = [{"name": "conferenceRecords/abc123/transcripts/t1"}]
ENTRIES = [
    {"participant": "conferenceRecords/abc123/participants/p1", "text": "Привет, коллеги",
     "languageCode": "ru-RU", "startTime": "2026-06-28T09:00:12Z", "endTime": "2026-06-28T09:00:15Z"},
    {"participant": "conferenceRecords/abc123/participants/p2", "text": "Давайте начнём",
     "languageCode": "ru-RU", "startTime": "2026-06-28T09:00:20Z", "endTime": "2026-06-28T09:00:23Z"},
]


class _Req:
    def __init__(self, r): self._r = r
    def execute(self): return self._r


class _Listable:
    def __init__(self, key, items): self._key, self._items = key, items
    def list(self, **kw): return _Req({self._key: self._items})
    def list_next(self, req, resp): return None


class _Transcripts(_Listable):
    def entries(self): return _Listable("transcriptEntries", ENTRIES)


class _ConfRecords(_Listable):
    def participants(self): return _Listable("participants", PARTICIPANTS)
    def transcripts(self): return _Transcripts("transcripts", TRANSCRIPTS)


class _FakeMeet:
    def conferenceRecords(self): return _ConfRecords("conferenceRecords", [CONFERENCE])
    def spaces(self):
        class _S:
            def get(self, name): return _Req(SPACE)
        return _S()


# --- fake LLM client -----------------------------------------------------------
CANNED = {
    "summary": {"tldr": "Обсудили запуск", "narrative": "Команда согласовала план запуска."},
    "actionItems": [{"title": "Подготовить отчёт", "owner": "Алмаз", "due": "2026-07-01", "sourceStartMs": 12000}],
    "analysis": {"topics": ["Запуск"], "decisions": ["Запускаем в июле"], "sentiment": "позитивный", "followUps": ["Созвон"]},
}


class _FakeLLM:
    class chat:
        class completions:
            @staticmethod
            def create(**kw):
                class _R:
                    choices = [type("C", (), {"message": type("M", (), {"content": json.dumps(CANNED)})})]
                return _R()


def check(label, passed):
    print(f"{'PASS' if passed else 'FAIL'}: {label}")
    return passed


def main():
    try:
        # 1. CAPTURE (fake Meet client) -> store
        run._CHECKPOINT = _tmp_root / ".capture_checkpoint"
        n = run.run_once(source=MeetRestSource(service=_FakeMeet()))
        mid = "abc123"

        # 2. STT — should be a no-op because capture imported Google's transcript
        transcribe.process_meeting(mid)

        # 3. AGENT (fake LLM client) -> store
        analyze.analyze_meeting(mid, _FakeLLM(), "fake-model")

        # 4. Verify the final record
        rec = store.load_record(mid)
        results = [
            check("capture saved 1 meeting", n == 1),
            check("metadata: joinUrl", rec.joinUrl == "https://meet.google.com/abc-defg-hij"),
            check("participants (2)", len(rec.participants) == 2),
            check("segments from Google transcript (2, sorted)", [s.startMs for s in rec.segments] == [12000, 20000]),
            check("speaker labelled", rec.segments[0].speaker.name == "Алмаз"),
            check("summary present", rec.summary is not None and rec.summary.tldr == "Обсудили запуск"),
            check("action items present", len(rec.actionItems) == 1),
            check("analysis present", rec.analysis is not None and rec.analysis.decisions == ["Запускаем в июле"]),
            check("talk-time computed locally", rec.analysis.talkTimeSeconds == {"Алмаз": 3.0, "Guest": 3.0}),
        ]
        print()
        print("PIPELINE OK — capture -> STT(skip) -> agent" if all(results) else "PIPELINE FAILED")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
