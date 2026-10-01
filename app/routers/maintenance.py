import os
import shutil
import time
import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Job, JobStatus
from app.auth.hmac_auth import hmac_auth_required
from app.config import settings
from app.utils.audit import log_audit_event

router = APIRouter(prefix="/api/maintenance", tags=["Maintenance"])


class CleanupRequest(BaseModel):
    max_age_hours: Optional[int] = Query(24, description="Maximum age of local scan files to retain in hours")


@router.post("/cleanup")
def cleanup_local_storage(
    payload: CleanupRequest = CleanupRequest(),
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Cleans up temporary local scan data files older than specified max_age_hours.
    """
    storage_dir = settings.LOCAL_STORAGE_DIR
    if not os.path.exists(storage_dir):
        return {"deleted_dirs": 0, "freed_bytes": 0, "message": "Storage directory does not exist."}

    now = time.time()
    max_age_sec = payload.max_age_hours * 3600
    deleted_dirs = 0
    freed_bytes = 0

    for item in os.listdir(storage_dir):
        item_path = os.path.join(storage_dir, item)
        if os.path.isdir(item_path):
            mtime = os.path.getmtime(item_path)
            if now - mtime > max_age_sec:
                # Calculate size before deletion
                dir_size = sum(
                    os.path.getsize(os.path.join(dirpath, filename))
                    for dirpath, _, filenames in os.walk(item_path)
                    for filename in filenames
                )
                try:
                    shutil.rmtree(item_path)
                    deleted_dirs += 1
                    freed_bytes += dir_size
                except Exception as exc:
                    pass

    log_audit_event(
        db=db,
        event_category="MAINTENANCE",
        event_type="CLEANUP",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        outcome="SUCCESS",
        extra_metadata={"deleted_dirs": deleted_dirs, "freed_bytes": freed_bytes}
    )

    return {
        "status": "SUCCESS",
        "deleted_dirs": deleted_dirs,
        "freed_bytes": freed_bytes,
        "message": f"Cleaned up {deleted_dirs} scan directory(ies)."
    }


@router.post("/detect-crashed")
def detect_crashed_jobs(
    timeout_minutes: Optional[int] = Query(None, description="Override crash timeout in minutes"),
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Scans for active jobs whose last_heartbeat exceeds the crash timeout threshold
    and transitions their state to CRASHED.
    """
    timeout = timeout_minutes or settings.CRASH_TIMEOUT_MINUTES
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(minutes=timeout)

    active_states = [JobStatus.RUNNING.value, JobStatus.NORMALIZING.value, JobStatus.UPLOADING_TO_MINIO.value]
    stale_jobs = db.query(Job).filter(
        Job.status.in_(active_states),
        Job.last_heartbeat < cutoff
    ).all()

    crashed_ids = []
    for job in stale_jobs:
        job.status = JobStatus.CRASHED.value
        job.error_detail = f"Job heartbeat timed out (no update for >{timeout} minutes)."
        crashed_ids.append(job.id)

    if crashed_ids:
        db.commit()

    log_audit_event(
        db=db,
        event_category="MAINTENANCE",
        event_type="DETECT_CRASHED",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        outcome="SUCCESS",
        extra_metadata={"crashed_count": len(crashed_ids), "crashed_ids": crashed_ids}
    )

    return {
        "crashed_count": len(crashed_ids),
        "crashed_scan_ids": crashed_ids,
        "timeout_minutes_used": timeout
    }
