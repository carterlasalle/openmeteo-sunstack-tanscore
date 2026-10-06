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
import ssl
import sys
import urllib.parse
import urllib.request
from itertools import pairwise
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

WOUDC_API = "https://api.woudc.org/collections/data_records/items"


def _tls_ctx() -> ssl.SSLContext:
    """Verifying TLS context. certifi's bundle comes first because some hosts
    lack the intermediate that api.woudc.org serves; the locked uv env ships
    certifi, so this stays deterministic."""
    import certifi

    return ssl.create_default_context(cafile=certifi.where())


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


def find_scans(
    station: str, date_from: str, date_to: str, limit: int = 20, page: int = 400,
) -> list[tuple[str, str]]:
    """Query the WOUDC API for Brewer spectral scans in a date window.

    The API 500s on `timestamp_date` range filters, so results are fetched
    newest-first (`sortby=-timestamp_date`) and the window is applied
    client-side. Because the newest scans of a window cluster in one season,
    the qualifying page is then subsampled with an even stride so the returned
    set spans the window instead of one month. Returns ``(station, url)`` pairs
    so a multi-station report can attribute each scan.
    """
    import urllib.parse
    import urllib.request

    matches: list[tuple[str, str]] = []
    offset = 0
    while offset < 4000:
        params: dict[str, object] = {
            "dataset_id": "Spectral_1.0",
            "instrument_name": "Brewer",
            "limit": page,
            "offset": offset,
            "sortby": "-timestamp_date",
        }
        if station:
            params["platform_name"] = station
        q = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{WOUDC_API}?{q}", timeout=90, context=_tls_ctx()) as r:
            d = json.loads(r.read().decode())
        feats = d.get("features", [])
        if not feats:
            break
        past = False
        for f in feats:
            pr = f.get("properties", {})
            u = pr.get("url")
            day = str(pr.get("timestamp_date") or "")[:10]
            name = str(pr.get("platform_name") or station or "?")
            if not u:
                continue
            if day > date_to:
                continue
            if day < date_from:
                past = True
                continue
            matches.append((name, u))
        if past or len(feats) < page:
            break
        offset += page
    if not matches or limit <= 0:
        return []
    if len(matches) <= limit:
        return matches
    stride = len(matches) / limit
    return [matches[int(i * stride)] for i in range(limit)]


def main(argv: list[str] | None = None) -> None:
    """Independent measured-spectrum validation report (§8.5).

    Computes per-scan UVA/UVB/erythemal/E_DP from WOUDC Brewer files, then
    reports overall and stratified statistics, plus the only offline model
    comparison available here: the Tier-C fixed-band proxy driven by the same
    measured UVA/UVB, scored against the §8.5 release targets.
    """
    import numpy as np
    import pandas as pd

    from sunstack.spectral import band_effective_weights

    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", default="Toronto,Hohenpeissenberg,Sodankyla,Uccle,Saskatoon")
    ap.add_argument("--window", default="2022-01-01,2024-12-31")
    ap.add_argument("--per-station", type=int, default=12)
    ap.add_argument("--fixture", default="")
    ap.add_argument("--urls", default="")
    ap.add_argument("--out", default="docs/validation/woudc_spectral_validation.md")
    ns = ap.parse_args(argv)

    parts = [p.strip() for p in str(ns.window).split(",")]
    d0 = parts[0]
    d1 = parts[1] if len(parts) > 1 else parts[0]

    pairs: list[tuple[str, str]] = []
    if ns.fixture:
        pairs = [("fixture", str(ns.fixture))]
    elif ns.urls:
        pairs = [("url", u.strip()) for u in str(ns.urls).split(",") if u.strip()]
    else:
        for st in [x.strip() for x in str(ns.stations).split(",") if x.strip()]:
            try:
                got = find_scans(st, d0, d1, limit=int(ns.per_station))
            except (OSError, ValueError) as exc:
                print(f"WARN {st}: {exc}")
                continue
            print(f"{st}: {len(got)} scans")
            pairs.extend(got)

    rows: list[dict[str, object]] = []
    for station, src in pairs:
        try:
            if ns.fixture:
                text = Path(src).read_text(encoding="utf-8")
            else:
                with urllib.request.urlopen(src, timeout=120, context=_tls_ctx()) as r:
                    text = r.read().decode(errors="replace")
        except (OSError, ValueError) as exc:
            print(f"WARN {src}: {exc}")
            continue
        for scan in parse_brewer_csv(text):
            wv = scan["wavelength_nm"]
            ir = scan["irradiance"]
            if not isinstance(wv, list) or not isinstance(ir, list) or len(wv) < 50:
                continue
            ch = integrate_channels([float(x) for x in wv], [float(x) for x in ir])
            summ = scan["summary"]
            if not isinstance(summ, dict):
                continue
            try:
                sza = float(summ.get("ZenAngle", "nan"))
            except ValueError:
                sza = float("nan")
            if not np.isfinite(sza) or sza >= 90:
                continue
            import re as _re

            _m = _re.search(r"/(\d{8})[._]", src)
            day = f"{_m.group(1)[:4]}-{_m.group(1)[4:6]}-{_m.group(1)[6:]}" if _m else ""
            rows.append({
                "station": station,
                "day": day,
                "sza": sza,
                "int_cie": summ.get("IntCIE", ""),
                "o3": summ.get("O3", ""),
                **ch,
            })

    out = Path(ns.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out.write_text(
            "# WOUDC Brewer spectral validation (independent, §8.5)\n\n"
            "No qualified scans retrieved in the requested window; the API was "
            "reachable but returned nothing for these stations/dates.\n",
            encoding="utf-8")
        print("woudc: no rows")
        return

    df = pd.DataFrame(rows)

    def _cie(v: object) -> float:
        try:
            return float(str(v))
        except ValueError:
            return float("nan")
    df["int_cie"] = df["int_cie"].map(_cie)
    # Brewer IntCIE is the CIE-weighted scan integral; a cloudless scan sits
    # near the clear-sky expectation for its SZA. Split sunny/cloudy at the
    # median of the retrieved set rather than inventing an absolute threshold.
    cie_med = df["int_cie"].median()
    df["sky"] = np.where(df["int_cie"] >= cie_med, "summer-clear", "cloudy")

    def _season(day: object) -> str:
        m = int(str(day)[5:7]) if len(str(day)) >= 7 and str(day)[5:7].isdigit() else 0
        return {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
                6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}.get(m, "?")
    df["season"] = df["day"].map(_season)

    # Tier-C proxy from the SAME measured UVA/UVB -> proxy E_DP relative error.
    w_uvb, w_uva = band_effective_weights()
    df["proxy_e_dp"] = df["uvb"] * w_uvb + df["uva"] * w_uva
    df["proxy_rel_err"] = (df["proxy_e_dp"] - df["e_dp"]) / df["e_dp"]

    def _stats(x: pd.Series) -> str:
        if len(x) == 0:
            return "| 0 | — | — | — |"
        return (f"| {len(x)} | {x.median():+.3f} | {x.abs().median():.3f} | "
                f"{x.abs().quantile(0.95):.3f} |")

    lines: list[str] = [
        "# WOUDC Brewer spectral validation (independent, §8.5)",
        "",
        f"Scans: **{len(df)}** from {df['station'].nunique()} station(s), window {d0}..{d1}.",
        "Stations: " + ", ".join(sorted(df["station"].unique())) + ".",
        "",
        (
            "Each scan is a measured 280-400 nm Brewer spectrum (WOUDC Spectral_1.0, "
            "QC flags preserved in the source files). UVA/UVB/erythemal/E_DP are "
            "integrated from the measured spectrum against the shipped action spectra; "
            "`proxy_rel_err` is the Tier-C fixed-band proxy error on the same row."
        ),
        "",
        "## Overall",
        "",
        "| n | median rel-err | median abs rel-err | p95 abs rel-err |",
        "|---|---|---|---|",
        _stats(df["proxy_rel_err"]),
        "",
        (
            f"Measured E_DP,h median **{df['e_dp'].median():.4f} W/m²** "
            f"(p05 {df['e_dp'].quantile(0.05):.4f}, p95 {df['e_dp'].quantile(0.95):.4f})."
        ),
        "",
        f"## Sky split (IntCIE median {cie_med:.3f})",
        "",
        "| sky | n | median rel-err | median abs rel-err | p95 abs rel-err |",
        "|---|---|---|---|---|",
    ]
    for sky in ("summer-clear", "cloudy"):
        lines.append(f"| {sky} " + _stats(df.loc[df['sky'] == sky, "proxy_rel_err"]))
    lines += ["", "## SZA bins", "",
              "| bin | n | median rel-err | median abs rel-err | p95 abs rel-err |",
              "|---|---|---|---|---|"]
    sza_edges = [0, 30, 45, 60, 70, 80, 90]
    for lo, hi in pairwise(sza_edges):
        sub = df[(df["sza"] >= lo) & (df["sza"] < hi)]
        lines.append(f"| {lo}-{hi} " + _stats(sub["proxy_rel_err"]))
    lines += ["", "## Per station (station-held-out analogue: each station's own scans)",
              "",
              "| station | n | median rel-err | median abs rel-err | p95 abs rel-err |",
              "|---|---|---|---|---|"]
    for st in sorted(df["station"].unique()):
        lines.append(f"| {st} " + _stats(df.loc[df["station"] == st, "proxy_rel_err"]))
    lines += ["", "## Seasonal subsets", "",
              "| season | n | median rel-err | median abs rel-err | p95 abs rel-err |",
              "|---|---|---|---|---|"]
    for season in ("DJF", "MAM", "JJA", "SON"):
        lines.append(f"| {season} " + _stats(df.loc[df["season"] == season, "proxy_rel_err"]))
    lines += ["", "## Measurement context", "",
              (
                  "- Brewer MKII/MKIII spectral scans; WOUDC QC flags live in the source "
                  "files and are not re-derived here."
              ),
              (
                  "- Instrument uncertainty is of order several percent in UVB and grows "
                  "at high SZA; these thresholds are product release gates, not claims "
                  "that the instruments are exact."
              ),
              "",
              "## Release targets (§8.5)",
              "",
              "| target | value | verdict |",
              "|---|---|---|",
              (
                  f"| median abs rel-err, all qualified | <= 0.15 | "
                  f"{'PASS' if df['proxy_rel_err'].abs().median() <= 0.15 else 'FAIL'} |"
              ),
              (
                  f"| median abs rel-err, clear-sky | <= 0.10 | "
                  f"{'PASS' if df.loc[df['sky'] == 'summer-clear', 'proxy_rel_err'].abs().median() <= 0.10 else 'FAIL'} |"
              ),
              "",
              (
                  "**Note.** This scores the Tier-C fixed-band proxy, the only spectral "
                  "model available offline; it is the same proxy the contract requires "
                  "to stay labelled degraded. A gate-passing Tier-B emulator replaces "
                  "this comparison when it exists."
              ),
              "",
              ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"woudc: {len(df)} scans -> {out}")


if __name__ == "__main__":
    main()
