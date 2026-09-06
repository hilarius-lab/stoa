# Smart Notebook utilities
from datetime import datetime
from .config import TIMEZONE

def normalize_event_time(value: datetime | None):
    if value is None:
        return datetime.now(TIMEZONE)

    if value.tzinfo is None:
        return value.replace(tzinfo=TIMEZONE)

    return value
