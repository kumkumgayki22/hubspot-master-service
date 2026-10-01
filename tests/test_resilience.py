import time
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import FailedExternalCall
from app.resilience.rate_limiter import RateLimiter, handle_rate_limit_response
from app.resilience.retry import is_retryable, retry_call
from app.resilience.dlq import write_to_dlq, scrub_payload


def test_rate_limiter_burst():
    limiter = RateLimiter(burst_limit=3, window_seconds=2)
    start = time.time()
    for _ in range(3):
        limiter.check_and_throttle()
    # 4th request should trigger throttle pause
    limiter.check_and_throttle()
    elapsed = time.time() - start
    assert elapsed >= 1.5


def test_is_retryable_exceptions():
    assert is_retryable(httpx.TimeoutException("Timeout")) is True
    assert is_retryable(httpx.NetworkError("Network issue")) is True

    req = httpx.Request("GET", "https://api.hubapi.com")
    res500 = httpx.Response(500, request=req)
    res404 = httpx.Response(404, request=req)

    assert is_retryable(httpx.HTTPStatusError("500 Error", request=req, response=res500)) is True
    assert is_retryable(httpx.HTTPStatusError("404 Error", request=req, response=res404)) is False


def test_retry_call_success():
    attempts = 0

    def mock_fn():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise httpx.TimeoutException("Transient error")
        return "success"

    result = retry_call(mock_fn, max_retries=3, delays=[0.01, 0.01], jitter=False)
    assert result == "success"
    assert attempts == 2


def test_scrub_payload():
    raw_payload = {
        "access_token": "secret_token_123",
        "client_id": "public_id_456",
        "nested": {
            "private_app_token": "secret_pat_789",
            "normal_field": "hello"
        }
    }
    scrubbed = scrub_payload(raw_payload)
    assert scrubbed["access_token"] == "[REDACTED]"
    assert scrubbed["client_id"] == "public_id_456"
    assert scrubbed["nested"]["private_app_token"] == "[REDACTED]"
    assert scrubbed["nested"]["normal_field"] == "hello"


def test_write_to_dlq():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    entry = write_to_dlq(
        db=session,
        target_service="HubSpot",
        operation="fetch_contacts",
        payload={"access_token": "secret123", "org_id": "org_999"},
        attempts=3,
        error=Exception("Connection reset"),
        organization_id="org_999",
        scan_id="scan_abc"
    )

    assert entry is not None
    assert entry.target_service == "HubSpot"
    assert entry.payload["access_token"] == "[REDACTED]"
    assert entry.payload["org_id"] == "org_999"
    assert entry.attempts == 3

    dlq_db = session.query(FailedExternalCall).filter(FailedExternalCall.scan_id == "scan_abc").first()
    assert dlq_db is not None

    session.close()
