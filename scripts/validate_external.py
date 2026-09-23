"""External validation: NASA POWER (UVA/UVB), CAMS UVBED, Open-Meteo UVI.

Uses only committed local artifacts (no network): calibration held-out
metrics, latest-run CAMS-derived UVI vs Open-Meteo UVI agreement, and
erythemal closure (UVI/40 vs CAMS UVBED). Temporal holdout discipline is
documented; train/test on identical targets without a held-out split is
forbidden (the UVA/UVB estimators use a year holdout; see model_metrics.json).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    y_true, y_pred = y_true[mask], y_pred[mask]
    if len(y_true) < 10:
        return {"n": 0}
    err = y_pred - y_true
    ss_res = float((err ** 2).sum())
    ss_tot = float(((y_true - y_true.mean()) ** 2).sum())
    return {
        "n": int(len(y_true)),
        "mae": round(float(np.abs(err).mean()), 4),
        "rmse": round(float(np.sqrt((err ** 2).mean())), 4),
        "bias": round(float(err.mean()), 4),
        "r2": round(float(1 - ss_res / ss_tot if ss_tot > 0 else float("nan")), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", default="data/latest/tables")
    ap.add_argument("--calibration", default="data/calibration")
    ap.add_argument("--out", default="docs/validation/external_validation.md")
    args = ap.parse_args()

    lines = ["# External validation (NASA POWER / CAMS / Open-Meteo)", ""]
    cal = Path(args.calibration)
    mm = cal / "model_metrics.json"
    if mm.exists():
        m = json.loads(mm.read_text())
        lines += ["## NASA POWER held-out (year-split) UVA/UVB estimator skill",
                  "", f"Rows: {m.get('rows')}; split year: {m.get('validation_split_year')}.",
                  "", "```json", json.dumps(m, indent=2)[:2000], "```", ""]
    else:
        lines += ["## NASA POWER", "", "model_metrics.json not found.", ""]

    latest = Path(args.latest)
    cams_p = latest / "cams_direct_forecast.parquet"
    hourly_p = latest / "tan_forecast_hourly.parquet"
    if cams_p.exists() and hourly_p.exists():
        cams = pd.read_parquet(cams_p)
        hourly = pd.read_parquet(hourly_p)
        uv = [c for c in cams.columns if "biologically_effective" in c.lower() and "clear" not in c.lower()]
        uvc = [c for c in cams.columns if "biologically_effective" in c.lower() and "clear" in c.lower()]
        lines += ["## CAMS UVBED vs Open-Meteo UVI (erythemal closure)", ""]
        if uv and uvc and "uv_index" in hourly:
            bed = pd.to_numeric(cams[uv[0]], errors="coerce").to_numpy()
            bed_c = pd.to_numeric(cams[uvc[0]], errors="coerce").to_numpy()
            cams_uvi = bed * 40.0
            # Align by nearest hour on the overlapping span (diagnostic, not training).
            ht = pd.to_datetime(hourly["time_utc"] if "time_utc" in hourly else hourly["time"], utc=True)
            ct = pd.to_datetime(cams["time_utc"], utc=True)
            om_uvi = pd.to_numeric(hourly["uv_index"], errors="coerce").to_numpy()
            # Daylight overlap only.
            day = om_uvi > 0.5
            # Resample CAMS to hourly stamps by merge_asof.
            a = pd.DataFrame({"t": ct, "cams_uvi": cams_uvi}).sort_values("t")
            b = pd.DataFrame({"t": ht, "om_uvi": om_uvi}).sort_values("t")
            merged = pd.merge_asof(b, a, on="t", direction="nearest", tolerance=pd.Timedelta("35min"))
            merged = merged.dropna(subset=["cams_uvi"])
            merged = merged[merged["om_uvi"] > 0.5]
            lines.append(f"CAMS UVBED field: `{uv[0]}` (dose rate, W/m^2 erythemal); "
                         f"CAMS UVI = 40 * UVBED; Open-Meteo `uv_index`; n_overlap_daylight={len(merged)}.")
            lines += ["", "```json",
                      json.dumps(_metrics(merged["om_uvi"].to_numpy(), merged["cams_uvi"].to_numpy()), indent=2),
                      "```", ""]
            lines += ["Stratification (error by SZA/cloud/season/AOD/ozone) requires the "
                      "multi-condition corpus and is tracked as follow-up; current report "
                      "covers topline closure plus the held-out estimator metrics above. "
                      "No training touched CAMS UVBED targets, so this comparison is independent.",
                      ""]
        else:
            lines += ["CAMS UVBED or hourly UVI columns missing.", ""]
    else:
        lines += ["## CAMS/Open-Meteo", "",
                  f"Latest tables not found under {latest}; run a live forecast first.", ""]
    lines += ["## Open-Meteo UVI self-consistency",
              "",
              "Modeled UVI in the hourly table IS Open-Meteo UVI (plus bounded HRRR/kt "
              "geometry corrections); an independent Open-Meteo check is therefore the "
              "CAMS-closure comparison above, not a self-comparison. Year-holdout "
              "discipline applies to the UVA/UVB estimators (see model_metrics.json).",
              ""]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out.read_text()[:3000])


if __name__ == "__main__":
    main()
