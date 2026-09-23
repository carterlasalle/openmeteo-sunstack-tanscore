"""Wavelength/action-spectrum photobiology core (v4).

Canonical quantities:
  E_mel(t)  = integral E_lambda(t,lambda) S_mel(lambda) dlambda  [W/m^2]
  TanDose   = integral E_mel(t) dt                              [J/m^2, melanogenic-effective]
  SED       = integral E_ery(t) dt / 100                        [dimensionless standard unit]

TanScore = 100 * E_mel / E_mel_global_reference (clipped 0-100).
No UVA/UVB hand weights. No sqrt interaction. Photoaddition holds:
  TanDose(l1+l2) == TanDose(l1) + TanDose(l2).

Action-spectrum interpolation is log-space in effectiveness (orders of
magnitude); linear interpolation would corrupt the UVB/UVA ratio.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_VERSION = "action-spectrum-v1"
TAN_SCORE_MODEL_VERSION = "action-spectrum-v1"
TAN_DOSE_MODEL_VERSION = "action-spectrum-v1"
PHOTOBIOLOGY_MODEL_VERSION = "action-spectrum-v1"
ACTION_SPECTRUM_TIER_PROVISIONAL = "provisional"

REQUIRED_DOMAIN_NM = (280.0, 400.0)

# SED convention: 1 SED = 100 J/m^2 erythemally weighted. UVI 1 = 25 mW/m^2
# erythemal => E_ery = UVI/40 W/m^2, SED = integral(UVI dt)/4000 (dt seconds).
UVI_TO_ERYTHEMAL_WM2 = 1.0 / 40.0
SED_J_M2 = 100.0

# Integration gaps: never silently integrate across missing hours.
DEFAULT_MAX_INTERP_GAP_S = 3 * 3600


def _spectra_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, Path.cwd()):
        cand = parent / "data" / "research" / "action_spectra"
        if cand.exists():
            return cand
    return Path("data/research/action_spectra")


@dataclass(frozen=True)
class ActionSpectrum:
    name: str
    wavelengths_nm: np.ndarray
    effectiveness: np.ndarray
    tier: str
    source: str
    sha256: str

    @property
    def log_effectiveness(self) -> np.ndarray:
        return np.log10(np.maximum(self.effectiveness, 1e-12))


_cache: dict[str, ActionSpectrum] = {}


def _load_meta(stem: str) -> dict:
    meta_path = _spectra_dir() / f"{stem}.meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"ERROR photobiology: action-spectrum metadata unavailable: {meta_path}"
        )
    return json.loads(meta_path.read_text(encoding="utf-8"))


def load_action_spectrum(stem: str = "parrish_delayed_melanogenesis") -> ActionSpectrum:
    """Load and strictly validate an action spectrum resource."""
    if stem in _cache:
        return _cache[stem]
    csv_path = _spectra_dir() / f"{stem}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            "ERROR photobiology: melanogenesis action spectrum unavailable: "
            f"{csv_path}"
        )
    meta = _load_meta(stem)
    df = pd.read_csv(csv_path)
    if "wavelength_nm" not in df or "effectiveness" not in df:
        raise ValueError(
            f"ERROR photobiology: {stem}.csv must have wavelength_nm,effectiveness columns"
        )
    waves = pd.to_numeric(df["wavelength_nm"], errors="coerce").to_numpy(dtype=float)
    eff = pd.to_numeric(df["effectiveness"], errors="coerce").to_numpy(dtype=float)
    if len(waves) < 10:
        raise ValueError(f"ERROR photobiology: {stem} has too few rows ({len(waves)})")
    if bool(np.isnan(waves).any()) or bool(np.isnan(eff).any()):
        raise ValueError(f"ERROR photobiology: {stem} contains NaN values")
    if bool((eff < 0).any()):
        raise ValueError(f"ERROR photobiology: {stem} has negative effectiveness")
    if len(np.unique(np.round(waves, 6))) != len(waves):
        raise ValueError(f"ERROR photobiology: {stem} has duplicated wavelengths")
    if bool((np.diff(waves) <= 0).any()):
        raise ValueError(
            f"ERROR photobiology: {stem} wavelengths must be strictly monotonic increasing"
        )
    lo, hi = REQUIRED_DOMAIN_NM
    if waves.min() > lo + 1e-9 or waves.max() < hi - 1e-9:
        raise ValueError(
            f"ERROR photobiology: {stem} must cover {lo:.0f}-{hi:.0f} nm "
            f"(covers {waves.min():.0f}-{waves.max():.0f} nm)"
        )
    if bool((eff <= 0).all()):
        raise ValueError(f"ERROR photobiology: {stem} is all-zero effectiveness")
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    recorded = str(meta.get("checksum_sha256", ""))
    if recorded and recorded != sha:
        raise ValueError(
            f"ERROR photobiology: {stem}.csv checksum mismatch "
            f"(file changed without regenerating metadata)"
        )
    spec = ActionSpectrum(
        name=stem,
        wavelengths_nm=waves,
        effectiveness=eff,
        tier=str(meta.get("tier", "unknown")),
        source=str(meta.get("source_title", meta.get("identifier", stem))),
        sha256=sha,
    )
    _cache[stem] = spec
    return spec


def require_canonical_spectrum(stem: str = "parrish_delayed_melanogenesis") -> ActionSpectrum:
    """Strict production gate: refuse provisional spectra when canonical required."""
    spec = load_action_spectrum(stem)
    if spec.tier != "canonical":
        raise RuntimeError(
            f"ERROR photobiology: strict mode requires the canonical spectrum but "
            f"{stem} tier is {spec.tier!r}. Obtain CIE 103/3 in usable form; "
            f"see data/research/action_spectra/{stem}.meta.json."
        )
    return spec


def effectiveness_at(spec: ActionSpectrum, wavelengths_nm: np.ndarray) -> np.ndarray:
    """Log-space interpolation of effectiveness (documented method).

    Effectiveness spans ~4 orders of magnitude (280 vs 400 nm); linear
    interpolation in effectiveness would over-weight the UVB shoulder and
    corrupt the UVA/UVB biological ratio. Interpolate in log10 space.
    """
    w = np.asarray(wavelengths_nm, dtype=float)
    if bool(((w < spec.wavelengths_nm.min() - 1e-9) | (w > spec.wavelengths_nm.max() + 1e-9)).any()):
        raise ValueError(
            "ERROR photobiology: target wavelengths outside action-spectrum domain"
        )
    logv = np.interp(w, spec.wavelengths_nm, spec.log_effectiveness)
    return 10.0 ** logv


def melanogenic_effective_irradiance(
    spectral_irradiance_wm2nm: np.ndarray,
    wavelengths_nm: np.ndarray,
    spec: ActionSpectrum | None = None,
) -> float:
    """E_mel = integral E_lambda * S_mel dlambda (trapezoidal in wavelength)."""
    if spec is None:
        spec = load_action_spectrum("parrish_delayed_melanogenesis")
    e = np.asarray(spectral_irradiance_wm2nm, dtype=float)
    w = np.asarray(wavelengths_nm, dtype=float)
    if e.shape != w.shape:
        raise ValueError("spectral irradiance and wavelengths must share shape")
    if bool((e < -1e-9).any()) or not bool(np.isfinite(e).all()):
        raise ValueError("ERROR photobiology: spectral irradiance has impossible values")
    s = effectiveness_at(spec, w)
    return float(np.trapezoid(np.clip(e, 0, None) * s, w))


def erythemal_irradiance_from_uvi(uvi: float | np.ndarray) -> np.ndarray:
    return np.asarray(uvi, dtype=float) * UVI_TO_ERYTHEMAL_WM2


def absolute_tan_score_from_melanogenic_irradiance(
    e_mel_wm2: float | np.ndarray,
    global_reference_wm2: float,
) -> np.ndarray:
    """score = clip(100 * E_mel / E_ref, 0, 100). Monotonic in E_mel."""
    if not np.isfinite(global_reference_wm2) or global_reference_wm2 <= 0:
        raise ValueError("ERROR photobiology: global reference must be positive finite")
    e = np.asarray(e_mel_wm2, dtype=float)
    return np.clip(100.0 * e / global_reference_wm2, 0, 100)


def _epoch_seconds(times_utc: pd.Series) -> np.ndarray:
    """Resolution-independent epoch seconds (pandas 3 has non-nano units)."""
    t = pd.to_datetime(times_utc, utc=True)
    return t.map(lambda x: x.timestamp()).to_numpy(dtype=float)


def _trapezoidal_dose(
    times_utc: pd.Series,
    values_wm2: pd.Series,
    max_gap_s: float = DEFAULT_MAX_INTERP_GAP_S,
) -> tuple[float, bool, float]:
    """Trapezoidal time integral with gap splitting.

    Returns (dose_J_m2, complete, coverage_fraction). Gaps larger than
    max_gap_s split the integration; covered seconds / total span gives the
    coverage fraction. Never silently integrates across missing hours.
    """
    t = pd.to_datetime(times_utc, utc=True)
    v = pd.to_numeric(values_wm2, errors="coerce").to_numpy(dtype=float)
    secs_all = _epoch_seconds(t)
    order = np.argsort(secs_all)
    t = t.iloc[order].reset_index(drop=True)
    v = v[order]
    valid = np.isfinite(v)
    n_valid = int(valid.sum())
    if n_valid == 0:
        # No valid samples: the dose is UNKNOWN (NaN), never zero.
        return float("nan"), False, 0.0
    if n_valid == 1:
        # A lone sample spans zero time (dose 0) but cannot claim a complete
        # window: coverage is undefined, so mark incomplete with zero coverage.
        return 0.0, False, 0.0
    secs = _epoch_seconds(t)
    dose = 0.0
    covered = 0.0
    total_span = float(secs[valid].max() - secs[valid].min()) if valid.sum() >= 2 else 0.0
    complete = True
    idx = np.where(valid)[0]
    from itertools import pairwise

    for a, b in pairwise(idx):
        dt = float(secs[b] - secs[a])
        if dt <= 0:
            continue
        if dt > max_gap_s:
            complete = False
            continue
        dose += 0.5 * (v[a] + v[b]) * dt
        covered += dt
    coverage = (covered / total_span) if total_span > 0 else 1.0
    return float(max(dose, 0.0)), bool(complete), float(np.clip(coverage, 0, 1))


def integrate_tandose(
    times_utc: pd.Series,
    e_mel_wm2: pd.Series,
    max_gap_s: float = DEFAULT_MAX_INTERP_GAP_S,
) -> dict[str, float | bool]:
    dose, complete, coverage = _trapezoidal_dose(times_utc, e_mel_wm2, max_gap_s)
    return {
        "tan_dose_melanogenic_j_m2": dose,
        "tan_dose_complete": complete,
        "tan_dose_coverage_fraction": coverage,
    }


def integrate_sed(
    times_utc: pd.Series,
    erythemal_wm2: pd.Series,
    max_gap_s: float = DEFAULT_MAX_INTERP_GAP_S,
) -> dict[str, float | bool]:
    dose_j, complete, coverage = _trapezoidal_dose(times_utc, erythemal_wm2, max_gap_s)
    return {
        "sed": float(dose_j / SED_J_M2),
        "sed_complete": complete,
        "sed_coverage_fraction": coverage,
    }


def integrate_band_dose(
    times_utc: pd.Series,
    band_wm2: pd.Series,
    max_gap_s: float = DEFAULT_MAX_INTERP_GAP_S,
) -> dict[str, float | bool]:
    dose_j, complete, coverage = _trapezoidal_dose(times_utc, band_wm2, max_gap_s)
    return {
        "dose_j_m2": dose_j,
        "dose_j_cm2": float(dose_j / 1e4),
        "complete": complete,
        "coverage_fraction": coverage,
    }


def reference_minutes(
    tandose_j_m2: float, e_mel_global_reference_wm2: float
) -> float:
    """Presentation unit only: equivalent minutes at fixed global reference."""
    if e_mel_global_reference_wm2 <= 0:
        raise ValueError("global reference must be positive")
    return float(tandose_j_m2 / e_mel_global_reference_wm2 / 60.0)


def model_metadata(global_reference: dict | None = None) -> dict[str, object]:
    try:
        mel = load_action_spectrum("parrish_delayed_melanogenesis")
        mel_meta = {
            "action_spectrum_name": mel.name,
            "action_spectrum_sha256": mel.sha256,
            "action_spectrum_source": mel.source,
            "photobiology_action_spectrum_tier": mel.tier,
        }
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        mel_meta = {"action_spectrum_error": str(exc)}
    try:
        ery = load_action_spectrum("cie_erythema_reference")
        ery_meta = {
            "erythema_spectrum_name": ery.name,
            "erythema_spectrum_sha256": ery.sha256,
        }
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        ery_meta = {"erythema_spectrum_error": str(exc)}
    base: dict[str, object] = {
        "photobiology_model_version": PHOTOBIOLOGY_MODEL_VERSION,
        "tan_score_model_version": TAN_SCORE_MODEL_VERSION,
        "tan_dose_model_version": TAN_DOSE_MODEL_VERSION,
        **mel_meta,
        **ery_meta,
    }
    if global_reference:
        base.update(global_reference)
    return base
