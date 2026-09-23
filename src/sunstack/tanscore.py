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
    """Propagate every direct CAMS UV/aerosol/column field (never fetch-and-drop).

    Adds erythemal irradiance (CAMS UVBED is a dose rate/irradiance, NOT an
    already-integrated SED), clear-sky companion, CAMS UVI (= 40 * E_ery),
    UV transmission, and downward-surface-UV irradiance derived from the
    accumulated CAMS field by time differencing. All spectral aerosol optics
    (AOD / absorption AOD / SSA / asymmetry at 340/355/380/400 nm) plus ozone,
    water vapor, cloud liquid/ice, total cloud, albedo, and radiation context
    are carried through for the spectral layer.
    """
    base_cols = [
        "time_utc", "ozone_du", "aod340", "aod380", "cams_forecast_albedo",
    ]
    if cams is None or cams.empty:
        return pd.DataFrame(columns=base_cols)
    out = pd.DataFrame({"time_utc": pd.to_datetime(cams["time_utc"], utc=True).astype("datetime64[ns, UTC]")})

    def grab(tokens: tuple[str, ...], excludes: tuple[str, ...] = ()) -> pd.Series:
        col = _find_col(cams, tokens, excludes)
        return num(cams, col) if col else pd.Series(np.nan, index=cams.index, dtype="float64")

    # Spectral aerosol optics at all four UV wavelengths.
    for wave in ("340", "355", "380", "400"):
        out[f"cams_aod_{wave}"] = grab(("aerosol", "optical", "depth", wave), ("absorption",))
        # Absorption AOD columns also contain "aerosol optical depth" tokens;
        # require "absorption" to disambiguate from total AOD above.
        out[f"cams_abs_aod_{wave}"] = grab(("absorption", "aerosol", "optical", wave))
        out[f"cams_ssa_{wave}"] = grab(("single", "scattering", "albedo", wave))
        out[f"cams_asymmetry_{wave}"] = grab(("asymmetry", wave))
    # Back-compat aliases used by the UVA/UVB estimator feature frame.
    out["aod340"] = out["cams_aod_340"]
    out["aod355"] = out["cams_aod_355"]
    out["aod380"] = out["cams_aod_380"]
    out["aod400"] = out["cams_aod_400"]

    ozone = _find_col(cams, ("total", "column", "ozone"))
    if ozone:
        oz = num(cams, ozone)
        med = oz.dropna().median() if oz.notna().any() else np.nan
        out["ozone_du"] = oz / 2.1415e-5 if pd.notna(med) and med < 5 else oz
        out["cams_ozone_du"] = out["ozone_du"]
    else:
        out["ozone_du"] = np.nan
        out["cams_ozone_du"] = np.nan

    out["cams_water_vapor"] = grab(("water", "vapour"))
    out["cams_cloud_liquid_water"] = grab(("cloud", "liquid", "water"))
    out["cams_cloud_ice_water"] = grab(("cloud", "ice", "water"))
    out["cams_total_cloud"] = grab(("total", "cloud", "cover"))
    albedo = _find_col(cams, ("forecast", "albedo"))
    out["cams_forecast_albedo"] = num(cams, albedo) if albedo else np.nan
    out["cams_direct_radiation"] = grab(("direct", "normal", "short", "wave"))
    out["cams_surface_solar_down"] = grab(("surface", "short", "wave", "downwards"))

    # Direct CAMS UV diagnostics. UVBED fields are dose RATES (W/m^2
    # erythemally weighted); they map 1:1 to erythemal irradiance.
    uvbed = grab(("uv", "biologically", "effective", "dose"), ("clear",))
    if uvbed.isna().all():
        uvbed = grab(("biologically", "effective"), ("clear",))
    uvbed_clear = grab(("biologically", "effective", "clear",))
    out["cams_erythemal_irradiance_wm2"] = uvbed
    out["cams_clear_sky_erythemal_irradiance_wm2"] = uvbed_clear
    out["cams_uv_index"] = uvbed * 40.0
    out["cams_uv_index_clear_sky"] = uvbed_clear * 40.0
    with np.errstate(divide="ignore", invalid="ignore"):
        out["cams_uv_transmission"] = (uvbed / uvbed_clear.replace(0, np.nan)).clip(0, 1.5)

    # Downward surface UV is an ACCUMULATED dose (J/m^2); differentiate to W/m^2.
    down_acc = grab(("downward", "uv"))
    if down_acc.isna().all():
        down_acc = grab(("downward_uv",))
    out["cams_downward_uv_accumulated_j_m2"] = down_acc
    try:
        tsec = pd.to_datetime(cams["time_utc"], utc=True).map(lambda x: x.timestamp())
        dvals = pd.to_numeric(down_acc, errors="coerce").to_numpy(dtype=float)
        irr = np.full_like(dvals, np.nan, dtype=float)
        dt = np.diff(np.asarray(tsec, dtype=float))
        dv = np.diff(dvals)
        with np.errstate(divide="ignore", invalid="ignore"):
            rate = np.where(dt > 0, dv / dt, np.nan)
        irr[1:] = np.clip(rate, 0, None)
        # First stamp has no backward difference; forward-fill from next if day.
        if len(irr) > 1 and not np.isfinite(irr[0]) and np.isfinite(irr[1]):
            irr[0] = irr[1]
        out["cams_downward_surface_uv_wm2"] = irr
    except (TypeError, ValueError):
        out["cams_downward_surface_uv_wm2"] = np.nan
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
        # Mode, not row zero: fallback cycles can concatenate, and the label
        # must describe the bulk of the data, not whichever row came first.
        modes = pd.Series(cams_direct["cams_cycle"]).dropna().mode()
        out["cams_cycle"] = str(modes.iloc[0]) if len(modes) else np.nan
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
        # mistaken for the calibrated model. Missing inputs stay missing
        # (NaN): only confirmed night rows (below) become zero.
        ghi = num(features, "ghi").to_numpy(dtype=float)
        uva = np.clip(0.055 * ghi, 0, 70)
        uvi = num(features, "uv_index").to_numpy(dtype=float)
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


def _uv_ghi_disagree(frame: pd.DataFrame) -> pd.Series:
    """True where broadband and UV inputs describe different skies.

    Heuristic priors, not fitted: flag only strong disagreement with the sun
    well up, so twilight angular physics (UV dies faster than GHI past ~65
    degrees) and night never trip it. NaN inputs never flag.
    """
    ghi = num(frame, "ghi")
    toa = num(frame, "terrestrial_radiation")
    uvi = num(frame, "uv_index")
    uvic = num(frame, "uv_index_clear_sky")
    sza = num(frame, "sza")
    sun_up = toa.fillna(0) > 100
    high_sun = sza.fillna(90) < 65
    kt_g = ghi / toa.where(toa.fillna(0) > 1)
    kt_u = uvi / uvic.where(uvic.fillna(0) > 1)
    bright_ghi_dark_uv = (kt_g > 0.5) & (kt_u < 0.3)
    dark_ghi_bright_uv = (kt_g < 0.25) & (kt_u > 0.6)
    return (sun_up & high_sun & (bright_ghi_dark_uv | dark_ghi_bright_uv)).fillna(False)


def apply_disagreement_penalty(confidence: pd.Series, disagree: pd.Series) -> pd.Series:
    """Halve confidence where inputs disagree. Values stay untouched; only
    trust is discounted. Both series must come from the same frame."""
    vals = pd.to_numeric(confidence, errors="coerce").to_numpy(dtype=float).copy()
    vals[disagree.fillna(False).to_numpy(dtype=bool)] *= 0.5
    return pd.Series(np.round(vals, 1), index=confidence.index)


_COMPASS_16 = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)


def sun_compass(azimuth_deg: float) -> str:
    """16-point compass label for a pvlib azimuth (degrees clockwise from N)."""
    if not np.isfinite(azimuth_deg):
        return "—"
    return _COMPASS_16[int((float(azimuth_deg) + 11.25) // 22.5) % 16]


def torso_lift_deg(elevation_deg: float) -> float | None:
    """Upper-body lift above horizontal that faces the torso normal at the sun.

    Pure geometry, not a fitted model: a horizontal torso's normal points at
    the zenith, so closing the (90 - elevation) gap points the chest at the
    sun. NaN or below-horizon elevation returns None — there is no sun to
    face, and a 90° "lift" would be a false prescription.
    """
    if not np.isfinite(elevation_deg) or elevation_deg <= 0:
        return None
    return round(float(np.clip(90.0 - elevation_deg, 0.0, 90.0)), 1)


def sun_posture_guidance(elevation_deg: float, azimuth_deg: float) -> str:
    """One-line lay guidance from solar geometry. Context only, never scored."""
    if not np.isfinite(elevation_deg) or elevation_deg <= 0:
        return "sun below horizon — no direct-sun posture"
    lift = torso_lift_deg(elevation_deg)
    compass = sun_compass(azimuth_deg)
    if elevation_deg >= 55:
        return f"sun {elevation_deg:.0f}° up ({compass}) — lay flat on back, face up"
    if elevation_deg >= 30:
        return (
            f"sun {elevation_deg:.0f}° up ({compass}) — lay flat, "
            f"or lift torso ~{lift:.0f}° toward {compass} to face it"
        )
    return (
        f"sun low {elevation_deg:.0f}° ({compass}) — face {compass}, "
        f"lift torso ~{lift:.0f}° toward the sun if comfortable"
    )


def add_sun_posture(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach sun-position context columns. Values untouched by construction."""
    out = frame.copy()
    elev = pd.to_numeric(frame.get("solar_elevation_deg"), errors="coerce")
    azim = pd.to_numeric(frame.get("solar_azimuth_deg"), errors="coerce")
    out["sun_compass"] = [sun_compass(float(a)) if pd.notna(a) else "—" for a in azim]
    out["torso_lift_deg"] = [torso_lift_deg(float(e)) if pd.notna(e) else None for e in elev]
    out["sun_posture_guidance"] = [
        sun_posture_guidance(float(e) if pd.notna(e) else float("nan"),
                             float(a) if pd.notna(a) else float("nan"))
        for e, a in zip(elev, azim)
    ]
    return out


def _require_photobiology_or_fail() -> tuple[object, float, str]:
    """Load melanogenesis spectrum + global reference, failing loudly."""
    from .photobiology import load_action_spectrum

    try:
        spec = load_action_spectrum("parrish_delayed_melanogenesis")
    except (FileNotFoundError, ValueError) as exc:
        raise RuntimeError(f"ERROR photobiology: {exc}") from exc
    ref = float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2)
    if not np.isfinite(ref) or ref <= 0:
        raise RuntimeError("ERROR photobiology: global melanogenic reference invalid")
    return spec, ref, spec.tier


def score_forecast(
    best_enriched: pd.DataFrame,
    calibration_dir: Path,
    cams_direct: pd.DataFrame | None = None,
    forecast_confidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    from .photobiology import (
        TAN_SCORE_MODEL_VERSION as _TSV,
    )
    from .photobiology import (
        absolute_tan_score_from_melanogenic_irradiance,
        erythemal_irradiance_from_uvi,
    )
    from .spectral import (
        SPECTRAL_BACKEND_VERSION,
        melanogenic_from_broadband,
        pigment_darkening_from_broadband,
        spectral_tier_for_row,
    )

    features = build_live_feature_frame(best_enriched, cams_direct)
    if features.empty:
        return features
    # Strict photobiology gate: missing spectrum or bad reference fails loudly,
    # never silently falls back to the legacy 55/30/15 formula.
    if config.REQUIRE_CANONICAL_SPECTRUM:
        from .photobiology import require_canonical_spectrum

        require_canonical_spectrum("parrish_delayed_melanogenesis")
    _spec, global_ref, spectrum_tier = _require_photobiology_or_fail()

    uva, uvb, tier = predict_uva_uvb(features, calibration_dir)
    out = features.copy()
    out["predicted_uva_wm2"] = np.round(uva, 3)
    out["predicted_uvb_wm2"] = np.round(uvb, 4)
    out["tan_calibration_tier"] = tier

    # v4 physical core: wavelength-additive Tier-C E_mel, no hand weights.
    e_mel = melanogenic_from_broadband(
        np.asarray(uva, dtype=float), np.asarray(uvb, dtype=float)
    )
    night = num(out, "is_day").fillna(1) == 0
    e_mel = np.where(night.to_numpy(), 0.0, e_mel)
    out["melanogenic_effective_irradiance_wm2"] = np.round(e_mel, 5)
    out["tan_score_absolute_0_100"] = np.round(
        absolute_tan_score_from_melanogenic_irradiance(e_mel, global_ref), 1
    )
    out["tan_score_model_version"] = _TSV
    out["photobiology_action_spectrum_tier"] = spectrum_tier
    out["global_reference_version"] = config.GLOBAL_MELANOGENIC_REFERENCE_VERSION
    out["global_reference_e_mel_wm2"] = global_ref
    out["spectral_backend"] = SPECTRAL_BACKEND_VERSION
    out["spectral_tier"] = spectral_tier_for_row()
    if str(out["spectral_tier"].iloc[0]) in ("A", "B"):
        # No silent tier inflation: reference/emulator quality may only be
        # claimed behind a validated manifest (SUNSTACK_TIERB_MANIFEST).
        from .spectral import validate_tierB_manifest

        if not config.TIERB_MANIFEST_PATH:
            raise RuntimeError(
                "ERROR spectral: tier A/B claimed with no emulator manifest "
                "configured (SUNSTACK_TIERB_MANIFEST unset). Build the corpus "
                "with scripts/build_spectral_corpus.py first."
            )
        import json as _json
        from pathlib import Path as _Path

        validate_tierB_manifest(
            _json.loads(_Path(config.TIERB_MANIFEST_PATH).read_text(encoding="utf-8")))
    # Temporary migration diagnostic: legacy value for comparison reports only.
    # Never used in ranking or UI headline scores after validation.
    out["legacy_absolute_tan_score_55_30_15"] = np.round(
        absolute_tan_score(num(out, "uv_index"), scol(out, "predicted_uva_wm2")), 1
    )
    out["absolute_tan_intensity_label"] = [
        _grade_absolute(float(x)) for x in num(out, "tan_score_absolute_0_100").fillna(np.nan)
    ]

    # UVI source fusion: EPA/NWS operational (US public product) + CAMS
    # spectral + Open-Meteo/GFS. Median of available sources resists a single
    # bad feed (e.g. OM best-match GFS/cloud mixing vs clear-sky + DNI).
    # Not a blind average: spread/confidence derive from the same sources.
    out["uvi_openmeteo"] = num(out, "uv_index")
    if "cams_uv_index" in out:
        out["uvi_cams"] = num(out, "cams_uv_index")
    else:
        out["uvi_cams"] = np.nan
    if "uvi_epa" in out:
        out["uvi_epa"] = num(out, "uvi_epa")
    else:
        out["uvi_epa"] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        stacked = np.vstack([
            out["uvi_openmeteo"].to_numpy(dtype=float),
            out["uvi_cams"].to_numpy(dtype=float),
            out["uvi_epa"].to_numpy(dtype=float),
        ])
        out["uvi_consensus"] = np.round(np.nanmedian(stacked, axis=0), 3)
        out["uvi_consensus_sources"] = np.sum(np.isfinite(stacked), axis=0).astype(int)
        out["uvi_source_spread"] = np.round(np.nanmax(stacked, axis=0) - np.nanmin(stacked, axis=0), 3)
    # Independent erythemal channel (SED input) from the consensus UVI. NEVER
    # added to TanScore. Consensus resists one bad source; raw OM UVI kept as
    # uvi_openmeteo for display/debug. Missing consensus stays missing: only
    # confirmed night rows read as zero, so the SED integrator marks true gaps
    # instead of trapezoids through invented zeros.
    out["erythemal_irradiance_wm2"] = np.round(
        erythemal_irradiance_from_uvi(out["uvi_consensus"].to_numpy(dtype=float)), 5
    )
    # Separate UVA-dominant pigment-darkening channel (existing pigment only).
    try:
        out["pigment_darkening_effective_irradiance"] = np.round(
            pigment_darkening_from_broadband(
                np.asarray(uva, dtype=float), np.asarray(uvb, dtype=float)
            ), 5,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise RuntimeError(f"ERROR photobiology: {exc}") from exc
    out["pigment_darkening_endpoint"] = (
        "existing-pigment oxidation/redistribution / persistent darkening"
    )

    # Agreement modulates confidence only, never the action-spectrum
    # weighting or E_mel. Pairwise OM/CAMS difference kept for back-compat;
    # uvi_source_spread covers all available sources including EPA.
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = np.maximum(
            np.maximum(out["uvi_openmeteo"].to_numpy(dtype=float),
                       out["uvi_cams"].to_numpy(dtype=float)), 0.5,
        )
        out["uvi_difference_absolute"] = (
            out["uvi_openmeteo"] - out["uvi_cams"]
        ).round(3)
        out["uvi_difference_percent"] = (
            (out["uvi_openmeteo"] - out["uvi_cams"]).abs() / denom
        ).round(4)

    ref_path = calibration_dir / "local_reference.parquet"
    # Version-gate BEFORE scoring percentiles: a stale/missing version file
    # means the parquet may hold legacy-55/30/15 percentiles, which must never
    # be mixed into v4 overall opportunity. Reject first (NaN = unavailable),
    # mark loudly; validation WARNs downstream.
    out["local_reference_version"] = "unknown"
    out["local_reference_stale"] = True
    _ref_usable = False
    try:
        import json as _json

        _ver_path = calibration_dir / "local_reference_version.json"
        if _ver_path.exists():
            _ver = _json.loads(_ver_path.read_text(encoding="utf-8"))
            out["local_reference_version"] = str(
                _ver.get("tan_score_model_version", "unknown"))
            _model_ok = (_ver.get("tan_score_model_version")
                         == config.TAN_SCORE_MODEL_VERSION)
            _refver_ok = (_ver.get("global_reference_version", None) in
                          (None, config.GLOBAL_MELANOGENIC_REFERENCE_VERSION))
            _refval = _ver.get("global_reference_e_mel_wm2", None)
            _refval_ok = (_refval is None or float(_refval) ==
                          float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2))
            # An env-overridden reference value without a version bump changes
            # Absolute silently: without a recorded value to compare, a mere
            # version match is not enough to trust the file. Missing value is
            # tolerated only for files written before the value was recorded.
            _ref_usable = bool(_model_ok and _refver_ok and _refval_ok)
            out["local_reference_stale"] = not _ref_usable
    except (OSError, ValueError, TypeError):
        pass
    local_ref = (pd.read_parquet(ref_path)
                 if (_ref_usable and ref_path.exists()) else pd.DataFrame())
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
    out["uv_input_disagree"] = _uv_ghi_disagree(out).to_numpy(dtype=bool)
    out["tan_forecast_confidence_0_100"] = apply_disagreement_penalty(
        out["tan_forecast_confidence_0_100"], out["uv_input_disagree"]
    )
    # CAMS/Open-Meteo UVI disagreement reduces confidence (physics untouched).
    disag = pd.to_numeric(out["uvi_difference_percent"], errors="coerce").fillna(0)
    strong = disag >= config.UVI_DISAGREEMENT_STRONG_FRAC
    mild = (disag >= config.UVI_DISAGREEMENT_WARN_FRAC) & ~strong
    conf = pd.to_numeric(out["tan_forecast_confidence_0_100"], errors="coerce")
    conf = conf.where(~mild, conf * 0.85).where(~strong, conf * 0.65)
    out["tan_forecast_confidence_0_100"] = np.round(conf, 1)
    out["uvi_source_disagree"] = (mild | strong).to_numpy(dtype=bool)

    # Useful contextual diagnostics that deliberately do NOT get TanScore weight.
    out["humidity_context_pct"] = num(out, "relative_humidity_2m")
    out["wet_bulb_context_f"] = num(out, "wet_bulb_temperature_2m")
    out["wind_context_mph"] = num(out, "wind_speed_10m")
    out["precipitation_context_probability_pct"] = num(out, "precipitation_probability")
    out["skin_plane_standard"] = "horizontal environmental reference"
    try:
        from .spectral import apply_skin_plane as _apply_plane

        out = _apply_plane(out)
    except ValueError as exc:
        import logging as _logging

        _logging.getLogger("sunstack").error(
            "Skin-plane configuration invalid (tilt=%s, azimuth=%s): %s",
            config.SKIN_TILT_DEG, config.SKIN_AZIMUTH_DEG, exc)
        raise
    out = add_sun_posture(out)
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
