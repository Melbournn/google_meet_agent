'''Disk drop-box (handoff §5). The only module that reads/writes meeting JSON files.'''
import os
from pathlib import Path
from shared.config import settings
from shared.schema import MeetingRecord, to_json, from_json

def meeting_dir(meeting_id:str) -> Path:
    '''function for computing the path'''
    return Path(settings.recordings_root)/meeting_id

def record_path(meeting_id:str) -> Path:
    '''function for obtaining path of the JSON file'''
    return meeting_dir(meeting_id)/f"{meeting_id}.json"

def load_record(meeting_id:str) -> MeetingRecord:
    '''function for loading the JSON file'''
    path = record_path(meeting_id)
    if not path.exists(): raise FileNotFoundError(f"No record for meeting {meeting_id} at {path}")
    text = path.read_text(encoding="utf-8")
    return from_json(text)

def save_record(record: MeetingRecord) -> None:
    '''function for saving the JSON file'''
    meeting_id = record.meetingId
    meeting_dir(meeting_id).mkdir(parents=True, exist_ok=True)
    text = to_json(record)
    final = record_path(meeting_id)
    tmp = final.with_suffix(final.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, final)
    return None

def list_meetings() -> list[str]:
    '''function for listing all meetings'''
    root = Path(settings.recordings_root)
    if not root.exists(): return []
    return [c.name for c in root.iterdir() if c.is_dir() and (c/f"{c.name}.json").exists()]