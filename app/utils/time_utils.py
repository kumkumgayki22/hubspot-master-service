import datetime
from typing import Optional


def calculate_duration(
    start: Optional[datetime.datetime],
    end: Optional[datetime.datetime] = None
) -> Optional[float]:
    """
    Calculates the duration in seconds between start and end datetimes.
    If end is omitted, uses the current UTC time.
    Returns float seconds or None if start is missing.
    """
    if not start:
        return None
    
    # Ensure datetimes are comparable
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
        
    if end is None:
        end = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    elif end.tzinfo is not None:
        end = end.replace(tzinfo=None)

    delta = end - start
    return round(delta.total_seconds(), 2)
