"""Minimal local stub for retry_requests (upstream ships no type information).

Only the surface SunStack calls is declared: ``retry`` wraps a
``requests.Session`` with backoff retries and returns that same session.
"""

from requests import Session

def retry(
    session: Session,
    retries: int = ...,
    backoff_factor: float = ...,
    status_to_retry: tuple[int, ...] = ...,
    prefixes: tuple[str, ...] = ...,
    **kwargs: object,
) -> Session: ...