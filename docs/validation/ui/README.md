# UI verification artifacts (§32.E)

Static export of `docs/index.html` (south-bend, the current published renderer),
captured in a real Chromium at the shipped widths. Equivalent evidence for the
pacific-palisades export is identical because both pages are generated from the
same `src/sunstack/serving.py` renderer.

| artifact | width | shows |
|---|---|---|
| `desktop-full.webp` | 1280 px | full page: hero (strongest + best-usable 30 min, confidence, `Local` / `Overall` / `Abs`), surface selector, day strip, day charts, hourly table with per-row `Local`, 30-minute table with a `Local` column, provenance line with `backend tierC-broadband-proxy-v2 (tier C)` |
| `mobile-full.webp` | 390 px | the same page at the narrow layout; no horizontal overflow (`scrollWidth == viewport`), every section present, headings H1 → H2 → H3 in order |
| `surface-selector.webp` | 1280 px | the surface control in its default `Unknown` state with the local-vs-regional explanation line ("At the default, flat, horizontal pose, ground reflection is geometrically zero…") |

## What each contract requirement maps to

- **desktop** — `desktop-full.webp`
- **narrow/mobile** — `mobile-full.webp`
- **surface selector** — `surface-selector.webp` (and the selector inside `desktop-full.webp`)
- **strongest vs best usable window** — hero line in `desktop-full.webp`:
  "Strongest 30 min 1:30 PM – 2 PM — 1124.3 E_mel J/m²; best usable 30 min … "
- **provenance/backend tier** — the hero's `backend tierC-broadband-proxy-v2 (tier C)` plus
  the `Advanced / Photobiology` provenance row
- **unknown/degraded state** — `Surface Unknown` in the controls, and the Tier-C
  degraded backend label; the missing-weather `UNKNOWN` feasibility path is covered
  by `tests/test_v5_feasibility.py::test_missing_required_weather_is_unknown_not_perfect`
  rather than a screenshot, because it needs a live frame with a missing field.

Recaptured 2026-10-06 against renderer commit `7f1fb96` (cool-neutral palette +
correct heading outline). Regenerate with a headless browser against a local
`python3 -m http.server` over `docs/`.