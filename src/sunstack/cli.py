from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from . import config
from .calibrate import (
    build_local_reference,
    build_serving_reference,
    build_training_dataset,
    compute_openmeteo_model_skill,
    prepare_nasa_training,
    train_uv_models,
)
from .derive import (
    add_solar_diagnostics,
    best_windows,
    deterministic_consensus,
    enrich_15min_with_hourly_uv,
    ensemble_probabilities,
    merge_air_quality,
)
from .fetch import fetch_all, probe_live, write_raw
from .history import (
    cds_credentials_present,
    fetch_cams_eac4_history,
    fetch_cams_forecast,
    fetch_epa_uv_forecast,
    fetch_nasa_power_history,
    fetch_openmeteo_historical_forecast,
    fetch_openmeteo_previous_runs,
)
from .normalize import (
    normalize_air_quality,
    normalize_deterministic,
    normalize_ensemble_mean,
    normalize_ensemble_members,
    normalize_hrrr_15min,
    normalize_profiles,
)
from .opportunity import (
    apply_outdoor_feasibility,
    attach_fitzpatrick,
    attach_personalization,
    build_30min_forecast,
    build_daily_summary,
)
from .tanscore import best_tan_windows, score_forecast
from .validation import (
    DataValidationError,
    ValidationIssue,
    raise_on_errors,
    validate_cams_direct,
    validate_live_sources,
    validate_scored_hourly,
)

LOG = logging.getLogger("sunstack")


def _setup_logging(root: Path, debug: bool = False) -> None:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.DEBUG if debug else logging.INFO)
    LOG.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.DEBUG if debug else logging.INFO)
    fh = logging.FileHandler(log_dir / "sunstack.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    LOG.addHandler(sh)
    LOG.addHandler(fh)


def _print_config() -> None:
    for site in config.active_sites():
        mark = " (default)" if site.default else ""
        print(f"Location {site.slug}{mark}: {site.lat}, {site.lon} ({site.timezone})")
    print(
        f"Strict default: {config.STRICT_DEFAULT}; direct CAMS required: {config.REQUIRE_DIRECT_CAMS}"
    )
    print(
        f"Outdoor temperature floor: {config.MIN_TAN_TEMP_F:.0f}F; hard heat ceiling: {config.MAX_TAN_TEMP_F:.0f}F"
    )
    print(
        "Overall score weights:",
        config.OVERALL_SCORE_WEIGHTS,
        f"(absolute headroom +{config.OVERALL_ABSOLUTE_HEADROOM:.0f})",
    )
    print("\nDeterministic models:")
    for x in config.DETERMINISTIC_MODELS:
        print("  -", x)
    print("\nFull-member ensembles:")
    for x in config.ENSEMBLE_MEMBER_MODELS:
        print("  -", x)
    print("\nEnsemble mean+spread:")
    for x in config.ENSEMBLE_MEAN_MODELS:
        print("  -", x)
    print(
        f"\nNASA POWER calibration: {config.NASA_POWER_START} -> {config.NASA_POWER_END}"
    )
    print(
        f"Open-Meteo historical: {config.OPENMETEO_HISTORY_START} -> {config.OPENMETEO_HISTORY_END}"
    )
    print(f"CAMS EAC4: {config.CAMS_EAC4_START_YEAR} -> {config.CAMS_EAC4_END_YEAR}")
    print(f"ADS/CAMS credentials detected: {cds_credentials_present()}")
    print("\nPhotobiology model (v5 delayed-pigmentation):")
    from .spectral import SPECTRAL_BACKEND_VERSION as _backend

    print(f"  tan_score_model={config.TAN_SCORE_MODEL_VERSION}")
    print(f"  action_spectrum={config.ACTION_SPECTRUM_VERSION} ({config.ACTION_SPECTRUM_STEM})")
    print(f"  global_reference={config.GLOBAL_MELANOGENIC_REFERENCE_VERSION} "
          f"E_mel={config.GLOBAL_MELANOGENIC_REFERENCE_WM2} W/m^2")
    print(f"  spectral_backend={_backend} (degraded Tier-C proxy; "
          f"strict Tier B requires {config.SPECTRAL_BACKEND_VERSION_V5}; "
          f"canonical_required={config.REQUIRE_CANONICAL_SPECTRUM})")
    print(f"  tandose_max_gap_s={config.TANDOSE_MAX_INTERP_GAP_S:g}")
    print(f"  skin_tilt_deg={config.SKIN_TILT_DEG:g} "
          f"skin_azimuth_deg={config.SKIN_AZIMUTH_DEG:g}")
    print(f"  uvi_disagree_warn/strong="
          f"{config.UVI_DISAGREEMENT_WARN_FRAC:g}/"
          f"{config.UVI_DISAGREEMENT_STRONG_FRAC:g} (confidence only)")


def _calibration_paths(
    root: Path, site_slug: str | None = None
) -> tuple[Path, Path, Path]:
    """Calibration dirs, namespaced per location. The default site keeps the legacy layout."""
    current = config.current_site()
    slug = site_slug or (current.slug if current is not None else None)
    site_root = (
        root
        if not slug or slug == config.default_site().slug
        else root / "sites" / slug
    )
    return (
        site_root / "calibration_sources",
        site_root / "calibration",
        Path(".cache") / "sunstack",
    )


def calibration_paths(
    root: Path, site_slug: str | None = None
) -> tuple[Path, Path, Path]:
    """Public alias for automation (scripts, CI) that must not touch privates."""
    return _calibration_paths(root, site_slug)


def bootstrap(
    root: Path,
    force: bool = False,
    skip_cams_history: bool = False,
    strict: bool = True,
    site: config.Site | None = None,
) -> dict[str, object]:
    with config.use_site(site) if site is not None else nullcontext():
        return _bootstrap_inner(
            root, force=force, skip_cams_history=skip_cams_history, strict=strict
        )


def _bootstrap_inner(
    root: Path,
    force: bool = False,
    skip_cams_history: bool = False,
    strict: bool = True,
) -> dict[str, object]:
    source_dir, calibration_dir, cache_dir = _calibration_paths(root)
    if (
        strict
        and config.REQUIRE_DIRECT_CAMS
        and not skip_cams_history
        and not cds_credentials_present()
    ):
        raise DataValidationError(
            "STRICT BOOTSTRAP requires Copernicus ADS credentials for CAMS EAC4. "
            "Configure ~/.cdsapirc (or CDSAPI_URL/CDSAPI_KEY), then rerun. "
            "Use --allow-degraded only if you intentionally accept a lower calibration tier."
        )

    LOG.info(
        "[1/5] NASA POWER hourly UVA/UVB history — real API requests for uncached years"
    )
    nasa = fetch_nasa_power_history(source_dir, cache_dir, force=force)
    LOG.info("NASA rows: %s", f"{len(nasa):,}")
    if strict and len(nasa) < 50_000:
        raise DataValidationError(
            f"NASA POWER history insufficient: only {len(nasa):,} rows"
        )

    LOG.info("[2/5] Open-Meteo historical forecast archive")
    om_hist = fetch_openmeteo_historical_forecast(source_dir, cache_dir, force=force)
    LOG.info("Open-Meteo historical rows: %s", f"{len(om_hist):,}")
    if strict and len(om_hist) < 5_000:
        raise DataValidationError(
            f"Open-Meteo historical archive insufficient: only {len(om_hist):,} rows"
        )

    LOG.info("[3/5] Open-Meteo Previous Runs lead-time archive")
    previous = fetch_openmeteo_previous_runs(source_dir, cache_dir, force=force)
    LOG.info("Previous-run rows: %s", f"{len(previous):,}")
    if strict and previous.empty:
        raise DataValidationError(
            "Open-Meteo Previous Runs returned no data; cannot calibrate lead-time skill"
        )

    cams_eac4 = pd.DataFrame()
    if not skip_cams_history and cds_credentials_present():
        LOG.info("[4/5] CAMS EAC4 aerosol/ozone history via ADS")
        cams_eac4 = fetch_cams_eac4_history(source_dir, force=force)
        LOG.info("CAMS EAC4 rows: %s", f"{len(cams_eac4):,}")
        if strict and cams_eac4.empty:
            raise DataValidationError("CAMS EAC4 retrieval produced no usable rows")
    else:
        LOG.warning("[4/5] CAMS EAC4 skipped — degraded calibration tier")

    LOG.info(
        "[5/5] Build calibration dataset, UVA/UVB models, local climatology, model skill"
    )
    training = build_training_dataset(nasa, om_hist, cams_eac4, calibration_dir)
    model_training = prepare_nasa_training(nasa, cams_eac4)
    if model_training.empty:
        raise DataValidationError("NASA/CAMS model training table is empty")
    model_metrics = train_uv_models(model_training, calibration_dir)
    local_ref = build_local_reference(model_training, calibration_dir)
    skill = compute_openmeteo_model_skill(previous, om_hist, calibration_dir)
    # Lead-aware serving references rebuild alongside the legacy reference so
    # fresh bootstraps never ship without them; missing hindcast inputs fall
    # back to legacy percentiles loudly at score time (no silent failure).
    build_serving_reference(source_dir, calibration_dir, config.TIMEZONE)
    if strict and local_ref.empty:
        raise DataValidationError("Local TanScore reference climatology is empty")

    summary: dict[str, object] = {
        "created_at": datetime.now().astimezone().isoformat(),
        "coordinates": [config.LATITUDE, config.LONGITUDE],
        "timezone": config.TIMEZONE,
        "strict": strict,
        "nasa_rows": len(nasa),
        "openmeteo_historical_rows": len(om_hist),
        "previous_runs_rows": len(previous),
        "cams_eac4_rows": len(cams_eac4),
        "training_rows": len(training),
        "local_reference_rows": len(local_ref),
        "skill_rows": len(skill),
        "direct_cams_credentials": cds_credentials_present(),
        "model_metrics": model_metrics,
        "tan_score_model": {
            "tan_score_model_version": config.TAN_SCORE_MODEL_VERSION,
            "global_reference_version": config.GLOBAL_MELANOGENIC_REFERENCE_VERSION,
            "global_reference_e_mel_wm2": config.GLOBAL_MELANOGENIC_REFERENCE_WM2,
            "formula": "score = clip(100 * E_mel / E_mel_global_reference, 0, 100)",
        },
        "legacy_absolute_score_definition_55_30_15": {
            "status": "DEPRECATED: retained for migration diagnostics only; "
                      "never used in v4 production scoring",
            "uvi_reference": config.ABSOLUTE_UVI_REFERENCE,
            "uva_reference_wm2": config.ABSOLUTE_UVA_REFERENCE_WM2,
            "weights": config.ABSOLUTE_TAN_WEIGHTS,
        },
    }
    (calibration_dir / "calibration_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    LOG.info("Calibration written to %s", calibration_dir)
    return summary


def ensure_calibration(
    root: Path, auto: bool = True, strict: bool = True, site: config.Site | None = None
) -> None:
    if strict and config.REQUIRE_DIRECT_CAMS and not cds_credentials_present():
        raise DataValidationError(
            "Strict mode requires Copernicus ADS credentials before calibration/live scoring. Configure ~/.cdsapirc first, or explicitly use --allow-degraded."
        )
    _, calibration_dir, _ = _calibration_paths(root, site.slug if site else None)
    required = [
        calibration_dir / "uva_uvb_models.joblib",
        calibration_dir / "local_reference.parquet",
    ]
    if all(p.exists() for p in required):
        return
    if not auto:
        if strict:
            raise DataValidationError(
                "Calibration missing. Run `uv run sunstack setup` or `uv run sunstack bootstrap`."
            )
        LOG.warning("Calibration missing; lower-accuracy fallback may be used")
        return
    LOG.info("No calibration found — bootstrapping automatically")
    bootstrap(
        root,
        force=False,
        skip_cams_history=not cds_credentials_present(),
        strict=strict,
        site=site,
    )


def _issue_dicts(issues: list[ValidationIssue]):
    return [
        {"severity": i.severity, "source": i.source, "message": i.message}
        for i in issues
    ]


def run_live(
    root: Path,
    auto_calibrate: bool = True,
    force_cams: bool = False,
    strict: bool = True,
    skin_type: int | None = None,
    min_temp_f: float | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
    fresh: bool = True,
    site: config.Site | None = None,
    surface_slug: str = "unknown",
    surface_extent: str = "local",
    skin_tilt_deg: float | None = None,
    skin_azimuth_deg: float | None = None,
    surface_uva_reflectance: float | None = None,
    surface_uvb_reflectance: float | None = None,
) -> Path:
    if site is not None:
        with config.use_site(site):
            return _run_live_inner(
                root,
                auto_calibrate=auto_calibrate,
                force_cams=force_cams,
                strict=strict,
                skin_type=skin_type,
                min_temp_f=min_temp_f,
                fresh=fresh,
                site=site,
                personal_mmd_j_m2=personal_mmd_j_m2,
                personal_mmd_basis=personal_mmd_basis,
                surface_slug=surface_slug,
                surface_extent=surface_extent,
                skin_tilt_deg=skin_tilt_deg,
                skin_azimuth_deg=skin_azimuth_deg,
                surface_uva_reflectance=surface_uva_reflectance,
                surface_uvb_reflectance=surface_uvb_reflectance,
            )
    return _run_live_inner(
        root,
        auto_calibrate=auto_calibrate,
        force_cams=force_cams,
        strict=strict,
        skin_type=skin_type,
        min_temp_f=min_temp_f,
        fresh=fresh,
        personal_mmd_j_m2=personal_mmd_j_m2,
        personal_mmd_basis=personal_mmd_basis,
        surface_slug=surface_slug,
        surface_extent=surface_extent,
        skin_tilt_deg=skin_tilt_deg,
        skin_azimuth_deg=skin_azimuth_deg,
        surface_uva_reflectance=surface_uva_reflectance,
        surface_uvb_reflectance=surface_uvb_reflectance,
    )


def _run_live_inner(
    root: Path,
    auto_calibrate: bool = True,
    force_cams: bool = False,
    strict: bool = True,
    skin_type: int | None = None,
    min_temp_f: float | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
    fresh: bool = True,
    site: config.Site | None = None,
    surface_slug: str = "unknown",
    surface_extent: str = "local",
    skin_tilt_deg: float | None = None,
    skin_azimuth_deg: float | None = None,
    surface_uva_reflectance: float | None = None,
    surface_uvb_reflectance: float | None = None,
) -> Path:
    site_root = (
        root
        if site is None or site.slug == config.default_site().slug
        else root / "sites" / site.slug
    )
    ensure_calibration(root, auto=auto_calibrate, strict=strict, site=site)
    _, calibration_dir, cache_dir = _calibration_paths(
        root, site.slug if site else None
    )
    # Collision-proof run ID (audit: second-resolution stamps collided
    # under simultaneous runs). Microseconds + pid suffix.
    import os as _os

    stamp = (datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
             + f"_{_os.getpid() % 100000:05d}")
    run_dir = site_root / "runs" / stamp
    raw_dir = run_dir / "raw"
    table_dir = run_dir / "tables"
    run_dir.mkdir(parents=True, exist_ok=True)

    LOG.info("Fetching live Open-Meteo sources%s", " (cache bypassed)" if fresh else "")
    results = fetch_all(cache_dir, fresh=fresh)
    write_raw(results, raw_dir)
    source_issues = validate_live_sources(results, strict=strict)
    for issue in source_issues:
        getattr(LOG, "error" if issue.severity == "ERROR" else "warning")(
            "[%s] %s", issue.source, issue.message
        )
    if strict:
        raise_on_errors(source_issues, "Required Open-Meteo live sources failed")
    successes = [r for r in results if r.payload is not None]
    LOG.info(
        "Fetched %d/%d Open-Meteo feeds successfully", len(successes), len(results)
    )

    det_hourly, det_daily, current = normalize_deterministic(results)
    profiles = normalize_profiles(results)
    hrrr15 = normalize_hrrr_15min(results)
    members = normalize_ensemble_members(results)
    ens_mean = normalize_ensemble_mean(results)
    air = normalize_air_quality(results)
    det_hourly = add_solar_diagnostics(det_hourly, 3600)
    members = add_solar_diagnostics(members, 3600)
    model_col = (
        det_hourly["model"]
        if "model" in det_hourly.columns
        else pd.Series(index=det_hourly.index, dtype=object)
    )
    best = (
        det_hourly.loc[model_col == "best_match"].copy()
        if not det_hourly.empty
        else pd.DataFrame()
    )
    hrrr15 = add_solar_diagnostics(enrich_15min_with_hourly_uv(hrrr15, best), 900)
    consensus = deterministic_consensus(det_hourly)
    ensemble_probs = ensemble_probabilities(members)
    best_air = merge_air_quality(best, air)
    sun_windows = best_windows(best_air, ensemble_probs, consensus)

    if strict and config.REQUIRE_DIRECT_CAMS and not cds_credentials_present():
        raise DataValidationError(
            "Direct CAMS spectral forecast is required in strict mode, but ADS credentials are missing. Configure ~/.cdsapirc, then rerun."
        )
    LOG.info("Fetching direct CAMS spectral forecast via ADS")
    cams_direct = (
        fetch_cams_forecast(run_dir, force=force_cams, raw_root=root)
        if cds_credentials_present()
        else pd.DataFrame()
    )
    cams_issues = (
        validate_cams_direct(cams_direct)
        if cds_credentials_present()
        else [
            ValidationIssue("ERROR", "cams_direct_ads", "ADS credentials unavailable")
        ]
    )
    for issue in cams_issues:
        getattr(LOG, "error" if issue.severity == "ERROR" else "warning")(
            "[%s] %s", issue.source, issue.message
        )
    if strict and config.REQUIRE_DIRECT_CAMS:
        raise_on_errors(cams_issues, "Direct CAMS spectral validation failed")
    # EPA/NWS operational UVI: opportunistic third UVI source (US ZIP sites).
    # Never gates the run; absence degrades to two-source consensus downstream.
    epa_zip = site.zip if site is not None else config.default_site().zip
    epa_hourly = pd.DataFrame()
    if epa_zip:
        LOG.info("Fetching EPA/NWS operational UVI for %s", epa_zip)
        epa_hourly, _ = fetch_epa_uv_forecast(run_dir, epa_zip)
        best_air = best_air.merge(epa_hourly.loc[:, ["time", "uvi_epa"]], on="time", how="left") if not epa_hourly.empty else best_air
    tan_hourly = score_forecast(best_air, calibration_dir, cams_direct, sun_windows,
                               strict=strict)
    tan_hourly = apply_outdoor_feasibility(tan_hourly, min_temp_f)
    tan_hourly = attach_fitzpatrick(tan_hourly, skin_type)
    try:
        from .doses import add_interval_doses as _add_hourly_doses
        tan_hourly = _add_hourly_doses(tan_hourly)
    except (ImportError, ValueError) as exc:
        LOG.error("[doses] hourly interval-dose integration failed: %s", exc)
        if strict:
            raise
    # Objective-first personalization columns (environmental physics untouched;
    # fractions stay NaN until a measured/compatible MMD is supplied). Runs
    # AFTER interval doses so the hourly fraction has a dose to divide.
    tan_hourly = attach_personalization(
        tan_hourly, personal_mmd_j_m2=personal_mmd_j_m2,
        basis=personal_mmd_basis)
    from .spectral import apply_skin_plane, resolve_skin_plane
    from .surface import resolve_surface

    skin_plane = resolve_skin_plane(skin_tilt_deg, skin_azimuth_deg)
    surface = resolve_surface(
        surface_slug, surface_uva_reflectance, surface_uvb_reflectance
    )
    tan_hourly = apply_skin_plane(
        tan_hourly,
        skin_plane.tilt_deg,
        skin_plane.azimuth_deg,
        surface.slug,
        surface_extent,
        surface_uva_reflectance,
        surface_uvb_reflectance,
    )
    # Strict photobiology gate: spectrum resource must evaluate.
    from .validation import validate_action_spectra

    photo_issues = validate_action_spectra(
        strict_canonical=config.REQUIRE_CANONICAL_SPECTRUM and strict
    )
    for issue in photo_issues:
        getattr(LOG, "error" if issue.severity == "ERROR" else "warning")(
            "[%s] %s", issue.source, issue.message
        )
    # Gate 1 (hourly product): validate the scored hourly frame now for fast
    # failure, but the STRICT publish gate runs after ALL products exist
    # (30-min + daily + cross-product invariants below). A broken final
    # product must never publish with validation_issues: [].
    score_issues = validate_scored_hourly(tan_hourly)
    for issue in score_issues:
        getattr(LOG, "error" if issue.severity == "ERROR" else "warning")(
            "[%s] %s", issue.source, issue.message
        )
    if strict:
        raise_on_errors(photo_issues + score_issues, "TanScore output validation failed")

    tan_30 = build_30min_forecast(tan_hourly, hrrr15, min_temp_f=min_temp_f,
                                     calibration_dir=calibration_dir)
    tan_30 = attach_fitzpatrick(tan_30, skin_type)
    tan_30 = attach_personalization(
        tan_30, personal_mmd_j_m2=personal_mmd_j_m2,
        basis=personal_mmd_basis, dose_col="tan_dose_30m_j_m2")
    tan_30 = apply_skin_plane(
        tan_30,
        skin_plane.tilt_deg,
        skin_plane.azimuth_deg,
        surface.slug,
        surface_extent,
        surface_uva_reflectance,
        surface_uvb_reflectance,
    )
    daily_tan = build_daily_summary(tan_30)
    tan_windows = best_tan_windows(tan_hourly)
    # Gate 2 (final products): strict validates the PUBLISHED artifacts, not
    # just the hourly frame. Cross-product invariants catch a broken final
    # product that hourly validation cannot see (audit P0).
    final_issues: list[ValidationIssue] = []
    if strict:
        from .validation import validate_final_products

        final_issues = validate_final_products(tan_hourly, tan_30, daily_tan)
        for issue in final_issues:
            getattr(LOG, "error" if issue.severity == "ERROR" else "warning")(
                "[%s] %s", issue.source, issue.message
            )
        raise_on_errors(final_issues, "Final product validation failed")

    # Privacy: personal MMD fractions must never persist into shared run
    # tables (audit: clearing the input didn't clear prior personalization,
    # and exports could carry it). Strip before writing; the API/export
    # layers recompute fractions per-request from query params instead.
    _personal_cols = ("personal_mmd_fraction", "personal_mmd_equivalent_dose_j_m2",
                      "personal_mmd_j_m2", "personalization_basis")
    for _frame in (tan_hourly, tan_30):
        for _col in _personal_cols:
            if _col in _frame.columns:
                _frame.drop(columns=[_col], inplace=True)
    from .output import (
        write_frame as _write_frame,  # deferred: output imports ui template; cli must stay import-light
    )

    for frame, name in [
        (det_hourly, "deterministic_hourly"),
        (det_daily, "deterministic_daily"),
        (current, "current_best_match"),
        (profiles, "deep_pressure_profiles"),
        (hrrr15, "hrrr_native_15min"),
        (members, "ensemble_members_long"),
        (ens_mean, "ensemble_mean_spread"),
        (ensemble_probs, "ensemble_probabilities"),
        (consensus, "deterministic_consensus"),
        (air, "air_quality_aerosols"),
        (cams_direct, "cams_direct_forecast"),
        (best_air, "best_match_enriched"),
        (sun_windows, "best_sun_windows"),
        (tan_hourly, "tan_forecast_hourly"),
        (tan_30, "tan_forecast_30min"),
        (daily_tan, "tan_daily_summary"),
        (tan_windows, "best_tan_windows"),
    ]:
        _write_frame(frame, table_dir, name)

    source_health = [
        {
            "name": r.name,
            "ok": r.payload is not None,
            "error": r.error,
            "elapsed_ms": r.elapsed_ms,
            "status_code": r.status_code,
            "from_cache": r.from_cache,
            "endpoint": r.endpoint,
        }
        for r in results
    ]
    source_health.append(
        {
            "name": "cams_direct_ads",
            "ok": not cams_direct.empty,
            "error": None if not cams_direct.empty else "empty/not available",
            "elapsed_ms": None,
            "status_code": None,
            "from_cache": False,
            "endpoint": "Copernicus ADS",
        }
    )

    summary: dict[str, object] = {
        "run": stamp,
        "created_at": datetime.now().astimezone().isoformat(),
        "coordinates": [config.LATITUDE, config.LONGITUDE],
        "timezone": config.TIMEZONE,
        "site_slug": site.slug if site else config.default_site().slug,
        "site_name": site.name if site else config.default_site().name,
        "strict": strict,
        "skin_type": skin_type,
        "personal_mmd_j_m2": personal_mmd_j_m2,
        "personalization_basis": personal_mmd_basis,
        "surface_material_slug": surface.slug,
        "surface_extent_mode": surface_extent,
        "skin_tilt_deg": skin_plane.tilt_deg,
        "skin_azimuth_deg": skin_plane.azimuth_deg,
        "exposure_basis": "environmental_horizontal",
        "min_tan_temperature_f": float(
            config.MIN_TAN_TEMP_F if min_temp_f is None else min_temp_f
        ),
        "successful_openmeteo_feeds": len(successes),
        "total_openmeteo_feeds": len(results),
        "direct_cams_used": not cams_direct.empty,
        "cams_cycle": str(cams_direct["cams_cycle"].iloc[0]) if "cams_cycle" in cams_direct and len(cams_direct) else None,
        # All cycles contributing rows (audit: iloc[0] hid mixed-cycle runs).
        "cams_cycles_used": sorted(cams_direct["cams_cycle"].dropna().astype(str).unique().tolist()) if "cams_cycle" in cams_direct and len(cams_direct) else [],
        "calibration_available": (calibration_dir / "uva_uvb_models.joblib").exists(),
        "calibration_tier": str(tan_hourly["tan_calibration_tier"].iloc[0]) if "tan_calibration_tier" in tan_hourly and len(tan_hourly) else None,
        "source_health": source_health,
        "validation_issues": _issue_dicts(
            source_issues + cams_issues + photo_issues + score_issues + final_issues,
        ),
        "schema_version": config.SCHEMA_VERSION,
        "temporal_semantics_version": config.TEMPORAL_SEMANTICS_VERSION,
        "photobiology_model_version": config.PHOTOBIOLOGY_MODEL_VERSION,
        "tan_score_model_version": config.TAN_SCORE_MODEL_VERSION,
        "tan_dose_model_version": config.TAN_SCORE_MODEL_VERSION,
        "action_spectrum_version": config.ACTION_SPECTRUM_VERSION,
        "spectral_backend_strict": config.SPECTRAL_BACKEND_VERSION_V5,
        "spectral_backend_degraded": config.SPECTRAL_DEGRADED_BACKEND,
        "surface_model_version": config.SURFACE_MODEL_VERSION,
        "confidence_version": config.CONFIDENCE_VERSION,
        "window_rank_version": config.WINDOW_RANK_VERSION,
        "global_reference_version": config.GLOBAL_MELANOGENIC_REFERENCE_VERSION,
        "global_reference_e_mel_wm2": config.GLOBAL_MELANOGENIC_REFERENCE_WM2,
        "deprecated_fields": config.DEPRECATED_FIELDS,
        "deprecated_aliases": config.DEPRECATED_ALIASES,
        "score_semantics": config.score_semantics(),
        "hard_blocks": {
            "active_rain": True,
            "active_snow": True,
            "thunderstorm": True,
            "temperature_below_f": float(
                config.MIN_TAN_TEMP_F if min_temp_f is None else min_temp_f
            ),
            "temperature_at_or_above_f": config.MAX_TAN_TEMP_F,
        },
        "rows": {
            "tan_forecast_hourly": len(tan_hourly),
            "tan_forecast_30min": len(tan_30),
            "tan_daily_summary": len(daily_tan),
            "cams_direct_forecast": len(cams_direct),
        },
    }
    try:
        from .photobiology import model_metadata as _model_metadata
        from .spectral import emulator_manifest as _emulator_manifest

        summary.update(_model_metadata({
            "global_reference_version": config.GLOBAL_MELANOGENIC_REFERENCE_VERSION,
            "global_reference_e_mel_wm2": config.GLOBAL_MELANOGENIC_REFERENCE_WM2,
        }))
        summary.update(_emulator_manifest())
    except (ImportError, ValueError, RuntimeError) as exc:
        summary["photobiology_metadata_error"] = str(exc)
    # Provenance split: forecast identity (what generated these rows) vs
    # renderer identity (what last touched the static page). A UI-only reskin
    # must update renderer_* only — never forecast_code_sha. See output.py.
    from .build_sha import build_sha as _build_sha
    summary["forecast_code_sha"] = _build_sha()
    summary["fusion_version"] = config.FUSION_VERSION
    summary["input_manifest"] = {
        "run_dir": str(run_dir),
        "raw_dir": str(raw_dir),
        "manifest_file": str(raw_dir / "manifest.json"),
        "retention": ("CI artifact sunstack-data-<run_id> (90 days) + "
                      "committed docs/data.json product; raw provider payloads "
                      "are local-only and NOT in git"),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    # Single latest-run pointer: atomic swap (audit: delete-then-copy left
    # a window with no/partial latest). Copy to temp + os.replace rename.
    # (A former LATEST marker file is gone: it collides on case-insensitive
    # filesystems.) Caller must hold config.site_lock() for cross-run safety.
    latest = site_root / "latest"
    _tmp = site_root / f".latest_tmp_{stamp}"
    if _tmp.is_symlink() or _tmp.is_file():
        _tmp.unlink()
    elif _tmp.exists():
        shutil.rmtree(_tmp)
    _latest_copy: Path = shutil.copytree(run_dir, _tmp)
    if latest.is_symlink() or latest.is_file():
        latest.unlink()
    elif latest.exists():
        shutil.rmtree(latest)
    os.replace(_tmp, latest)

    LOG.info("Run written to %s", run_dir)
    if not daily_tan.empty:
        cols = [
            c
            for c in [
                "date",
                "day_status",
                "day_overall_peak_0_100",
                "day_absolute_peak_0_100",
                "day_local_peak_0_100",
                "day_atmospheric_peak_0_100",
                "day_confidence_at_peak_0_100",
                "best_window_start",
                "best_window_end",
                "best_hour_start",
            ]
            if c in daily_tan
        ]
        print("\nBest tanning times by day:")
        print(daily_tan[cols].to_string(index=False))
    if not tan_windows.empty:
        cols = [
            c
            for c in [
                "time",
                "overall_tan_opportunity_0_100",
                "tan_score_absolute_0_100",
                "local_tan_score_0_100",
                "atmospheric_quality_percentile_0_100",
                "tan_forecast_confidence_0_100",
                "outdoor_feasibility_0_100",
                "outdoor_block_reason",
                "uv_index",
                "predicted_uva_wm2",
            ]
            if c in tan_windows
        ]
        print("\nTop hourly tanning opportunities:")
        print(tan_windows[cols].head(15).to_string(index=False))
    return run_dir


def _global_reference_status() -> tuple[bool, str]:
    """Locate + sanity-check the versioned global melanogenic reference."""
    try:
        from importlib import resources

        ref = (resources.files("sunstack") / "_data" /
               "global_melanogenic_reference" / "reference.json")
        if ref.is_file():
            import json as _json

            manifest = _json.loads(ref.read_text(encoding="utf-8"))
            value = float(manifest.get("global_reference_e_mel_wm2", 0))
            version = str(manifest.get("global_reference_version", ""))
            if value > 0 and version:
                return True, f"{version} ({value:g} W/m^2 mel) [packaged]"
            return False, "packaged reference.json has invalid value/version"
    except (ImportError, OSError, TypeError, ValueError):
        pass
    here = Path(__file__).resolve()
    candidates = [here.parent.parent.parent / "data" / "calibration" /
                  "global_melanogenic_reference" / "reference.json",
                  Path.cwd() / "data" / "calibration" /
                  "global_melanogenic_reference" / "reference.json"]
    for cand in candidates:
        if cand.exists():
            try:
                import json as _json

                manifest = _json.loads(cand.read_text(encoding="utf-8"))
                value = float(manifest.get("global_reference_e_mel_wm2", 0))
                version = str(manifest.get("global_reference_version", ""))
                if value > 0 and version:
                    return True, f"{version} ({value:g} W/m^2 mel)"
                return False, f"{cand}: invalid value/version"
            except (OSError, ValueError) as exc:
                return False, f"{cand}: unreadable ({exc})"
    return False, "reference.json not found"


def doctor(root: Path, probe: bool = False) -> bool:
    _, calibration_dir, _ = _calibration_paths(root)
    checks = {
        "ADS/CAMS credentials": cds_credentials_present(),
        "UVA/UVB model": (calibration_dir / "uva_uvb_models.joblib").exists(),
        "local climatology": (calibration_dir / "local_reference.parquet").exists(),
        "model skill table": (
            calibration_dir / "openmeteo_model_skill.parquet"
        ).exists(),
    }
    # Photobiology pre-flight (§19): without evaluable spectra + reference the
    # model cannot run at all — always fatal, even --allow-degraded (degraded
    # covers source tiers, never missing physics files).
    from .validation import validate_action_spectra

    photo_issues = validate_action_spectra(
        strict_canonical=config.REQUIRE_CANONICAL_SPECTRUM)
    photo_errors = [i for i in photo_issues if i.severity == "ERROR"]
    checks["action spectra (melanogenesis/erythema/IPD)"] = not photo_errors
    ref_ok, ref_detail = _global_reference_status()
    checks["global melanogenic reference"] = ref_ok
    print("SunStack doctor")
    print(f"  location: {config.LATITUDE}, {config.LONGITUDE} ({config.TIMEZONE})")
    for k, v in checks.items():
        print(f"  {k}: {'OK' if v else 'MISSING'}")
    for issue in photo_errors:
        print(f"  photobiology ERROR: [{issue.source}] {issue.message}")
    print(f"  global reference detail: {ref_detail}")
    # Stale local climatology is loud but non-fatal (validation WARNs at run).
    stale_note = ""
    try:
        import json as _json

        ver_path = calibration_dir / "local_reference_version.json"
        if ver_path.exists():
            ver = _json.loads(ver_path.read_text(encoding="utf-8"))
            if ver.get("tan_score_model_version") != config.TAN_SCORE_MODEL_VERSION:
                stale_note = (
                    f"  local reference STALE (model "
                    f"{ver.get('tan_score_model_version')}; current "
                    f"{config.TAN_SCORE_MODEL_VERSION}): rebuild with "
                    f"scripts/rebuild_v4_references.py")
        else:
            stale_note = ("  local reference version: unknown (no "
                          "local_reference_version.json)")
    except (OSError, ValueError):
        stale_note = "  local reference version: unreadable"
    if stale_note:
        print(stale_note)
    ok = (
        all(checks.values())
        if config.REQUIRE_DIRECT_CAMS
        else all(v for k, v in checks.items() if k != "ADS/CAMS credentials")
    )
    if probe:
        print("\nProbing live Open-Meteo APIs (3 tiny parallel probes)...", flush=True)
        results = probe_live()
        for r in results:
            print(
                f"  {'OK' if r.payload is not None else 'FAIL':4} {r.name:48} {r.elapsed_ms or 0:8.1f} ms {r.error or ''}",
                flush=True,
            )
        if any(r.payload is None for r in results):
            ok = False
    if not cds_credentials_present() and config.REQUIRE_DIRECT_CAMS:
        print(
            "\nCAMS setup required: create a Copernicus ADS account, accept dataset terms, and configure ~/.cdsapirc."
        )
    return ok


def debug_report(root: Path, photobiology: bool = False) -> None:
    print("SunStack debug")
    latest = root / "latest"
    print("  latest:", latest.resolve() if latest.exists() else "MISSING")
    log = root / "logs" / "sunstack.log"
    print("  log:", log.resolve() if log.exists() else "MISSING")
    if latest.exists():
        summary = latest / "summary.json"
        if summary.exists():
            print(summary.read_text())
        manifest = latest / "raw" / "manifest.json"
        if manifest.exists():
            print("\nOpen-Meteo manifest:")
            print(manifest.read_text())
    if photobiology:
        debug_photobiology(root)


def debug_photobiology(root: Path) -> None:
    """Expose every photobiology internal: versions, spectra, E_mel, doses."""
    import pandas as pd

    print("\nSunStack photobiology debug")
    try:
        from .photobiology import (
            ACTION_SPECTRUM_STEM,
            load_action_spectrum,
            model_metadata,
        )
        from .spectral import band_effective_weights, emulator_manifest

        for stem in (ACTION_SPECTRUM_STEM, "cie_erythema_reference",
                     "ipd_action_spectrum"):
            try:
                spec = load_action_spectrum(stem)
                print(f"  spectrum {stem}: tier={spec.tier} sha256={spec.sha256[:16]}... source={spec.source}")
            except (FileNotFoundError, ValueError) as exc:
                print(f"  spectrum {stem}: ERROR {exc}")
        w_uvb, w_uva = band_effective_weights()
        print(f"  Tier-C band weights: w_uvb={w_uvb:.6f} w_uva={w_uva:.6f}")
        print(f"  emulator: {emulator_manifest()}")
        print(f"  metadata: {model_metadata()}")
    except (ImportError, ValueError, RuntimeError) as exc:
        print(f"  photobiology core ERROR: {exc}")
    print(f"  global_reference: {config.GLOBAL_MELANOGENIC_REFERENCE_VERSION} "
          f"E_mel={config.GLOBAL_MELANOGENIC_REFERENCE_WM2} W/m^2")
    print(f"  tan_score_model={config.TAN_SCORE_MODEL_VERSION} "
          f"require_canonical={config.REQUIRE_CANONICAL_SPECTRUM}")
    latest = root / "latest"
    hourly = latest / "tables" / "tan_forecast_hourly.parquet"
    if hourly.exists():
        try:
            df = pd.read_parquet(hourly)
            cols = ["time", "melanogenic_effective_irradiance_wm2", "uv_index",
                    "uvi_openmeteo", "uvi_cams", "uvi_difference_percent",
                    "tan_score_absolute_0_100", "legacy_absolute_tan_score_55_30_15",
                    "erythemal_irradiance_wm2",
                    "pigment_darkening_effective_irradiance",
                    "tan_dose_1h_j_m2", "sed_1h",
                    "uva_dose_1h_j_m2", "uvb_dose_1h_j_m2",
                    "pigment_darkening_dose_1h_j_m2",
                    "spectral_backend",
                    "spectral_tier", "tan_score_model_version", "cams_cycle",
                    "tan_calibration_tier", "uv_input_disagree", "tan_forecast_confidence_0_100"]
            show = [c for c in cols if c in df.columns]
            print(f"  latest hourly photobiology columns present: {show}")
            missing = [c for c in cols if c not in df.columns]
            if missing:
                print(f"  MISSING columns (stale run?): {missing}")
            else:
                day = df.head(6).loc[:, show].to_string(index=False)
                print(day)
        except (OSError, ValueError) as exc:
            print(f"  hourly read ERROR: {exc}")
    else:
        print("  no latest hourly table")


def _publish_site(site: config.Site) -> None:
    """Commit + push one site's docs and data. Small atomic publishes."""
    import subprocess

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=False,
    )
    slug = site.slug
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    # Audit: the runner's checkout has uv-sync side effects (uv.lock churn)
    # that must never wedge publish. Reset tracked-only churn first.
    subprocess.run(["git", "checkout", "--", "uv.lock"], check=False)
    if slug == config.default_site().slug:
        subprocess.run(["git", "add", "docs", "-f", "data/calibration"], check=False)
    else:
        subprocess.run(
            [
                "git",
                "add",
                f"docs/sites/{slug}",
                "-f",
                f"data/sites/{slug}/calibration",
            ],
            check=False,
        )
    subprocess.run(["git", "checkout", "--", "uv.lock"], check=False)
    committed = subprocess.run(
        ["git", "commit", "-m", f"Scheduled run {slug} {stamp}"], check=False
    )
    _ = committed
    # Stash any regenerated-but-uncommitted files (other site's docs, run
    # state) so the rebase never wedges on "unstaged changes" between the two
    # per-site publishes. Restored right after, before the push.
    subprocess.run(["git", "stash", "push", "-m", f"publish-{slug}",
                    "--", "docs", "data"], check=False)
    # The site-refresh job also writes this site's data.json (it re-stamps
    # renderer_code_sha and nothing else). data.json is a single-line JSON
    # document, so any concurrent reskin edit conflicts with our freshly
    # exported payload, and `--rebase -X ours` resolves in favour of the
    # *upstream* side: git then reports "patch contents already upstream" and
    # silently drops the whole forecast payload from our commit. That is how
    # the default site stopped publishing fresh rows while the runner's own
    # tables were current. Keep our payload and re-assert it after the rebase.
    dest_data = (
        Path("docs") / "data.json"
        if slug == config.default_site().slug
        else Path("docs") / "sites" / slug / "data.json"
    )
    saved_payload = dest_data.read_bytes() if dest_data.exists() else None
    pulled = subprocess.run(["git", "pull", "--rebase", "-X", "ours"], check=False)
    if pulled.returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], check=False)
        second = subprocess.run(
            ["git", "pull", "--rebase", "-X", "theirs"], check=False
        )
        if second.returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], check=False)
            subprocess.run(["git", "stash", "pop"], check=False)
            raise RuntimeError(f"publish rebase failed for {slug}")
    subprocess.run(["git", "stash", "pop"], check=False)
    if saved_payload is not None and dest_data.read_bytes() != saved_payload:
        LOG.warning("Rebase dropped the %s payload; re-asserting the exported rows", slug)
        dest_data.write_bytes(saved_payload)
        subprocess.run(["git", "add", str(dest_data)], check=False)
        subprocess.run(["git", "commit", "--amend", "--no-edit"], check=False)
    pushed = subprocess.run(["git", "push"], check=False)
    if pushed.returncode != 0:
        raise RuntimeError(f"publish push failed for {slug}")


def run_one_site(
    root: Path,
    site: config.Site,
    strict: bool = True,
    skin_type: int | None = None,
    min_temp_f: float | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
    fresh: bool = True,
    force_cams: bool = False,
    auto_calibrate: bool = True,
    surface_slug: str = "unknown",
    surface_extent: str = "local",
    skin_tilt_deg: float | None = None,
    skin_azimuth_deg: float | None = None,
    surface_uva_reflectance: float | None = None,
    surface_uvb_reflectance: float | None = None,
) -> Path:
    """Run, export, and publish a single site. One site = one commit.

    Alternating run→publish per site (not run-all→publish-all) means a slow
    or failing second site can never take down the first site's fresh data.
    Cold (uncalibrated) sites are skipped with a warning — the
    location-calibrate workflow owns bootstrap, not the forecast job — so a
    new location can never wedge South Bend past the 60-minute timeout.
    Zero quality reduction by construction: identical code path per site,
    strict stays on, no fallback tiers, no skipped validations.
    """
    with config.site_lock():
        return _run_one_site_locked(
            root, site, strict, skin_type, min_temp_f, personal_mmd_j_m2,
            personal_mmd_basis, fresh, force_cams, auto_calibrate, surface_slug,
            surface_extent, skin_tilt_deg, skin_azimuth_deg,
            surface_uva_reflectance, surface_uvb_reflectance,
        )


def _run_one_site_locked(
    root: Path,
    site: config.Site,
    strict: bool = True,
    skin_type: int | None = None,
    min_temp_f: float | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
    fresh: bool = True,
    force_cams: bool = False,
    auto_calibrate: bool = True,
    surface_slug: str = "unknown",
    surface_extent: str = "local",
    skin_tilt_deg: float | None = None,
    skin_azimuth_deg: float | None = None,
    surface_uva_reflectance: float | None = None,
    surface_uvb_reflectance: float | None = None,
) -> Path:
    from .output import export_static_site

    _, calibration_dir, _ = _calibration_paths(
        root, site.slug if site.slug != config.default_site().slug else None
    )
    required = [
        calibration_dir / "uva_uvb_models.joblib",
        calibration_dir / "local_reference.parquet",
    ]
    if not all(p.exists() for p in required):
        LOG.warning(
            "Skipping %s: calibration missing (%s). Awaiting location-calibrate workflow; scores unchanged elsewhere.",
            site.slug,
            calibration_dir,
        )
        raise _SiteSkipped(f"calibration missing for {site.slug}")
    run_dir = run_live(
        root,
        auto_calibrate=auto_calibrate,
        force_cams=force_cams,
        strict=strict,
        skin_type=skin_type,
        min_temp_f=min_temp_f,
        personal_mmd_j_m2=personal_mmd_j_m2,
        personal_mmd_basis=personal_mmd_basis,
        fresh=fresh,
        site=site,
        surface_slug=surface_slug,
        surface_extent=surface_extent,
        skin_tilt_deg=skin_tilt_deg,
        skin_azimuth_deg=skin_azimuth_deg,
        surface_uva_reflectance=surface_uva_reflectance,
        surface_uvb_reflectance=surface_uvb_reflectance,
    )
    dest = (
        Path("docs")
        if site.slug == config.default_site().slug
        else Path("docs") / "sites" / site.slug
    )
    # Export reads the freshly written site run from the data root.
    info = export_static_site(
        root,
        dest,
        skin_type=skin_type,
        min_temp_f=min_temp_f or 50.0,
        site_slug=site.slug,
    )
    LOG.info("Site %s exported: %s events", site.slug, info["events"])
    # Gate 3 (serialized artifact): validate the published data.json AS
    # CONSUMERS SEE IT before any commit/publish step (contract §25.2). In
    # strict mode a fatal science-contract failure aborts publication — the
    # run tables stay on disk for inspection but never ship. This is the only
    # gate that reads the serialized payload; Gates 1-2 validate frames.
    if strict:
        import importlib.util as _importlib_util
        from pathlib import Path as _Path

        # Loaded by path, not package import: scripts/validate_published_artifact
        # imports sunstack.photobiology at call time, so a top-level
        # `from scripts... import` would close an import cycle (cli ->
        # scripts -> sunstack) that basedpyright flags and that risks
        # partially-initialized modules at runtime.
        _spec = _importlib_util.spec_from_file_location(
            "validate_published_artifact",
            _Path(__file__).resolve().parent.parent.parent
            / "scripts" / "validate_published_artifact.py",
        )
        assert _spec is not None and _spec.loader is not None
        _validator = _importlib_util.module_from_spec(_spec)
        _spec.loader.exec_module(_validator)
        _result = _validator.validate_artifact(_Path(dest) / "data.json")
        _failures = _result.get("failures")
        assert isinstance(_failures, dict)
        _failed = {k: v for k, v in _failures.items() if v}
        for _check, _msgs in _failed.items():
            assert isinstance(_msgs, list)
            for _msg in _msgs:
                LOG.error("[artifact %s] %s", _check, _msg)
        if not _result.get("passed"):
            raise DataValidationError(
                f"Serialized artifact validation failed for {site.slug}: "
                + "; ".join(f"{k}: {len(v)}" for k, v in _failed.items()
                            if isinstance(v, list))
            )
    _publish_site(site)
    return run_dir


def _run_all_sites(
    root: Path,
    strict: bool = True,
    skin_type: int | None = None,
    min_temp: float | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
    fresh: bool = True,
    force_cams: bool = False,
    auto_calibrate: bool = True,
    only_slug: str | None = None,
    surface_slug: str = "unknown",
    surface_extent: str = "local",
    skin_tilt_deg: float | None = None,
    skin_azimuth_deg: float | None = None,
    surface_uva_reflectance: float | None = None,
    surface_uvb_reflectance: float | None = None,
) -> None:
    sites = config.active_sites()
    if only_slug:
        sites = [s for s in sites if s.slug == only_slug]
        if not sites:
            raise DataValidationError(f"unknown site slug: {only_slug}")
    for site in sites:
        try:
            run_one_site(
                root,
                site,
                strict=strict,
                skin_type=skin_type,
                min_temp_f=min_temp,
                personal_mmd_j_m2=personal_mmd_j_m2,
                personal_mmd_basis=personal_mmd_basis,
                fresh=fresh,
                force_cams=force_cams,
                auto_calibrate=auto_calibrate,
                surface_slug=surface_slug,
                surface_extent=surface_extent,
                skin_tilt_deg=skin_tilt_deg,
                skin_azimuth_deg=skin_azimuth_deg,
                surface_uva_reflectance=surface_uva_reflectance,
                surface_uvb_reflectance=surface_uvb_reflectance,
            )
        except _SiteSkipped as exc:
            LOG.warning("Site skipped, continuing to next site: %s", exc)


class _SiteSkipped(RuntimeError):
    """A site was deliberately skipped (cold calibration); not a failure."""


def _build_parser() -> argparse.ArgumentParser:
    from .surface import SURFACE_EXTENT_MODES

    parser = argparse.ArgumentParser(
        description="SunStack: calibrated absolute/local TanScore + outdoor opportunity UI"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=[
            "run",
            "setup",
            "bootstrap",
            "ui",
            "export",
            "reskin",
            "doctor",
            "debug",
            "show-config",
        ],
    )
    parser.add_argument("--out", default="data", help="Repository-local output root")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refetch/rebuild historical calibration source data",
    )
    parser.add_argument("--skip-cams-history", action="store_true")
    parser.add_argument("--no-auto-calibrate", action="store_true")
    parser.add_argument("--force-cams", action="store_true")
    parser.add_argument(
        "--allow-degraded",
        action="store_true",
        help="Continue without critical/full-tier sources; errors remain visible",
    )
    parser.add_argument(
        "--skin-type",
        type=int,
        choices=range(1, 7),
        default=None,
        help="Optional Fitzpatrick I-VI context",
    )
    surface_context_help = (
        "Skin-plane context only; ranking stays environmental_horizontal "
        "fixed-duration dose. Export and reskin ignore this setting."
    )
    parser.add_argument(
        "--surface",
        default="unknown",
        metavar="SLUG",
        help=f"Local surface material slug. {surface_context_help}",
    )
    parser.add_argument(
        "--surface-extent",
        default="local",
        choices=SURFACE_EXTENT_MODES,
        help=f"Surface extent mode. {surface_context_help}",
    )
    parser.add_argument(
        "--skin-tilt-deg",
        type=float,
        default=None,
        help=f"Skin-plane tilt in degrees (0-180; default from config). {surface_context_help}",
    )
    parser.add_argument(
        "--skin-azimuth-deg",
        type=float,
        default=None,
        help=f"Skin-plane azimuth in degrees (0-360; default from config). {surface_context_help}",
    )
    parser.add_argument(
        "--surface-uva-reflectance",
        type=float,
        default=None,
        help=f"Custom surface UVA reflectance [0,1]; requires --surface custom. {surface_context_help}",
    )
    parser.add_argument(
        "--surface-uvb-reflectance",
        type=float,
        default=None,
        help=f"Custom surface UVB reflectance [0,1]; requires --surface custom. {surface_context_help}",
    )
    parser.add_argument(
        "--personal-mmd",
        type=float,
        default=None,
        help="Optional measured/estimated personal MMD in melanogenic-effective "
             "J/m^2 (compatible action-weighted system only); enables "
             "personal_mmd_fraction without touching environmental physics",
    )
    parser.add_argument(
        "--personal-mmd-basis",
        default=None,
        choices=["SUNSTACK_EFFECTIVE_DOSE_MEASURED", "SOURCE_SPECTRUM_MEASURED",
                 "OBJECTIVE_ESTIMATE", "COARSE_ESTIMATE"],
        help="Provenance label for --personal-mmd (Fitzpatrick-only estimates "
             "stay COARSE_ESTIMATE with wide uncertainty)",
    )
    parser.add_argument(
        "--min-temp",
        type=float,
        default=None,
        help="Outdoor tanning temperature floor in F",
    )
    parser.add_argument(
        "--cached-live",
        action="store_true",
        help="Allow cached live Open-Meteo responses (default is real fresh requests)",
    )
    parser.add_argument(
        "--probe", action="store_true", help="Doctor: make real live API probe requests"
    )
    parser.add_argument(
        "--photobiology",
        action="store_true",
        help="Debug: include full photobiology internals (spectra, E_mel, doses, tiers)",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--site",
        default=None,
        help="Run for one location slug (default: all enabled sites)",
    )
    parser.add_argument(
        "--site-dir",
        default="docs",
        help="Static site output dir for the export command",
    )
    return parser


def main() -> None:
    from argparse import Namespace

    parser = _build_parser()
    args: Namespace = parser.parse_args()
    if args.personal_mmd is not None and not args.personal_mmd_basis:
        # Same rule as the dashboard/API 400: an MMD without an explicit
        # basis would publish fractions with implied-but-absent provenance.
        parser.error("--personal-mmd requires --personal-mmd-basis "
                     "(SUNSTACK_EFFECTIVE_DOSE_MEASURED, SOURCE_SPECTRUM_MEASURED, OBJECTIVE_ESTIMATE, or COARSE_ESTIMATE)")
    surface_slug = args.surface.strip().lower()
    if surface_slug == "custom":
        if (
            args.surface_uva_reflectance is None
            or args.surface_uvb_reflectance is None
        ):
            parser.error(
                "--surface custom requires --surface-uva-reflectance "
                "and --surface-uvb-reflectance"
            )
    elif (
        args.surface_uva_reflectance is not None
        or args.surface_uvb_reflectance is not None
    ):
        parser.error(
            "--surface-uva-reflectance and --surface-uvb-reflectance "
            "require --surface custom"
        )
    from .surface import resolve_surface

    try:
        args.surface = resolve_surface(
            surface_slug,
            args.surface_uva_reflectance,
            args.surface_uvb_reflectance,
        ).slug
    except ValueError as exc:
        parser.error(str(exc))
    if args.skin_tilt_deg is not None and not 0 <= args.skin_tilt_deg <= 180:
        parser.error("--skin-tilt-deg must be in [0, 180]")
    if args.skin_azimuth_deg is not None:
        if not 0 <= args.skin_azimuth_deg <= 360:
            parser.error("--skin-azimuth-deg must be in [0, 360]")
        if args.skin_azimuth_deg == 360:
            args.skin_azimuth_deg = 0.0
    root = Path(args.out)
    _setup_logging(root, debug=args.verbose)
    strict = config.STRICT_DEFAULT and not args.allow_degraded
    try:
        sites = config.active_sites()
        if args.site:
            sites = [s for s in sites if s.slug == args.site]
            if not sites:
                raise DataValidationError(f"unknown site slug: {args.site}")
        if args.command == "show-config":
            _print_config()
        elif args.command == "doctor":
            if not doctor(root, probe=args.probe):
                sys.exit(2)
        elif args.command == "debug":
            debug_report(root, photobiology=args.photobiology)
        elif args.command in {"setup", "bootstrap"}:
            for site in sites:
                bootstrap(
                    root,
                    force=args.force,
                    skip_cams_history=args.skip_cams_history,
                    strict=strict,
                    site=site,
                )
            if args.command == "setup":
                for site in sites:
                    run_live(
                        root,
                        auto_calibrate=False,
                        force_cams=True,
                        strict=strict,
                        skin_type=args.skin_type,
                        min_temp_f=args.min_temp,
                        fresh=True,
                        site=site,
                        personal_mmd_j_m2=args.personal_mmd,
                        personal_mmd_basis=args.personal_mmd_basis,
                        surface_slug=args.surface,
                        surface_extent=args.surface_extent,
                        skin_tilt_deg=args.skin_tilt_deg,
                        skin_azimuth_deg=args.skin_azimuth_deg,
                        surface_uva_reflectance=args.surface_uva_reflectance,
                        surface_uvb_reflectance=args.surface_uvb_reflectance,
                    )
                print("\nSetup complete. Launch the dashboard with: uv run sunstack ui")
        elif args.command == "ui":
            from .ui import serve

            serve(
                root, host=args.host, port=args.port, open_browser=not args.no_browser,
                run_live_fn=run_live,
            )
        elif args.command == "export":
            from .output import export_static_site

            for site in sites:
                dest = (
                    Path(args.site_dir)
                    if site.slug == config.default_site().slug
                    else Path(args.site_dir) / "sites" / site.slug
                )
                info = export_static_site(
                    root,
                    dest,
                    skin_type=args.skin_type,
                    min_temp_f=args.min_temp or 50.0,
                    site_slug=site.slug,
                    personal_mmd_j_m2=args.personal_mmd,
                    personal_mmd_basis=args.personal_mmd_basis,
                )
                print(
                    f"Static site {site.slug}: {info['out_dir']} ({info['hourly_rows']} hourly, {info['half_rows']} half-hour, {info['days']} days, {info['events']} events)"
                )
        elif args.command == "reskin":
            from .output import reskin_static_dir

            for site in sites:
                page = (
                    Path(args.site_dir)
                    if site.slug == config.default_site().slug
                    else Path(args.site_dir) / "sites" / site.slug
                )
                info = reskin_static_dir(page, site.slug)
                print(
                    f"Reskinned {site.slug}: {info['page']} (run {info['run']}, build {info['build_sha']})"
                )
        else:
            _run_all_sites(
                root,
                strict=strict,
                skin_type=args.skin_type,
                min_temp=args.min_temp,
                personal_mmd_j_m2=args.personal_mmd,
                personal_mmd_basis=args.personal_mmd_basis,
                fresh=not args.cached_live,
                force_cams=args.force_cams,
                auto_calibrate=not args.no_auto_calibrate,
                only_slug=args.site,
                surface_slug=args.surface,
                surface_extent=args.surface_extent,
                skin_tilt_deg=args.skin_tilt_deg,
                skin_azimuth_deg=args.skin_azimuth_deg,
                surface_uva_reflectance=args.surface_uva_reflectance,
                surface_uvb_reflectance=args.surface_uvb_reflectance,
            )
    except Exception as exc:
        LOG.exception("FATAL")
        print(f"\nSUNSTACK FATAL: {exc}", file=sys.stderr)
        print(
            f"Full debug log: {(root / 'logs' / 'sunstack.log').resolve()}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
