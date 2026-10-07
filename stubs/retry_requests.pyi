"""Minimal local stub for retry_requests (upstream ships no type information).

Only the surface SunStack calls is declared. ``retry`` wraps a
``requests.Session`` with backoff retries and returns the wrapped session (or a
fresh ``requests.Session`` when called without one), so the wrapped session's
type is preserved for callers.
"""

from typing import TypeVar

from requests import Session

_SessionT = TypeVar("_SessionT", bound=Session)

def retry(
    session: _SessionT | None = ...,
    retries: int = ...,
    backoff_factor: float = ...,
    status_to_retry: tuple[int, ...] = ...,
    prefixes: tuple[str, ...] = ...,
    **kwargs: object,
) -> _SessionT: ...