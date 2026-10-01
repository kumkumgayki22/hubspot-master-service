import time
import logging
from typing import Any, Optional, List
import httpx
from app.config import settings

logger = logging.getLogger("hubspot_master_service.rate_limiter")


class RateLimiter:
    """
    Sliding window and Retry-After rate limiter for HubSpot API requests.
    Enforces burst limit (~100 requests per 10 seconds) and handles 429 responses.
    """

    def __init__(self, burst_limit: int = None, window_seconds: int = None):
        self.burst_limit = burst_limit or settings.HUBSPOT_BURST_LIMIT
        self.window_seconds = window_seconds or settings.HUBSPOT_RATE_LIMIT_WINDOW_SECONDS
        self._request_timestamps: List[float] = []

    def check_and_throttle(self):
        """
        Proactively throttles requests if approaching burst limit.
        """
        now = time.time()
        # Remove timestamps outside window
        self._request_timestamps = [ts for ts in self._request_timestamps if now - ts <= self.window_seconds]

        if len(self._request_timestamps) >= self.burst_limit:
            oldest = self._request_timestamps[0]
            sleep_duration = self.window_seconds - (now - oldest) + 0.1
            if sleep_duration > 0:
                logger.warning(
                    f"Burst rate limit reached ({len(self._request_timestamps)} reqs in {self.window_seconds}s). "
                    f"Throttling for {sleep_duration:.2f} seconds."
                )
                time.sleep(sleep_duration)
                now = time.time()
                self._request_timestamps = [ts for ts in self._request_timestamps if now - ts <= self.window_seconds]

        self._request_timestamps.append(time.time())


def handle_rate_limit_response(response: httpx.Response) -> bool:
    """
    Detects HTTP 429 Too Many Requests response, reads Retry-After header,
    sleeps for the required time, and returns True to signal caller to retry.
    """
    if response.status_code == 429:
        retry_after_hdr = response.headers.get("Retry-After")
        retry_after_seconds = settings.HUBSPOT_DEFAULT_RETRY_AFTER

        if retry_after_hdr:
            try:
                retry_after_seconds = float(retry_after_hdr)
            except ValueError:
                retry_after_seconds = settings.HUBSPOT_DEFAULT_RETRY_AFTER

        logger.warning(
            f"HubSpot API returned 429 Too Many Requests. "
            f"Waiting {retry_after_seconds:.2f} seconds before retrying..."
        )
        time.sleep(retry_after_seconds)
        return True

    return False
