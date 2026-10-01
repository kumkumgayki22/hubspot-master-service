import time
import datetime
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.db.models import Job, JobStatus, FailedExternalCall
from app.storage.minio_client import MinIOStorageClient
from app.config import settings

router = APIRouter(prefix="/api", tags=["Public"])

APP_START_TIME = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


@router.get("/health", status_code=status.HTTP_200_OK)
def health_check(db: Session = Depends(get_db)):
    """
    Health check probe verifying database connectivity, MinIO availability, and service version.
    Public endpoint (no HMAC required).
    """
    db_healthy = False
    db_error = None
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception as exc:
        db_error = str(exc)

    minio_client = MinIOStorageClient()
    minio_healthy = minio_client.ensure_bucket_exists()

    overall_healthy = db_healthy and minio_healthy
    uptime_seconds = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - APP_START_TIME).total_seconds()

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "version": "1.0.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
        "uptime_seconds": round(uptime_seconds, 2),
        "checks": {
            "database": {
                "status": "up" if db_healthy else "down",
                "error": db_error
            },
            "minio_storage": {
                "status": "up" if minio_healthy else "down",
                "bucket": settings.MINIO_BUCKET,
                "endpoint": settings.MINIO_ENDPOINT
            }
        }
    }


@router.get("/stats")
def public_stats(db: Session = Depends(get_db)):
    """
    Public aggregate service metrics.
    Public endpoint (no HMAC required).
    """
    total_jobs = db.query(Job).count()
    completed_jobs = db.query(Job).filter(Job.status == JobStatus.COMPLETED.value).count()
    failed_jobs = db.query(Job).filter(Job.status == JobStatus.FAILED.value).count()
    dlq_failures = db.query(FailedExternalCall).count()

    all_jobs = db.query(Job).all()
    total_records = 0
    for j in all_jobs:
        counts = j.entity_record_counts or {}
        total_records += sum(counts.values())

    return {
        "service": settings.APP_NAME,
        "total_jobs_processed": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "total_records_extracted": total_records,
        "dead_letter_queue_entries": dlq_failures
    }
