import requests
from requests.adapters import HTTPAdapter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from urllib3.util.retry import Retry


class RetriableAPIError(Exception):
    """Raised when an API error is retriable (transient)."""

    pass


class NonRetriableAPIError(Exception):
    """Raised when an API error should not be retried (e.g., 401, 403)."""

    pass


def build_session(
    retries: int = 3,
    backoff_factor: float = 1.0,
    status_forcelist=(429, 500, 502, 503, 504),
) -> requests.Session:
    """Build a requests.Session with retry logic.

    Uses urllib3's Retry adapter for automatic retries on transient errors.
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "POST", "PUT", "DELETE"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def retry_on_transient(max_attempts: int = 4):
    """Tenacity decorator for retrying on transient errors.

    Use on async/sync functions that make external calls.
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(
            (requests.ConnectionError, requests.Timeout, RetriableAPIError)
        ),
        reraise=True,
    )
