'''Capture interface. Every capture source (Meet REST, Media API, browser bot) implements this so downstream stages depend on the abstraction, not on Google specifics.'''
from abc import ABC, abstractmethod
from datetime import datetime
from shared.schema import MeetingRecord

class CaptureSource(ABC):
    '''Abstract source of finished-meeting records.'''
    @abstractmethod
    def fetch_finished_meetings(self, since: datetime | None = None) -> list[MeetingRecord]:
        '''Return records for meetings that finished since the last poll.'''
        raise NotImplementedError
