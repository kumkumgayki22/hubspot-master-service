import datetime
import uuid
from enum import Enum
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.db.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RESUMING = "RESUMING"
    NORMALIZING = "NORMALIZING"
    UPLOADING_TO_MINIO = "UPLOADING_TO_MINIO"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CRASHED = "CRASHED"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False, default=JobStatus.PENDING.value, index=True)
    
    # Configuration and object targets for run
    object_types = Column(JSON, nullable=False, default=list)
    request_config = Column(JSON, nullable=True, default=dict)
    
    # Progress and statistics
    entity_record_counts = Column(JSON, nullable=False, default=dict)
    error_detail = Column(Text, nullable=True)
    
    # Heartbeat and timing fields
    last_heartbeat = Column(DateTime, nullable=False, default=utc_now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    normalized_at = Column(DateTime, nullable=True)
    minio_uploaded_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    # Relationship to checkpoints
    checkpoints = relationship("JobCheckpoint", back_populates="job", cascade="all, delete-orphan")


class JobCheckpoint(Base):
    __tablename__ = "job_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    object_type = Column(String(64), nullable=False, index=True)
    
    cursor = Column(String(512), nullable=True)
    records_processed = Column(Integer, nullable=False, default=0)
    is_completed = Column(Boolean, nullable=False, default=False)
    last_updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    job = relationship("Job", back_populates="checkpoints")

    __table_args__ = (
        Index("idx_job_object_type", "scan_id", "object_type", unique=True),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_category = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    actor_client_id = Column(String(128), nullable=True)
    actor_role = Column(String(64), nullable=True)
    organization_id = Column(String(128), nullable=True, index=True)
    
    entity_type = Column(String(64), nullable=True)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(128), nullable=True)
    
    http_method = Column(String(16), nullable=True)
    endpoint = Column(String(256), nullable=True)
    request_ip = Column(String(64), nullable=True)
    status_code = Column(Integer, nullable=True)
    
    outcome = Column(String(32), nullable=False, index=True)  # SUCCESS, FAILURE, DENIED
    severity = Column(String(16), nullable=False, default="INFO")
    error_detail = Column(Text, nullable=True)
    extra_metadata = Column(JSON, nullable=True, default=dict)
    
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)


class FailedExternalCall(Base):
    __tablename__ = "failed_external_calls"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_service = Column(String(64), nullable=False, index=True)
    operation = Column(String(128), nullable=False)
    organization_id = Column(String(128), nullable=True, index=True)
    scan_id = Column(String(64), nullable=True, index=True)
    
    payload = Column(JSON, nullable=True)
    attempts = Column(Integer, nullable=False, default=1)
    last_error = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="LOGGED")
    
    created_at = Column(DateTime, nullable=False, default=utc_now)
