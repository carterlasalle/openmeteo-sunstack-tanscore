from __future__ import annotations

import numpy as np
import pandas as pd

from .calibrate import num, scol


def _num(frame: pd.DataFrame, name: str) -> pd.Series:
    return num(frame, name)


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    n = pd.to_numeric(numerator, errors="coerce")
    d = pd.to_numeric(denominator, errors="coerce")
    if not isinstance(n, pd.Series) or not isinstance(d, pd.Series):
        raise TypeError("safe_ratio expects Series inputs")
    out = n / d.where(d.abs() > 1e-9)
    return out.replace([np.inf, -np.inf], np.nan)


def add_solar_diagnostics(frame: pd.DataFrame, interval_seconds: int = 3600) -> pd.DataFrame:
    """Add physically useful ratios plus a ranking score.

    The score is deliberately heuristic. Crucially, it RENORMALIZES across
    whatever evidence is actually available on a row. Ensemble systems that do
    not publish UV are therefore not incorrectly assigned a zero score.
    """
    if frame.empty:
        return frame.copy()
    out = frame.copy()

    uv = _num(out, "uv_index")
    uv_clear = _num(out, "uv_index_clear_sky")
    ghi = _num(out, "shortwave_radiation")
    ghi_i = _num(out, "shortwave_radiation_instant")
    direct = _num(out, "direct_radiation")
    direct_i = _num(out, "direct_radiation_instant")
    diffuse = _num(out, "diffuse_radiation")
    diffuse_i = _num(out, "diffuse_radiation_instant")
    dni = _num(out, "direct_normal_irradiance")
    dni_i = _num(out, "direct_normal_irradiance_instant")
    toa = _num(out, "terrestrial_radiation")
    toa_i = _num(out, "terrestrial_radiation_instant")
    sunshine = _num(out, "sunshine_duration")

    out["uv_transmission"] = safe_ratio(uv, uv_clear)
    out["uv_attenuation"] = 1.0 - out["uv_transmission"]
    out["clearness_index"] = safe_ratio(ghi, toa)
    out["clearness_index_instant"] = safe_ratio(ghi_i, toa_i)
    out["direct_fraction"] = safe_ratio(direct, ghi)
    out["diffuse_fraction"] = safe_ratio(diffuse, ghi)
    out["direct_fraction_instant"] = safe_ratio(direct_i, ghi_i)
    out["diffuse_fraction_instant"] = safe_ratio(diffuse_i, ghi_i)
    out["sunshine_fraction"] = sunshine / float(interval_seconds)

    out["ghi_balance_error"] = ghi - (direct + diffuse)
    out["ghi_balance_error_instant"] = ghi_i - (direct_i + diffuse_i)

    rh_levels = [c for c in [
        "relative_humidity_925hPa", "relative_humidity_850hPa",
        "relative_humidity_700hPa", "relative_humidity_500hPa",
        "relative_humidity_300hPa",
    ] if c in out]
    if rh_levels:
        out["upper_air_rh_max"] = out[rh_levels].apply(pd.to_numeric, errors="coerce").max(axis=1)

    cloud_levels = [c for c in [
        "cloud_cover_925hPa", "cloud_cover_850hPa", "cloud_cover_700hPa",
        "cloud_cover_500hPa", "cloud_cover_300hPa",
    ] if c in out]
    if cloud_levels:
        out["upper_air_cloud_max"] = out[cloud_levels].apply(pd.to_numeric, errors="coerce").max(axis=1)

    uv_abs = (uv / 6.0).clip(0, 1)
    uv_trans = out["uv_transmission"].clip(0, 1.2)
    dni_strength = (dni_i.where(dni_i.notna(), dni) / 850.0).clip(0, 1)
    clear_strength = (
        out["clearness_index_instant"].where(
            out["clearness_index_instant"].notna(), out["clearness_index"]
        ) / 0.78
    ).clip(0, 1)
    directness = out["direct_fraction_instant"].where(
        out["direct_fraction_instant"].notna(), out["direct_fraction"]
    ).clip(0, 1)
    sunny_fraction = out["sunshine_fraction"].clip(0, 1)

    # Renormalize to the evidence available on each row. This avoids assigning
    # zero merely because (for example) an ensemble does not provide UV.
    components = [
        (uv_abs, 0.30),
        (uv_trans, 0.15),
        (dni_strength, 0.20),
        (clear_strength, 0.15),
        (directness, 0.10),
        (sunny_fraction, 0.10),
    ]
    weighted_sum = pd.Series(0.0, index=out.index)
    weight_sum = pd.Series(0.0, index=out.index)
    for series, weight in components:
        valid = series.notna()
        weighted_sum = weighted_sum + series.fillna(0) * weight
        weight_sum = weight_sum + valid.astype(float) * weight
    base = (weighted_sum / weight_sum.where(weight_sum > 0)).clip(0, 1)

    pop = (_num(out, "precipitation_probability") / 100.0).clip(0, 1)
    precip = _num(out, "precipitation")
    cape = _num(out, "cape")
    cin = _num(out, "convective_inhibition")
    low_cloud = (_num(out, "cloud_cover_low") / 100.0).clip(0, 1)

    penalty = pd.Series(0.0, index=out.index)
    penalty += 0.18 * pop.fillna(0)
    penalty += 0.05 * low_cloud.fillna(0)
    penalty += 0.12 * (precip.fillna(0) > 0.01).astype(float)
    penalty += 0.04 * ((cape.fillna(0) > 1000) & (cin.fillna(-999) > -50)).astype(float)

    score = 100.0 * (base - penalty).clip(0, 1)
    out["sun_score_0_100"] = score.where(weight_sum > 0).round(1)
    out["sun_score_evidence_weight"] = weight_sum.round(2)
    return out


def enrich_15min_with_hourly_uv(hrrr15: pd.DataFrame, hourly_best: pd.DataFrame) -> pd.DataFrame:
    """Interpolate hourly UV onto native HRRR 15-minute timestamps.

    Radiation remains native HRRR. UV is explicitly marked as interpolated so
    downstream users never mistake it for native 15-minute UV model output.
    """
    if hrrr15.empty or hourly_best.empty:
        return hrrr15.copy()
    out = hrrr15.copy()
    out_dt = pd.to_datetime(out["time"], errors="coerce")
    hb = hourly_best.loc[:, [c for c in ["time", "uv_index", "uv_index_clear_sky"] if c in hourly_best]].copy()
    hb["_dt"] = pd.to_datetime(scol(hb, "time"), errors="coerce")
    hb = hb.dropna(subset="_dt").drop_duplicates("_dt").set_index("_dt").sort_index()
    target = pd.DatetimeIndex(out_dt.dropna().unique()).sort_values()
    union = hb.index.union(target).sort_values()
    for col in ["uv_index", "uv_index_clear_sky"]:
        if col not in hb:
            continue
        s = _num(hb, col).reindex(union).interpolate(method="time", limit_area="inside")
        mapper = s.reindex(out_dt.values).to_numpy()
        out[col] = mapper
    out["uv_temporal_source"] = "best_match_hourly_time_interpolated"
    return out


def _physical_consensus_frame(hourly: pd.DataFrame) -> pd.DataFrame:
    """Return a QA copy for cross-model consensus calculations."""
    df = hourly.copy()
    # Best Match is a synthesis of model sources and must not count as an
    # additional independent model vote when the raw component models are here.
    if "model" in df:
        df = df.loc[scol(df, "model") != "best_match"].copy()

    ghi = _num(df, "shortwave_radiation_instant")
    toa = _num(df, "terrestrial_radiation_instant")
    # Small cloud-edge enhancements are possible, so allow generous headroom;
    # reject only obviously impossible model/mapping artifacts.
    valid_ghi = (ghi >= -5) & (toa.isna() | (ghi <= toa * 1.20 + 50))
    if "shortwave_radiation_instant" in df:
        df.loc[~valid_ghi, "shortwave_radiation_instant"] = np.nan

    dni = _num(df, "direct_normal_irradiance_instant")
    valid_dni = (dni >= -5) & (dni <= 1200)
    if "direct_normal_irradiance_instant" in df:
        df.loc[~valid_dni, "direct_normal_irradiance_instant"] = np.nan
    return df


def deterministic_consensus(hourly: pd.DataFrame) -> pd.DataFrame:
    if hourly.empty:
        return pd.DataFrame()
    df = _physical_consensus_frame(hourly)
    metrics = [
        "temperature_2m", "cloud_cover", "cloud_cover_low", "cloud_cover_mid",
        "cloud_cover_high", "precipitation_probability",
        "shortwave_radiation_instant", "direct_normal_irradiance_instant",
        "diffuse_radiation_instant", "sun_score_0_100",
    ]
    metrics = [m for m in metrics if m in df.columns]
    pieces = []
    for metric in metrics:
        grouped = df.groupby("time", dropna=False)[metric].agg(["count", "mean", "median", "std", "min", "max"])
        grouped.columns = [f"{metric}__{c}" for c in grouped.columns]
        pieces.append(grouped)
    if not pieces:
        return pd.DataFrame()
    out = pd.concat(pieces, axis=1).reset_index()

    penalties = []
    normalizers = {
        "cloud_cover": 35.0,
        "shortwave_radiation_instant": 180.0,
        "direct_normal_irradiance_instant": 250.0,
        "temperature_2m": 8.0,
    }
    for metric, scale in normalizers.items():
        col = f"{metric}__std"
        if col in out:
            penalties.append((_num(out, col) / scale).clip(0, 1))
    if penalties:
        penalty = pd.concat(penalties, axis=1).mean(axis=1, skipna=True)
        if not isinstance(penalty, pd.Series):
            raise TypeError("consensus penalty must be a Series")
        vals = penalty.to_numpy(dtype=float, na_value=np.nan)
        agreement = pd.Series(np.round(100.0 * (1.0 - vals), 1), index=penalty.index)
        out["deterministic_agreement_0_100"] = agreement
    return out


def ensemble_probabilities(ensemble_long: pd.DataFrame) -> pd.DataFrame:
    if ensemble_long.empty:
        return pd.DataFrame()
    df = add_solar_diagnostics(ensemble_long)

    def prob(frame: pd.DataFrame, name: str, predicate) -> float:
        x = _num(frame, name).dropna()
        if x.empty:
            return np.nan
        return 100.0 * float(predicate(x).mean())

    rows = []
    for model, mdf in df.groupby("model", dropna=False):
        for time, g in mdf.groupby("time", dropna=False):
            row = {
                "model": model,
                "time": time,
                "member_count": int(scol(g, "member").nunique()) if "member" in g else len(g),
                "p_cloud_lt_30": prob(g, "cloud_cover", lambda x: x < 30),
                "p_cloud_lt_60": prob(g, "cloud_cover", lambda x: x < 60),
                "p_precip_gt_0_01in": prob(g, "precipitation", lambda x: x > 0.01),
                "p_uv_ge_3": prob(g, "uv_index", lambda x: x >= 3),
                "p_uv_ge_5": prob(g, "uv_index", lambda x: x >= 5),
                "p_uv_ge_6": prob(g, "uv_index", lambda x: x >= 6),
                "p_ghi_instant_ge_500": prob(g, "shortwave_radiation_instant", lambda x: x >= 500),
                "p_ghi_instant_ge_700": prob(g, "shortwave_radiation_instant", lambda x: x >= 700),
                "p_dni_instant_ge_600": prob(g, "direct_normal_irradiance_instant", lambda x: x >= 600),
                "p_dni_instant_ge_800": prob(g, "direct_normal_irradiance_instant", lambda x: x >= 800),
                "p_sun_score_ge_70": prob(g, "sun_score_0_100", lambda x: x >= 70),
                "p_sun_score_ge_85": prob(g, "sun_score_0_100", lambda x: x >= 85),
            }
            if "shortwave_radiation_instant" in g:
                row["ghi_instant_mean"] = _num(g, "shortwave_radiation_instant").mean()
                row["ghi_instant_std"] = _num(g, "shortwave_radiation_instant").std()
            if "direct_normal_irradiance_instant" in g:
                row["dni_instant_mean"] = _num(g, "direct_normal_irradiance_instant").mean()
                row["dni_instant_std"] = _num(g, "direct_normal_irradiance_instant").std()
            if "cloud_cover" in g:
                row["cloud_mean"] = _num(g, "cloud_cover").mean()
                row["cloud_std"] = _num(g, "cloud_cover").std()
            if "uv_index" in g:
                row["uv_mean"] = _num(g, "uv_index").mean()
                row["uv_std"] = _num(g, "uv_index").std()
            rows.append(row)
    return pd.DataFrame(rows)


def merge_air_quality(best_match: pd.DataFrame, air: pd.DataFrame) -> pd.DataFrame:
    if best_match.empty:
        return best_match.copy()
    out = best_match.copy()
    if air.empty:
        return out
    aq = air.copy()
    keep = [str(c) for c in aq.columns if c not in {"source", "model", "timezone", "latitude_grid", "longitude_grid", "elevation_m", "generationtime_ms"}]
    aq = aq.loc[:, keep]
    rename = {c: f"air__{c}" for c in keep if c != "time"}
    aq = aq.rename(columns=rename)
    return out.merge(aq, on="time", how="left")


def _row_weighted_mean(df: pd.DataFrame, specs: list[tuple[str, float, bool]]) -> pd.Series:
    num = pd.Series(0.0, index=df.index)
    den = pd.Series(0.0, index=df.index)
    for col, weight, invert in specs:
        if col not in df:
            continue
        x = _num(df, col)
        if invert:
            x = 100.0 - x
        valid = x.notna()
        num += x.fillna(0) * weight
        den += valid.astype(float) * weight
    return num / den.where(den > 0)


def best_windows(best_match_enriched: pd.DataFrame, ensemble_probs: pd.DataFrame, consensus: pd.DataFrame) -> pd.DataFrame:
    if best_match_enriched.empty:
        return pd.DataFrame()
    df = best_match_enriched.copy()
    if "is_day" in df:
        df = df.loc[_num(df, "is_day").fillna(0) > 0]
    if ensemble_probs is not None and not ensemble_probs.empty:
        ep = ensemble_probs.groupby("time", as_index=False).agg({
            c: "mean" for c in ensemble_probs.columns if c.startswith("p_")
        })
        if not isinstance(ep, pd.DataFrame):
            raise TypeError("ensemble mean aggregation must produce a DataFrame")
        df = df.merge(ep, on="time", how="left")
    if consensus is not None and not consensus.empty:
        cols = ["time"] + [c for c in consensus.columns if c == "deterministic_agreement_0_100"]
        df = df.merge(consensus.loc[:, cols], on="time", how="left")

    # Probability-like support for genuinely strong, direct, usable sun. Use only
    # fields the ensemble systems actually provide. Missing systems/fields do not
    # become zeros.
    # Confidence is built only from ensemble quantities that are actually comparable
    # across systems. Do not use ensemble SunScore here because several ensemble
    # systems omit UV; a renormalized radiation-only score is useful diagnostically
    # but is not equivalent to a full UV-aware score.
    df["ensemble_strong_sun_support_0_100"] = _row_weighted_mean(df, [
        ("p_dni_instant_ge_600", 0.35, False),
        ("p_ghi_instant_ge_700", 0.30, False),
        ("p_cloud_lt_60", 0.20, False),
        ("p_precip_gt_0_01in", 0.15, True),
    ]).round(1)

    support = _num(df, "ensemble_strong_sun_support_0_100")
    agreement = _num(df, "deterministic_agreement_0_100")
    # Ensemble scenario support dominates; independent deterministic agreement
    # provides the second view.
    conf_num = 0.65 * support.fillna(0) + 0.35 * agreement.fillna(0)
    conf_den = 0.65 * support.notna().astype(float) + 0.35 * agreement.notna().astype(float)
    df["sun_window_confidence_0_100"] = (conf_num / conf_den.where(conf_den > 0)).round(1)

    sort_cols = [c for c in ["sun_score_0_100", "sun_window_confidence_0_100"] if c in df]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False)
    return df
