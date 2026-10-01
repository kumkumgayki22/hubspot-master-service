import hashlib
import hmac
import time
from typing import Dict, Optional, Tuple, Set
from fastapi import Request, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from app.config import settings

# Memory cache for used nonces with timestamp cleanup
_USED_NONCES: Dict[str, float] = {}


def _cleanup_expired_nonces():
    now = time.time()
    max_age = settings.HMAC_SIGNATURE_MAX_AGE
    expired = [nonce for nonce, ts in _USED_NONCES.items() if now - ts > max_age]
    for nonce in expired:
        _USED_NONCES.pop(nonce, None)


def compute_canonical_string(method: str, path: str, timestamp: str, nonce: str, body_bytes: bytes) -> str:
    """
    Constructs canonical string: METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)
    """
    body_hash = hashlib.sha256(body_bytes).hexdigest() if body_bytes else hashlib.sha256(b"").hexdigest()
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"


def calculate_hmac_signature(secret_key: str, canonical_string: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_hmac_signature(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    signature: str,
    client_id: str,
    body_bytes: bytes
) -> Tuple[bool, str, Optional[str]]:
    """
    Verifies signature, timestamp freshness, and nonce uniqueness.
    Returns: (is_valid, role, error_reason)
    """
    if not settings.HMAC_ENABLED:
        return True, "COORDINATOR", None

    _cleanup_expired_nonces()

    # 1. Timestamp Freshness Check
    try:
        ts_val = float(timestamp)
    except (ValueError, TypeError):
        return False, "", "INVALID_TIMESTAMP_FORMAT"

    now = time.time()
    if abs(now - ts_val) > settings.HMAC_SIGNATURE_MAX_AGE:
        return False, "", "TIMESTAMP_EXPIRED"

    # 2. Replay Prevention Check
    if nonce in _USED_NONCES:
        return False, "", "NONCE_REPLAYED"

    # 3. Determine Client Role & Secret Key
    secret_key = None
    role = ""

    if client_id == "coordinator" or client_id == "core":
        secret_key = settings.HMAC_SECRET_KEY_CORE
        role = "COORDINATOR"
    elif client_id == "engineer" or client_id == "readonly":
        secret_key = settings.HMAC_SECRET_KEY_ENGINEER
        role = "ENGINEER"
    else:
        # Fallback check based on signature match if custom client IDs are used
        expected_core = calculate_hmac_signature(
            settings.HMAC_SECRET_KEY_CORE,
            compute_canonical_string(method, path, timestamp, nonce, body_bytes)
        )
        if hmac.compare_digest(expected_core, signature):
            secret_key = settings.HMAC_SECRET_KEY_CORE
            role = "COORDINATOR"
        else:
            expected_eng = calculate_hmac_signature(
                settings.HMAC_SECRET_KEY_ENGINEER,
                compute_canonical_string(method, path, timestamp, nonce, body_bytes)
            )
            if hmac.compare_digest(expected_eng, signature):
                secret_key = settings.HMAC_SECRET_KEY_ENGINEER
                role = "ENGINEER"

    if not secret_key:
        return False, "", "INVALID_CLIENT_ID_OR_SIGNATURE"

    # 4. Verify Signature
    canonical_str = compute_canonical_string(method, path, timestamp, nonce, body_bytes)
    expected_sig = calculate_hmac_signature(secret_key, canonical_str)

    if not hmac.compare_digest(expected_sig.lower(), signature.lower()):
        return False, "", "SIGNATURE_MISMATCH"

    # Record nonce
    _USED_NONCES[nonce] = now
    return True, role, None


async def hmac_auth_required(request: Request) -> Dict[str, str]:
    """
    FastAPI dependency to enforce HMAC authentication for protected endpoints.
    """
    if not settings.HMAC_ENABLED:
        return {"client_id": "coordinator", "role": "COORDINATOR"}

    # Exempt public/health routes
    exempt_paths = {"/api/health", "/api/stats", "/docs", "/openapi.json", "/redoc", "/"}
    if request.url.path in exempt_paths:
        return {"client_id": "public", "role": "PUBLIC"}

    sig = request.headers.get("X-HS-Signature")
    ts = request.headers.get("X-HS-Timestamp")
    client_id = request.headers.get("X-HS-Client-ID")
    nonce = request.headers.get("X-HS-Nonce")

    if not all([sig, ts, client_id, nonce]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required HMAC security headers (X-HS-Signature, X-HS-Timestamp, X-HS-Client-ID, X-HS-Nonce)."
        )

    body_bytes = await request.body()
    is_valid, role, reason = verify_hmac_signature(
        method=request.method,
        path=request.url.path,
        timestamp=ts,
        nonce=nonce,
        signature=sig,
        client_id=client_id,
        body_bytes=body_bytes
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"HMAC authentication failed: {reason}"
        )

    # Role Permission Check: Engineer is Read-Only (GET only)
    if role == "ENGINEER" and request.method.upper() != "GET":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Engineer role has read-only permissions (GET operations only)."
        )

    return {"client_id": client_id, "role": role}
