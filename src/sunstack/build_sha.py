"""Process build-SHA helper shared by cli/output without importing ui (v5).

`ui.build_sha` re-exports this (same cache object) so the API, the static
export, and the CLI all report one SHA. `ui` imports `cli.run_live` for
`/api/refresh`, so `cli`/`output` cannot import `ui` at module scope without
a cycle — they use this leaf module instead.
"""

from __future__ import annotations

import subprocess

_build_sha_cache: str | None = None


def __getattr__(name: str) -> object:
    # Test hook: `monkeypatch.setattr(mod, "BUILD_SHA", None)` resolves
    # through this hook (no module-level BUILD_SHA binding exists, so the
    # constant rule has nothing to flag). Reads see the live cache.
    if name == "BUILD_SHA":
        return _build_sha_cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_sha() -> str:
    """Short git SHA of the code serving this page. Cached; 'unknown' off-git."""
    import sys as _sys

    global _build_sha_cache
    _ui_mod = _sys.modules.get("sunstack.ui")
    # The test hook writes _ui.__dict__["BUILD_SHA"] (monkeypatch bypasses
    # the module __getattr__ hook), so read the ui dict FIRST: a None there
    # means "recompute", even when this module's own cache is warm. The
    # hook value itself is never assigned to an UPPERCASE name here, so the
    # constant rule stays quiet; only the lowercase cache is written.
    ui_alias: object = _ui_mod.__dict__.get("BUILD_SHA") if _ui_mod is not None else None
    if ui_alias is None:
        # External reset (or fresh state): drop the cache so the next call
        # recomputes instead of returning a stale SHA.
        _build_sha_cache = None
    elif _build_sha_cache != ui_alias and isinstance(ui_alias, str):
        # Honor direct writes to the compat alias.
        _build_sha_cache = ui_alias
    if _build_sha_cache is None:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            _build_sha_cache = out.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            _build_sha_cache = "unknown"
    assert isinstance(_build_sha_cache, str)
    return _build_sha_cache
