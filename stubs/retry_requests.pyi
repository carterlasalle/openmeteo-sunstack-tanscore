"""Minimal local stub for retry_requests (upstream ships no type information).

Only the surface SunStack calls is declared: ``retry`` wraps a
``requests.Session`` with backoff retries and returns the wrapped session (or a
fresh ``requests.Session`` when called without one).
"""

from requests import Session

def retry(
    session: Session | None = ...,
    **_kwargs: object,
) -> Session: ...