from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import pvlib.location
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from . import config


def solar_features(times_utc: pd.Series, altitude_m: float = 220.0) -> pd.DataFrame:
    """Solar position + Ineichen clear-sky on the training site coordinates.

    Single code path for both sides of the UVA/UVB model: the live forecast
    frame and the NASA POWER training frame must see the same clear-sky
    algorithm, otherwise `clear_ghi` carries train/serve skew.
    """
    idx = pd.DatetimeIndex(times_utc)
    loc = pvlib.location.Location(config.LATITUDE, config.LONGITUDE, tz="UTC", altitude=altitude_m)
    pos = pd.DataFrame(loc.get_solarposition(idx))
    clear = pd.DataFrame(loc.get_clearsky(idx, model="ineichen"))
    frame = pd.DataFrame({
        "time_utc": idx,
        "sza": num(pos, "apparent_zenith"),
        "solar_elevation_deg": num(pos, "apparent_elevation"),
        "solar_azimuth_deg": num(pos, "azimuth"),
        "clear_ghi": num(clear, "ghi"),
        "clear_dni": num(clear, "dni"),
        "clear_dhi": num(clear, "dhi"),
    })
    # Series inputs share pvlib's datetime index, which the dict constructor
    # would otherwise adopt (colliding with the time_utc merge key downstream).
    return frame.reset_index(drop=True)


MODEL_FEATURES = [
    "ghi", "dni", "dhi", "clear_ghi", "kt", "albedo", "aod55", "cloud",
    "sza", "temp_c", "rh", "pressure_kpa", "ozone_du", "aod340", "aod380",
]

NASA_RENAME = {
    "ALLSKY_SFC_UVA": "uva",
    "ALLSKY_SFC_UVB": "uvb",
    "ALLSKY_SFC_UV_INDEX": "uvi",
    "ALLSKY_SFC_SW_DWN": "ghi",
    "ALLSKY_SFC_SW_DNI": "dni",
    "ALLSKY_SFC_SW_DIFF": "dhi",
    "CLRSKY_SFC_SW_DWN": "clear_ghi",
    "ALLSKY_KT": "kt",
    "ALLSKY_SRF_ALB": "albedo",
    "AOD_55": "aod55",
    "CLOUD_AMT": "cloud",
    "SZA": "sza",
    "T2M": "temp_c",
    "RH2M": "rh",
    "PS": "pressure_kpa",
}


def _find_col(df: pd.DataFrame, *tokens: str) -> str | None:
    wanted = [t.lower() for t in tokens]
    for c in df.columns:
        low = c.lower()
        if all(t in low for t in wanted):
            return c
    return None


def _angstroem(aod1: pd.Series, wave1: float, aod2: pd.Series, wave2: float) -> pd.Series:
    a = pd.to_numeric(aod1, errors="coerce")
    b = pd.to_numeric(aod2, errors="coerce")
    if not isinstance(a, pd.Series) or not isinstance(b, pd.Series):
        raise TypeError("angstrom inputs must be Series")
    valid = (a > 0) & (b > 0)
    out = pd.Series(np.nan, index=a.index, dtype="float64")
    out.loc[valid] = -np.log(a.loc[valid] / b.loc[valid]) / math.log(wave1 / wave2)
    return out.clip(-1, 4)


def scol(frame: pd.DataFrame, name: str) -> pd.Series:
    """Unique-column access with a verified Series contract.

    Plain ``frame[name]`` types as Series | DataFrame and silently returns a
    DataFrame on duplicated labels, which then fails far from the cause.
    This fails loud at the access instead.
    """
    out = frame[name]
    if not isinstance(out, pd.Series):
        raise TypeError(f"expected unique Series column {name!r}, got {type(out).__name__}")
    return out


def num(frame: pd.DataFrame, name: str, default: float = float("nan")) -> pd.Series:
    """Numeric-column read with a quiet default (missing → NaN column)."""
    if name not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    out = pd.to_numeric(scol(frame, name), errors="coerce")
    if not isinstance(out, pd.Series):
        raise TypeError(f"expected numeric Series for column {name!r}")
    return out


def _utc_ns(frame: pd.DataFrame) -> pd.DataFrame:
    # Historical sources disagree on datetime unit (us vs ns). merge_asof/merge
    # require identical key dtypes, so coerce every merge input to one unit.
    if "time_utc" in frame.columns:
        frame = frame.copy()
        frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True).astype("datetime64[ns, UTC]")
    return frame

def prepare_nasa_training(nasa: pd.DataFrame, cams_eac4: pd.DataFrame | None = None) -> pd.DataFrame:
    if nasa.empty:
        return pd.DataFrame()
    df = nasa.rename(columns=NASA_RENAME).copy()
    keep = ["time_utc", *NASA_RENAME.values()]
    df = _utc_ns(df.loc[:, [c for c in keep if c in df.columns]])
    # One clear-sky algorithm on both sides of the model. POWER's
    # CLRSKY_SFC_SW_DWN is MERRA-based while live serves pvlib Ineichen;
    # training on the served algorithm removes the train/serve skew.
    df["clear_ghi"] = solar_features(scol(df, "time_utc"))["clear_ghi"].to_numpy()


    # NASA cloud amount is percent; EAC4 total cloud cover is 0-1. Keep model input
    # in percent because that maps directly to live Open-Meteo cloud_cover.
    if "cloud" in df:
        cloud = num(df, "cloud")
        if cloud.dropna().max() <= 1.5:
            df["cloud"] = cloud * 100.0

    if cams_eac4 is not None and not cams_eac4.empty:
        cams = cams_eac4.copy().sort_values("time_utc")
        c469 = _find_col(cams, "aerosol", "optical", "469")
        c550 = _find_col(cams, "aerosol", "optical", "550")
        c670 = _find_col(cams, "aerosol", "optical", "670")
        c865 = _find_col(cams, "aerosol", "optical", "865")
        ozone = _find_col(cams, "total", "column", "ozone")
        cols = ["time_utc"] + [c for c in (c469, c550, c670, c865, ozone) if c]
        cams = _utc_ns(cams.loc[:, cols])
        ren = {}
        if c469: ren[c469] = "cams_aod469"
        if c550: ren[c550] = "cams_aod550"
        if c670: ren[c670] = "cams_aod670"
        if c865: ren[c865] = "cams_aod865"
        if ozone: ren[ozone] = "cams_ozone_kgm2"
        cams = cams.rename(columns=ren)
        df = pd.merge_asof(
            df.sort_values("time_utc"), cams.sort_values("time_utc"), on="time_utc",
            direction="nearest", tolerance=timedelta(minutes=100),
        )
        if "cams_aod469" in df and "cams_aod865" in df:
            alpha = _angstroem(scol(df, "cams_aod469"), 469.0, scol(df, "cams_aod865"), 865.0)
            df["aod340"] = scol(df, "cams_aod469") * (340.0 / 469.0) ** (-alpha)
            df["aod380"] = scol(df, "cams_aod469") * (380.0 / 469.0) ** (-alpha)
        if "cams_ozone_kgm2" in df:
            # 1 Dobson Unit = 2.1415e-5 kg m^-2 of ozone.
            df["ozone_du"] = num(df, "cams_ozone_kgm2") / 2.1415e-5

    if "aod340" not in df:
        df["aod340"] = np.nan
    if "aod380" not in df:
        df["aod380"] = np.nan
    if "ozone_du" not in df:
        df["ozone_du"] = np.nan

    for c in [*MODEL_FEATURES, "uva", "uvb", "uvi"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def absolute_tan_score(uvi: pd.Series | np.ndarray | float, uva: pd.Series | np.ndarray | float):
    u = np.clip(np.asarray(uvi, dtype="float64") / config.ABSOLUTE_UVI_REFERENCE, 0, 1)
    a = np.clip(np.asarray(uva, dtype="float64") / config.ABSOLUTE_UVA_REFERENCE_WM2, 0, 1)
    interaction = np.sqrt(u * a)
    w = config.ABSOLUTE_TAN_WEIGHTS
    score = 100.0 * (w["uvi"] * u + w["uva"] * a + w["interaction"] * interaction)
    return np.clip(score, 0, 100)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)),
        "median_absolute_error": float(np.median(np.abs(y_true - y_pred))),
    }


def train_uv_models(training: pd.DataFrame, calibration_dir: Path) -> dict:
    calibration_dir.mkdir(parents=True, exist_ok=True)
    if training.empty:
        raise RuntimeError("NASA POWER calibration data is empty")
    work = training.copy()
    daylight = (num(work, "ghi").fillna(0) > 10) & (num(work, "sza").fillna(180) < 90)
    work = work.loc[daylight & scol(work, "uva").notna() & scol(work, "uvb").notna()].copy()
    if len(work) < 1000:
        raise RuntimeError(f"Too few daylight calibration rows: {len(work)}")

    years = pd.to_datetime(scol(work, "time_utc"), utc=True).dt.year
    split_year = int(years.max()) - 2
    train_mask = years <= split_year
    test_mask = years > split_year
    if test_mask.sum() < 500:
        cutoff = int(len(work) * 0.8)
        train_mask = pd.Series(False, index=work.index)
        train_mask.iloc[:cutoff] = True
        test_mask = ~train_mask

    for feat in MODEL_FEATURES:
        if feat not in work:
            work[feat] = np.nan
    # Degraded-tier training (e.g. no CAMS EAC4 history) leaves whole feature
    # columns constant/NaN, on which HistGradientBoosting's binning crashes
    # instead of training the documented lower tier. Drop such columns loudly
    # and record them: the bundle's feature list is the contract that
    # prediction reindexes against.
    dropped: list[str] = []
    kept: list[str] = []
    for feat in MODEL_FEATURES:
        col = pd.to_numeric(work[feat], errors="coerce")
        if int(col.dropna().nunique()) < 2:
            dropped.append(feat)
        else:
            kept.append(feat)
    if not kept:
        raise RuntimeError("No usable training features: every column is constant/NaN")
    if dropped:
        import logging as _logging

        _logging.getLogger("sunstack").warning(
            "Calibration training without features %s; bundle tier reduced", dropped)
    X = work.loc[:, kept]
    bundle: dict[str, object] = {
        "features": kept,
        "dropped_constant_features": dropped,
        "source": "NASA POWER hourly UVA/UVB; optional CAMS EAC4 atmospheric columns",
        "reference_uvi": config.ABSOLUTE_UVI_REFERENCE,
        "reference_uva_wm2": config.ABSOLUTE_UVA_REFERENCE_WM2,
    }
    report: dict[str, object] = {"rows": len(work), "validation_split_year": split_year,
                                 "dropped_constant_features": dropped}

    for target in ("uva", "uvb"):
        model = HistGradientBoostingRegressor(
            learning_rate=0.045,
            max_iter=350,
            max_leaf_nodes=31,
            min_samples_leaf=30,
            l2_regularization=0.15,
            random_state=23,
        )
        model.fit(X.loc[train_mask], work.loc[train_mask, target])
        pred = np.clip(model.predict(X.loc[test_mask]), 0, None)
        report[target] = _metrics(work.loc[test_mask, target].to_numpy(), pred)
        bundle[f"{target}_model"] = model

    joblib.dump(bundle, calibration_dir / "uva_uvb_models.joblib")
    (calibration_dir / "model_metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def build_local_reference(training: pd.DataFrame, calibration_dir: Path) -> pd.DataFrame:
    """Historical local reference rebuilt with the v4 action-spectrum score.

    Legacy 55/30/15 percentiles must NOT be retained: this builder always uses
    melanogenic-effective irradiance mapped through the versioned global
    reference. The legacy absolute is kept as a diagnostic column only.
    """
    if training.empty:
        return pd.DataFrame()
    ref = training.loc[:, [c for c in ["time_utc", "uva", "uvb", "uvi", "sza", "ghi"] if c in training]].copy()
    ref = ref.dropna(subset="time_utc").dropna(subset="uva").dropna(subset="uvi")
    if "uvb" in ref:
        # Missing bands are dropped, never zeroed: a zeroed band would plant
        # understated E_mel values in the climatology and inflate every local
        # percentile computed against it.
        ref = ref.dropna(subset="uvb")
    ref = ref.loc[(scol(ref, "ghi").fillna(0) > 10) & (scol(ref, "sza").fillna(180) < 90)]
    try:
        from .spectral import melanogenic_from_broadband

        e_mel = melanogenic_from_broadband(
            pd.to_numeric(scol(ref, "uva"), errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(scol(ref, "uvb" if "uvb" in ref else "uvi"), errors="coerce").to_numpy(dtype=float)
            if "uvb" in ref else pd.to_numeric(scol(ref, "uvi"), errors="coerce").to_numpy(dtype=float) * 0.15,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise RuntimeError(f"ERROR photobiology: {exc}") from exc
    from .photobiology import absolute_tan_score_from_melanogenic_irradiance

    ref["melanogenic_effective_irradiance_wm2"] = np.round(e_mel, 5)
    ref["absolute_tan_score_0_100"] = np.round(
        absolute_tan_score_from_melanogenic_irradiance(
            e_mel, float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2)
        ), 1,
    )
    ref["legacy_absolute_tan_score_55_30_15"] = np.round(
        absolute_tan_score(scol(ref, "uvi"), scol(ref, "uva")), 1
    )
    ref["tan_score_model_version"] = config.TAN_SCORE_MODEL_VERSION
    ref["global_reference_version"] = config.GLOBAL_MELANOGENIC_REFERENCE_VERSION
    tz = ZoneInfo(config.TIMEZONE)
    local = pd.to_datetime(scol(ref, "time_utc"), utc=True).dt.tz_convert(tz)
    ref["time_local"] = local.astype(str)
    ref["day_of_year"] = local.dt.dayofyear
    ref["local_hour"] = local.dt.hour + local.dt.minute / 60.0
    ref["solar_elevation_deg"] = 90.0 - num(ref, "sza")
    ref["year"] = local.dt.year
    calibration_dir.mkdir(parents=True, exist_ok=True)
    ref.to_parquet(calibration_dir / "local_reference.parquet", index=False)
    ref.to_csv(calibration_dir / "local_reference.csv", index=False)
    (calibration_dir / "local_reference_version.json").write_text(
        json.dumps({
            "tan_score_model_version": config.TAN_SCORE_MODEL_VERSION,
            "global_reference_version": config.GLOBAL_MELANOGENIC_REFERENCE_VERSION,
            "global_reference_e_mel_wm2": config.GLOBAL_MELANOGENIC_REFERENCE_WM2,
            "rows": len(ref),
        }, indent=2), encoding="utf-8",
    )
    return ref


def build_training_dataset(
    nasa: pd.DataFrame,
    openmeteo_hist: pd.DataFrame,
    cams_eac4: pd.DataFrame,
    calibration_dir: Path,
) -> pd.DataFrame:
    base = prepare_nasa_training(nasa, cams_eac4)
    if base.empty:
        return base
    if openmeteo_hist is not None and not openmeteo_hist.empty:
        om = _utc_ns(openmeteo_hist.copy().sort_values("time_utc"))
        om = om.rename(columns={c: f"om_{c}" for c in om.columns if c not in {"time_utc", "source", "model"}})
        base = pd.merge_asof(
            base.sort_values("time_utc"), om.sort_values("time_utc"), on="time_utc",
            direction="nearest", tolerance=timedelta(minutes=35),
        )
        if not isinstance(base, pd.DataFrame):
            raise TypeError("training merge must produce a DataFrame")
    calibration_dir.mkdir(parents=True, exist_ok=True)
    base.to_parquet(calibration_dir / "training_calibration_hourly.parquet", index=False)
    # CSV is intentionally a convenience subset because the full table can be large.
    base.tail(250_000).to_csv(calibration_dir / "training_calibration_hourly.csv", index=False)
    return base


def compute_openmeteo_model_skill(
    previous: pd.DataFrame,
    verifying: pd.DataFrame,
    calibration_dir: Path,
) -> pd.DataFrame:
    if previous.empty or verifying.empty:
        return pd.DataFrame()
    truth = _utc_ns(verifying.loc[:, ["time_utc", *[v for v in config.PREVIOUS_RUN_BASE_VARIABLES if v in verifying]]].copy())
    rows: list[dict[str, object]] = []
    for model, group in _utc_ns(previous).groupby("model"):
        if not isinstance(group, pd.DataFrame):
            raise TypeError("model group must be a DataFrame")
        merged = group.merge(truth, on="time_utc", how="inner", suffixes=("", "__truth"))
        for variable in config.PREVIOUS_RUN_BASE_VARIABLES:
            truth_col = f"{variable}__truth" if f"{variable}__truth" in merged else variable
            if truth_col not in merged:
                continue
            y = num(merged, truth_col)
            for lead in config.PREVIOUS_RUN_LEADS:
                fcol = variable if lead == 0 else f"{variable}_previous_day{lead}"
                if fcol not in merged:
                    continue
                x = num(merged, fcol)
                xv = x.to_numpy(dtype=float, na_value=np.nan)
                yv = y.to_numpy(dtype=float, na_value=np.nan)
                mask = ~np.isnan(xv) & ~np.isnan(yv)
                if mask.sum() < 48:
                    continue
                err = xv[mask] - yv[mask]
                xs = pd.Series(xv[mask])
                rows.append({
                    "model": model,
                    "variable": variable,
                    "lead_days": lead,
                    "n": int(mask.sum()),
                    "mae": float(np.abs(err).mean()),
                    "rmse": float(np.sqrt((err ** 2).mean())),
                    "bias": float(err.mean()),
                    "correlation": float(xs.corr(pd.Series(yv[mask]))) if mask.sum() > 2 else np.nan,
                    "verification_source": "openmeteo_historical_forecast_best_match",
                })
    skill = pd.DataFrame(rows)
    if skill.empty:
        return skill
    # Within each variable/lead, convert inverse MAE to a normalized skill weight.
    mae = num(skill, "mae")
    inv = 1.0 / mae.replace(0, 1e-6)
    skill["inverse_mae"] = inv
    denom = inv.groupby([scol(skill, "variable"), scol(skill, "lead_days")]).transform("sum")
    skill["normalized_weight"] = inv / denom
    calibration_dir.mkdir(parents=True, exist_ok=True)
    skill.to_parquet(calibration_dir / "openmeteo_model_skill.parquet", index=False)
    skill.to_csv(calibration_dir / "openmeteo_model_skill.csv", index=False)
    return skill
