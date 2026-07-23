'''Google Meet REST API capture source (Option A).

Two layers:
  * pure mapping functions (Google response dict -> MeetingRecord) — unit-tested,
  * MeetRestSource — implements CaptureSource by calling the live Meet API and
    feeding the responses through the mapping functions.
'''
import re
from datetime import datetime

from googleapiclient.discovery import build

from shared.schema import Person, Participant, Segment, MeetingRecord
from shared.config import settings
from capture.base import CaptureSource
from capture.google_auth import get_credentials

def _person(p: dict) -> Person:
    for key in ("signedinUser", "anonymousUser", "phoneUser"):
        if key in p:
            sub = p[key]
            id = sub.get("user") if key == "signedinUser" else None
            return Person(name=sub.get("displayName"), id=id)
    return Person()

def _parse_time(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)
        return datetime.fromisoformat(s)

def _offset_ms(conf_start: datetime, t: datetime) -> int:
    return int((t - conf_start).total_seconds() * 1000)

def build_participant(p: dict) -> Participant:
    person = _person(p)

    return Participant(
        name = person.name,
        id = person.id,
        joinedAt = p.get("earliestStartTime"),
        leftAt = p.get("latestEndTime"),
    )

def _people_by_ref(participants: list[dict]) -> dict[str, Person]:
    return {p["name"]: _person(p) for p in participants}

def build_segment(entry: dict, people_by_ref: dict[str, Person], conf_start: datetime) -> Segment:
    speaker = people_by_ref.get(entry["participant"]) or Person()
    startMs = _offset_ms(conf_start, _parse_time(entry["startTime"]))
    endMs = _offset_ms(conf_start, _parse_time(entry["endTime"]))
    text = entry["text"]
    return Segment(speaker = speaker, startMs = startMs, endMs = endMs, text = text)

def build_meeting_record(conference, space, participants, entries) -> MeetingRecord:
    meeting_id = conference["name"].split("/")[-1]  # bare id (filesystem-safe key), not "conferenceRecords/abc123"
    conf_start = _parse_time(conference["startTime"])
    people_by_ref = _people_by_ref(participants)
    segments = sorted([build_segment(e, people_by_ref, conf_start) for e in entries], key=lambda s: s.startMs)
    participants = [build_participant(p) for p in participants]
    language = entries[0]["languageCode"] if entries else (settings.stt_language or "ru")
    organizer = Person() # TODO: enrich organizer via Admin SDK / Directory API later
    startedAt, endedAt = conference["startTime"], conference["endTime"]
    joinUrl = space["meetingUri"]
    return MeetingRecord(meetingId = meeting_id,
                         joinUrl=joinUrl,
                         organizer=organizer,
                         participants=participants,
                         startedAt=startedAt,
                         endedAt=endedAt,
                         language=language,
                         segments = segments,
                         )


class MeetRestSource(CaptureSource):
    '''Fetches finished meetings from the Google Meet REST API (Option A).'''

    def __init__(self, service=None):
        # service is injectable for testing; in production build the real client.
        self._service = service or build("meet", "v2", credentials=get_credentials())

    def _list_all(self, collection, items_key: str, **list_kwargs) -> list:
        '''Collect every page of a Meet list call into one list.'''
        items = []
        request = collection.list(**list_kwargs)
        while request is not None:
            response = request.execute()
            items.extend(response.get(items_key, []))
            request = collection.list_next(request, response)
        return items

    def fetch_finished_meetings(self, since: datetime | None = None) -> list[MeetingRecord]:
        flt = f'end_time>="{since.isoformat()}"' if since else None
        confs = self._list_all(
            self._service.conferenceRecords(), "conferenceRecords", filter=flt
        )

        records = []
        for conf in confs:
            space = self._service.spaces().get(name=conf["space"]).execute()
            participants = self._list_all(
                self._service.conferenceRecords().participants(),
                "participants",
                parent=conf["name"],
            )
            transcripts = self._list_all(
                self._service.conferenceRecords().transcripts(),
                "transcripts",
                parent=conf["name"],
            )
            entries = []
            for t in transcripts:
                entries.extend(
                    self._list_all(
                        self._service.conferenceRecords().transcripts().entries(),
                        "transcriptEntries",
                        parent=t["name"],
                    )
                )
            records.append(build_meeting_record(conf, space, participants, entries))
        return records

