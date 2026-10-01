import time
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import Base, get_db
from app.db.models import Job, JobStatus, AuditLog
from app.config import settings
from app.auth.hmac_auth import compute_canonical_string, calculate_hmac_signature

# Setup shared in-memory SQLite database for testing FastAPI routes
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _get_hmac_headers(method: str, path: str, body: bytes = b"", client_id: str = "coordinator", secret: str = None) -> dict:
    sec = secret or settings.HMAC_SECRET_KEY_CORE
    ts = str(time.time())
    nonce = f"test_nonce_{time.time()}_{path.replace('/', '_')}"
    canonical = compute_canonical_string(method, path, ts, nonce, body)
    sig = calculate_hmac_signature(sec, canonical)
    return {
        "X-HS-Signature": sig,
        "X-HS-Timestamp": ts,
        "X-HS-Client-ID": client_id,
        "X-HS-Nonce": nonce,
        "Content-Type": "application/json"
    }


def test_public_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "version" in data


def test_public_stats():
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "service" in data


def test_validate_credentials():
    payload = {"private_app_token": "pat-na1-test-token"}
    path = "/api/validate-credentials"
    body_bytes = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    headers = _get_hmac_headers("POST", path, body=body_bytes)

    with patch("app.auth.hubspot_auth.HubSpotAuthClient.validate_credentials") as mock_val:
        mock_val.return_value = {"valid": True, "status_code": 200, "message": "Credentials valid."}
        res = client.post(path, json=payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["valid"] is True


def test_scan_lifecycle_api():
    path_start = "/api/scan/start"
    body_dict = {
        "organization_id": "org_api_test",
        "object_types": ["contacts"],
        "credentials": {"private_app_token": "pat-12345"},
        "run_in_background": False
    }

    body_bytes = json.dumps(body_dict, separators=(',', ':')).encode("utf-8")

    with patch("app.services.scan_engine.ScanEngine.run_job") as mock_run:
        mock_run.return_value = None
        
        headers = _get_hmac_headers("POST", path_start, body=body_bytes)
        res_start = client.post(path_start, json=body_dict, headers=headers)
        assert res_start.status_code == 202
        scan_id = res_start.json()["scan_id"]
        assert scan_id is not None

        # Get status
        path_status = f"/api/scan/{scan_id}/status"
        headers_status = _get_hmac_headers("GET", path_status)
        res_status = client.get(path_status, headers=headers_status)
        assert res_status.status_code == 200
        assert res_status.json()["organization_id"] == "org_api_test"

        # List scans
        path_list = "/api/scan/list"
        headers_list = _get_hmac_headers("GET", path_list)
        res_list = client.get(path_list, headers=headers_list)
        assert res_list.status_code == 200
        assert len(res_list.json()["items"]) >= 1

        # Scan statistics
        path_stats = "/api/scan/statistics"
        headers_stats = _get_hmac_headers("GET", path_stats)
        res_stats = client.get(path_stats, headers=headers_stats)
        assert res_stats.status_code == 200
        assert "total_jobs" in res_stats.json()

        # Pause scan
        path_pause = f"/api/scan/{scan_id}/pause"
        headers_pause = _get_hmac_headers("POST", path_pause)
        res_pause = client.post(path_pause, headers=headers_pause)
        assert res_pause.status_code == 200
        assert res_pause.json()["status"] == "PAUSED"

        # Resume scan
        path_resume = f"/api/scan/{scan_id}/resume"
        headers_resume = _get_hmac_headers("POST", path_resume)
        res_resume = client.post(path_resume, headers=headers_resume)
        assert res_resume.status_code == 200
        assert res_resume.json()["status"] == "RESUMING"

        # Cancel scan
        path_cancel = f"/api/scan/{scan_id}/cancel"
        headers_cancel = _get_hmac_headers("POST", path_cancel)
        res_cancel = client.post(path_cancel, headers=headers_cancel)
        assert res_cancel.status_code == 200
        assert res_cancel.json()["status"] == "CANCELLED"

        # Remove scan
        path_remove = f"/api/scan/{scan_id}/remove"
        headers_remove = _get_hmac_headers("DELETE", path_remove)
        res_remove = client.delete(path_remove, headers=headers_remove)
        assert res_remove.status_code == 200


def test_normalization_api():
    path_supp = "/api/normalization/supported-objects"
    headers = _get_hmac_headers("GET", path_supp)
    res = client.get(path_supp, headers=headers)
    assert res.status_code == 200
    assert "contacts" in res.json()["supported_objects"]


def test_maintenance_api():
    path_crashed = "/api/maintenance/detect-crashed"
    headers = _get_hmac_headers("POST", path_crashed)
    res = client.post(path_crashed, headers=headers)
    assert res.status_code == 200
    assert "crashed_count" in res.json()


def test_audit_api():
    path_logs = "/api/audit/logs"
    headers = _get_hmac_headers("GET", path_logs)
    res = client.get(path_logs, headers=headers)
    assert res.status_code == 200
    assert "items" in res.json()

    path_stats = "/api/audit/stats"
    headers_stats = _get_hmac_headers("GET", path_stats)
    res_stats = client.get(path_stats, headers=headers_stats)
    assert res_stats.status_code == 200
    assert "total_audit_logs" in res_stats.json()
