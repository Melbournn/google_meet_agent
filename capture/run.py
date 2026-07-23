"""
Stage 0 runner — poll a capture source and persist each finished meeting.

Fetches meetings that finished since the last checkpoint, saves each as
{recordings_root}/{meetingId}/{meetingId}.json (via shared.store), then advances
the checkpoint to the latest endedAt seen. Idempotent: re-running never
duplicates work (save_record overwrites, and the checkpoint skips old meetings).

Usage:
    python -m capture.run          # one poll cycle
"""

import sys
from datetime import datetime
from pathlib import Path

from shared.config import settings
from shared import store
from capture.base import CaptureSource
from capture.meet_rest_source import MeetRestSource

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_CHECKPOINT = Path(settings.recordings_root) / ".capture_checkpoint"


def _load_checkpoint() -> datetime | None:
    """Return the last-processed endedAt, or None on first run."""
    if not _CHECKPOINT.exists():
        return None
    try:
        return datetime.fromisoformat(_CHECKPOINT.read_text(encoding="utf-8").strip())
    except ValueError:
        return None  # unreadable checkpoint -> treat as first run


def _save_checkpoint(when: datetime) -> None:
    _CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    _CHECKPOINT.write_text(when.isoformat(), encoding="utf-8")


def run_once(source: CaptureSource | None = None) -> int:
    """Fetch finished meetings since the checkpoint, save them, advance checkpoint.

    Returns the number of meetings saved.
    """
    source = source or MeetRestSource()
    since = _load_checkpoint()

    records = source.fetch_finished_meetings(since=since)
    latest = since
    for rec in records:
        store.save_record(rec)
        print(f"[capture] saved {rec.meetingId} ({len(rec.segments)} segment(s))")
        if latest is None or rec.endedAt > latest:
            latest = rec.endedAt

    if latest is not None and latest != since:
        _save_checkpoint(latest)

    return len(records)


def main() -> None:
    n = run_once()
    print(f"[capture] done — {n} meeting(s) processed")


if __name__ == "__main__":
    main()
