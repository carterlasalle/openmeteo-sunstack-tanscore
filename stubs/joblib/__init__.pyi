"""Minimal local stubs for joblib (upstream ships none).

Only the surface SunStack uses is declared. ``load`` returns ``object``, not
``Any``: unpickling yields an arbitrary shape, so callers narrow the value at
the bundle boundary instead of silently inheriting ``Any``.
"""

from os import PathLike

def load(
    filename: str | PathLike[str],
    mmap_mode: str | None = ...,
    *,
    ensure_native_byte_order: str = ...,
) -> object: ...
def dump(
    value: object,
    filename: str | PathLike[str],
    compress: int | tuple[int, int] = ...,
    protocol: int | None = ...,
) -> list[str]: ...