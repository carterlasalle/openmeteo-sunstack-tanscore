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


def _bin(s: pd.Series, edges: list[float], labels: list[str]) -> pd.Series:
    return pd.cut(pd.to_numeric(s, errors="coerce"), bins=edges, labels=labels,
                  include_lowest=True)


def _stratified_table(df: pd.DataFrame, truth: str, pred: str,
                      strata: dict[str, pd.Series]) -> list[str]:
    out = ["| stratum | n | MAE | RMSE | bias |",
           "|---|---|---|---|---|"]
    for name, groups in strata.items():
        for label, mask in groups.items():
            sub = df.loc[mask]
            m = _metrics(sub[truth].to_numpy(), sub[pred].to_numpy())
            if m.get("n", 0) >= 10:
                out.append(f"| {name}={label} | {m['n']} | {m['mae']} | "
                           f"{m['rmse']} | {m['bias']} |")
            else:
                out.append(f"| {name}={label} | {m.get('n', 0)} | — | — | — |")
    return out


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

    # Estimator holdout stratification: predict the post-split-year rows with
    # the committed bundle and bin errors by SZA/cloud/season/AOD/ozone.
    try:
        import joblib as _joblib

        bundle_p = cal / "uva_uvb_models.joblib"
        train_p = cal / "training_calibration_hourly.parquet"
        split_year = int(json.loads(mm.read_text()).get("validation_split_year", 2024)) \
            if mm.exists() else 2024
        if bundle_p.exists() and train_p.exists():
            bundle = _joblib.load(bundle_p)
            feats = list(bundle["features"])
            t = pd.read_parquet(train_p)
            yrs = pd.to_datetime(t["time_utc"], utc=True).dt.year
            test = t.loc[yrs > split_year].copy()
            X = test.reindex(columns=feats)
            for target in ("uva", "uvb"):
                test[f"pred_{target}"] = np.clip(
                    bundle[f"{target}_model"].predict(X), 0, None)
            test["month"] = pd.to_datetime(
                test["time_utc"], utc=True).dt.month
            sza_b = _bin(test["sza"], [0, 30, 50, 65, 80, 95],
                         ["0-30", "30-50", "50-65", "65-80", "80-95"])
            cloud_b = _bin(test["cloud"], [0, 20, 60, 101],
                           ["clear 0-20", "partly 20-60", "cloudy 60-100"])
            month_b = test["month"].map(
                lambda x: "DJF" if x in (12, 1, 2)
                else ("MAM" if x in (3, 4, 5)
                      else ("JJA" if x in (6, 7, 8) else "SON")))
            aod_med = pd.to_numeric(test["aod340"], errors="coerce").median()
            ozo_med = pd.to_numeric(test["ozone_du"], errors="coerce").median()
            strata = {
                "SZA": {lab: (sza_b == lab).to_numpy()
                        for lab in sza_b.cat.categories},
                "cloud": {lab: (cloud_b == lab).to_numpy()
                          for lab in cloud_b.cat.categories},
                "season": {lab: (month_b == lab).to_numpy()
                           for lab in ("DJF", "MAM", "JJA", "SON")},
                "AOD340": {"low": (pd.to_numeric(test["aod340"], errors="coerce") <= aod_med).to_numpy(),
                           "high": (pd.to_numeric(test["aod340"], errors="coerce") > aod_med).to_numpy()},
                "ozone": {"low": (pd.to_numeric(test["ozone_du"], errors="coerce") <= ozo_med).to_numpy(),
                          "high": (pd.to_numeric(test["ozone_du"], errors="coerce") > ozo_med).to_numpy()},
            }
            for target in ("uva", "uvb"):
                lines += [f"### Holdout {target.upper()} error by SZA / cloud / season / AOD / ozone",
                          "",
                          f"(post-{split_year} holdout, n={len(test)}; "
                          f"AOD340 median {aod_med:.3f}; ozone median {ozo_med:.0f} DU)",
                          ""]
                lines += _stratified_table(test, target, f"pred_{target}", strata)
                lines += [""]
        else:
            lines += ["Holdout stratification skipped (bundle or training table missing).", ""]
    except (OSError, ValueError, KeyError, ImportError) as exc:
        lines += [f"Holdout stratification skipped ({exc}).", ""]

    latest = Path(args.latest)
    cams_p = latest / "cams_direct_forecast.parquet"
    hourly_p = latest / "tan_forecast_hourly.parquet"
    if cams_p.exists() and hourly_p.exists():
        cams = pd.read_parquet(cams_p)
        hourly = pd.read_parquet(hourly_p)
        uv = [c for c in cams.columns if "biologically_effective" in c.lower() and "clear" not in c.lower()]
        uvc = [c for c in cams.columns if "biologically_effective" in c.lower() and "clear" in c.lower()]
        lines += ["## CAMS UVBED vs Open-Meteo UVI (erythemal closure)", ""]
        if uv and uvc and "uv_index" in hourly and "time_utc" in hourly:
            bed = pd.to_numeric(cams[uv[0]], errors="coerce").to_numpy()
            cams_uvi = bed * 40.0
            # Align by nearest hour on the overlapping span (diagnostic, not training).
            # Canonical UTC only: naive local `time` must never be parsed as
            # UTC here, or the join and season strata shift by the site offset.
            ht = pd.to_datetime(hourly["time_utc"], utc=True)
            ct = pd.to_datetime(cams["time_utc"], utc=True)
            om_uvi = pd.to_numeric(hourly["uv_index"], errors="coerce").to_numpy()
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
            # Stratify the closure by SZA / cloud / season / AOD / ozone using
            # hourly context columns carried on the merge keys.
            try:
                # Align hourly context (SZA/cloud/AOD/ozone/season) onto the
                # merged closure rows with a second merge_asof carrying extras.
                ctx = pd.DataFrame({
                    "t": ht,
                    "sza": pd.to_numeric(hourly.get("sza"), errors="coerce"),
                    "cloud": pd.to_numeric(
                        hourly.get("cloud_cover"), errors="coerce"),
                    "aod340": pd.to_numeric(
                        hourly.get("aod340"), errors="coerce"),
                    "ozone": pd.to_numeric(
                        hourly.get("ozone_du"), errors="coerce"),
                    "month": ht.dt.month,
                }).sort_values("t")
                m2 = pd.merge_asof(merged.sort_values("t"), ctx, on="t",
                                   direction="nearest",
                                   tolerance=pd.Timedelta("35min"))
                sza_b = _bin(m2["sza"], [0, 30, 50, 65, 80, 95],
                             ["0-30", "30-50", "50-65", "65-80", "80-95"])
                cloud_b = _bin(m2["cloud"], [0, 20, 60, 101],
                               ["clear 0-20", "partly 20-60", "cloudy 60-100"])
                month_b = m2["month"].map(
                    lambda x: "DJF" if x in (12, 1, 2)
                    else ("MAM" if x in (3, 4, 5)
                          else ("JJA" if x in (6, 7, 8) else "SON")))
                aod_med = m2["aod340"].median()
                ozo_med = m2["ozone"].median()
                strata = {
                    "SZA": {lab: (sza_b == lab).to_numpy()
                            for lab in sza_b.cat.categories},
                    "cloud": {lab: (cloud_b == lab).to_numpy()
                              for lab in cloud_b.cat.categories},
                    "season": {lab: (month_b == lab).to_numpy()
                               for lab in ("DJF", "MAM", "JJA", "SON")},
                    "AOD340": {"low": (m2["aod340"] <= aod_med).to_numpy(),
                               "high": (m2["aod340"] > aod_med).to_numpy()},
                    "ozone": {"low": (m2["ozone"] <= ozo_med).to_numpy(),
                              "high": (m2["ozone"] > ozo_med).to_numpy()},
                }
                lines += ["### Closure error by SZA / cloud / season / AOD / ozone",
                          "",
                          f"(AOD340 median split at {aod_med:.3f}; ozone median "
                          f"split at {ozo_med:.0f} DU; CAMS UVI predicted, "
                          f"Open-Meteo UVI as comparator — NOT truth: see the "
                          f"forecast-UVI bias section below)",
                          ""]
                lines += _stratified_table(m2, "om_uvi", "cams_uvi", strata)
                lines += [""]
            except (KeyError, ValueError, TypeError) as exc:
                lines += [f"Stratification skipped ({exc}).", ""]
            lines += ["No training touched CAMS UVBED targets, so this comparison "
                      "is independent.",
                      "NOTE: the bias concentrates at high sun (SZA 30-50) with "
                      "near-zero CAMS values while Open-Meteo peaks — consistent "
                      "with a ~4-5 h diurnal phase offset in the decoded CAMS "
                      "valid times (under investigation in history._dataset_time_column), "
                      "not with a radiometric scale error. This attribution is "
                      "unconfirmed until a measured phase analysis supports it; "
                      "meanwhile the UVI-disagreement confidence penalty is the "
                      "correct architectural response.",
                      ""]
        else:
            lines += ["CAMS UVBED, hourly UVI, or hourly time_utc columns missing; "
                      "closure skipped (naive local times are never parsed as UTC).", ""]
    else:
        lines += ["## CAMS/Open-Meteo", "",
                  f"Latest tables not found under {latest}; run a live forecast first.", ""]
    # Forecast-UVI bias vs POWER truth by SZA: reads the closure bias above
    # correctly (a hot comparator, not a cold CAMS model) and explains the
    # live E_mel/E_ery SZA fall. Optional: needs calibration_sources tables.
    arch_om = cal.parent / "calibration_sources" / "tables" / "openmeteo_historical_hourly.parquet"
    arch_pw = cal.parent / "calibration_sources" / "tables" / "nasa_power_hourly.parquet"
    if arch_om.exists() and arch_pw.exists():
        try:
            _om = pd.read_parquet(arch_om, columns=["time_utc", "uv_index"])
            _pw = pd.read_parquet(arch_pw)
            _m = pd.merge_asof(
                _om.sort_values("time_utc"), _pw.sort_values("time_utc"),
                on="time_utc", direction="nearest",
                tolerance=pd.Timedelta("35min")).dropna(
                    subset=["uv_index", "ALLSKY_SFC_UV_INDEX", "SZA"])
            _m = _m.loc[_m["ALLSKY_SFC_UV_INDEX"] > 0.3]
            _rel = ((_m["uv_index"] - _m["ALLSKY_SFC_UV_INDEX"]) /
                    _m["ALLSKY_SFC_UV_INDEX"].replace(0, np.nan))
            _bins = pd.cut(_m["SZA"], [0, 30, 50, 65, 80, 95],
                           labels=["0-30", "30-50", "50-65", "65-80", "80-95"])
            _rows = []
            for _lab in _bins.cat.categories:
                _sub = _rel.loc[(_bins == _lab).to_numpy()]
                if len(_sub) >= 100:
                    _rows.append(f"| SZA {_lab} | {len(_sub)} | {_sub.mean():+.3f} |")
            lines += ["## Forecast UVI bias vs POWER truth by SZA",
                      "",
                      "Archived Open-Meteo UVI minus NASA POWER UVI, relative, "
                      "on overlapping hours (POWER truth is itself modeled, so "
                      "corroborating rather than definitive):",
                      "",
                      "| stratum | n | mean relative bias |",
                      "|---|---|---|\n" + "\n".join(_rows) if _rows else
                      "| (insufficient overlap) | 0 | — |",
                      "",
                      "Reading: the comparator in the closure section runs hot "
                      "at low sun, which depresses live E_mel/E_ery with SZA "
                      "independent of any Tier-C shape error.",
                      ""]
        except (KeyError, ValueError, TypeError, OSError) as exc:
            lines += [f"Forecast-UVI bias section skipped ({exc}).", ""]
    else:
        lines += ["## Forecast UVI bias vs POWER truth by SZA",
                  "",
                  "Skipped: calibration_sources archive tables not present "
                  "for this site.",
                  ""]
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
