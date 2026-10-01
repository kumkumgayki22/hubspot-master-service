import time
import httpx
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from app.config import settings


class HubSpotCredentials(BaseModel):
    private_app_token: Optional[str] = Field(default=None, description="HubSpot Private App Token (Bearer)")
    access_token: Optional[str] = Field(default=None, description="OAuth 2.0 Access Token")
    refresh_token: Optional[str] = Field(default=None, description="OAuth 2.0 Refresh Token")
    client_id: Optional[str] = Field(default=None, description="HubSpot OAuth Client ID")
    client_secret: Optional[str] = Field(default=None, description="HubSpot OAuth Client Secret")
    expires_at: Optional[float] = Field(default=None, description="Token expiration unix timestamp")


class HubSpotAuthClient:
    """
    Manages OAuth token retrieval/refreshing and credentials validation.
    Caches access tokens until near expiry.
    """

    def __init__(self):
        self._token_cache: Dict[str, Dict[str, Any]] = {}

    def get_access_token(self, credentials: HubSpotCredentials) -> str:
        """
        Returns a valid access token for the given credentials.
        Refreshes OAuth tokens automatically if near expiry.
        """
        # 1. Private App Token check
        if credentials.private_app_token:
            return credentials.private_app_token

        # 2. Existing valid access token check
        now = time.time()
        if credentials.access_token:
            # Check if expires_at is available and still valid (5 minute buffer)
            if not credentials.expires_at or credentials.expires_at > (now + 300):
                return credentials.access_token

        # 3. Refresh token exchange
        if credentials.refresh_token:
            client_id = credentials.client_id or settings.HUBSPOT_CLIENT_ID
            client_secret = credentials.client_secret or settings.HUBSPOT_CLIENT_SECRET
            
            if not client_id or not client_secret:
                raise ValueError("Missing client_id or client_secret required for OAuth refresh.")

            # Check local cache first
            cache_key = f"{client_id}:{credentials.refresh_token}"
            cached = self._token_cache.get(cache_key)
            if cached and cached["expires_at"] > (now + 300):
                return cached["access_token"]

            # Perform refresh HTTP call
            payload = {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": credentials.refresh_token,
            }

            with httpx.Client(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
                res = client.post(settings.HUBSPOT_TOKEN_URL, data=payload)
                if res.status_code != 200:
                    raise ValueError(f"Failed to refresh HubSpot access token: {res.status_code} - {res.text}")
                
                data = res.json()
                new_token = data["access_token"]
                expires_in = data.get("expires_in", 21600)  # default 6 hours
                new_expires_at = now + expires_in
                
                self._token_cache[cache_key] = {
                    "access_token": new_token,
                    "expires_at": new_expires_at
                }
                return new_token

        if credentials.access_token:
            return credentials.access_token

        raise ValueError("No valid authentication token provided in HubSpot credentials.")

    def validate_credentials(self, credentials: HubSpotCredentials) -> Dict[str, Any]:
        """
        Validates credentials via a lightweight identity call without starting a scan job.
        """
        token = self.get_access_token(credentials)
        headers = {"Authorization": f"Bearer {token}"}
        
        # Test endpoint: CRM contacts list with limit 1
        url = f"{settings.HUBSPOT_API_BASE_URL.rstrip('/')}/crm/v3/objects/contacts?limit=1"

        with httpx.Client(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            res = client.get(url, headers=headers)
            if res.status_code == 200:
                return {
                    "valid": True,
                    "status_code": 200,
                    "message": "Credentials successfully validated against HubSpot API."
                }
            elif res.status_code in (401, 403):
                return {
                    "valid": False,
                    "status_code": res.status_code,
                    "message": f"Authentication failed: {res.text}"
                }
            else:
                return {
                    "valid": False,
                    "status_code": res.status_code,
                    "message": f"Unexpected response from HubSpot API: {res.text}"
                }
