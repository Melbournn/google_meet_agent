"""
Dev smoketest for the pure mapping in capture/meet_rest_source.py — no live API.

Feeds sample Google Meet API responses through build_meeting_record and checks:
  - meetingId, joinUrl
  - participants (signed-in AND anonymous) mapped
  - segments sorted by startMs, absolute time -> offset conversion (09:00:12 -> 12000)
  - Russian text intact
  - summary/analysis left empty

Run:  python -m capture._mapping_smoketest
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from capture.meet_rest_source import build_meeting_record

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
        "earliestStartTime": "2026-06-28T09:00:05Z",
        "latestEndTime": "2026-06-28T09:41:00Z",
        "signedinUser": {"user": "users/11223344", "displayName": "Алмаз"},
    },
    {
        "name": "conferenceRecords/abc123/participants/p2",
        "earliestStartTime": "2026-06-28T09:00:10Z",
        "latestEndTime": "2026-06-28T09:40:00Z",
        "anonymousUser": {"displayName": "Guest"},
    },
]
# Deliberately out of order to test sorting.
ENTRIES = [
    {
        "name": ".../entries/e2",
        "participant": "conferenceRecords/abc123/participants/p2",
        "text": "Давайте начнём",
        "languageCode": "ru-RU",
        "startTime": "2026-06-28T09:00:20Z",
        "endTime": "2026-06-28T09:00:23Z",
    },
    {
        "name": ".../entries/e1",
        "participant": "conferenceRecords/abc123/participants/p1",
        "text": "Привет, коллеги",
        "languageCode": "ru-RU",
        "startTime": "2026-06-28T09:00:12Z",
        "endTime": "2026-06-28T09:00:15Z",
    },
]


def main():
    rec = build_meeting_record(CONFERENCE, SPACE, PARTICIPANTS, ENTRIES)
    checks = {
        "meetingId": rec.meetingId == "conferenceRecords/abc123",
        "joinUrl": rec.joinUrl == "https://meet.google.com/abc-defg-hij",
        "2 participants": len(rec.participants) == 2,
        "signed-in name": rec.participants[0].name == "Алмаз",
        "signed-in id": rec.participants[0].id == "users/11223344",
        "anonymous name": rec.participants[1].name == "Guest",
        "anonymous id is None": rec.participants[1].id is None,
        "segments sorted": [s.startMs for s in rec.segments] == [12000, 20000],
        "offset conversion (09:00:12 -> 12000)": rec.segments[0].startMs == 12000,
        "endMs conversion (09:00:15 -> 15000)": rec.segments[0].endMs == 15000,
        "speaker labelled": rec.segments[0].speaker.name == "Алмаз",
        "russian text intact": rec.segments[0].text == "Привет, коллеги",
        "language": rec.language == "ru-RU",
        "summary empty": rec.summary is None,
        "analysis empty": rec.analysis is None,
    }
    ok = True
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
        ok = ok and passed
    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
