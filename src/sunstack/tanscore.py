from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd

from . import config
from .calibrate import MODEL_FEATURES, absolute_tan_score, num, scol, solar_features


def _find_col(df: pd.DataFrame, tokens: tuple[str, ...], excludes: tuple[str, ...] = ()) -> str | None:
    for c in df.columns:
        low = c.lower()
        if all(t.lower() in low for t in tokens) and not any(x.lower() in low for x in excludes):
            return c
    return None


def _to_utc_from_openmeteo(times: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(times)
    if getattr(parsed.dt, "tz", None) is None:
        parsed = parsed.dt.tz_localize(ZoneInfo(config.TIMEZONE), ambiguous="infer", nonexistent="shift_forward")
    # Canonical ns unit: live Open-Meteo strings parse as us, while xarray-derived
    # CAMS frames are ns, and merges require identical key dtypes.
    return parsed.dt.tz_convert("UTC").astype("datetime64[ns, UTC]")


def _cams_features(cams: pd.DataFrame | None) -> pd.DataFrame:
    if cams is None or cams.empty:
        return pd.DataFrame(columns=["time_utc", "ozone_du", "aod340", "aod380", "cams_forecast_albedo"])
    out = pd.DataFrame({"time_utc": pd.to_datetime(cams["time_utc"], utc=True).astype("datetime64[ns, UTC]")})
    c340 = _find_col(cams, ("aerosol", "optical", "depth", "340"), ("absorption", "fine"))
    c380 = _find_col(cams, ("aerosol", "optical", "depth", "380"), ("absorption", "fine"))
    ozone = _find_col(cams, ("total", "column", "ozone"))
    albedo = _find_col(cams, ("forecast", "albedo"))
    if c340:
        out["aod340"] = num(cams, c340)
    else:
        out["aod340"] = np.nan
    if c380:
        out["aod380"] = num(cams, c380)
    else:
        out["aod380"] = np.nan
    if ozone:
        oz = num(cams, ozone)
        med = oz.dropna().median() if oz.notna().any() else np.nan
        out["ozone_du"] = oz / 2.1415e-5 if pd.notna(med) and med < 5 else oz
    else:
        out["ozone_du"] = np.nan
    out["cams_forecast_albedo"] = num(cams, albedo) if albedo else np.nan
    return out


def build_live_feature_frame(best: pd.DataFrame, cams_direct: pd.DataFrame | None = None) -> pd.DataFrame:
    if best.empty:
        return pd.DataFrame()
    out = best.copy()
    out["time_utc"] = _to_utc_from_openmeteo(scol(out, "time"))
    if "elevation_m" in out:
        elev = num(out, "elevation_m").dropna()
        altitude = float(elev.median()) if elev.notna().any() else 220.0
    else:
        altitude = 220.0
    solar = solar_features(scol(out, "time_utc"), altitude)
    out = out.merge(solar, on="time_utc", how="left")

    # Training-feature mapping. POWER training uses hourly-mean broadband radiation,
    # so prefer Open-Meteo's preceding-hour means rather than *_instant fields.
    out["ghi"] = num(out, "shortwave_radiation")
    out["dni"] = num(out, "direct_normal_irradiance")
    out["dhi"] = num(out, "diffuse_radiation")
    toa = num(out, "terrestrial_radiation")
    out["kt"] = out["ghi"] / toa.where(toa > 1)
    out["cloud"] = num(out, "cloud_cover")
    out["temp_c"] = (num(out, "temperature_2m") - 32.0) * (5.0 / 9.0)
    out["rh"] = num(out, "relative_humidity_2m")
    out["pressure_kpa"] = num(out, "surface_pressure") / 10.0

    # Open-Meteo CAMS AOD550 is already merged by merge_air_quality() under air__*.
    if "air__aerosol_optical_depth" in out:
        out["aod55"] = num(out, "air__aerosol_optical_depth")
    else:
        out["aod55"] = np.nan

    camsf = _cams_features(cams_direct)
    if cams_direct is not None and not cams_direct.empty and "cams_cycle" in cams_direct:
        out["cams_cycle"] = str(cams_direct["cams_cycle"].iloc[0])
    else:
        out["cams_cycle"] = np.nan
    if not camsf.empty:
        out = pd.merge_asof(
            out.sort_values("time_utc"), camsf.sort_values("time_utc"), on="time_utc",
            direction="nearest", tolerance=timedelta(minutes=70),
        )
    else:
        out["ozone_du"] = np.nan
        out["aod340"] = np.nan
        out["aod380"] = np.nan
        out["cams_forecast_albedo"] = np.nan

    # Prefer direct CAMS forecast albedo. Otherwise use a conservative generic 0.20;
    # the model learns albedo as a modest modifier, not a dominant term.
    out["albedo"] = num(out, "cams_forecast_albedo").fillna(0.20)
    for c in MODEL_FEATURES:
        if c not in out:
            out[c] = np.nan
    return out


def _load_bundle(calibration_dir: Path):
    path = calibration_dir / "uva_uvb_models.joblib"
    return joblib.load(path) if path.exists() else None


def predict_uva_uvb(features: pd.DataFrame, calibration_dir: Path) -> tuple[np.ndarray, np.ndarray, str]:
    bundle = _load_bundle(calibration_dir)
    if bundle is not None:
        X = features.reindex(columns=bundle["features"])
        uva = np.clip(bundle["uva_model"].predict(X), 0, None)
        uvb = np.clip(bundle["uvb_model"].predict(X), 0, None)
        full_cams = all(c in features and num(features, c).notna().any() for c in ("ozone_du", "aod340", "aod380"))
        tier = "nasa_power_ml_plus_cams_spectral" if full_cams else "nasa_power_ml"
    else:
        # Last-resort fallback only. It is explicitly labeled so it can never be
        # mistaken for the calibrated model.
        ghi = num(features, "ghi").fillna(0).to_numpy()
        uva = np.clip(0.055 * ghi, 0, 70)
        uvi = num(features, "uv_index").fillna(0).to_numpy()
        uvb = np.clip(0.10 * uvi, 0, 3)
        tier = "uncalibrated_fallback"
    # No sun above the horizon means no surface UV, full stop. The ML models
    # otherwise leak small positive values through the night.
    night = num(features, "is_day").fillna(1) == 0
    uva = np.where(night.to_numpy(), 0.0, uva)
    uvb = np.where(night.to_numpy(), 0.0, uvb)
    return uva, uvb, tier


def _percentile(values: pd.Series, value: float) -> float:
    clean = pd.to_numeric(values, errors="coerce")
    if not isinstance(clean, pd.Series):
        raise TypeError("percentile values must be a Series")
    vals = clean.dropna().to_numpy()
    if not len(vals) or not np.isfinite(value):
        return np.nan
    return float(100.0 * np.mean(vals <= value))


def _circular_doy_distance(series: pd.Series, doy: int) -> pd.Series:
    nums = pd.to_numeric(series, errors="coerce")
    if not isinstance(nums, pd.Series):
        raise TypeError("doy series must be a Series")
    diff = (nums - doy).abs()
    mirror = 366 - diff
    return diff.where(diff <= mirror, mirror)


def fnum(row: pd.Series, name: str, default: float = float("nan")) -> float:
    """Scalar float read with a quiet default (missing/garbage → default)."""
    v = row.get(name, default)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def add_local_scores(forecast: pd.DataFrame, local_ref: pd.DataFrame) -> pd.DataFrame:
    out = forecast.copy()
    if local_ref is None or local_ref.empty:
        out["local_tan_score_0_100"] = np.nan
        out["atmospheric_quality_percentile_0_100"] = np.nan
        return out
    ref = local_ref.copy()
    local_times = pd.to_datetime(scol(out, "time_utc"), utc=True).dt.tz_convert(ZoneInfo(config.TIMEZONE))
    local_scores = []
    atm_scores = []
    for idx, row in out.iterrows():
        lt = local_times.loc[idx]
        doy = int(lt.dayofyear)
        elev = fnum(row, "solar_elevation_deg")
        score = fnum(row, "tan_score_absolute_0_100")
        seasonal = ref.loc[_circular_doy_distance(scol(ref, "day_of_year"), doy) <= config.LOCAL_DOY_WINDOW_DAYS]
        if len(seasonal) < 250:
            seasonal = ref
        local_scores.append(_percentile(scol(seasonal, "absolute_tan_score_0_100"), score))

        same_geometry = seasonal.loc[
            (num(seasonal, "solar_elevation_deg") - elev).abs()
            <= config.LOCAL_SOLAR_ELEVATION_WINDOW_DEG
        ]
        if len(same_geometry) < 100:
            same_geometry = seasonal.loc[
                (num(seasonal, "solar_elevation_deg") - elev).abs() <= 15.0
            ]
        atm_scores.append(_percentile(scol(same_geometry, "absolute_tan_score_0_100"), score))
    out["local_tan_score_0_100"] = np.round(local_scores, 1)
    out["atmospheric_quality_percentile_0_100"] = np.round(atm_scores, 1)
    return out


def _grade_absolute(score: float) -> str:
    if not np.isfinite(score): return "unknown"
    if score >= 80: return "extreme natural tanning intensity"
    if score >= 65: return "very strong"
    if score >= 50: return "strong"
    if score >= 35: return "moderate"
    if score >= 20: return "low-moderate"
    return "low"


def _grade_local(score: float) -> str:
    if not np.isfinite(score): return "unknown"
    if score >= 98: return "exceptional locally"
    if score >= 90: return "excellent locally"
    if score >= 75: return "good locally"
    if score >= 50: return "typical-to-good locally"
    if score >= 25: return "below typical locally"
    return "poor locally"


def score_forecast(
    best_enriched: pd.DataFrame,
    calibration_dir: Path,
    cams_direct: pd.DataFrame | None = None,
    forecast_confidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    features = build_live_feature_frame(best_enriched, cams_direct)
    if features.empty:
        return features
    uva, uvb, tier = predict_uva_uvb(features, calibration_dir)
    out = features.copy()
    out["predicted_uva_wm2"] = np.round(uva, 3)
    out["predicted_uvb_wm2"] = np.round(uvb, 4)
    out["tan_calibration_tier"] = tier
    out["tan_score_absolute_0_100"] = np.round(
        absolute_tan_score(num(out, "uv_index"), scol(out, "predicted_uva_wm2")), 1
    )
    out["absolute_tan_intensity_label"] = [
        _grade_absolute(float(x)) for x in num(out, "tan_score_absolute_0_100").fillna(np.nan)
    ]

    ref_path = calibration_dir / "local_reference.parquet"
    local_ref = pd.read_parquet(ref_path) if ref_path.exists() else pd.DataFrame()
    out = add_local_scores(out, local_ref)
    out["local_tan_label"] = [_grade_local(float(x)) for x in num(out, "local_tan_score_0_100").fillna(np.nan)]

    # Keep quality and uncertainty separate. A low confidence never changes the
    # physical TanScore; it only changes how much to trust that forecast.
    if forecast_confidence is not None and not forecast_confidence.empty and "time" in forecast_confidence:
        confidence_cols = [c for c in [
            "time", "ensemble_strong_sun_support_0_100", "deterministic_agreement_0_100",
            "sun_window_confidence_0_100",
        ] if c in forecast_confidence]
        if len(confidence_cols) > 1:
            out = out.merge(forecast_confidence.loc[:, confidence_cols], on="time", how="left")
    if "sun_window_confidence_0_100" in out:
        out["tan_forecast_confidence_0_100"] = num(out, "sun_window_confidence_0_100")
    else:
        out["tan_forecast_confidence_0_100"] = np.nan

    # Useful contextual diagnostics that deliberately do NOT get TanScore weight.
    out["humidity_context_pct"] = num(out, "relative_humidity_2m")
    out["wet_bulb_context_f"] = num(out, "wet_bulb_temperature_2m")
    out["wind_context_mph"] = num(out, "wind_speed_10m")
    out["precipitation_context_probability_pct"] = num(out, "precipitation_probability")
    out["skin_plane_standard"] = "horizontal environmental reference"
    return out


def best_tan_windows(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return scored
    out = scored.copy()
    daylight = num(out, "is_day").fillna(1) > 0
    out = out.loc[daylight].copy()
    # Ranking uses absolute physics first; local score is interpretation, not a way
    # to inflate biologically weaker conditions. Confidence breaks near-ties only.
    if "overall_tan_opportunity_0_100" in out:
        out["tan_window_rank_value"] = num(out, "overall_tan_opportunity_0_100")
    else:
        confidence = num(out, "tan_forecast_confidence_0_100").fillna(50)
        out["tan_window_rank_value"] = (
            num(out, "tan_score_absolute_0_100") * 0.90 + confidence * 0.10
        )
    return out.sort_values(["tan_window_rank_value", "tan_score_absolute_0_100"], ascending=False)
