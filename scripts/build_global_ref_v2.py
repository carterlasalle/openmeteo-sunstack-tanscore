"""Build global-mel-ref-v2 from multi-site NASA POWER UVA/UVB (Tier-B unblock).

Reads per-site POWER hourly JSON (ALLSKY_SFC_UVA/UVB, 2024) fetched live
from power.larc.nasa.gov, converts each daylight hour to E_DP,h via the
shipped Tier-C band weights (documented proxy until the uvspec corpus
emulator lands), and mints the v2 reference as the empirical p99.9 plus
fixed headroom. Writes reference.json + manifest with per-site hashes.

Usage:
  uv run python scripts/build_global_ref_v2.py --sites-dir /tmp/power_sites --out data/calibration/global_melanogenic_reference_v2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SITE_META: dict[str, tuple[float, float, str]] = {
    "london": (51.5, -0.13, "midlatitude maritime"),
    "tokyo": (35.69, 139.69, "midlatitude coastal"),
    "saopaulo": (-23.55, -46.63, "subtropical urban"),
    "nairobi": (-1.29, 36.82, "equatorial highland 1795m"),
    "newyork": (40.71, -74.0, "midlatitude coastal"),
    "sydney": (-33.87, 151.21, "subtropical coastal"),
    "reykjavik": (64.15, -21.94, "high latitude maritime"),
    "mexicocity": (19.43, -99.13, "tropical highland 2240m"),
    "dubai": (25.2, 55.27, "subtropical desert"),
    "buenosaires": (-34.6, -58.38, "midlatitude"),
    "moscow": (55.75, 37.62, "high-midlatitude continental"),
    "singapore": (1.35, 103.82, "equatorial maritime"),
}

HEADROOM_FACTOR = 1.1  # explicit fixed headroom above empirical p99.9


def main(argv: list[str] | None = None) -> None:
    import numpy as np
    import pandas as pd

    from sunstack.spectral import band_effective_weights

    ap = argparse.ArgumentParser()
    ap.add_argument("--sites-dir", default="/tmp/power_sites")
    ap.add_argument("--out", default="data/calibration/global_melanogenic_reference_v2")
    ap.add_argument("--pattern", default="power_*_2024.json")
    ns = ap.parse_args(argv)
    sdir = Path(ns.sites_dir)
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    w_uvb, w_uva = band_effective_weights()
    frames: list[pd.DataFrame] = []
    site_info: list[dict[str, object]] = []
    files = sorted(sdir.glob(ns.pattern))
    if not files:
        raise FileNotFoundError(f"no POWER site files in {sdir}/{ns.pattern}")
    for fp in files:
        slug = fp.stem.replace("power_", "").replace("_2024", "")
        lat, lon, regime = SITE_META.get(slug, (float("nan"), float("nan"), "unknown"))
        raw = fp.read_bytes()
        d = json.loads(raw)
        params = d.get("properties", {}).get("parameter", {})
        uva = params.get("ALLSKY_SFC_UVA", {})
        uvb = params.get("ALLSKY_SFC_UVB", {})
        idx = sorted(set(uva) & set(uvb))
        df = pd.DataFrame({
            "time": pd.to_datetime(idx, format="%Y%m%d%H"),
            "uva": [float(uva[t]) for t in idx],
            "uvb": [float(uvb[t]) for t in idx],
            "site": slug,
        })
        df["e_dp"] = df["uvb"] * w_uvb + df["uva"] * w_uva
        day = df[(df["uva"] > 0.5) | (df["uvb"] > 0.005)]
        frames.append(day)
        site_info.append({
            "site": slug, "lat": lat, "lon": lon, "regime": regime,
            "daylight_hours": len(day),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    all_e = np.concatenate([f["e_dp"].to_numpy() for f in frames])
    all_e = all_e[np.isfinite(all_e) & (all_e > 0)]
    p999 = float(np.quantile(all_e, 0.999))
    ref = round(p999 * HEADROOM_FACTOR, 4)
    out_ref = {
        "global_reference_version": "global-mel-ref-v2",
        "global_reference_e_mel_wm2": ref,
        "policy": "empirical p99.9 of multi-site POWER daylight E_DP,h (Tier-C band-weight proxy) plus 10% fixed headroom",
        "empirical_p999": round(p999, 4),
        "headroom_factor": HEADROOM_FACTOR,
        "n_daylight_hours": len(all_e),
        "sites": site_info,
        "band_weights": {"w_uvb": w_uvb, "w_uva": w_uva},
        "backend_note": "Tier-C broadband proxy values; replaced by Tier-B emulator convolution when the uvspec corpus lands",
    }
    (out / "reference.json").write_text(json.dumps(out_ref, indent=2) + "\n", encoding="utf-8")
    print(f"global-mel-ref-v2: {ref} W/m2 from {len(all_e)} daylight hours across {len(site_info)} sites")


if __name__ == "__main__":
    main()
