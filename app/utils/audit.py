import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.db.models import AuditLog

logger = logging.getLogger("hubspot_master_service.audit")


def log_audit_event(
    db: Session,
    event_category: str,
    event_type: str,
    outcome: str = "SUCCESS",
    actor_client_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    organization_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    http_method: Optional[str] = None,
    endpoint: Optional[str] = None,
    request_ip: Optional[str] = None,
    status_code: Optional[int] = None,
    severity: str = "INFO",
    error_detail: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None
) -> Optional[AuditLog]:
    """
    Creates an AuditLog entry in PostgreSQL database.
    """
    try:
        log_entry = AuditLog(
            event_category=event_category,
            event_type=event_type,
            actor_client_id=actor_client_id,
            actor_role=actor_role,
            organization_id=organization_id,
            entity_type=entity_type,
            resource_type=resource_type,
            resource_id=resource_id,
            http_method=http_method,
            endpoint=endpoint,
            request_ip=request_ip,
            status_code=status_code,
            outcome=outcome,
            severity=severity,
            error_detail=error_detail,
            extra_metadata=extra_metadata or {}
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry
    except Exception as exc:
        logger.error(f"Failed to record audit log entry: {exc}")
        if db:
            db.rollback()
        return None
