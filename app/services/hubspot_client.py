import logging
from typing import List, Dict, Any, Optional, Tuple
import httpx
from app.config import settings
from app.resilience.rate_limiter import RateLimiter, handle_rate_limit_response
from app.resilience.retry import retry_call

logger = logging.getLogger("hubspot_master_service.hubspot_client")


class HubSpotClient:
    """
    Client for interacting with HubSpot CRM API v3.
    Supports cursor-based pagination and integrates rate limiting and retries.
    """

    def __init__(self, access_token: str, rate_limiter: Optional[RateLimiter] = None):
        self.access_token = access_token
        self.rate_limiter = rate_limiter or RateLimiter()

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def fetch_page(
        self,
        object_type: str,
        limit: int = 100,
        after: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Fetches a single page of CRM records or owners using cursor pagination.
        Returns: (records, next_after_cursor)
        """
        base_url = settings.HUBSPOT_API_BASE_URL.rstrip("/")
        
        if object_type == "owners":
            url = f"{base_url}/crm/v3/owners/"
        else:
            url = f"{base_url}/crm/v3/objects/{object_type}"

        params: Dict[str, Any] = {"limit": limit}
        if after:
            params["after"] = after

        def _do_request():
            self.rate_limiter.check_and_throttle()
            with httpx.Client(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
                resp = client.get(url, headers=self._get_headers(), params=params)
                
                # Check for 429 rate limit
                if handle_rate_limit_response(resp):
                    # Retry call after sleep inside handle_rate_limit_response
                    resp = client.get(url, headers=self._get_headers(), params=params)
                
                resp.raise_for_status()
                return resp.json()

        data = retry_call(
            _do_request,
            op_label=f"HubSpot API fetch_page ({object_type})"
        )

        results = data.get("results", [])
        
        # Extract next cursor
        next_cursor = None
        paging = data.get("paging")
        if paging and isinstance(paging, dict):
            next_info = paging.get("next")
            if next_info and isinstance(next_info, dict):
                next_cursor = next_info.get("after")

        return results, next_cursor
