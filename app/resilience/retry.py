import time
import random
import logging
from typing import Callable, Any, List, Optional
import httpx
from app.config import settings

logger = logging.getLogger("hubspot_master_service.retry")


def is_retryable(exc: Exception) -> bool:
    """
    Classifies transient errors as retryable.
    429 is handled separately by the rate limiter.
    500/502/503/504 and connection/timeout errors are retryable.
    400/401/403/404 are non-retryable.
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError, httpx.ReadTimeout)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in (500, 502, 503, 504):
            return True

    return False


def retry_call(
    fn: Callable[[], Any],
    max_retries: Optional[int] = None,
    delays: Optional[List[float]] = None,
    jitter: bool = True,
    op_label: str = "External Operation"
) -> Any:
    """
    Executes fn with exponential backoff retries for transient errors.
    """
    retries = max_retries if max_retries is not None else settings.EXTERNAL_CALL_MAX_RETRIES
    delay_list = delays if delays is not None else settings.EXTERNAL_CALL_RETRY_DELAYS

    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            attempt += 1
            if not is_retryable(exc) or attempt > retries:
                logger.error(f"{op_label} failed after {attempt} attempt(s): {exc}")
                raise exc

            # Calculate backoff delay
            base_delay = delay_list[min(attempt - 1, len(delay_list) - 1)]
            sleep_time = base_delay + (random.uniform(0, 0.5) if jitter else 0)
            
            logger.warning(
                f"{op_label} failed with retryable error ({exc}). "
                f"Attempt {attempt}/{retries}. Retrying in {sleep_time:.2f}s..."
            )
            time.sleep(sleep_time)
