import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Job, JobStatus, JobCheckpoint
from app.services.scan_engine import ScanEngine


def test_scan_engine_successful_run():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    job = Job(
        organization_id="org_test_scan",
        status=JobStatus.PENDING.value,
        object_types=["contacts"],
        request_config={"credentials": {"private_app_token": "pat-test-12345"}}
    )
    db.add(job)
    db.commit()

    # Mock HubSpot API responses
    mock_records = [
        {"id": "1", "properties": {"firstname": "Test1"}, "createdAt": "2023-01-01", "archived": False},
        {"id": "2", "properties": {"firstname": "Test2"}, "createdAt": "2023-01-01", "archived": False}
    ]

    with patch("app.services.scan_engine.HubSpotClient") as mock_client_cls, \
         patch("app.services.scan_engine.MinIOStorageClient") as mock_minio_cls:
        
        mock_client = MagicMock()
        mock_client.fetch_page.return_value = (mock_records, None)
        mock_client_cls.return_value = mock_client

        mock_minio = MagicMock()
        mock_minio.ensure_bucket_exists.return_value = True
        mock_minio.upload_file.return_value = {"success": True}
        mock_minio_cls.return_value = mock_minio

        scan_engine = ScanEngine(db)
        finished_job = scan_engine.run_job(job.id)

        assert finished_job.status == JobStatus.COMPLETED.value
        assert finished_job.entity_record_counts["contacts"] == 2
        assert finished_job.completed_at is not None

        cp = db.query(JobCheckpoint).filter(JobCheckpoint.scan_id == job.id, JobCheckpoint.object_type == "contacts").first()
        assert cp is not None
        assert cp.is_completed is True
        assert cp.records_processed == 2

    db.close()


def test_scan_engine_cooperative_pause():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    job = Job(
        organization_id="org_test_pause",
        status=JobStatus.PAUSED.value,
        object_types=["contacts"],
        request_config={"credentials": {"private_app_token": "pat-test-12345"}}
    )
    db.add(job)
    db.commit()

    with patch("app.services.scan_engine.HubSpotClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.fetch_page.return_value = ([{"id": "1", "properties": {}}], "cursor_page_2")
        mock_client_cls.return_value = mock_client

        scan_engine = ScanEngine(db)
        paused_job = scan_engine.run_job(job.id)

        assert paused_job.status == JobStatus.PAUSED.value

    db.close()
