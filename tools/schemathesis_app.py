"""ASGI entry point for schemathesis: the FastAPI app over a frozen payload.

Schemathesis needs an importable app object, while `create_app(root)` needs a page
directory holding `data.json`. Pointing it at the committed fixture keeps the run
deterministic and offline: the fuzzer exercises the request/response contracts of
the API surface, not the live feeds.
"""

from __future__ import annotations

import pathlib

from sunstack.ui import create_app

ROOT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rendered_site"
app = create_app(ROOT)
