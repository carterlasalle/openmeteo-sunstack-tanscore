from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .calibrate import num


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
    if "tan_score_model_version" in df:
        versions = set(pd.Series(df["tan_score_model_version"]).dropna().astype(str).unique().tolist())
        if versions and versions != {"action-spectrum-v1"}:
            issues.append(ValidationIssue("ERROR", "photobiology", f"unexpected tan_score_model_version: {sorted(versions)}"))
    if "spectral_tier" in df:
        tiers = set(pd.Series(df["spectral_tier"]).dropna().astype(str).unique().tolist())
        if tiers - {"A", "B", "C"}:
            issues.append(ValidationIssue("ERROR", "photobiology", f"invalid spectral tier: {sorted(tiers)}"))
    return issues


def raise_on_errors(issues: list[ValidationIssue], prefix: str = "SunStack validation failed") -> None:
    errors = [x for x in issues if x.severity == "ERROR"]
    if errors:
        msg = "\n".join(f"  - [{x.source}] {x.message}" for x in errors)
        raise DataValidationError(f"{prefix}:\n{msg}")


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
        from .photobiology import load_action_spectrum
    except ImportError as exc:
        return [ValidationIssue("ERROR", "photobiology", f"photobiology module unavailable: {exc}")]
    for stem in ("parrish_delayed_melanogenesis", "cie_erythema_reference", "ipd_action_spectrum"):
        try:
            spec = load_action_spectrum(stem)
        except (FileNotFoundError, ValueError) as exc:
            issues.append(ValidationIssue("ERROR", "photobiology", str(exc)))
            continue
        if spec.tier == "provisional" and strict_canonical and stem == "parrish_delayed_melanogenesis":
            issues.append(ValidationIssue(
                "ERROR", "photobiology",
                f"strict mode requires the canonical spectrum but {stem} tier is provisional",
            ))
    return issues
