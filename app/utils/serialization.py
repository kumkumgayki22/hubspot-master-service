import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID
from typing import Any


def deep_serialize(obj: Any) -> Any:
    """
    Recursively converts Decimals, UUIDs, Enums, and Datetimes
    into JSON-safe structures for API responses and DB JSON columns.
    """
    if obj is None:
        return None
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): deep_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [deep_serialize(item) for item in obj]
    if hasattr(obj, "__dict__"):
        return deep_serialize(obj.__dict__)
    return str(obj)
