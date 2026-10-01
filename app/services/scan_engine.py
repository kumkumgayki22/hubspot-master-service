import os
import json
import logging
import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.db.models import Job, JobStatus, JobCheckpoint
from app.auth.hubspot_auth import HubSpotAuthClient, HubSpotCredentials
from app.services.hubspot_client import HubSpotClient
from app.normalization.normalizer import DataNormalizer, SUPPORTED_OBJECT_TYPES
from app.storage.minio_client import MinIOStorageClient
from app.resilience.dlq import write_to_dlq
from app.config import settings

logger = logging.getLogger("hubspot_master_service.scan_engine")


class ScanEngine:
    """
    Core execution engine for HubSpot extraction scan jobs.
    Handles cursor pagination, checkpointing, pause/resume, DLQ error handling,
    normalization, and MinIO uploads.
    """

    def __init__(self, db: Session):
        self.db = db
        self.auth_client = HubSpotAuthClient()
        self.minio_client = MinIOStorageClient()

    def run_job(self, job_id: str) -> Job:
        """
        Executes a scan job synchronously or inside a background task.
        """
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job with ID {job_id} not found.")

        # Update job status to RUNNING
        job.status = JobStatus.RUNNING.value
        if not job.started_at:
            job.started_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        job.last_heartbeat = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        self.db.commit()

        # Parse credentials from request_config
        req_config = job.request_config or {}
        creds_data = req_config.get("credentials", {})
        creds = HubSpotCredentials(**creds_data)

        # Get valid access token
        try:
            access_token = self.auth_client.get_access_token(creds)
        except Exception as exc:
            logger.error(f"Failed to authenticate HubSpot credentials for job {job_id}: {exc}")
            write_to_dlq(
                db=self.db,
                target_service="HubSpot",
                operation="Authenticate",
                payload=creds_data,
                attempts=1,
                error=exc,
                organization_id=job.organization_id,
                scan_id=job.id
            )
            job.status = JobStatus.FAILED.value
            job.error_detail = f"Authentication error: {exc}"
            self.db.commit()
            return job

        hubspot_client = HubSpotClient(access_token=access_token)
        target_objects = job.object_types if job.object_types else SUPPORTED_OBJECT_TYPES
        
        # Local scratch directory for job raw data and parquet files
        job_dir = os.path.join(settings.LOCAL_STORAGE_DIR, job.id)
        os.makedirs(job_dir, exist_ok=True)

        extracted_data_by_object: Dict[str, List[Dict[str, Any]]] = {}
        entity_counts: Dict[str, int] = dict(job.entity_record_counts or {})

        try:
            # 1. Extraction & Checkpointing Loop
            for obj_type in target_objects:
                # Check current job state before starting object
                self.db.refresh(job)
                if job.status in (JobStatus.PAUSED.value, JobStatus.CANCELLED.value):
                    logger.info(f"Job {job.id} detected status '{job.status}'. Stopping extraction loop.")
                    return job

                # Fetch or create checkpoint
                checkpoint = self.db.query(JobCheckpoint).filter(
                    JobCheckpoint.scan_id == job.id,
                    JobCheckpoint.object_type == obj_type
                ).first()

                if not checkpoint:
                    checkpoint = JobCheckpoint(
                        scan_id=job.id,
                        object_type=obj_type,
                        cursor=None,
                        records_processed=0,
                        is_completed=False
                    )
                    self.db.add(checkpoint)
                    self.db.commit()
                    self.db.refresh(checkpoint)

                if checkpoint.is_completed:
                    logger.info(f"Object '{obj_type}' already marked completed for job {job.id}. Skipping.")
                    # Load previously extracted local records if present
                    raw_file = os.path.join(job_dir, f"{obj_type}.jsonl")
                    extracted_data_by_object[obj_type] = self._load_raw_jsonl(raw_file)
                    continue

                records_acc = []
                # Load any existing records accumulated so far
                raw_file = os.path.join(job_dir, f"{obj_type}.jsonl")
                if os.path.exists(raw_file):
                    records_acc = self._load_raw_jsonl(raw_file)

                current_cursor = checkpoint.cursor

                while True:
                    # Check for cooperative pause/cancel between pagination pages
                    self.db.refresh(job)
                    if job.status == JobStatus.PAUSED.value:
                        logger.info(f"Job {job.id} paused cooperatively at object {obj_type} cursor '{current_cursor}'.")
                        self._save_raw_jsonl(raw_file, records_acc)
                        return job
                    elif job.status == JobStatus.CANCELLED.value:
                        logger.info(f"Job {job.id} cancelled cooperatively at object {obj_type}.")
                        self._save_raw_jsonl(raw_file, records_acc)
                        return job

                    # Fetch page from HubSpot
                    records, next_cursor = hubspot_client.fetch_page(
                        object_type=obj_type,
                        limit=settings.HUBSPOT_DEFAULT_PAGE_SIZE,
                        after=current_cursor
                    )

                    records_acc.extend(records)

                    # Update checkpoint state
                    checkpoint.cursor = next_cursor
                    checkpoint.records_processed = len(records_acc)
                    checkpoint.is_completed = (next_cursor is None)
                    checkpoint.last_updated_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

                    # Update Job progress & heartbeat
                    entity_counts[obj_type] = len(records_acc)
                    job.entity_record_counts = entity_counts
                    job.last_heartbeat = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

                    self.db.commit()

                    current_cursor = next_cursor
                    if not current_cursor:
                        break

                # Save raw jsonl output
                self._save_raw_jsonl(raw_file, records_acc)
                extracted_data_by_object[obj_type] = records_acc

            # 2. Normalization Phase
            self.db.refresh(job)
            if job.status in (JobStatus.PAUSED.value, JobStatus.CANCELLED.value):
                return job

            job.status = JobStatus.NORMALIZING.value
            self.db.commit()

            parquet_files: Dict[str, str] = {}
            for obj_type in target_objects:
                recs = extracted_data_by_object.get(obj_type, [])
                pq_path, count = DataNormalizer.normalize_to_parquet(
                    object_type=obj_type,
                    records=recs,
                    output_dir=job_dir,
                    scan_id=job.id
                )
                parquet_files[obj_type] = pq_path

            job.normalized_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            self.db.commit()

            # 3. MinIO Upload Phase
            job.status = JobStatus.UPLOADING_TO_MINIO.value
            self.db.commit()

            processing_date = datetime.date.today().isoformat()
            for obj_type, pq_path in parquet_files.items():
                try:
                    self.minio_client.upload_file(
                        file_path=pq_path,
                        table_name=obj_type,
                        organization_id=job.organization_id,
                        processing_date=processing_date
                    )
                except Exception as upload_err:
                    logger.warning(f"MinIO upload attempt failed for {obj_type}: {upload_err}")
                    write_to_dlq(
                        db=self.db,
                        target_service="MinIO",
                        operation="UploadParquet",
                        payload={"table": obj_type, "file": pq_path},
                        attempts=1,
                        error=upload_err,
                        organization_id=job.organization_id,
                        scan_id=job.id
                    )

            job.minio_uploaded_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            job.status = JobStatus.COMPLETED.value
            job.completed_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            self.db.commit()
            logger.info(f"Job {job.id} successfully COMPLETED.")
            return job

        except Exception as exc:
            logger.error(f"Execution error in job {job_id}: {exc}", exc_info=True)
            write_to_dlq(
                db=self.db,
                target_service="HubSpotMasterService",
                operation="RunJob",
                payload={"job_id": job_id},
                attempts=1,
                error=exc,
                organization_id=job.organization_id,
                scan_id=job.id
            )
            job.status = JobStatus.FAILED.value
            job.error_detail = str(exc)
            self.db.commit()
            return job

    @staticmethod
    def _save_raw_jsonl(filepath: str, records: List[Dict[str, Any]]):
        with open(filepath, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")

    @staticmethod
    def _load_raw_jsonl(filepath: str) -> List[Dict[str, Any]]:
        if not os.path.exists(filepath):
            return []
        records = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        return records
