import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db.database import Base
from app.db.models import Job, JobCheckpoint, AuditLog, FailedExternalCall, JobStatus
from app.utils.encryption import Encrypter
from app.utils.serialization import deep_serialize
from app.utils.time_utils import calculate_duration


def test_settings_load():
    assert settings.APP_NAME == "HubSpot Master Service"
    assert settings.HMAC_SIGNATURE_MAX_AGE == 300
    assert settings.HUBSPOT_BURST_LIMIT == 100


def test_db_models_instantiation():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    job = Job(
        organization_id="org_test_123",
        status=JobStatus.PENDING.value,
        object_types=["contacts", "deals"]
    )
    session.add(job)
    session.commit()

    assert job.id is not None
    assert job.status == "PENDING"

    cp = JobCheckpoint(
        scan_id=job.id,
        object_type="contacts",
        cursor="cursor_abc",
        records_processed=50
    )
    session.add(cp)
    session.commit()

    assert cp.scan_id == job.id
    assert cp.records_processed == 50

    session.close()


def test_encrypter():
    encrypter = Encrypter("secret-test-key")
    secret_text = "pat-na1-12345678-abcd"
    encrypted = encrypter.encrypt(secret_text)
    assert encrypted != secret_text

    decrypted = encrypter.decrypt(encrypted)
    assert decrypted == secret_text


def test_deep_serialize():
    data = {
        "timestamp": datetime.datetime(2023, 1, 1, 12, 0, 0),
        "status": JobStatus.COMPLETED,
        "items": [1, "two", 3.0]
    }
    serialized = deep_serialize(data)
    assert serialized["status"] == "COMPLETED"
    assert "2023-01-01" in serialized["timestamp"]


def test_time_utils():
    start = datetime.datetime(2023, 1, 1, 12, 0, 0)
    end = datetime.datetime(2023, 1, 1, 12, 0, 30)
    duration = calculate_duration(start, end)
    assert duration == 30.0
