import os
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Job, JobStatus
from app.auth.hmac_auth import hmac_auth_required
from app.normalization.normalizer import DataNormalizer, SUPPORTED_OBJECT_TYPES
from app.config import settings

router = APIRouter(prefix="/api/normalization", tags=["Normalization"])


@router.get("/supported-objects")
def get_supported_objects():
    """
    Returns list of supported HubSpot object types for data extraction & normalization.
    """
    return {
        "supported_objects": SUPPORTED_OBJECT_TYPES,
        "count": len(SUPPORTED_OBJECT_TYPES)
    }


@router.post("/{scan_id}/normalize")
def normalize_scan_data(
    scan_id: str,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Triggers normalization on extracted JSON data for a scan job.
    """
    job = db.query(Job).filter(Job.id == scan_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan job '{scan_id}' not found.")

    job_dir = os.path.join(settings.LOCAL_STORAGE_DIR, job.id)
    if not os.path.exists(job_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No local extracted data found for scan job '{scan_id}'."
        )

    job.status = JobStatus.NORMALIZING.value
    db.commit()

    normalized_files: Dict[str, Any] = {}
    target_objects = job.object_types or SUPPORTED_OBJECT_TYPES

    for obj_type in target_objects:
        raw_file = os.path.join(job_dir, f"{obj_type}.jsonl")
        recs = ScanEngine._load_raw_jsonl(raw_file) if hasattr(ScanEngine, "_load_raw_jsonl") else []
        pq_path, count = DataNormalizer.normalize_to_parquet(
            object_type=obj_type,
            records=recs,
            output_dir=job_dir,
            scan_id=job.id
        )
        normalized_files[obj_type] = {
            "parquet_file": pq_path,
            "record_count": count,
            "size_bytes": os.path.getsize(pq_path) if os.path.exists(pq_path) else 0
        }

    return {
        "scan_id": job.id,
        "status": "SUCCESS",
        "normalized_tables": normalized_files
    }


@router.get("/{scan_id}/tables")
def get_normalized_tables(
    scan_id: str,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Lists normalized parquet files and details for a scan job.
    """
    job = db.query(Job).filter(Job.id == scan_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan job '{scan_id}' not found.")

    job_dir = os.path.join(settings.LOCAL_STORAGE_DIR, job.id)
    tables = []

    target_objects = job.object_types or SUPPORTED_OBJECT_TYPES
    for obj_type in target_objects:
        pq_file = os.path.join(job_dir, f"{obj_type}_{scan_id}.parquet")
        if os.path.exists(pq_file):
            size = os.path.getsize(pq_file)
            minio_key = DataNormalizer.normalize_to_parquet.__module__  # placeholder
            object_key = f"hubspot/{obj_type}/glynac_organization_id={job.organization_id}/processing_date={job.created_at.date().isoformat()}/{obj_type}.parquet"
            tables.append({
                "table_name": obj_type,
                "local_file": pq_file,
                "size_bytes": size,
                "minio_object_key": object_key
            })

    return {
        "scan_id": job.id,
        "organization_id": job.organization_id,
        "table_count": len(tables),
        "tables": tables
    }
