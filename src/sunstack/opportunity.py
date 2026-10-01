from __future__ import annotations

import logging
import math
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pvlib.location

from . import config
from .calibrate import num, scol

LOG = logging.getLogger("sunstack")


def _num(df: pd.DataFrame, name: str, default=np.nan) -> pd.Series:
    return num(df, name, default)


RAIN_CODES = set(range(51, 68)) | {80, 81, 82}
SNOW_CODES = set(range(71, 78)) | {85, 86}
THUNDER_CODES = {95, 96, 99}


def _weighted_geometric(row: pd.Series) -> float:
    vals: dict[str, Any] = {
        "absolute": row.get("tan_score_absolute_0_100", np.nan),
        "local": row.get("local_tan_score_0_100", np.nan),
        "atmosphere": row.get("atmospheric_quality_percentile_0_100", np.nan),
        "confidence": row.get("tan_forecast_confidence_0_100", np.nan),
    }
    weights = config.OVERALL_SCORE_WEIGHTS
    usable = [
        (float(vals[k]), float(weights[k]))
        for k in weights
        if bool(pd.notna(vals.get(k)))
    ]
    if not usable:
        return np.nan
    total_w = sum(w for _, w in usable)
    # 0 is a legitimate score; clamp only for logarithm math.
    geom = math.exp(sum((w / total_w) * math.log(max(v, 0.25)) for v, w in usable))
    absolute = vals["absolute"]
    if pd.notna(absolute):
        # Local rarity and favorable atmosphere may improve interpretation, but can
        # never turn biologically weak radiation into an elite global opportunity.
        geom = min(geom, float(absolute) + config.OVERALL_ABSOLUTE_HEADROOM)
    return float(np.clip(geom, 0, 100))


def apply_outdoor_feasibility(
    scored: pd.DataFrame, min_temp_f: float | None = None
) -> pd.DataFrame:
    """Add outdoor usability without contaminating environmental TanScore.

    Hard blocks follow user-requested practical rules (active rain/snow, thunder,
    extreme heat, or configurable cold floor). Forecast precipitation probability,
    wind, and marginal temperatures are soft opportunity penalties only.
    """
    if scored.empty:
        return scored.copy()
    out = scored.copy()
    min_temp = float(config.MIN_TAN_TEMP_F if min_temp_f is None else min_temp_f)
    temp = _num(out, "temperature_2m")
    # Sun-adjusted feels-like for BARE SKIN lying still (user context:
    # shirtless + shorts on grass/sand). Solar heating from headline UVI x
    # clear-sky transmission (bare skin gains ~1.5x the clothed adult), plus a
    # muggy penalty from dew point (sweat can't evaporate), minus wind strip
    # (lying still = wind does all cooling). Used for the comfort band ONLY —
    # hard blocks still use the thermometer.
    _uvi = _num(out, "uvi_consensus" if "uvi_consensus" in out.columns else "uv_index")
    _clear = _num(out, "uv_index_clear_sky")
    _trans = (_uvi / _clear.replace(0, np.nan)).clip(0, 1.2).fillna(0.5)
    _wind_f = _num(out, "wind_speed_10m", 0).fillna(0)
    _dew = _num(out, "dew_point_2m")
    _sun_add = (18.0 * (_uvi / 10.0).clip(0, 1.2) * _trans.clip(0, 1)).fillna(0)
    _muggy = ((_dew - 65.0).clip(0, 15) * 0.6).fillna(0)
    _wind_cut = (8.0 * (_wind_f / 25.0).clip(0, 1.5)).fillna(0)
    out["sun_adjusted_feels_like_f"] = np.round((temp + _sun_add + _muggy - _wind_cut), 1)
    _feel = temp + _sun_add + _muggy - _wind_cut
    feels = _num(out, "apparent_temperature")
    rain = _num(out, "rain", 0).fillna(0)
    showers = _num(out, "showers", 0).fillna(0)
    snow = _num(out, "snowfall", 0).fillna(0)
    pop = _num(out, "precipitation_probability", 0).fillna(0).clip(0, 100)
    wind = _num(out, "wind_speed_10m", 0).fillna(0)
    rh = _num(out, "relative_humidity_2m")
    code = _num(out, "weather_code").fillna(-1).round().astype(int)

    rain_now = (
        (rain > config.ACTIVE_PRECIP_IN_THRESHOLD)
        | (showers > config.ACTIVE_PRECIP_IN_THRESHOLD)
        | code.isin(RAIN_CODES)
    )
    snow_now = (snow > config.ACTIVE_SNOW_IN_THRESHOLD) | code.isin(SNOW_CODES)
    thunder = code.isin(THUNDER_CODES)
    too_hot = temp >= config.MAX_TAN_TEMP_F
    too_cold = temp < min_temp
    hard_block = rain_now | snow_now | thunder | too_hot | too_cold

    multiplier = pd.Series(1.0, index=out.index)
    # Cold/heat comfort penalties use sun-adjusted feels-like: 65F calm + high
    # sun feels ~warm and must not be shitted on; same 65F in wind feels cold.
    # Floor sain: the penalty curve is shallower (0.65 floor, was 0.45) so
    # strong sun is never dragged to POOR by mild air alone.
    cold_band = (_feel >= min_temp) & (_feel < config.COMFORTABLE_TAN_TEMP_F)
    if config.COMFORTABLE_TAN_TEMP_F > min_temp:
        frac = (_feel - min_temp) / (config.COMFORTABLE_TAN_TEMP_F - min_temp)
        multiplier.loc[cold_band] *= 0.65 + 0.35 * frac.loc[cold_band].clip(0, 1)
    warm = (temp >= config.HEAT_WARNING_TEMP_F) & (temp < config.MAX_TAN_TEMP_F)
    if config.MAX_TAN_TEMP_F > config.HEAT_WARNING_TEMP_F:
        heat_frac = (temp - config.HEAT_WARNING_TEMP_F) / (
            config.MAX_TAN_TEMP_F - config.HEAT_WARNING_TEMP_F
        )
        multiplier.loc[warm] *= 1.0 - 0.45 * heat_frac.loc[warm].clip(0, 1)

    # Rain risk is a practical window-reliability penalty, not a melanogenesis term.
    multiplier *= 1.0 - config.PRECIP_PROBABILITY_PENALTY_MAX * (pop / 100.0) ** 1.2
    multiplier.loc[wind >= config.WIND_WARNING_MPH] *= 0.80
    multiplier.loc[wind >= config.WIND_STRONG_MPH] *= 0.65
    multiplier.loc[hard_block] = 0.0

    reasons: list[str] = []
    flags: list[str] = []
    for i in out.index:
        rs, fs = [], []
        if bool(rain_now.loc[i]):
            rs.append("active rain/drizzle/showers")
        if bool(snow_now.loc[i]):
            rs.append("active snow")
        if bool(thunder.loc[i]):
            rs.append("thunderstorm")
        if pd.notna(temp.loc[i]) and temp.loc[i] >= config.MAX_TAN_TEMP_F:
            rs.append(f"temperature >= {config.MAX_TAN_TEMP_F:.0f}F")
        if pd.notna(temp.loc[i]) and temp.loc[i] < min_temp:
            rs.append(f"temperature < {min_temp:.0f}F")
        if not rs:
            if pd.notna(_feel.loc[i]) and _feel.loc[i] < config.COMFORTABLE_TAN_TEMP_F:
                fs.append("cold")
            if pd.notna(temp.loc[i]) and temp.loc[i] >= config.HEAT_WARNING_TEMP_F:
                fs.append("heat")
            if pop.loc[i] >= 40:
                fs.append(f"{pop.loc[i]:.0f}% precipitation risk")
            if wind.loc[i] >= config.WIND_WARNING_MPH:
                fs.append("windy")
            if (
                pd.notna(rh.loc[i])
                and pd.notna(temp.loc[i])
                and rh.loc[i] >= 80
                and temp.loc[i] >= 80
            ):
                fs.append("humid/sweaty")
            if pd.notna(feels.loc[i]) and feels.loc[i] >= 100:
                fs.append("high apparent temperature")
        reasons.append("; ".join(rs))
        flags.append("; ".join(fs))

    _comfort = pd.Series("perfect", index=out.index)
    _comfort = _comfort.mask(temp < min_temp, "too cold")
    _comfort = _comfort.mask(cold_band, "cool")
    _comfort = _comfort.mask((_feel >= config.COMFORTABLE_TAN_TEMP_F) & (temp < config.COMFORTABLE_TAN_TEMP_F), "sun-warmed")
    try:
        _comfort = _comfort.mask((temp >= config.HEAT_WARNING_TEMP_F) & (temp < config.MAX_TAN_TEMP_F), "warm")
        _comfort = _comfort.mask(temp >= config.MAX_TAN_TEMP_F, "too hot")
    except (TypeError, ValueError):
        pass
    out["comfort_band"] = _comfort.where(~hard_block.fillna(False), _comfort)
    out["outdoor_feasibility_0_100"] = np.round(multiplier * 100, 1)
    out["outdoor_blocked"] = hard_block.to_numpy()
    out["outdoor_block_reason"] = reasons
    out["outdoor_flags"] = flags
    out["minimum_tan_temperature_f"] = min_temp

    out["overall_components_unblocked_0_100"] = out.apply(
        _weighted_geometric, axis=1
    ).round(1)
    # Coverage honesty (audit: missing components silently redefined Overall).
    _comp_cols = ("tan_score_absolute_0_100", "local_tan_score_0_100",
                  "atmospheric_quality_percentile_0_100",
                  "tan_forecast_confidence_0_100")
    _cov = np.zeros(len(out), dtype=int)
    for c in _comp_cols:
        if c in out.columns:
            col = pd.to_numeric(out[c], errors="coerce")
            assert isinstance(col, pd.Series)
            _cov = _cov + col.notna().to_numpy().astype(int)
    out["overall_component_coverage"] = _cov
    out["overall_tan_opportunity_0_100"] = (
        (out["overall_components_unblocked_0_100"] * multiplier).clip(0, 100).round(1)
    )
    # No sun above the horizon means no opportunity, full stop. Mirrors the
    # night-zero clamp on predicted UVA/UVB; kills the log-math floor (~1)
    # that the geometric mean leaves on night rows.
    sza = _num(out, "sza")
    night = sza.notna() & (sza >= 90)
    if bool(night.any()):
        out.loc[
            night.to_numpy(),
            ["overall_components_unblocked_0_100", "overall_tan_opportunity_0_100"],
        ] = 0.0
    return out


def fitzpatrick_context(skin_type: int | None) -> dict[str, str | int | None]:
    if skin_type is None:
        return {
            "fitzpatrick_type": None,
            "fitzpatrick_label": "not specified",
            "skin_response_note": "Environmental scores are skin-type independent.",
        }
    labels = {
        1: "Type I — very sun-sensitive; usually burns, little tanning",
        2: "Type II — sun-sensitive; burns readily, tans minimally",
        3: "Type III — intermediate response; may burn, tans gradually",
        4: "Type IV — less burn-prone; generally tans readily",
        5: "Type V — deeply pigmented; rarely burns, tans readily",
        6: "Type VI — very deeply pigmented; lowest erythema susceptibility of Fitzpatrick groups",
    }
    if skin_type not in labels:
        raise ValueError("Fitzpatrick skin type must be an integer from 1 to 6")
    return {
        "fitzpatrick_type": skin_type,
        "fitzpatrick_label": labels[skin_type],
        "skin_response_note": "Fitzpatrick type changes risk/response interpretation, not environmental TanScore. Published MED/MMD values overlap substantially within types; objective skin color or measured MED/MMD is more precise.",
    }


def personalization_context(
    constitutive_ita_deg: float | None = None,
    facultative_ita_deg: float | None = None,
    melanin_index: float | None = None,
    l_star: float | None = None,
    pigment_protection_factor: float | None = None,
    measured_med_sed: float | None = None,
    measured_mmd: float | None = None,
    measured_mmd_source_spectrum: str | None = None,
    fitzpatrick_type: int | None = None,
) -> dict[str, object]:
    """Objective-first personalization context. Never alters environmental physics.

    Precedence: measured/objective pigmentation > Fitzpatrick. No precise
    personal MMD is computed from Fitzpatrick alone; Fitzpatrick-only
    estimates are disabled by default (return None with wide-uncertainty note).
    """
    has_objective = any(
        v is not None for v in (constitutive_ita_deg, facultative_ita_deg,
                                melanin_index, l_star, pigment_protection_factor)
    )
    has_measured = measured_med_sed is not None or measured_mmd is not None
    if has_measured:
        basis = "MEASURED"
    elif has_objective:
        basis = "OBJECTIVE_ESTIMATE"
    elif fitzpatrick_type is not None:
        basis = "COARSE_ESTIMATE (Fitzpatrick-only, very wide uncertainty, disabled by default)"
    else:
        basis = "not personalized"
    return {
        "constitutive_ita_deg": constitutive_ita_deg,
        "facultative_ita_deg": facultative_ita_deg,
        "melanin_index": melanin_index,
        "l_star": l_star,
        "pigment_protection_factor": pigment_protection_factor,
        "measured_med_sed": measured_med_sed,
        "measured_mmd": measured_mmd,
        "measured_mmd_source_spectrum": measured_mmd_source_spectrum,
        "personalization_basis": basis,
        "personalization_note": (
            "Environmental TanDose is skin-type independent. "
            "personal_mmd_fraction = TanDose / personal_mmd_equivalent_dose "
            "only when a measured/compatible MMD exists; Fitzpatrick alone never yields a precise MMD."
        ),
    }


def attach_personalization(
    df: pd.DataFrame,
    personal_mmd_j_m2: float | None = None,
    basis: str | None = None,
    dose_col: str = "tan_dose_1h_j_m2",
) -> pd.DataFrame:
    """Add personal_mmd_fraction without touching environmental columns.

    An MMD without an explicit basis is rejected: fractions with implied-but-
    absent provenance are worse than no fractions. Callers that only forward
    user input (CLI/API/export) enforce the same rule at their boundary.
    """
    if personal_mmd_j_m2 is not None and basis is None:
        raise ValueError(
            "personal_mmd_j_m2 requires an explicit basis (MEASURED, "
            "OBJECTIVE_ESTIMATE, or COARSE_ESTIMATE)")
    out = df.copy()
    out["personalization_basis"] = basis or "not personalized"
    if personal_mmd_j_m2 is not None and np.isfinite(personal_mmd_j_m2) and personal_mmd_j_m2 > 0:
        if dose_col in out:
            dose = pd.to_numeric(out[dose_col], errors="coerce")
            out["personal_mmd_fraction"] = (dose / personal_mmd_j_m2).round(3)
        else:
            # Dose column not computed yet (e.g. personalization attached
            # before interval integration): UNKNOWN, never a crash.
            out["personal_mmd_fraction"] = np.nan
        out["personal_mmd_equivalent_dose_j_m2"] = personal_mmd_j_m2
    else:
        out["personal_mmd_fraction"] = np.nan
        out["personal_mmd_equivalent_dose_j_m2"] = np.nan
    return out


def attach_fitzpatrick(df: pd.DataFrame, skin_type: int | None) -> pd.DataFrame:
    out = df.copy()
    ctx = fitzpatrick_context(skin_type)
    for k, v in ctx.items():
        out[k] = v
    # Qualitative risk context only; avoid false numeric MED multipliers.
    if skin_type is None:
        out["personal_uv_risk_context"] = "not personalized"
    elif skin_type <= 2:
        out["personal_uv_risk_context"] = (
            "higher erythema susceptibility; avoid treating TanScore as safe exposure guidance"
        )
    elif skin_type <= 4:
        out["personal_uv_risk_context"] = (
            "intermediate erythema susceptibility; individual response varies substantially"
        )
    else:
        out["personal_uv_risk_context"] = (
            "lower erythema susceptibility than lighter phototypes, but UV damage still occurs"
        )
    return out


def _as_utc(stamps: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(stamps)
    if getattr(parsed.dt, "tz", None) is None:
        parsed = parsed.dt.tz_localize(
            ZoneInfo(config.TIMEZONE), ambiguous="infer", nonexistent="shift_forward"
        )
    return parsed.dt.tz_convert("UTC")


def _toa_wm2(times_utc: pd.Series) -> np.ndarray:
    """Exact extraterrestrial horizontal irradiance: pure solar geometry."""
    loc = pvlib.location.Location(config.LATITUDE, config.LONGITUDE, tz="UTC")
    zen = pd.DataFrame(loc.get_solarposition(pd.DatetimeIndex(times_utc)))[
        "zenith"
    ].to_numpy(dtype=float)
    return np.clip(1361.1 * np.cos(np.radians(zen)), 0, None)


def build_30min_forecast(
    hourly: pd.DataFrame, hrrr15: pd.DataFrame | None = None,
    min_temp_f: float | None = None,
    calibration_dir = None,
) -> pd.DataFrame:
    if hourly.empty:
        return pd.DataFrame()
    h = hourly.copy()
    local = pd.to_datetime(h["time"])
    h["dt"] = local
    # DST fall-back repeats wall-clock labels (1:00-2:00am twice) when the API
    # returns both instances. Input order is chronological, so the first label
    # is the pre-transition instance; either way these are night rows that
    # never affect windows. Dedupe so the resample below cannot abort the run.
    h = h.loc[~h["dt"].duplicated(keep="first")].copy()
    h = h.sort_values("dt").set_index("dt")
    # Schema contract for the hourly->subhour transformer: every numeric
    # column the downstream pipeline needs must survive here, regardless of
    # the dtype the feed happened to deliver (object/string/None). Missing
    # weather must NEVER silently read as perfect weather downstream.
    _SUBHOUR_NUMERIC_COLUMNS = (
        # UV / scoring
        "uv_index",
        "uvi_openmeteo",
        "uvi_consensus",
        "uvi_epa",
        "uvi_cams",
        "uvi_source_spread",
        "uvi_consensus_sources",
        "uvi_sunny",
        "uvi_cloudy",
        "predicted_uva_wm2",
        "predicted_uvb_wm2",
        "shortwave_radiation_instant",
        "overall_tan_opportunity_0_100",
        "tan_score_absolute_0_100",
        # weather / feasibility (P0: these were silently dropped when
        # object-typed, so 30-min rows read as comfortable and dry)
        "temperature_2m",
        "apparent_temperature",
        "relative_humidity_2m",
        "precipitation_probability",
        "precipitation",
        "rain",
        "showers",
        "snowfall",
        "wind_speed_10m",
        "wind_gusts_10m",
        "weather_code",
    )
    numeric = h.select_dtypes(include=[np.number, "bool"]).copy()
    for _col in _SUBHOUR_NUMERIC_COLUMNS:
        if _col in h.columns and _col not in numeric.columns:
            numeric[_col] = pd.to_numeric(h[_col], errors="coerce")
    # Loud invariant: feasibility inputs absent from the hourly frame stay
    # absent downstream (feasibility treats missing temp as NaN->blocked, but
    # missing rain/wind as 0). Warn so a silently-dropped column can never
    # again read as perfect weather without anyone noticing.
    _missing = [c for c in ("temperature_2m", "precipitation_probability",
                            "wind_speed_10m", "weather_code")
                if c not in numeric.columns]
    if _missing and not h.empty:
        LOG.warning("30-min transformer missing feasibility columns: %s", _missing)
    idx = pd.date_range(h.index.min(), h.index.max(), freq="30min")
    union_idx = numeric.index.union(idx)
    # Boolean flags cannot hold reindex gaps (numpy bool upcasts to object and
    # breaks time interpolation) and must never be numerically interpolated:
    # forward-fill them like the discrete fields below.
    bool_cols = numeric.select_dtypes(include=["bool"]).columns.tolist()
    base = (
        numeric.drop(columns=bool_cols)
        .reindex(union_idx)
        .sort_index()
        .interpolate(method="time")
        .reindex(idx)
    )
    for col in bool_cols:
        base[col] = numeric[col].reindex(union_idx).sort_index().ffill().reindex(idx)
    # Never extrapolate an observation beyond its hourly valid span. pandas
    # time-interpolation forward-fills trailing NaNs, which would otherwise
    # fabricate horizon-limited fields (e.g. every CAMS column flatlined
    # across the 9 days past the 5-day CAMS horizon). Stamps outside each
    # column's [first_valid, last_valid] hourly span revert to NaN; interior
    # gaps keep their time interpolation, which is the honest middle.
    for col in base.columns:
        hseries = numeric[col].dropna() if col in numeric.columns else None
        if hseries is None or hseries.empty:
            base[col] = np.nan
            continue
        lo, hi = hseries.index.min(), hseries.index.max()
        base.loc[(base.index < lo) | (base.index > hi), col] = np.nan
    base = base.reindex(columns=[c for c in numeric.columns if c in base.columns])
    base.index.name = "dt"
    out = base.reset_index()
    out["time"] = out["dt"].dt.strftime("%Y-%m-%dT%H:%M")
    out["subhour_source"] = "interpolated_hourly"
    # Clear-sky-index interpolation for instantaneous GHI. Linear blends fail
    # where solar geometry moves fast (sunrise/sunset shoulders): they invent
    # light before sunrise. kt is smooth and dimensionless; the :30 TOA below
    # is exact astronomy, not interpolated. Backed by HRRR native 15-min
    # truth: daylight MAE 53.8 -> 51.5, median 16.0 -> 12.1 (n=258 slots).
    if "shortwave_radiation_instant" in h.columns:
        ghi_h = pd.to_numeric(h["shortwave_radiation_instant"], errors="coerce")
        toa_h = _toa_wm2(_as_utc(h.index.to_series()))
        kt_h = (ghi_h.to_numpy() / np.where(toa_h > 1, toa_h, np.nan)).clip(0, 1.5)
        kt_h = pd.Series(kt_h, index=h.index)
        stamps = pd.to_datetime(out["dt"])
        kt_30 = (
            kt_h.reindex(h.index.union(stamps))
            .sort_index()
            .interpolate(method="time")
            .reindex(stamps)
        )
        toa_30 = _toa_wm2(_as_utc(stamps))
        lin_ghi = np.asarray(
            ghi_h.reindex(h.index.union(stamps))
            .sort_index()
            .interpolate(method="time")
            .reindex(stamps),
            dtype=float,
        )
        kt_ghi = kt_30.to_numpy(dtype=float) * toa_30
        night = toa_30 <= 1
        improved = np.where(night, 0.0, np.where(np.isfinite(kt_ghi), kt_ghi, lin_ghi))
        out["shortwave_radiation_instant"] = improved
        # Propagate the geometry correction to the displayed UV numbers with
        # the same bounded-ratio pattern as the native-HRRR correction below.
        with np.errstate(divide="ignore", invalid="ignore"):
            raw_ratio = improved / np.where(lin_ghi > 5, lin_ghi, np.nan)
        ratio = np.where(
            night,
            0.0,
            np.where(np.isfinite(raw_ratio), np.clip(raw_ratio, 0.7, 1.3), 1.0),
        )
        changed = np.isfinite(ratio) & (ratio != 1.0)
        if changed.any() and {"predicted_uva_wm2", "uv_index"}.issubset(out.columns):
            out.loc[changed, "predicted_uva_wm2"] = (
                _num(out, "predicted_uva_wm2").to_numpy()[changed] * ratio[changed]
            )
            if "predicted_uvb_wm2" in out:
                out.loc[changed, "predicted_uvb_wm2"] = _num(
                    out, "predicted_uvb_wm2"
                ).to_numpy()[changed] * np.sqrt(ratio[changed])
            out.loc[changed, "uv_index"] = _num(out, "uv_index").to_numpy()[
                changed
            ] * np.sqrt(ratio[changed])
            if "tan_score_absolute_0_100" in out:
                # Single-pass derived state (§4): recompute ALL children from
                # the corrected primitives, never a hand-picked subset.
                from .state import recompute_derived_state as _recompute

                sub = _recompute(out.loc[changed].copy())
                for col in ("melanogenic_effective_irradiance_wm2",
                            "tan_score_absolute_0_100", "erythemal_irradiance_wm2",
                            "pigment_darkening_effective_irradiance",
                            "uvi_consensus", "uvi_consensus_sources",
                            "uvi_consensus_vote_count", "uvi_source_spread",
                            "uvi_sunny", "uvi_cloudy",
                            "uvi_difference_absolute", "uvi_difference_percent",
                            "fusion_version",
                            "legacy_absolute_tan_score_55_30_15",
                            "tan_score_model_version"):
                    if col in sub:
                        out.loc[changed, col] = sub[col].to_numpy()
    # Discrete WMO weather codes / day-night flags must never be numerically interpolated.
    for discrete in ("weather_code", "is_day"):
        if discrete in h.columns:
            nearest = (
                h[discrete]
                .reindex(h.index.union(idx))
                .sort_index()
                .ffill()
                .reindex(idx)
            )
            out[discrete] = nearest.to_numpy()
    # Run-constant model metadata is data we already have: carry it forward
    # instead of degrading to missing. Only genuinely constant fields qualify
    # — time-varying quantities (uvi_cams, CAMS irradiances, differences) must
    # stay NaN where unobserved, never forward-filled into fabrication.
    for constant in ("spectral_tier", "spectral_backend", "tan_score_model_version",
                     "tan_dose_model_version", "global_reference_version",
                     "photobiology_action_spectrum_tier", "tan_calibration_tier",
                     "local_reference_version", "cams_cycle"):
        if constant in h.columns:
            out[constant] = (
                h[constant]
                .reindex(h.index.union(idx))
                .sort_index()
                .ffill()
                .reindex(idx)
                .to_numpy()
            )

    # Solar geometry is recomputed exactly at every :30 stamp with pvlib
    # (audit: linear interpolation mislabeled as "true mid-hour sun"; near
    # noon the error is small, at shoulders it is not). Same code path serves
    # hourly, half-hourly, and future 15-min grids.
    try:
        import pvlib.location as _pvloc

        _loc = _pvloc.Location(config.LATITUDE, config.LONGITUDE, tz="UTC")
        _times = pd.DatetimeIndex(pd.to_datetime(_as_utc(out["dt"])))
        _pos = pd.DataFrame(_loc.get_solarposition(_times))
        out["solar_elevation_deg"] = np.round(
            90.0 - _pos["zenith"].to_numpy(dtype=float), 2)
        out["solar_azimuth_deg"] = np.round(
            _pos["azimuth"].to_numpy(dtype=float), 2)
    except (ImportError, ValueError, TypeError):
        pass
    try:
        from .tanscore import add_sun_posture as _add_posture

        if {"solar_elevation_deg", "solar_azimuth_deg"}.issubset(out.columns):
            out = _add_posture(out)
    except ImportError:
        pass

    if hrrr15 is not None and not hrrr15.empty:
        native = hrrr15.copy()
        native["dt"] = pd.to_datetime(native["time"])
        native = native[native["dt"].dt.minute.isin([0, 30])].set_index("dt")
        solar_cols = [
            "temperature_2m",
            "relative_humidity_2m",
            "dew_point_2m",
            "apparent_temperature",
            "precipitation",
            "rain",
            "snowfall",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
            "shortwave_radiation",
            "direct_radiation",
            "diffuse_radiation",
            "direct_normal_irradiance",
            "terrestrial_radiation",
            "shortwave_radiation_instant",
            "direct_radiation_instant",
            "diffuse_radiation_instant",
            "direct_normal_irradiance_instant",
            "terrestrial_radiation_instant",
        ]
        # Snapshot the current (possibly kt-improved) GHI BEFORE native values
        # overwrite it below. The correction ratio then measures native vs the
        # best estimate so far — not a second independent bound stacked on the
        # first (0.7 x 0.45 compounded to 0.31 in production data).
        baseline_ghi = (
            _num(out, "shortwave_radiation_instant").to_numpy()
            if "shortwave_radiation_instant" in out
            else None
        )
        mask = out["dt"].isin(native.index.tolist())
        for col in solar_cols:
            # Native HRRR may reintroduce a column the hourly transformer
            # dropped (e.g. object-typed weather rescued above keeps it, but
            # a column absent from hourly entirely must still come through).
            if col in native:
                if col not in out:
                    out[col] = np.nan
                out.loc[mask, col] = out.loc[mask, "dt"].map(native[col])
        out.loc[mask, "subhour_source"] = (
            "native_HRRR_radiation_weather_plus_interpolated_UV"
        )

        # Use the native HRRR broadband change as a bounded correction to UVA/UVB estimates.
        if baseline_ghi is not None and "predicted_uva_wm2" in out:
            native_ghi = _num(out, "shortwave_radiation_instant").to_numpy()
            ratio = np.divide(
                native_ghi,
                baseline_ghi,
                out=np.ones_like(native_ghi, dtype=float),
                where=np.isfinite(baseline_ghi) & (baseline_ghi > 40),
            )
            ratio = np.clip(ratio, 0.45, 1.55)
            is_native = out["subhour_source"].str.startswith("native_HRRR").to_numpy()
            out.loc[is_native, "predicted_uva_wm2"] *= ratio[is_native]
            if "predicted_uvb_wm2" in out:
                out.loc[is_native, "predicted_uvb_wm2"] *= np.sqrt(ratio[is_native])
            if "uv_index" in out:
                out.loc[is_native, "uv_index"] *= np.sqrt(ratio[is_native])
            if "uvi_consensus" in out:
                out.loc[is_native, "uvi_consensus"] *= np.sqrt(ratio[is_native])
            if {"uv_index", "predicted_uva_wm2", "tan_score_absolute_0_100"}.issubset(
                out.columns
            ):
                # Single-pass derived state (§4): the corrected sources feed
                # ONE recompute of consensus/erythemal/E_mel/disagreement. No
                # second hand-rolled fusion below may overwrite it.
                from .state import recompute_derived_state as _recompute_native

                sub = _recompute_native(out.loc[is_native].copy())
                for col in ("melanogenic_effective_irradiance_wm2",
                            "tan_score_absolute_0_100", "erythemal_irradiance_wm2",
                            "pigment_darkening_effective_irradiance",
                            "uvi_consensus", "uvi_consensus_sources",
                            "uvi_consensus_vote_count", "uvi_source_spread",
                            "uvi_sunny", "uvi_cloudy",
                            "uvi_difference_absolute", "uvi_difference_percent",
                            "fusion_version",
                            "legacy_absolute_tan_score_55_30_15",
                            "tan_score_model_version"):
                    if col in sub:
                        out.loc[is_native, col] = sub[col].to_numpy()
            _spread = pd.to_numeric(
                _num(out, "uvi_source_spread"), errors="coerce").fillna(0)
            out["uvi_source_disagree"] = (_spread >= 1.0).to_numpy(dtype=bool)
    # Local/Atmospheric recompute: Absolute changed under HRRR/kt correction
    # above, but Local/Atmo still percentile the OLD physics (audit: composite
    # of two physical states). Recompute against the calibration reference
    # when one is available; otherwise leave interpolated values.
    if calibration_dir is not None:
        try:
            import pandas as _pd

            from .tanscore import add_local_scores as _add_local

            _ref_path = calibration_dir / "local_reference.parquet"
            _ver_path = calibration_dir / "local_reference_version.json"
            _ref_ok = False
            try:
                import json as _json

                from . import config as _cfg

                _ver = _json.loads(_ver_path.read_text(encoding="utf-8"))
                _ref_ok = (_ver.get("tan_score_model_version")
                           == _cfg.TAN_SCORE_MODEL_VERSION)
            except (OSError, ValueError, TypeError):
                _ref_ok = False
            if _ref_ok and _ref_path.exists():
                _ref = _pd.read_parquet(_ref_path)
                # add_local_scores keys on time_utc; the 30-min frame carries
                # dt/time. Alias (not rename) so downstream keeps both.
                if "time_utc" not in out.columns and "dt" in out.columns:
                    out["time_utc"] = _pd.to_datetime(out["dt"], utc=True)
                out = _add_local(out, _ref)
        except (ImportError, ValueError, OSError):
            pass

    # Reapply merged opportunity after sub-hour corrections, carrying the
    # requested temperature floor (audit: used to fall back to 50F default).
    out = apply_outdoor_feasibility(out, min_temp_f)
    # Trailing interval doses (TanDose/SED/UVA/UVB) via trapezoidal integration.
    try:
        from .doses import add_interval_doses as _add_doses

        out = _add_doses(out)
    except (ImportError, ValueError) as exc:
        # Loud degradation: dose columns stay absent downstream (NaN-tolerant
        # readers show unknown), but the cause is logged, never swallowed.
        LOG.warning("30-min interval doses unavailable: %s", exc)
    return out


# Weekly class blocks, minutes since midnight ET, Mon=0..Fri=4 (mirrors UI CLASSES).
# South-Bend (Eastern) only; other sites get no constraint.
_CLASS_BLOCKS = {
    0: [(660, 735), (770, 820), (840, 950)],
    1: [(570, 620), (660, 735)],
    2: [(660, 735), (770, 820), (840, 950)],
    3: [(660, 735)],
    4: [(770, 820)],
}


def _in_class(dt: pd.Timestamp) -> bool:
    try:
        wd = int(dt.dayofweek)
    except (AttributeError, TypeError, ValueError):
        return False
    if wd > 4:
        return False
    mins = int(dt.hour) * 60 + int(dt.minute)
    return any(a <= mins < b for a, b in _CLASS_BLOCKS.get(wd, []))


def _best_contiguous_window(
    day: pd.DataFrame, threshold_delta: float = 12.0,
    skip_class: bool = False,
) -> tuple[pd.Timestamp, pd.Timestamp, float] | None:
    """Longest near-peak sustained outdoor period (legacy Overall-based).

    Contract §16.4: this is NOT the maximum-dose fixed-duration window — it
    answers "longest comfortable stretch near the peak", ranked by Overall
    opportunity. Physical dose ranking lives in best_fixed_dose_window().
    """
    if day.empty:
        return None
    d = day.sort_values(by=["dt"]).copy()
    score = _num(d, "overall_tan_opportunity_0_100").fillna(0)
    peak = float(score.max())
    if peak <= 0:
        return None
    eligible = d[
        (score >= max(10.0, peak - threshold_delta))
        & (~d["outdoor_blocked"].fillna(False))
    ].copy()
    if skip_class:
        eligible = eligible.loc[~eligible["dt"].map(_in_class)].copy()
    if eligible.empty:
        return None
    groups, cur, last = [], [], None
    for _, row in eligible.iterrows():
        if last is None or row["dt"] - last == pd.Timedelta(minutes=30):
            cur.append(row)
        else:
            groups.append(cur)
            cur = [row]
        last = row["dt"]
    if cur:
        groups.append(cur)
    groups.sort(
        key=lambda g: (
            len(g),
            np.mean([float(x["overall_tan_opportunity_0_100"]) for x in g]),
        ),
        reverse=True,
    )
    g = groups[0]
    return (
        g[0]["dt"],
        g[-1]["dt"] + pd.Timedelta(minutes=30),
        float(np.mean([x["overall_tan_opportunity_0_100"] for x in g])),
    )


def best_fixed_dose_window(
    day: pd.DataFrame, duration_min: int = 30,
    usable_only: bool = True, comfort_min: float | None = None,
    dose_tolerance_frac: float = 0.01,
) -> tuple[pd.Timestamp, pd.Timestamp, float] | None:
    """Maximum expected delayed-pigmentation dose over a fixed window (§16.3).

    Candidates are explicit [start, start+duration) intervals on the 30-min
    grid. Primary key: expected E_mel dose. Near-ties (within
    dose_tolerance_frac or the model uncertainty floor) break toward lower
    expected error, then comfort, then earliest start. Local percentile never
    enters the physical objective. Returns (start, end, dose_J_m2).
    """
    if day.empty:
        return None
    d = day.sort_values(by=["dt"]).copy()
    d["dt"] = pd.to_datetime(d["dt"])
    step = pd.Timedelta(minutes=30)
    # A duration-D window on the 30-min grid needs D/30 legs = D/30+1 stamps:
    # 30 min -> 2 stamps (one trapezoid leg), 60 min -> 3 stamps (two legs).
    n_legs = max(round(duration_min / 30), 1)
    n_slots = n_legs + 1
    e_mel = _num(d, "melanogenic_effective_irradiance_wm2")
    conf = _num(d, "tan_forecast_confidence_0_100")
    blocked = d["outdoor_blocked"].fillna(False) if "outdoor_blocked" in d else False
    stamps = d["dt"].reset_index(drop=True)
    e_vals = e_mel.reset_index(drop=True)
    c_vals = conf.reset_index(drop=True)
    if isinstance(blocked, pd.Series):
        blocked = blocked.reset_index(drop=True)
    best: tuple[object, object, float] | None = None
    best_err = float("inf")
    for i in range(len(d) - n_slots + 1):
        # Candidate [start, start+duration): n_slots stamps bound n_legs
        # trapezoid legs. A 30-min window on the 30-min grid integrates ONE
        # leg: 0.5*(e0+e1)*1800 — the honest interval energy, never e0*1800
        # as if the stamp were a backward mean.
        window_idx = list(range(i, i + n_slots))
        ok_grid = all(
            stamps.iloc[window_idx[k + 1]] - stamps.iloc[window_idx[k]] == step
            for k in range(n_slots - 1))
        if not ok_grid:
            continue
        seg = e_vals.iloc[window_idx]
        if bool(seg.isna().any()):
            continue
        if bool((seg <= 0).all()):
            continue  # night/zero window: no physical stimulus to rank
        if usable_only and isinstance(blocked, pd.Series) and bool(blocked.iloc[window_idx].any()):
            continue
        vals = [float(seg.iloc[j]) for j in range(len(seg))]
        legs = sum(0.5 * (vals[k] + vals[k + 1]) * 1800.0 for k in range(n_slots - 1)) if n_slots > 1 else 0.0
        dose = float(legs)
        err = float(100.0 - c_vals.iloc[window_idx].mean()) if bool(c_vals.iloc[window_idx].notna().any()) else 50.0
        if best is None or dose > best[2] * (1.0 + dose_tolerance_frac) or (
            abs(dose - best[2]) <= best[2] * dose_tolerance_frac and err < best_err
        ):
            best = (stamps.iloc[i], stamps.iloc[i] + pd.Timedelta(minutes=duration_min), dose)
            best_err = err
    if best is None:
        return None
    start = pd.to_datetime(best[0])
    end = pd.to_datetime(best[1])
    return (start, end, float(best[2]))


def build_daily_summary(subhour: pd.DataFrame) -> pd.DataFrame:
    if subhour.empty:
        return pd.DataFrame()
    df = subhour.copy()
    df["dt"] = pd.to_datetime(df["dt"])
    df["date"] = df["dt"].dt.date.astype(str)
    rows = []
    for day, g in df.groupby("date"):
        if not isinstance(g, pd.DataFrame):
            raise TypeError("date group must be a DataFrame")
        # Astronomical daylight (audit: wall-clock 8-20 was wrong by
        # season/latitude/DST). is_day when present, else solar elevation.
        def _col(name: str, _g: pd.DataFrame = g) -> pd.Series:
            _raw = _g.get(name)
            _n, _idx = len(_g), _g.index
            return pd.to_numeric(
                _raw if isinstance(_raw, pd.Series)
                else pd.Series([_raw] * _n, index=_idx),
                errors="coerce")
        _isday = _col("is_day")
        if bool(_isday.notna().any()):
            daylight = g.loc[_isday.fillna(0) > 0].copy()
        elif "solar_elevation_deg" in g.columns:
            daylight = g.loc[_col("solar_elevation_deg").fillna(-90) > 0].copy()
        else:
            # No astronomical signal at all (unit fixtures): fall back to the
            # legacy wall-clock window rather than dropping the day silently.
            _hours = pd.to_datetime(scol(g, "dt")).dt.hour
            daylight = g.loc[(_hours >= 8) & (_hours < 20)].copy()
        if daylight.empty:
            continue
        score = _num(daylight, "overall_tan_opportunity_0_100").fillna(0)
        best_idx = score.idxmax()
        best = daylight.loc[best_idx]
        # Best one-hour rolling pair.
        s = daylight.sort_values(by=["dt"]).reset_index(drop=True)
        best_hour = None
        best_hour_score = -1.0
        for i in range(len(s) - 1):
            if s.loc[i + 1, "dt"] - s.loc[i, "dt"] != pd.Timedelta(minutes=30):
                continue
            window_rows = s.loc[i : i + 1]
            if not isinstance(window_rows, pd.DataFrame):
                raise TypeError("rolling window slice must be a DataFrame")
            pair = _num(window_rows, "overall_tan_opportunity_0_100").fillna(0)
            avg = float(pair.mean())
            if avg > best_hour_score:
                best_hour_score = avg
                best_hour = s.loc[i, "dt"]
        window = _best_contiguous_window(daylight)
        # Class-aware window: same ranking, class blocks excluded (south-bend
        # Eastern schedule; None when the whole window is in class).
        avail = _best_contiguous_window(daylight, skip_class=True)
        # v5 physical ranking (§16.3, fixed-duration-dose-v2): strongest 30m
        # E_mel dose regardless of comfort; best usable 30m among windows
        # passing hard outdoor constraints. Local percentile never enters.
        strongest_30m = best_fixed_dose_window(daylight, 30, usable_only=False)
        usable_30m = best_fixed_dose_window(daylight, 30, usable_only=True)
        try:
            from .doses import day_totals as _day_totals
            from .doses import window_dose as _window_dose

            _day_row = _day_totals(g)
            _day_match = _day_row.loc[_day_row["date"] == day]
            _day_doses = _day_match.iloc[0].to_dict() if len(_day_match) else {}
            _win_doses = _window_dose(g, window[0], window[1]) if window else {}
        except (ImportError, ValueError, KeyError, RuntimeError):
            _day_doses, _win_doses = {}, {}
        # Best-30m / best-hour interval doses from trailing columns when present.
        # Trailing columns END at their row stamp: the dose for the forward
        # interval [t, t+30m) selected as best_30m_start=t lives on the row at
        # t+30m, so read there (searching the full day grid g, since t+30m can
        # sit outside the daylight slice). Missing end stamp -> NaN, never a
        # neighboring slot's dose relabeled.
        def _col_at(col: str, stamp, _grid: pd.DataFrame = g) -> float:
            try:
                hit = _grid.loc[pd.to_datetime(_grid["dt"]) == pd.to_datetime(stamp), col]
                return float(hit.iloc[0]) if len(hit) else float("nan")
            except (KeyError, ValueError, IndexError, TypeError):
                return float("nan")
        _best_end = best["dt"] + pd.Timedelta(minutes=30)
        best_hour_end = (best_hour + pd.Timedelta(minutes=60)) if best_hour is not None else None
        try:
            from .doses import window_dose as _wd2

            _hour_doses = _wd2(g, best_hour, best_hour_end) if best_hour is not None else {}
        except (ImportError, ValueError, KeyError, RuntimeError):
            _hour_doses = {}
        rows.append(
            {
                "date": day,
                "day_overall_peak_0_100": round(
                    float(best["overall_tan_opportunity_0_100"]), 1
                ),
                # Contract §16.5/§27.11: every field named peak is that
                # field's own maximum, never the value at another metric's
                # peak. Values AT the opportunity peak ride as *_at_best_*.
                "day_absolute_peak_0_100": round(
                    float(_num(daylight, "tan_score_absolute_0_100").max()), 1
                ),
                "day_absolute_at_best_usable_30m_0_100": round(
                    float(best.get("tan_score_absolute_0_100", np.nan)), 1
                ),
                "day_local_peak_0_100": round(
                    float(_num(daylight, "local_tan_score_0_100").max()), 1
                ),
                "day_local_at_best_usable_30m_0_100": round(
                    float(best.get("local_tan_score_0_100", np.nan)), 1
                ),
                "day_atmospheric_peak_0_100": round(
                    float(_num(daylight, "atmospheric_quality_percentile_0_100").max()), 1
                ),
                "day_confidence_at_peak_0_100": round(
                    float(best.get("tan_forecast_confidence_0_100", np.nan)), 1
                ),
                "best_30m_start": best["dt"].isoformat(),
                "best_30m_tan_dose_j_m2": _col_at("tan_dose_30m_j_m2", _best_end),
                "best_30m_sed": _col_at("sed_30m", _best_end),
                "best_hour_start": best_hour.isoformat()
                if best_hour is not None
                else None,
                "best_hour_score_0_100": round(best_hour_score, 1)
                if best_hour is not None
                else np.nan,
                "best_hour_tan_dose_j_m2": float(_hour_doses.get("tan_dose_best_window_j_m2", float("nan"))),
                "best_hour_sed": float(_hour_doses.get("sed_best_window", float("nan"))),
                "best_hour_tan_dose_complete": bool(_hour_doses.get("tan_dose_best_window_complete", False)),
                "best_hour_tan_dose_coverage_fraction": float(_hour_doses.get("tan_dose_best_window_coverage_fraction", float("nan"))),
                "best_hour_sed_complete": bool(_hour_doses.get("sed_best_window_complete", False)),
                "best_hour_sed_coverage_fraction": float(_hour_doses.get("sed_best_window_coverage_fraction", float("nan"))),
                "best_window_start": window[0].isoformat() if window else None,
                "best_window_end": window[1].isoformat() if window else None,
                "best_window_mean_0_100": round(window[2], 1) if window else np.nan,
                "best_available_window_start": avail[0].isoformat() if avail else None,
                "best_available_window_end": avail[1].isoformat() if avail else None,
                "best_available_window_mean_0_100": round(avail[2], 1) if avail else np.nan,
                "best_window_rank_formula": "window-rank-v1 (mean overall opportunity over contiguous eligible half-hours; dose reported, not ranked)",
                "strongest_30m_start": strongest_30m[0].isoformat() if strongest_30m else None,
                "strongest_30m_end": strongest_30m[1].isoformat() if strongest_30m else None,
                "strongest_30m_dose_j_m2": round(strongest_30m[2], 1) if strongest_30m else np.nan,
                "best_usable_30m_start": usable_30m[0].isoformat() if usable_30m else None,
                "best_usable_30m_end": usable_30m[1].isoformat() if usable_30m else None,
                "best_usable_30m_dose_j_m2": round(usable_30m[2], 1) if usable_30m else np.nan,
                "window_rank_version": "fixed-duration-dose-v2",
                "exposure_basis": "environmental_horizontal",
                "tan_dose_best_window_j_m2": float(_win_doses.get("tan_dose_best_window_j_m2", float("nan"))),
                "tan_dose_best_window_complete": bool(_win_doses.get("tan_dose_best_window_complete", False)),
                "tan_dose_best_window_coverage_fraction": float(_win_doses.get("tan_dose_best_window_coverage_fraction", float("nan"))),
                "sed_best_window": float(_win_doses.get("sed_best_window", float("nan"))),
                "sed_best_window_complete": bool(_win_doses.get("sed_best_window_complete", False)),
                "sed_best_window_coverage_fraction": float(_win_doses.get("sed_best_window_coverage_fraction", float("nan"))),
                "uva_dose_window_j_m2": float(_win_doses.get("uva_dose_window_j_m2", float("nan"))),
                "uvb_dose_window_j_m2": float(_win_doses.get("uvb_dose_window_j_m2", float("nan"))),
                "tan_dose_day_j_m2": float(_day_doses.get("tan_dose_day_j_m2", float("nan"))),
                "tan_dose_day_reference_minutes": float(_day_doses.get("tan_dose_day_reference_minutes", float("nan"))),
                "tan_dose_complete": bool(_day_doses.get("tan_dose_complete", False)),
                "tan_dose_coverage_fraction": float(_day_doses.get("tan_dose_coverage_fraction", float("nan"))),
                "sed_day_total": float(_day_doses.get("sed_day_total", float("nan"))),
                "sed_complete": bool(_day_doses.get("sed_complete", False)),
                "sed_coverage_fraction": float(_day_doses.get("sed_coverage_fraction", float("nan"))),
                "uva_dose_day_j_m2": float(_day_doses.get("uva_dose_day_j_m2", float("nan"))),
                "uvb_dose_day_j_m2": float(_day_doses.get("uvb_dose_day_j_m2", float("nan"))),
                "peak_uv_index": round(float(_num(s, "uvi_consensus" if "uvi_consensus" in s else "uv_index").max()), 2),
                "peak_predicted_uva_wm2": round(
                    float(_num(s, "predicted_uva_wm2").max()), 2
                ),
                "peak_temperature_f": round(
                    float(_num(s, "temperature_2m").max()), 1
                ),
                "peak_precip_probability_pct": round(
                    float(_num(s, "precipitation_probability").max()), 1
                ),
                # Values at the opportunity peak (what the old peak_* fields
                # used to mean). True maxima above; both kept for back-compat.
                "uvi_at_best": round(float(best.get("uvi_consensus", best.get("uv_index", np.nan))), 2),
                "temperature_at_best_f": round(
                    float(best.get("temperature_2m", np.nan)), 1
                ),
                "precip_at_best_pct": round(
                    float(best.get("precipitation_probability", np.nan)), 1
                ),
                "peak_30m_tan_dose_j_m2": round(
                    float(_num(s, "tan_dose_30m_j_m2").max()), 1
                ),
                "peak_30m_sed": round(
                    float(_num(s, "sed_30m").max()), 3
                ),
                "day_high_temperature_f": round(
                    float(_num(s, "temperature_2m").max()), 1
                ),
                "day_low_temperature_f": round(
                    float(_num(s, "temperature_2m").min()), 1
                ),
                "day_high_feels_like_f": round(
                    float(_num(s, "apparent_temperature").max()), 1
                ),
                "day_low_feels_like_f": round(
                    float(_num(s, "apparent_temperature").min()), 1
                ),
                "day_peak_wind_mph": round(float(_num(s, "wind_speed_10m").max()), 1),
                "day_peak_gust_mph": round(float(_num(s, "wind_gusts_10m").max()), 1),
                "blocked_half_hours": int(
                    scol(daylight, "outdoor_blocked").fillna(False).sum()
                ),
                "day_status": _day_status(float(best["overall_tan_opportunity_0_100"])),
            }
        )
    return pd.DataFrame(rows)


def _day_status(score: float) -> str:
    if not np.isfinite(score):
        return "UNKNOWN"
    if score >= 80:
        return "EXCELLENT"
    if score >= 65:
        return "VERY GOOD"
    if score >= 50:
        return "GOOD"
    if score >= 35:
        return "FAIR"
    if score > 0:
        return "POOR"
    return "NO OUTDOOR WINDOW"
