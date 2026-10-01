from typing import Dict, Any
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.auth.hmac_auth import hmac_auth_required
from app.auth.hubspot_auth import HubSpotAuthClient, HubSpotCredentials
from app.utils.audit import log_audit_event

router = APIRouter(prefix="/api", tags=["Credentials"])


@router.post("/validate-credentials")
def validate_credentials(
    credentials: HubSpotCredentials,
    db: Session = Depends(get_db),
    auth: Dict[str, str] = Depends(hmac_auth_required)
):
    """
    Validates HubSpot API credentials by making a lightweight test call to HubSpot CRM API.
    Does not initiate a scan job.
    """
    client = HubSpotAuthClient()
    result = client.validate_credentials(credentials)

    outcome = "SUCCESS" if result.get("valid") else "FAILURE"
    log_audit_event(
        db=db,
        event_category="CREDENTIALS",
        event_type="VALIDATE",
        actor_client_id=auth.get("client_id"),
        actor_role=auth.get("role"),
        outcome=outcome,
        status_code=result.get("status_code"),
        error_detail=result.get("message") if outcome == "FAILURE" else None
    )

    return result
