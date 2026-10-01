from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Job, JobStatus, JobCheckpoint
from app.auth.hmac_auth import hmac_auth_required
from app.auth.hubspot_auth import HubSpotCredentials
from app.services.scan_engine import ScanEngine
from app.utils.pagination import build_pagination_info
from app.utils.audit import log_audit_event
from app.utils.time_utils import calculate_duration

router = APIRouter(prefix="/api/scan", tags=["Scan Jobs"])


class StartScanRequest(BaseModel):
    organization_id: str = Field(..., description="Unique organization ID")
    object_types: Optional[List[str]] = Field(
        default=None,
        description="Target HubSpot object types (e.g. contacts, companies, deals, tickets, owners). Default: all."
    )
    credentials: HubSpotCredentials
    run_in_background: bool = Field(default=True, description="Run scan task asynchronously in background")


def _execute_job_task(job_id: str):
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        engine = ScanEngine(db)
        engine.run_job(job_id)
    finally:
        db.close()


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
def start_scan(
    payload: StartScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Initiates a new HubSpot data extraction scan job for an organization.
    """
    job = Job(
        organization_id=payload.organization_id,
        status=JobStatus.PENDING.value,
        object_types=payload.object_types or ["contacts", "companies", "deals", "tickets", "owners"],
        request_config={"credentials": payload.credentials.model_dump()},
        entity_record_counts={}
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    log_audit_event(
        db=db,
        event_category="SCAN",
        event_type="START",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        organization_id=payload.organization_id,
        resource_type="JOB",
        resource_id=job.id,
        outcome="SUCCESS"
    )

    if payload.run_in_background:
        background_tasks.add_task(_execute_job_task, job.id)
    else:
        engine = ScanEngine(db)
        engine.run_job(job.id)
        db.refresh(job)

    return {
        "scan_id": job.id,
        "organization_id": job.organization_id,
        "status": job.status,
        "object_types": job.object_types,
        "created_at": job.created_at
    }


@router.get("/{scan_id}/status")
def get_scan_status(
    scan_id: str,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Retrieves the status, record counts, checkpoints, and timing details for a scan job.
    """
    job = db.query(Job).filter(Job.id == scan_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan job '{scan_id}' not found.")

    checkpoints = db.query(JobCheckpoint).filter(JobCheckpoint.scan_id == scan_id).all()
    cp_list = [
        {
            "object_type": cp.object_type,
            "cursor": cp.cursor,
            "records_processed": cp.records_processed,
            "is_completed": cp.is_completed,
            "last_updated_at": cp.last_updated_at
        }
        for cp in checkpoints
    ]

    duration_seconds = calculate_duration(job.started_at, job.completed_at)

    return {
        "scan_id": job.id,
        "organization_id": job.organization_id,
        "status": job.status,
        "object_types": job.object_types,
        "entity_record_counts": job.entity_record_counts or {},
        "checkpoints": cp_list,
        "error_detail": job.error_detail,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "normalized_at": job.normalized_at,
        "minio_uploaded_at": job.minio_uploaded_at,
        "last_heartbeat": job.last_heartbeat,
        "duration_seconds": duration_seconds
    }


@router.post("/{scan_id}/pause")
def pause_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Requests cooperative pause for an active scan job.
    """
    job = db.query(Job).filter(Job.id == scan_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan job '{scan_id}' not found.")

    if job.status not in (JobStatus.RUNNING.value, JobStatus.PENDING.value, JobStatus.RESUMING.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot pause scan job in status '{job.status}'."
        )

    job.status = JobStatus.PAUSED.value
    db.commit()

    log_audit_event(
        db=db,
        event_category="SCAN",
        event_type="PAUSE",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        organization_id=job.organization_id,
        resource_type="JOB",
        resource_id=job.id
    )

    return {"scan_id": job.id, "status": job.status, "message": "Pause signal sent."}


@router.post("/{scan_id}/resume")
def resume_scan(
    scan_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Resumes a paused scan job from its last saved cursor checkpoint.
    """
    job = db.query(Job).filter(Job.id == scan_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan job '{scan_id}' not found.")

    if job.status != JobStatus.PAUSED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume scan job in status '{job.status}'. Must be PAUSED."
        )

    job.status = JobStatus.RESUMING.value
    db.commit()

    background_tasks.add_task(_execute_job_task, job.id)

    log_audit_event(
        db=db,
        event_category="SCAN",
        event_type="RESUME",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        organization_id=job.organization_id,
        resource_type="JOB",
        resource_id=job.id
    )

    return {"scan_id": job.id, "status": job.status, "message": "Resume task initiated."}


@router.post("/{scan_id}/cancel")
def cancel_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Cancels an active or paused scan job.
    """
    job = db.query(Job).filter(Job.id == scan_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan job '{scan_id}' not found.")

    if job.status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job '{scan_id}' is already in terminal state '{job.status}'."
        )

    job.status = JobStatus.CANCELLED.value
    db.commit()

    log_audit_event(
        db=db,
        event_category="SCAN",
        event_type="CANCEL",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        organization_id=job.organization_id,
        resource_type="JOB",
        resource_id=job.id
    )

    return {"scan_id": job.id, "status": job.status, "message": "Scan job cancelled."}


@router.get("/list")
def list_scans(
    organization_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Lists scan jobs with optional filtering by organization_id and status.
    """
    query = db.query(Job)
    if organization_id:
        query = query.filter(Job.organization_id == organization_id)
    if status_filter:
        query = query.filter(Job.status == status_filter.upper())

    total = query.count()
    offset = (page - 1) * page_size
    jobs = query.order_by(Job.created_at.desc()).offset(offset).limit(page_size).all()

    items = [
        {
            "scan_id": j.id,
            "organization_id": j.organization_id,
            "status": j.status,
            "object_types": j.object_types,
            "entity_record_counts": j.entity_record_counts,
            "created_at": j.created_at,
            "completed_at": j.completed_at
        }
        for j in jobs
    ]

    pagination = build_pagination_info(page=page, page_size=page_size, total=total)
    return {"items": items, "pagination": pagination}


@router.get("/statistics")
def get_scan_statistics(
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Returns global aggregate statistics across all scan jobs.
    """
    total_jobs = db.query(Job).count()
    completed_jobs = db.query(Job).filter(Job.status == JobStatus.COMPLETED.value).count()
    failed_jobs = db.query(Job).filter(Job.status == JobStatus.FAILED.value).count()
    running_jobs = db.query(Job).filter(Job.status == JobStatus.RUNNING.value).count()
    paused_jobs = db.query(Job).filter(Job.status == JobStatus.PAUSED.value).count()
    crashed_jobs = db.query(Job).filter(Job.status == JobStatus.CRASHED.value).count()

    all_jobs = db.query(Job).all()
    total_records = 0
    for j in all_jobs:
        counts = j.entity_record_counts or {}
        total_records += sum(counts.values())

    return {
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "running_jobs": running_jobs,
        "paused_jobs": paused_jobs,
        "crashed_jobs": crashed_jobs,
        "total_records_extracted": total_records
    }


@router.delete("/{scan_id}/remove", status_code=status.HTTP_200_OK)
def remove_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Deletes a scan job record and its associated checkpoints.
    """
    job = db.query(Job).filter(Job.id == scan_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan job '{scan_id}' not found.")

    org_id = job.organization_id
    db.delete(job)
    db.commit()

    log_audit_event(
        db=db,
        event_category="SCAN",
        event_type="REMOVE",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        organization_id=org_id,
        resource_type="JOB",
        resource_id=scan_id
    )

    return {"scan_id": scan_id, "message": "Scan job removed successfully."}
