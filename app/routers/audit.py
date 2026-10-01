from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import get_db
from app.db.models import AuditLog
from app.auth.hmac_auth import hmac_auth_required
from app.utils.pagination import build_pagination_info

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/logs")
def get_audit_logs(
    organization_id: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    event_category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Retrieves audit logs with optional filtering and pagination.
    """
    query = db.query(AuditLog)
    if organization_id:
        query = query.filter(AuditLog.organization_id == organization_id)
    if outcome:
        query = query.filter(AuditLog.outcome == outcome.upper())
    if event_category:
        query = query.filter(AuditLog.event_category == event_category.upper())

    total = query.count()
    offset = (page - 1) * page_size
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size).all()

    items = [
        {
            "id": log.id,
            "event_category": log.event_category,
            "event_type": log.event_type,
            "actor_client_id": log.actor_client_id,
            "actor_role": log.actor_role,
            "organization_id": log.organization_id,
            "outcome": log.outcome,
            "severity": log.severity,
            "error_detail": log.error_detail,
            "extra_metadata": log.extra_metadata,
            "created_at": log.created_at
        }
        for log in logs
    ]

    pagination = build_pagination_info(page=page, page_size=page_size, total=total)
    return {"items": items, "pagination": pagination}


@router.get("/stats")
def get_audit_stats(
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Returns audit statistics summary (totals by category, outcome, severity).
    """
    total_logs = db.query(AuditLog).count()
    success_count = db.query(AuditLog).filter(AuditLog.outcome == "SUCCESS").count()
    failure_count = db.query(AuditLog).filter(AuditLog.outcome == "FAILURE").count()
    denied_count = db.query(AuditLog).filter(AuditLog.outcome == "DENIED").count()

    categories = db.query(AuditLog.event_category, func.count(AuditLog.id)).group_by(AuditLog.event_category).all()
    by_category = {cat: count for cat, count in categories if cat}

    return {
        "total_audit_logs": total_logs,
        "outcomes": {
            "SUCCESS": success_count,
            "FAILURE": failure_count,
            "DENIED": denied_count
        },
        "by_category": by_category
    }
