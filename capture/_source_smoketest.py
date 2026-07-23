"""
Dev smoketest for MeetRestSource — no live Google call.

Injects a FAKE Meet API client that returns canned responses (mirroring the
real client's nested resource + pagination shape), and verifies the full
fetch -> map -> collect path, including the `transcriptEntries` key and paging.

Run:  python -m capture._source_smoketest
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from capture.meet_rest_source import MeetRestSource

# ---- canned Google-shaped data ------------------------------------------------
CONFERENCE = {
    "name": "conferenceRecords/abc123",
    "startTime": "2026-06-28T09:00:00Z",
    "endTime": "2026-06-28T09:42:00Z",
    "space": "spaces/xyz",
}
SPACE = {"name": "spaces/xyz", "meetingUri": "https://meet.google.com/abc-defg-hij"}
PARTICIPANTS = [
    {
        "name": "conferenceRecords/abc123/participants/p1",
        "signedinUser": {"user": "users/11223344", "displayName": "Алмаз"},
    },
    {
        "name": "conferenceRecords/abc123/participants/p2",
        "anonymousUser": {"displayName": "Guest"},
    },
]
TRANSCRIPTS = [{"name": "conferenceRecords/abc123/transcripts/t1"}]
ENTRIES = [
    {
        "participant": "conferenceRecords/abc123/participants/p2",
        "text": "Давайте начнём",
        "languageCode": "ru-RU",
        "startTime": "2026-06-28T09:00:20Z",
        "endTime": "2026-06-28T09:00:23Z",
    },
    {
        "participant": "conferenceRecords/abc123/participants/p1",
        "text": "Привет, коллеги",
        "languageCode": "ru-RU",
        "startTime": "2026-06-28T09:00:12Z",
        "endTime": "2026-06-28T09:00:15Z",
    },
]


# ---- a fake that mimics googleapiclient's resource + pagination surface -------
class _Req:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Listable:
    """A collection whose .list() returns one page and .list_next() ends paging."""
    def __init__(self, key, items):
        self._key, self._items = key, items

    def list(self, **kwargs):
        return _Req({self._key: self._items})

    def list_next(self, request, response):
        return None  # single page


class _Transcripts(_Listable):
    def entries(self):
        return _Listable("transcriptEntries", ENTRIES)


class _ConferenceRecords(_Listable):
    def participants(self):
        return _Listable("participants", PARTICIPANTS)

    def transcripts(self):
        return _Transcripts("transcripts", TRANSCRIPTS)


class _Spaces:
    def get(self, name):
        return _Req(SPACE)


class _FakeService:
    def conferenceRecords(self):
        return _ConferenceRecords("conferenceRecords", [CONFERENCE])

    def spaces(self):
        return _Spaces()


def main():
    src = MeetRestSource(service=_FakeService())
    records = src.fetch_finished_meetings()

    checks = {
        "one record returned": len(records) == 1,
    }
    if records:
        rec = records[0]
        checks.update({
            "meetingId": rec.meetingId == "conferenceRecords/abc123",
            "joinUrl": rec.joinUrl == "https://meet.google.com/abc-defg-hij",
            "2 participants": len(rec.participants) == 2,
            "2 segments (transcriptEntries key worked)": len(rec.segments) == 2,
            "segments sorted": [s.startMs for s in rec.segments] == [12000, 20000],
            "speaker labelled": rec.segments[0].speaker.name == "Алмаз",
            "russian intact": rec.segments[0].text == "Привет, коллеги",
            "anonymous id None": rec.participants[1].id is None,
        })

    ok = True
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
        ok = ok and passed
    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
