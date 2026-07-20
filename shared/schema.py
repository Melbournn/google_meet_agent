'''
Frozen cross-stage contract (handoff §4). Every pipeline stage reads and writes this MeetingRecord as one JSON file per
meeting. Do NOT change field names or shapes without migrating capture, STT, agent, archive, UI, and Notion together — a change here
breaks all of them at once.
'''
import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

#We are going to use Google Meet Rest API for capturing audio
#JSON key strategy: attributes are named in camelCase to match the §4 wire format exactly

class Person(BaseModel):
    name: Optional[str] = None
    id: Optional[str] = None


class Participant(BaseModel):
    name: str
    id: str
    joinedAt: Optional[datetime.datetime] = None
    leftAt: Optional[datetime.datetime] = None



class Segment(BaseModel):
    speaker: Person
    startMs: int
    endMs: int
    text: str


class Summary(BaseModel):
    tldr: str
    narrative: str


class ActionItem(BaseModel):
    title: str
    owner: Optional[str] = None
    due: Optional[datetime.date] = None
    sourceStartMs: Optional[int] = None


class Analysis(BaseModel):
    topics: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    sentiment: str
    followUps: list[str] = Field(default_factory=list)
    talkTimeSeconds: dict[str, float] = Field(default_factory=dict)


class MeetingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meetingId: str
    tenantId: Optional[str] = None
    joinUrl: str
    subject: Optional[str] = None
    organizer: Person
    participants: list[Participant] = Field(default_factory=list)
    startedAt: datetime.datetime
    endedAt: datetime.datetime
    language: str
    audioArtifactUri: Optional[str] = None
    segments: list[Segment] = Field(default_factory=list)
    summary: Optional[Summary] = None
    actionItems: list[ActionItem] = Field(default_factory=list)
    analysis: Optional[Analysis] = None

def to_json(record: MeetingRecord) -> str:
    return record.model_dump_json(indent=2)

def from_json(text: str) -> MeetingRecord:
    return MeetingRecord.model_validate_json(text)
