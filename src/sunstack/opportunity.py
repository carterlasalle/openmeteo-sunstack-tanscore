from __future__ import annotations

import math
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pvlib.location

from . import config
from .calibrate import absolute_tan_score, num, scol

RAIN_CODES = set(range(51, 68)) | {80, 81, 82}
SNOW_CODES = set(range(71, 78)) | {85, 86}
THUNDER_CODES = {95, 96, 99}

def _num(df: pd.DataFrame, name: str, default=np.nan) -> pd.Series:
    return num(df, name, default)


def _weighted_geometric(row: pd.Series) -> float:
    vals: dict[str, Any] = {
        "absolute": row.get("tan_score_absolute_0_100", np.nan),
        "local": row.get("local_tan_score_0_100", np.nan),
        "atmosphere": row.get("atmospheric_quality_percentile_0_100", np.nan),
        "confidence": row.get("tan_forecast_confidence_0_100", np.nan),
    }
    weights = config.OVERALL_SCORE_WEIGHTS
    usable = [(float(vals[k]), float(weights[k])) for k in weights if bool(pd.notna(vals.get(k)))]
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


def apply_outdoor_feasibility(scored: pd.DataFrame, min_temp_f: float | None = None) -> pd.DataFrame:
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
    feels = _num(out, "apparent_temperature")
    rain = _num(out, "rain", 0).fillna(0)
    showers = _num(out, "showers", 0).fillna(0)
    snow = _num(out, "snowfall", 0).fillna(0)
    pop = _num(out, "precipitation_probability", 0).fillna(0).clip(0, 100)
    wind = _num(out, "wind_speed_10m", 0).fillna(0)
    rh = _num(out, "relative_humidity_2m")
    code = _num(out, "weather_code").fillna(-1).round().astype(int)

    rain_now = (rain > config.ACTIVE_PRECIP_IN_THRESHOLD) | (showers > config.ACTIVE_PRECIP_IN_THRESHOLD) | code.isin(RAIN_CODES)
    snow_now = (snow > config.ACTIVE_SNOW_IN_THRESHOLD) | code.isin(SNOW_CODES)
    thunder = code.isin(THUNDER_CODES)
    too_hot = temp >= config.MAX_TAN_TEMP_F
    too_cold = temp < min_temp
    hard_block = rain_now | snow_now | thunder | too_hot | too_cold

    multiplier = pd.Series(1.0, index=out.index)
    # Cold/heat comfort penalties between hard floors/ceilings.
    cold_band = (temp >= min_temp) & (temp < config.COMFORTABLE_TAN_TEMP_F)
    if config.COMFORTABLE_TAN_TEMP_F > min_temp:
        frac = (temp - min_temp) / (config.COMFORTABLE_TAN_TEMP_F - min_temp)
        multiplier.loc[cold_band] *= (0.45 + 0.55 * frac.loc[cold_band].clip(0, 1))
    warm = (temp >= config.HEAT_WARNING_TEMP_F) & (temp < config.MAX_TAN_TEMP_F)
    if config.MAX_TAN_TEMP_F > config.HEAT_WARNING_TEMP_F:
        heat_frac = (temp - config.HEAT_WARNING_TEMP_F) / (config.MAX_TAN_TEMP_F - config.HEAT_WARNING_TEMP_F)
        multiplier.loc[warm] *= (1.0 - 0.45 * heat_frac.loc[warm].clip(0, 1))

    # Rain risk is a practical window-reliability penalty, not a melanogenesis term.
    multiplier *= (1.0 - config.PRECIP_PROBABILITY_PENALTY_MAX * (pop / 100.0) ** 1.2)
    multiplier.loc[wind >= config.WIND_WARNING_MPH] *= 0.80
    multiplier.loc[wind >= config.WIND_STRONG_MPH] *= 0.65
    multiplier.loc[hard_block] = 0.0

    reasons: list[str] = []
    flags: list[str] = []
    for i in out.index:
        rs, fs = [], []
        if bool(rain_now.loc[i]): rs.append("active rain/drizzle/showers")
        if bool(snow_now.loc[i]): rs.append("active snow")
        if bool(thunder.loc[i]): rs.append("thunderstorm")
        if pd.notna(temp.loc[i]) and temp.loc[i] >= config.MAX_TAN_TEMP_F: rs.append(f"temperature >= {config.MAX_TAN_TEMP_F:.0f}F")
        if pd.notna(temp.loc[i]) and temp.loc[i] < min_temp: rs.append(f"temperature < {min_temp:.0f}F")
        if not rs:
            if pd.notna(temp.loc[i]) and temp.loc[i] < config.COMFORTABLE_TAN_TEMP_F: fs.append("cold")
            if pd.notna(temp.loc[i]) and temp.loc[i] >= config.HEAT_WARNING_TEMP_F: fs.append("heat")
            if pop.loc[i] >= 40: fs.append(f"{pop.loc[i]:.0f}% precipitation risk")
            if wind.loc[i] >= config.WIND_WARNING_MPH: fs.append("windy")
            if pd.notna(rh.loc[i]) and pd.notna(temp.loc[i]) and rh.loc[i] >= 80 and temp.loc[i] >= 80: fs.append("humid/sweaty")
            if pd.notna(feels.loc[i]) and feels.loc[i] >= 100: fs.append("high apparent temperature")
        reasons.append("; ".join(rs))
        flags.append("; ".join(fs))

    out["outdoor_feasibility_0_100"] = np.round(multiplier * 100, 1)
    out["outdoor_blocked"] = hard_block.to_numpy()
    out["outdoor_block_reason"] = reasons
    out["outdoor_flags"] = flags
    out["minimum_tan_temperature_f"] = min_temp

    out["overall_components_unblocked_0_100"] = out.apply(_weighted_geometric, axis=1).round(1)
    out["overall_tan_opportunity_0_100"] = (
        out["overall_components_unblocked_0_100"] * multiplier
    ).clip(0, 100).round(1)
    # No sun above the horizon means no opportunity, full stop. Mirrors the
    # night-zero clamp on predicted UVA/UVB; kills the log-math floor (~1)
    # that the geometric mean leaves on night rows.
    sza = _num(out, "sza")
    night = sza.notna() & (sza >= 90)
    if bool(night.any()):
        out.loc[night.to_numpy(), ["overall_components_unblocked_0_100", "overall_tan_opportunity_0_100"]] = 0.0
    return out


def fitzpatrick_context(skin_type: int | None) -> dict[str, str | int | None]:
    if skin_type is None:
        return {"fitzpatrick_type": None, "fitzpatrick_label": "not specified", "skin_response_note": "Environmental scores are skin-type independent."}
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


def attach_fitzpatrick(df: pd.DataFrame, skin_type: int | None) -> pd.DataFrame:
    out = df.copy()
    ctx = fitzpatrick_context(skin_type)
    for k, v in ctx.items():
        out[k] = v
    # Qualitative risk context only; avoid false numeric MED multipliers.
    if skin_type is None:
        out["personal_uv_risk_context"] = "not personalized"
    elif skin_type <= 2:
        out["personal_uv_risk_context"] = "higher erythema susceptibility; avoid treating TanScore as safe exposure guidance"
    elif skin_type <= 4:
        out["personal_uv_risk_context"] = "intermediate erythema susceptibility; individual response varies substantially"
    else:
        out["personal_uv_risk_context"] = "lower erythema susceptibility than lighter phototypes, but UV damage still occurs"
    return out


def _as_utc(stamps: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(stamps)
    if getattr(parsed.dt, "tz", None) is None:
        parsed = parsed.dt.tz_localize(ZoneInfo(config.TIMEZONE), ambiguous="infer", nonexistent="shift_forward")
    return parsed.dt.tz_convert("UTC")


def _toa_wm2(times_utc: pd.Series) -> np.ndarray:
    """Exact extraterrestrial horizontal irradiance: pure solar geometry."""
    loc = pvlib.location.Location(config.LATITUDE, config.LONGITUDE, tz="UTC")
    zen = pd.DataFrame(loc.get_solarposition(pd.DatetimeIndex(times_utc)))["zenith"].to_numpy(dtype=float)
    return np.clip(1361.1 * np.cos(np.radians(zen)), 0, None)


def build_30min_forecast(hourly: pd.DataFrame, hrrr15: pd.DataFrame | None = None) -> pd.DataFrame:
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
    numeric = h.select_dtypes(include=[np.number, "bool"]).copy()
    # Some feeds deliver numeric-looking columns as strings/None, which the
    # dtype filter silently drops (the UI then falls back to a different
    # product for those cells). Coerce the display-critical ones explicitly.
    for _col in (
        "uv_index", "predicted_uva_wm2", "predicted_uvb_wm2",
        "shortwave_radiation_instant", "overall_tan_opportunity_0_100",
        "tan_score_absolute_0_100",
    ):
        if _col in h.columns and _col not in numeric.columns:
            numeric[_col] = pd.to_numeric(h[_col], errors="coerce")
    idx = pd.date_range(h.index.min(), h.index.max(), freq="30min")
    union_idx = numeric.index.union(idx)
    # Boolean flags cannot hold reindex gaps (numpy bool upcasts to object and
    # breaks time interpolation) and must never be numerically interpolated:
    # forward-fill them like the discrete fields below.
    bool_cols = numeric.select_dtypes(include=["bool"]).columns.tolist()
    base = (
        numeric.drop(columns=bool_cols)
        .reindex(union_idx).sort_index().interpolate(method="time").reindex(idx)
    )
    for col in bool_cols:
        base[col] = numeric[col].reindex(union_idx).sort_index().ffill().reindex(idx)
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
        kt_30 = kt_h.reindex(h.index.union(stamps)).sort_index().interpolate(method="time").reindex(stamps)
        toa_30 = _toa_wm2(_as_utc(stamps))
        lin_ghi = np.asarray(
            ghi_h.reindex(h.index.union(stamps)).sort_index().interpolate(method="time").reindex(stamps),
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
        ratio = np.where(night, 0.0, np.where(np.isfinite(raw_ratio), np.clip(raw_ratio, 0.7, 1.3), 1.0))
        changed = np.isfinite(ratio) & (ratio != 1.0)
        if changed.any() and {"predicted_uva_wm2", "uv_index"}.issubset(out.columns):
            out.loc[changed, "predicted_uva_wm2"] = (
                _num(out, "predicted_uva_wm2").to_numpy()[changed] * ratio[changed]
            )
            if "predicted_uvb_wm2" in out:
                out.loc[changed, "predicted_uvb_wm2"] = (
                    _num(out, "predicted_uvb_wm2").to_numpy()[changed] * np.sqrt(ratio[changed])
                )
            out.loc[changed, "uv_index"] = (
                _num(out, "uv_index").to_numpy()[changed] * np.sqrt(ratio[changed])
            )
            if "tan_score_absolute_0_100" in out:
                out.loc[changed, "tan_score_absolute_0_100"] = absolute_tan_score(
                    out.loc[changed, "uv_index"], out.loc[changed, "predicted_uva_wm2"]
                )
    # Discrete WMO weather codes / day-night flags must never be numerically interpolated.
    for discrete in ("weather_code", "is_day"):
        if discrete in h.columns:
            nearest = h[discrete].reindex(h.index.union(idx)).sort_index().ffill().reindex(idx)
            out[discrete] = nearest.to_numpy()

    # Preserve/string interpolate nearest labels from hourly.
    nearest = h.reset_index()[["dt"]].copy()
    nearest["time_key"] = nearest["dt"]

    if hrrr15 is not None and not hrrr15.empty:
        native = hrrr15.copy()
        native["dt"] = pd.to_datetime(native["time"])
        native = native[native["dt"].dt.minute.isin([0, 30])].set_index("dt")
        solar_cols = [
            "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
            "precipitation", "rain", "snowfall", "weather_code", "wind_speed_10m", "wind_gusts_10m",
            "shortwave_radiation", "direct_radiation", "diffuse_radiation", "direct_normal_irradiance",
            "terrestrial_radiation", "shortwave_radiation_instant", "direct_radiation_instant",
            "diffuse_radiation_instant", "direct_normal_irradiance_instant", "terrestrial_radiation_instant",
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
            if col in native and col in out:
                out.loc[mask, col] = out.loc[mask, "dt"].map(native[col])
        out.loc[mask, "subhour_source"] = "native_HRRR_radiation_weather_plus_interpolated_UV"

        # Use the native HRRR broadband change as a bounded correction to UVA/UVB estimates.
        if baseline_ghi is not None and "predicted_uva_wm2" in out:
            native_ghi = _num(out, "shortwave_radiation_instant").to_numpy()
            ratio = np.divide(native_ghi, baseline_ghi, out=np.ones_like(native_ghi, dtype=float), where=np.isfinite(baseline_ghi) & (baseline_ghi > 40))
            ratio = np.clip(ratio, 0.45, 1.55)
            is_native = out["subhour_source"].str.startswith("native_HRRR").to_numpy()
            out.loc[is_native, "predicted_uva_wm2"] *= ratio[is_native]
            if "predicted_uvb_wm2" in out:
                out.loc[is_native, "predicted_uvb_wm2"] *= np.sqrt(ratio[is_native])
            if "uv_index" in out:
                out.loc[is_native, "uv_index"] *= np.sqrt(ratio[is_native])
            if {"uv_index", "predicted_uva_wm2", "tan_score_absolute_0_100"}.issubset(out.columns):
                out.loc[is_native, "tan_score_absolute_0_100"] = absolute_tan_score(
                    out.loc[is_native, "uv_index"], out.loc[is_native, "predicted_uva_wm2"]
                )

    # Reapply merged opportunity after sub-hour corrections.
    out = apply_outdoor_feasibility(out)
    return out


def _best_contiguous_window(day: pd.DataFrame, threshold_delta: float = 12.0) -> tuple[pd.Timestamp, pd.Timestamp, float] | None:
    if day.empty:
        return None
    d = day.sort_values(by=["dt"]).copy()
    score = _num(d, "overall_tan_opportunity_0_100").fillna(0)
    peak = float(score.max())
    if peak <= 0:
        return None
    eligible = d[(score >= max(10.0, peak - threshold_delta)) & (~d["outdoor_blocked"].fillna(False))].copy()
    if eligible.empty:
        return None
    groups, cur, last = [], [], None
    for _, row in eligible.iterrows():
        if last is None or row["dt"] - last == pd.Timedelta(minutes=30):
            cur.append(row)
        else:
            groups.append(cur); cur = [row]
        last = row["dt"]
    if cur: groups.append(cur)
    groups.sort(key=lambda g: (len(g), np.mean([float(x["overall_tan_opportunity_0_100"]) for x in g])), reverse=True)
    g = groups[0]
    return g[0]["dt"], g[-1]["dt"] + pd.Timedelta(minutes=30), float(np.mean([x["overall_tan_opportunity_0_100"] for x in g]))


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
        hours = scol(g, "dt").dt.hour
        daylight = g.loc[(hours >= 8) & (hours < 20)].copy()
        if daylight.empty:
            continue
        score = _num(daylight, "overall_tan_opportunity_0_100").fillna(0)
        best_idx = score.idxmax()
        best = daylight.loc[best_idx]
        # Best one-hour rolling pair.
        s = daylight.sort_values(by=["dt"]).reset_index(drop=True)
        best_hour = None
        best_hour_score = -1.0
        for i in range(len(s)-1):
            if s.loc[i+1, "dt"] - s.loc[i, "dt"] != pd.Timedelta(minutes=30):
                continue
            window_rows = s.loc[i:i+1]
            if not isinstance(window_rows, pd.DataFrame):
                raise TypeError("rolling window slice must be a DataFrame")
            pair = _num(window_rows, "overall_tan_opportunity_0_100").fillna(0)
            avg = float(pair.mean())
            if avg > best_hour_score:
                best_hour_score = avg
                best_hour = s.loc[i, "dt"]
        window = _best_contiguous_window(daylight)
        rows.append({
            "date": day,
            "day_overall_peak_0_100": round(float(best["overall_tan_opportunity_0_100"]), 1),
            "day_absolute_peak_0_100": round(float(best.get("tan_score_absolute_0_100", np.nan)), 1),
            "day_local_peak_0_100": round(float(best.get("local_tan_score_0_100", np.nan)), 1),
            "day_atmospheric_peak_0_100": round(float(best.get("atmospheric_quality_percentile_0_100", np.nan)), 1),
            "day_confidence_at_peak_0_100": round(float(best.get("tan_forecast_confidence_0_100", np.nan)), 1),
            "best_30m_start": best["dt"].isoformat(),
            "best_hour_start": best_hour.isoformat() if best_hour is not None else None,
            "best_hour_score_0_100": round(best_hour_score, 1) if best_hour is not None else np.nan,
            "best_window_start": window[0].isoformat() if window else None,
            "best_window_end": window[1].isoformat() if window else None,
            "best_window_mean_0_100": round(window[2], 1) if window else np.nan,
            "peak_uv_index": round(float(best.get("uv_index", np.nan)), 2),
            "peak_predicted_uva_wm2": round(float(best.get("predicted_uva_wm2", np.nan)), 2),
            "peak_temperature_f": round(float(best.get("temperature_2m", np.nan)), 1),
            "peak_precip_probability_pct": round(float(best.get("precipitation_probability", np.nan)), 1),
            "blocked_half_hours": int(scol(daylight, "outdoor_blocked").fillna(False).sum()),
            "day_status": _day_status(float(best["overall_tan_opportunity_0_100"])),
        })
    return pd.DataFrame(rows)


def _day_status(score: float) -> str:
    if not np.isfinite(score): return "UNKNOWN"
    if score >= 80: return "EXCELLENT"
    if score >= 65: return "VERY GOOD"
    if score >= 50: return "GOOD"
    if score >= 35: return "FAIR"
    if score > 0: return "POOR"
    return "NO OUTDOOR WINDOW"
