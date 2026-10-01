import time
import pytest
from app.config import settings
from app.auth.hmac_auth import (
    compute_canonical_string,
    calculate_hmac_signature,
    verify_hmac_signature
)


def test_canonical_string_computation():
    canonical = compute_canonical_string(
        method="POST",
        path="/api/scan/start",
        timestamp="1600000000",
        nonce="nonce_123",
        body_bytes=b'{"org_id":"test"}'
    )
    assert canonical.startswith("POST\n/api/scan/start\n1600000000\nnonce_123\n")


def test_hmac_signature_verification_success():
    method = "POST"
    path = "/api/scan/start"
    ts = str(time.time())
    nonce = f"nonce_test_{time.time()}"
    body = b'{"organization_id":"org_1"}'
    
    canonical = compute_canonical_string(method, path, ts, nonce, body)
    sig = calculate_hmac_signature(settings.HMAC_SECRET_KEY_CORE, canonical)

    valid, role, reason = verify_hmac_signature(
        method=method,
        path=path,
        timestamp=ts,
        nonce=nonce,
        signature=sig,
        client_id="coordinator",
        body_bytes=body
    )
    assert valid is True
    assert role == "COORDINATOR"
    assert reason is None


def test_hmac_signature_engineer_role():
    method = "GET"
    path = "/api/scan/list"
    ts = str(time.time())
    nonce = f"nonce_eng_{time.time()}"
    body = b""
    
    canonical = compute_canonical_string(method, path, ts, nonce, body)
    sig = calculate_hmac_signature(settings.HMAC_SECRET_KEY_ENGINEER, canonical)

    valid, role, reason = verify_hmac_signature(
        method=method,
        path=path,
        timestamp=ts,
        nonce=nonce,
        signature=sig,
        client_id="engineer",
        body_bytes=body
    )
    assert valid is True
    assert role == "ENGINEER"


def test_hmac_expired_timestamp():
    method = "GET"
    path = "/api/scan/list"
    expired_ts = str(time.time() - 1000)  # > 300 sec ago
    nonce = f"nonce_exp_{time.time()}"
    body = b""
    
    canonical = compute_canonical_string(method, path, expired_ts, nonce, body)
    sig = calculate_hmac_signature(settings.HMAC_SECRET_KEY_CORE, canonical)

    valid, role, reason = verify_hmac_signature(
        method=method,
        path=path,
        timestamp=expired_ts,
        nonce=nonce,
        signature=sig,
        client_id="coordinator",
        body_bytes=body
    )
    assert valid is False
    assert reason == "TIMESTAMP_EXPIRED"


def test_hmac_nonce_replay():
    method = "GET"
    path = "/api/scan/list"
    ts = str(time.time())
    nonce = f"nonce_replay_{time.time()}"
    body = b""
    
    canonical = compute_canonical_string(method, path, ts, nonce, body)
    sig = calculate_hmac_signature(settings.HMAC_SECRET_KEY_CORE, canonical)

    # First call - valid
    valid1, role1, reason1 = verify_hmac_signature(
        method=method, path=path, timestamp=ts, nonce=nonce, signature=sig, client_id="coordinator", body_bytes=body
    )
    assert valid1 is True

    # Second call with same nonce - replayed
    valid2, role2, reason2 = verify_hmac_signature(
        method=method, path=path, timestamp=ts, nonce=nonce, signature=sig, client_id="coordinator", body_bytes=body
    )
    assert valid2 is False
    assert reason2 == "NONCE_REPLAYED"
