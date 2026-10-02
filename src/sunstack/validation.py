from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import TAN_SCORE_MODEL_VERSION
from .frame import num


class SunStackError(RuntimeError):
    pass


class SourceFailure(SunStackError):
    pass


class DataValidationError(SunStackError):
    pass


@dataclass
class ValidationIssue:
    severity: str
    source: str
    message: str


def validate_live_sources(results, strict: bool = True) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by_name = {r.name: r for r in results}
    required_exact = ["deterministic__best_match", "hrrr_15min", "air_quality"]
    for name in required_exact:
        r = by_name.get(name)
        if r is None or r.payload is None:
            issues.append(ValidationIssue("ERROR", name, r.error if r else "missing source"))

    deterministic_ok = sum(1 for r in results if r.name.startswith("deterministic__") and r.payload is not None)
    ensemble_ok = sum(1 for r in results if r.name.startswith("ensemble_members__") and r.payload is not None)
    mean_ok = sum(1 for r in results if r.name.startswith("ensemble_mean__") and r.payload is not None)
    if deterministic_ok < 8:
        issues.append(ValidationIssue("ERROR" if strict else "WARN", "deterministic_models", f"only {deterministic_ok} deterministic feeds succeeded; expected at least 8"))
    if ensemble_ok < 2:
        issues.append(ValidationIssue("ERROR" if strict else "WARN", "ensemble_members", f"only {ensemble_ok} full-member ensemble systems succeeded; expected at least 2"))
    if mean_ok < 4:
        issues.append(ValidationIssue("WARN", "ensemble_mean", f"only {mean_ok} ensemble mean/spread systems succeeded"))

    for r in results:
        if r.error and r.name not in required_exact:
            issues.append(ValidationIssue("WARN", r.name, r.error))
    return issues


def validate_scored_hourly(df: pd.DataFrame) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if df.empty:
        return [ValidationIssue("ERROR", "tan_forecast_hourly", "scored forecast is empty")]
    for col in ["uv_index", "predicted_uva_wm2", "tan_score_absolute_0_100", "local_tan_score_0_100", "tan_forecast_confidence_0_100"]:
        if col not in df:
            issues.append(ValidationIssue("ERROR", "tan_forecast_hourly", f"required column missing: {col}"))
        elif num(df, col).notna().mean() < 0.50:
            issues.append(ValidationIssue("ERROR", "tan_forecast_hourly", f"column {col} is >50% missing"))
    if "tan_score_absolute_0_100" in df:
        x = num(df, "tan_score_absolute_0_100")
        if bool(((x < 0) | (x > 100)).any()):
            issues.append(ValidationIssue("ERROR", "tan_forecast_hourly", "absolute TanScore outside 0-100"))
    # v4 photobiology gates: fail loudly, never silently use legacy.
    for col in ["melanogenic_effective_irradiance_wm2", "erythemal_irradiance_wm2",
                "tan_score_model_version", "spectral_backend"]:
        if col not in df:
            issues.append(ValidationIssue("ERROR", "photobiology", f"required v4 column missing: {col}"))
    if "melanogenic_effective_irradiance_wm2" in df:
        e = num(df, "melanogenic_effective_irradiance_wm2")
        if bool((e < -1e-9).any()):
            issues.append(ValidationIssue("ERROR", "photobiology", "E_mel has physically impossible negative values"))
        if bool((e > 5).any()):
            issues.append(ValidationIssue("ERROR", "photobiology", "E_mel exceeds 5 W/m^2 (unphysical for natural sun)"))
    if "erythemal_irradiance_wm2" in df:
        r = num(df, "erythemal_irradiance_wm2")
        if bool((r < -1e-9).any()):
            issues.append(ValidationIssue("ERROR", "photobiology", "erythemal irradiance has physically impossible negative values"))
    if "tan_score_model_version" in df:
        versions = set(pd.Series(df["tan_score_model_version"]).dropna().astype(str).unique().tolist())
        if versions and versions != {TAN_SCORE_MODEL_VERSION}:
            issues.append(ValidationIssue("ERROR", "photobiology", f"unexpected tan_score_model_version: {sorted(versions)}"))
    if "spectral_tier" in df:
        tiers = set(pd.Series(df["spectral_tier"]).dropna().astype(str).unique().tolist())
        if tiers - {"A", "B", "C"}:
            issues.append(ValidationIssue("ERROR", "photobiology", f"invalid spectral tier: {sorted(tiers)}"))
    if "local_reference_stale" in df:
        try:
            if bool(pd.Series(df["local_reference_stale"]).fillna(True).any()):
                versions = pd.Series(
                    df.get("local_reference_version")).dropna().astype(str).unique().tolist()
                issues.append(ValidationIssue(
                    "WARN", "local_reference",
                    f"local percentiles not from the current score model "
                    f"(versions seen: {versions or ['unknown']}); rebuild with "
                    f"scripts/rebuild_v4_references.py"))
        except (TypeError, ValueError):
            pass
    return issues


def raise_on_errors(issues: list[ValidationIssue], prefix: str = "SunStack validation failed") -> None:
    errors = [x for x in issues if x.severity == "ERROR"]
    if errors:
        msg = "\n".join(f"  - [{x.source}] {x.message}" for x in errors)
        raise DataValidationError(f"{prefix}:\n{msg}")


def validate_final_products(
    hourly: pd.DataFrame, half: pd.DataFrame, daily: pd.DataFrame,
) -> list[ValidationIssue]:
    """Cross-product invariants on the PUBLISHED artifacts (strict gate 2).

    Hourly validation cannot see these: 30-min/daily derivation bugs (weather
    loss, fusion drift, false peaks) shipped with validation_issues: [].
    """
    issues: list[ValidationIssue] = []
    if half.empty:
        return [ValidationIssue("ERROR", "tan_forecast_30min", "30-min product is empty")]
    if daily.empty:
        return [ValidationIssue("ERROR", "tan_daily_summary", "daily product is empty")]
    # 1. Fusion integrity: consensus inside visible source range, integer
    # source count, spread equals max-min (audit: 2.5 sources, drifted ΔUV).
    for label, frame in (("30min", half), ("hourly", hourly)):
        if frame.empty:
            continue
        for _, r in frame.iterrows():
            # Same triple the fusion consumes (state._stack_sources):
            # uvi_openmeteo when present else the OM display value uv_index,
            # plus CAMS and EPA. The gate must never compare a fused spread
            # against a different triple than the one that produced it.
            try:
                om_col = ("uvi_openmeteo" if r.get("uvi_openmeteo") is not None
                          and pd.notna(r.get("uvi_openmeteo")) else "uv_index")
                vs = [float(r[c]) for c in (om_col, "uvi_cams", "uvi_epa")
                      if r.get(c) is not None and pd.notna(r[c])]
            except (TypeError, ValueError):
                continue
            cons = r.get("uvi_consensus")
            if (len(vs) >= 2 and cons is not None and pd.notna(cons)
                    and not (min(vs) - 0.01 <= float(cons) <= max(vs) + 0.01)):
                issues.append(ValidationIssue(
                    "ERROR", f"tan_forecast_{label}",
                    f"consensus {cons} outside sources at {r.get('time')}"))
                break
            sp = r.get("uvi_source_spread")
            if (len(vs) >= 2 and sp is not None and pd.notna(sp)
                    and abs(float(sp) - (max(vs) - min(vs))) > 0.02):
                issues.append(ValidationIssue(
                    "ERROR", f"tan_forecast_{label}",
                    f"spread {sp} != source range at {r.get('time')}"))
                break
        sc = frame.get("uvi_consensus_sources")
        if sc is not None:
            bad = pd.to_numeric(sc, errors="coerce")
            if bool(((bad % 1) != 0).any()):
                issues.append(ValidationIssue(
                    "ERROR", f"tan_forecast_{label}",
                    "uvi_consensus_sources is fractional (interpolated metadata)"))
    # 2. Daily peaks are real maxima, not values-at-opportunity-peak.
    try:
        daylight = half.copy()
        daylight["date"] = pd.to_datetime(daylight["dt"]).dt.date.astype(str)
        for _, d in daily.iterrows():
            day = str(d.get("date"))
            g = daylight[daylight["date"] == day]
            if g.empty:
                continue
            # peak_uv_index is the true daylight max; peak_30m_* are true
            # maxima. best_30m_* is the dose AT the opportunity peak (product
            # semantics, not a max) and must NOT be compared to the column max.
            for col, dcol in (("uvi_consensus", "peak_uv_index"),
                              ("tan_dose_30m_j_m2", "peak_30m_tan_dose_j_m2"),
                              ("sed_30m", "peak_30m_sed")):
                if col in g.columns and dcol in d and pd.notna(d[dcol]):
                    actual = pd.to_numeric(g[col], errors="coerce").max()
                    if pd.notna(actual) and abs(float(actual) - float(d[dcol])) > 0.05 * max(1.0, abs(float(actual))):
                        issues.append(ValidationIssue(
                            "ERROR", "tan_daily_summary",
                            f"{dcol}={d[dcol]} != true max {round(float(actual), 2)} on {day}"))
                        break
    except (KeyError, ValueError, TypeError):
        pass
    # 3. Daily weather summaries must not be all-null (weather-loss signal).
    for col in ("day_high_temperature_f", "day_peak_wind_mph"):
        if col in daily.columns and daily[col].isna().all():
            issues.append(ValidationIssue(
                "ERROR", "tan_daily_summary",
                f"{col} is 100% null: 30-min weather never arrived"))
    # 4. Exact-hour weather parity hourly<->30min (audit: 161/196 disagreed).
    try:
        hh = hourly[["time", "temperature_2m"]].copy()
        mm = half[half["time"].isin(hh["time"])][["time", "temperature_2m"]]
        j = hh.merge(mm, on="time", suffixes=("_h", "_m"))
        if len(j):
            dt = (pd.to_numeric(j["temperature_2m_h"], errors="coerce")
                  - pd.to_numeric(j["temperature_2m_m"], errors="coerce")).abs()
            if bool((dt > 1.0).sum() > len(j) * 0.1):
                issues.append(ValidationIssue(
                    "ERROR", "tan_forecast_30min",
                    "exact-hour temperature diverges hourly<->30min (weather loss)"))
    except (KeyError, ValueError, TypeError):
        pass
    return issues


def validate_cams_direct(df: pd.DataFrame) -> list[ValidationIssue]:
    if df is None or df.empty:
        return [ValidationIssue("ERROR", "cams_direct_ads", "no CAMS rows returned")]
    lows = [c.lower() for c in df.columns]
    def present(tokens): return any(all(t in c for t in tokens) for c in lows)
    issues=[]
    for name,tokens in [
        ("AOD340", ("aerosol","optical","340")),
        ("AOD380", ("aerosol","optical","380")),
        ("total-column ozone", ("total","column","ozone")),
    ]:
        if not present(tokens): issues.append(ValidationIssue("ERROR", "cams_direct_ads", f"required spectral field missing: {name}"))
    if not (present(("uv","biologically","effective")) or present(("downward","uv"))):
        issues.append(ValidationIssue("WARN", "cams_direct_ads", "CAMS UV diagnostic field missing; scoring can still use spectral AOD + ozone"))
    # v4: full UV/aerosol propagation is required, not fetch-and-drop.
    for name, tokens in [
        ("UVBED clear-sky", ("biologically","effective","clear")),
        ("downward surface UV", ("downward","uv")),
        ("AOD355", ("aerosol","optical","355")),
        ("AOD400", ("aerosol","optical","400")),
        ("absorption AOD340", ("absorption","340")),
        ("SSA340", ("single","scattering","340")),
        ("asymmetry340", ("asymmetry","340")),
        ("water vapour", ("water","vapour")),
        ("cloud liquid water", ("cloud","liquid","water")),
        ("cloud ice water", ("cloud","ice","water")),
        ("forecast albedo", ("forecast","albedo")),
    ]:
        if not present(tokens):
            issues.append(ValidationIssue("WARN", "cams_direct_ads", f"expected CAMS field not propagated: {name}"))
    return issues


def validate_action_spectra(strict_canonical: bool = False) -> list[ValidationIssue]:
    """Fail loudly when the photobiology model cannot be evaluated."""
    issues: list[ValidationIssue] = []
    try:
        from .photobiology import ACTION_SPECTRUM_STEM, load_action_spectrum
    except ImportError as exc:
        return [ValidationIssue("ERROR", "photobiology", f"photobiology module unavailable: {exc}")]
    for stem in (ACTION_SPECTRUM_STEM, "cie_erythema_reference", "ipd_action_spectrum"):
        try:
            spec = load_action_spectrum(stem)
        except (FileNotFoundError, ValueError) as exc:
            issues.append(ValidationIssue("ERROR", "photobiology", str(exc)))
            continue
        if strict_canonical and stem == ACTION_SPECTRUM_STEM and spec.tier != "canonical":
            # Same rule as require_canonical_spectrum: anything but canonical
            # fails, including an "unknown" tier from metadata without a tier
            # key (which must not slip past validation only to be rejected
            # later inside score_forecast).
            issues.append(ValidationIssue(
                "ERROR", "photobiology",
                f"strict mode requires the canonical spectrum but {stem} tier is {spec.tier!r}",
            ))
    return issues
