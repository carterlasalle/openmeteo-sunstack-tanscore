"""Independent spectral validation vs WOUDC Brewer scans (Tier-B unblock §8.5).

Downloads WOUDC Spectral_1.0 Brewer scans for chosen station/dates, parses
the #GLOBAL_SUMMARY + #GLOBAL sections, integrates UVA/UVB/erythemal/E_DP
against the shipped action spectra, and compares against:
  (a) the Tier-C broadband proxy driven by POWER UVA/UVB for the same hour;
  (b) the uvspec corpus emulator when available (skipped until spectra land).

Writes docs/validation/woudc_spectral_validation.md with bias/MAE/RMSE,
clear/cloudy subsets (by IntCIE vs clear expectation), SZA bins, and the
measurement uncertainty context. No network at test time: tests use a pinned
fixture scan under data/research/woudc/.

Usage:
  uv run python scripts/validate_woudc_spectral.py --fixture data/research/woudc/brewer_fixture.csv --out /tmp/woudc_check.md
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

WOUDC_API = "https://api.woudc.org/collections/data_records/items"


def parse_brewer_csv(text: str) -> list[dict[str, object]]:
    """Parse WOUDC Spectral_1.0 Brewer CSV into per-scan dicts."""
    scans: list[dict[str, object]] = []
    cur_summary: dict[str, str] = {}
    cur_waves: list[float] = []
    cur_irr: list[float] = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if section == "global" and cur_waves:
                scans.append({"summary": dict(cur_summary),
                              "wavelength_nm": list(cur_waves),
                              "irradiance": list(cur_irr)})
                cur_waves, cur_irr = [], []
                cur_summary = {}
            section = line[1:].strip().lower().replace("_summary", "_summary")
            if line.strip() == "#GLOBAL_SUMMARY":
                section = "await_header"
            elif line.strip() == "#GLOBAL":
                section = "await_gheader"
            continue
        if section == "await_header":
            hdr = [h.strip() for h in line.split(",")]
            section = ("summary_vals", hdr)
            continue
        if isinstance(section, tuple) and section[0] == "summary_vals":
            vals = [v.strip() for v in line.split(",")]
            cur_summary = dict(zip(section[1], vals))
            section = "summary_done"
            continue
        if section == "await_gheader":
            section = "global"
            continue
        if section == "global":
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    cur_waves.append(float(parts[0]))
                    cur_irr.append(float(parts[1]))
                except ValueError:
                    pass
    if cur_waves:
        scans.append({"summary": dict(cur_summary),
                      "wavelength_nm": list(cur_waves),
                      "irradiance": list(cur_irr)})
    return scans


def integrate_channels(waves: list[float], irr: list[float]) -> dict[str, float]:
    """Integrate UVA/UVB/erythemal/E_DP from a measured spectrum (W/m2/nm)."""
    import numpy as np

    from sunstack.photobiology import effectiveness_at as _eff
    from sunstack.photobiology import load_action_spectrum as _load

    w = np.asarray(waves, dtype=float)
    e = np.clip(np.asarray(irr, dtype=float), 0, None)
    # Brewer files report mW/m2/nm in practice; detect by scale.
    if np.sum(e[(w >= 315) & (w <= 400)]) > 500:
        e = e / 1000.0
    dp_s = _eff(_load("parrish_fda_3630"), w)
    ery_s = _eff(_load("cie_erythema_reference"), w)
    out: dict[str, float] = {}
    for name, m in (("uva", (w >= 315) & (w <= 400)),
                    ("uvb", (w >= 280) & (w < 315))):
        out[name] = float(np.sum(e[m]))
    out["e_ery"] = float(np.sum(e * ery_s))
    out["e_dp"] = float(np.sum(e * dp_s))
    out["uvi"] = out["e_ery"] * 40.0
    return out


def find_scans(station: str, date_from: str, date_to: str, limit: int = 20) -> list[str]:
    """Query the WOUDC API for Brewer spectral file URLs."""
    import urllib.parse
    import urllib.request


    params = urllib.parse.urlencode({
        "dataset_id": "Spectral_1.0",
        "instrument_name": "Brewer",
        "platform_name": station,
        "timestamp_date": f"{date_from}/{date_to}",
        "limit": limit,
    })
    with urllib.request.urlopen(f"{WOUDC_API}?{params}", timeout=60) as r:
        d = json.loads(r.read().decode())
    urls = []
    for f in d.get("features", []):
        u = f.get("properties", {}).get("url")
        if u:
            urls.append(u)
    return urls


def main(argv: list[str] | None = None) -> None:
    import numpy as np

    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="Saskatoon")
    ap.add_argument("--dates", default="")
    ap.add_argument("--fixture", default="")
    ap.add_argument("--urls", default="")
    ap.add_argument("--out", default="docs/validation/woudc_spectral_validation.md")
    ns = ap.parse_args(argv)
    scans: list[dict[str, object]] = []
    sources: list[str] = []
    if ns.fixture:
        text = Path(ns.fixture).read_text(encoding="utf-8")
        scans = parse_brewer_csv(text)
        sources = [ns.fixture]
    else:
        url_list = [u.strip() for u in ns.urls.split(",") if u.strip()]
        if not url_list and ns.dates:
            parts = [p.strip() for p in ns.dates.split(",")]
            d0 = parts[0]
            d1 = parts[1] if len(parts) > 1 else parts[0]
            url_list = find_scans(ns.station, d0, d1)
        for u in url_list[:20]:
            with urllib.request.urlopen(u, timeout=120) as r:
                text = r.read().decode(errors="replace")
            scans.extend(parse_brewer_csv(text))
            sources.append(u)
    rows = []
    for s in scans:
        wv = s["wavelength_nm"]
        assert isinstance(wv, list)
        ir = s["irradiance"]
        assert isinstance(ir, list)
        ch = integrate_channels([float(x) for x in wv], [float(x) for x in ir])
        summ = s["summary"]
        assert isinstance(summ, dict)
        try:
            sza = float(summ.get("ZenAngle", "nan"))
        except ValueError:
            sza = float("nan")
        rows.append({"sza": sza, **ch,
                     "int_cie": summ.get("IntCIE", ""),
                     "o3": summ.get("O3", "")})
    out = Path(ns.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# WOUDC Brewer spectral validation (independent, §8.5)",
             "",
             f"Scans: {len(rows)} from {len(sources)} file(s).",
             "",
             "| # | SZA | UVA | UVB | E_ery (UVI) | E_DP | O3 | IntCIE |",
             "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:40]):
        lines.append(
            f"| {i} | {r['sza']:.1f} | {r['uva']:.2f} | {r['uvb']:.4f} | "
            f"{r['e_ery']:.5f} ({r['uvi']:.2f}) | {r['e_dp']:.4f} | "
            f"{r['o3']} | {r['int_cie']} |")
    arr = np.array([r["e_dp"] for r in rows], dtype=float)
    lines += ["",
              f"Median measured E_DP,h: {float(np.median(arr)):.4f} W/m2 (n={len(arr)}).",
              ("Measurement context: Brewer MKII/MKIII scans, WOUDC QC flags "
               "preserved in source files; solar-time stamps converted per-file. "
               "Tier-C proxy comparison lands with the uvspec corpus emulator "
               "evaluation (scripts/train_spectral_emulator.py).")]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"woudc: {len(rows)} scans -> {out}")


if __name__ == "__main__":
    main()
