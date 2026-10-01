import json
import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.db.models import FailedExternalCall
from app.utils.serialization import deep_serialize
from app.config import settings

logger = logging.getLogger("hubspot_master_service.dlq")

SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "private_app_token",
    "client_secret",
    "password",
    "authorization",
    "x-hs-signature",
    "secret",
}


def scrub_payload(payload: Any) -> Any:
    """
    Recursively redacts sensitive security fields from request payloads
    before persisting to Dead-Letter Queue / database.
    """
    if isinstance(payload, dict):
        scrubbed = {}
        for k, v in payload.items():
            if str(k).lower() in SENSITIVE_KEYS:
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_payload(v)
        return scrubbed
    elif isinstance(payload, list):
        return [scrub_payload(item) for item in payload]
    return payload


def write_to_dlq(
    db: Session,
    target_service: str,
    operation: str,
    payload: Any,
    attempts: int,
    error: Exception,
    organization_id: Optional[str] = None,
    scan_id: Optional[str] = None
) -> Optional[FailedExternalCall]:
    """
    Persists an exhausted external call failure to the Dead-Letter Queue (failed_external_calls table).
    Never raises exceptions so that normal job error recording is not interrupted.
    """
    try:
        scrubbed = scrub_payload(payload)
        serialized_payload = deep_serialize(scrubbed)

        # Cap payload size if JSON string representation exceeds max bytes
        json_str = json.dumps(serialized_payload)
        if len(json_str.encode("utf-8")) > settings.DLQ_PAYLOAD_MAX_BYTES:
            serialized_payload = {
                "_truncated": True,
                "message": f"Payload exceeded max bytes ({settings.DLQ_PAYLOAD_MAX_BYTES}). Truncated for security.",
                "sample": str(serialized_payload)[:1000]
            }

        dlq_entry = FailedExternalCall(
            target_service=target_service,
            operation=operation,
            organization_id=organization_id,
            scan_id=scan_id,
            payload=serialized_payload,
            attempts=attempts,
            last_error=str(error),
            status="LOGGED"
        )
        db.add(dlq_entry)
        db.commit()
        db.refresh(dlq_entry)
        logger.info(f"Recorded exhausted failure in DLQ: ID {dlq_entry.id} ({target_service} {operation})")
        return dlq_entry
    except Exception as exc:
        logger.error(f"Failed to record entry in Dead-Letter Queue: {exc}")
        if db:
            db.rollback()
        return None
