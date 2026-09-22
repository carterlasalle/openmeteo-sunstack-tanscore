from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .calibrate import (
    build_local_reference,
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
    build_30min_forecast,
    build_daily_summary,
)
from .output import write_frame
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
    sh.setFormatter(fmt); sh.setLevel(logging.DEBUG if debug else logging.INFO)
    fh = logging.FileHandler(log_dir / "sunstack.log", encoding="utf-8")
    fh.setFormatter(fmt); fh.setLevel(logging.DEBUG)
    LOG.addHandler(sh); LOG.addHandler(fh)


def _print_config() -> None:
    for site in config.active_sites():
        mark = " (default)" if site.default else ""
        print(f"Location {site.slug}{mark}: {site.lat}, {site.lon} ({site.timezone})")
    print(f"Strict default: {config.STRICT_DEFAULT}; direct CAMS required: {config.REQUIRE_DIRECT_CAMS}")
    print(f"Outdoor temperature floor: {config.MIN_TAN_TEMP_F:.0f}F; hard heat ceiling: {config.MAX_TAN_TEMP_F:.0f}F")
    print("Overall score weights:", config.OVERALL_SCORE_WEIGHTS, f"(absolute headroom +{config.OVERALL_ABSOLUTE_HEADROOM:.0f})")
    print("\nDeterministic models:")
    for x in config.DETERMINISTIC_MODELS: print("  -", x)
    print("\nFull-member ensembles:")
    for x in config.ENSEMBLE_MEMBER_MODELS: print("  -", x)
    print("\nEnsemble mean+spread:")
    for x in config.ENSEMBLE_MEAN_MODELS: print("  -", x)
    print(f"\nNASA POWER calibration: {config.NASA_POWER_START} -> {config.NASA_POWER_END}")
    print(f"Open-Meteo historical: {config.OPENMETEO_HISTORY_START} -> {config.OPENMETEO_HISTORY_END}")
    print(f"CAMS EAC4: {config.CAMS_EAC4_START_YEAR} -> {config.CAMS_EAC4_END_YEAR}")
    print(f"ADS/CAMS credentials detected: {cds_credentials_present()}")


def _calibration_paths(root: Path, site_slug: str | None = None) -> tuple[Path, Path, Path]:
    """Calibration dirs, namespaced per location. The default site keeps the legacy layout."""
    current = config.current_site()
    slug = site_slug or (current.slug if current is not None else None)
    site_root = root if not slug or slug == config.default_site().slug else root / "sites" / slug
    return site_root / "calibration_sources", site_root / "calibration", Path(".cache") / "sunstack"


def calibration_paths(root: Path, site_slug: str | None = None) -> tuple[Path, Path, Path]:
    """Public alias for automation (scripts, CI) that must not touch privates."""
    return _calibration_paths(root, site_slug)


def bootstrap(root: Path, force: bool = False, skip_cams_history: bool = False, strict: bool = True,
              site: config.Site | None = None) -> dict[str, object]:
    with config.use_site(site) if site is not None else nullcontext():
        return _bootstrap_inner(root, force=force, skip_cams_history=skip_cams_history, strict=strict)


def _bootstrap_inner(root: Path, force: bool = False, skip_cams_history: bool = False, strict: bool = True) -> dict[str, object]:
    source_dir, calibration_dir, cache_dir = _calibration_paths(root)
    if strict and config.REQUIRE_DIRECT_CAMS and not skip_cams_history and not cds_credentials_present():
        raise DataValidationError(
            "STRICT BOOTSTRAP requires Copernicus ADS credentials for CAMS EAC4. "
            "Configure ~/.cdsapirc (or CDSAPI_URL/CDSAPI_KEY), then rerun. "
            "Use --allow-degraded only if you intentionally accept a lower calibration tier."
        )

    LOG.info("[1/5] NASA POWER hourly UVA/UVB history — real API requests for uncached years")
    nasa = fetch_nasa_power_history(source_dir, cache_dir, force=force)
    LOG.info("NASA rows: %s", f"{len(nasa):,}")
    if strict and len(nasa) < 50_000:
        raise DataValidationError(f"NASA POWER history insufficient: only {len(nasa):,} rows")

    LOG.info("[2/5] Open-Meteo historical forecast archive")
    om_hist = fetch_openmeteo_historical_forecast(source_dir, cache_dir, force=force)
    LOG.info("Open-Meteo historical rows: %s", f"{len(om_hist):,}")
    if strict and len(om_hist) < 5_000:
        raise DataValidationError(f"Open-Meteo historical archive insufficient: only {len(om_hist):,} rows")

    LOG.info("[3/5] Open-Meteo Previous Runs lead-time archive")
    previous = fetch_openmeteo_previous_runs(source_dir, cache_dir, force=force)
    LOG.info("Previous-run rows: %s", f"{len(previous):,}")
    if strict and previous.empty:
        raise DataValidationError("Open-Meteo Previous Runs returned no data; cannot calibrate lead-time skill")

    cams_eac4 = pd.DataFrame()
    if not skip_cams_history and cds_credentials_present():
        LOG.info("[4/5] CAMS EAC4 aerosol/ozone history via ADS")
        cams_eac4 = fetch_cams_eac4_history(source_dir, force=force)
        LOG.info("CAMS EAC4 rows: %s", f"{len(cams_eac4):,}")
        if strict and cams_eac4.empty:
            raise DataValidationError("CAMS EAC4 retrieval produced no usable rows")
    else:
        LOG.warning("[4/5] CAMS EAC4 skipped — degraded calibration tier")

    LOG.info("[5/5] Build calibration dataset, UVA/UVB models, local climatology, model skill")
    training = build_training_dataset(nasa, om_hist, cams_eac4, calibration_dir)
    model_training = prepare_nasa_training(nasa, cams_eac4)
    if model_training.empty:
        raise DataValidationError("NASA/CAMS model training table is empty")
    model_metrics = train_uv_models(model_training, calibration_dir)
    local_ref = build_local_reference(model_training, calibration_dir)
    skill = compute_openmeteo_model_skill(previous, om_hist, calibration_dir)
    if strict and local_ref.empty:
        raise DataValidationError("Local TanScore reference climatology is empty")

    summary: dict[str, object] = {
        "created_at": datetime.now().astimezone().isoformat(), "coordinates": [config.LATITUDE, config.LONGITUDE],
        "timezone": config.TIMEZONE, "strict": strict, "nasa_rows": len(nasa),
        "openmeteo_historical_rows": len(om_hist), "previous_runs_rows": len(previous),
        "cams_eac4_rows": len(cams_eac4), "training_rows": len(training),
        "local_reference_rows": len(local_ref), "skill_rows": len(skill),
        "direct_cams_credentials": cds_credentials_present(), "model_metrics": model_metrics,
        "absolute_score_definition": {"uvi_reference": config.ABSOLUTE_UVI_REFERENCE, "uva_reference_wm2": config.ABSOLUTE_UVA_REFERENCE_WM2, "weights": config.ABSOLUTE_TAN_WEIGHTS},
    }
    (calibration_dir / "calibration_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    LOG.info("Calibration written to %s", calibration_dir)
    return summary


def ensure_calibration(root: Path, auto: bool = True, strict: bool = True,
                       site: config.Site | None = None) -> None:
    if strict and config.REQUIRE_DIRECT_CAMS and not cds_credentials_present():
        raise DataValidationError("Strict mode requires Copernicus ADS credentials before calibration/live scoring. Configure ~/.cdsapirc first, or explicitly use --allow-degraded.")
    _, calibration_dir, _ = _calibration_paths(root, site.slug if site else None)
    required = [calibration_dir / "uva_uvb_models.joblib", calibration_dir / "local_reference.parquet"]
    if all(p.exists() for p in required): return
    if not auto:
        if strict: raise DataValidationError("Calibration missing. Run `uv run sunstack setup` or `uv run sunstack bootstrap`.")
        LOG.warning("Calibration missing; lower-accuracy fallback may be used")
        return
    LOG.info("No calibration found — bootstrapping automatically")
    bootstrap(root, force=False, skip_cams_history=not cds_credentials_present(), strict=strict, site=site)

def _issue_dicts(issues: list[ValidationIssue]):
    return [{"severity": i.severity, "source": i.source, "message": i.message} for i in issues]


def run_live(root: Path, auto_calibrate: bool = True, force_cams: bool = False, strict: bool = True,
             skin_type: int | None = None, min_temp_f: float | None = None, fresh: bool = True,
             site: config.Site | None = None) -> Path:
    if site is not None:
        with config.use_site(site):
            return _run_live_inner(root, auto_calibrate=auto_calibrate, force_cams=force_cams, strict=strict,
                                   skin_type=skin_type, min_temp_f=min_temp_f, fresh=fresh, site=site)
    return _run_live_inner(root, auto_calibrate=auto_calibrate, force_cams=force_cams, strict=strict,
                           skin_type=skin_type, min_temp_f=min_temp_f, fresh=fresh)


def _run_live_inner(root: Path, auto_calibrate: bool = True, force_cams: bool = False, strict: bool = True,
                    skin_type: int | None = None, min_temp_f: float | None = None, fresh: bool = True,
                    site: config.Site | None = None) -> Path:
    site_root = root if site is None or site.slug == config.default_site().slug else root / "sites" / site.slug
    ensure_calibration(root, auto=auto_calibrate, strict=strict, site=site)
    _, calibration_dir, cache_dir = _calibration_paths(root, site.slug if site else None)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_dir = site_root / "runs" / stamp; raw_dir = run_dir / "raw"; table_dir = run_dir / "tables"
    run_dir.mkdir(parents=True, exist_ok=True)

    LOG.info("Fetching live Open-Meteo sources%s", " (cache bypassed)" if fresh else "")
    results = fetch_all(cache_dir, fresh=fresh)
    write_raw(results, raw_dir)
    source_issues = validate_live_sources(results, strict=strict)
    for issue in source_issues:
        getattr(LOG, "error" if issue.severity == "ERROR" else "warning")("[%s] %s", issue.source, issue.message)
    if strict: raise_on_errors(source_issues, "Required Open-Meteo live sources failed")
    successes = [r for r in results if r.payload is not None]
    LOG.info("Fetched %d/%d Open-Meteo feeds successfully", len(successes), len(results))

    det_hourly, det_daily, current = normalize_deterministic(results)
    profiles = normalize_profiles(results); hrrr15 = normalize_hrrr_15min(results)
    members = normalize_ensemble_members(results); ens_mean = normalize_ensemble_mean(results); air = normalize_air_quality(results)
    det_hourly = add_solar_diagnostics(det_hourly, 3600); members = add_solar_diagnostics(members, 3600)
    model_col = det_hourly["model"] if "model" in det_hourly.columns else pd.Series(index=det_hourly.index, dtype=object)
    best = det_hourly.loc[model_col == "best_match"].copy() if not det_hourly.empty else pd.DataFrame()
    hrrr15 = add_solar_diagnostics(enrich_15min_with_hourly_uv(hrrr15, best), 900)
    consensus = deterministic_consensus(det_hourly); ensemble_probs = ensemble_probabilities(members)
    best_air = merge_air_quality(best, air); sun_windows = best_windows(best_air, ensemble_probs, consensus)

    if strict and config.REQUIRE_DIRECT_CAMS and not cds_credentials_present():
        raise DataValidationError("Direct CAMS spectral forecast is required in strict mode, but ADS credentials are missing. Configure ~/.cdsapirc, then rerun.")
    LOG.info("Fetching direct CAMS spectral forecast via ADS")
    cams_direct = fetch_cams_forecast(run_dir, force=force_cams, raw_root=root) if cds_credentials_present() else pd.DataFrame()
    cams_issues = validate_cams_direct(cams_direct) if cds_credentials_present() else [ValidationIssue("ERROR", "cams_direct_ads", "ADS credentials unavailable")]
    for issue in cams_issues:
        getattr(LOG, "error" if issue.severity == "ERROR" else "warning")("[%s] %s", issue.source, issue.message)
    if strict and config.REQUIRE_DIRECT_CAMS:
        raise_on_errors(cams_issues, "Direct CAMS spectral validation failed")

    tan_hourly = score_forecast(best_air, calibration_dir, cams_direct, sun_windows)
    tan_hourly = apply_outdoor_feasibility(tan_hourly, min_temp_f)
    tan_hourly = attach_fitzpatrick(tan_hourly, skin_type)
    score_issues = validate_scored_hourly(tan_hourly)
    for issue in score_issues:
        getattr(LOG, "error" if issue.severity == "ERROR" else "warning")("[%s] %s", issue.source, issue.message)
    if strict: raise_on_errors(score_issues, "TanScore output validation failed")

    tan_30 = build_30min_forecast(tan_hourly, hrrr15)
    tan_30 = attach_fitzpatrick(tan_30, skin_type)
    daily_tan = build_daily_summary(tan_30)
    tan_windows = best_tan_windows(tan_hourly)

    for frame, name in [
        (det_hourly,"deterministic_hourly"),(det_daily,"deterministic_daily"),(current,"current_best_match"),
        (profiles,"deep_pressure_profiles"),(hrrr15,"hrrr_native_15min"),(members,"ensemble_members_long"),
        (ens_mean,"ensemble_mean_spread"),(ensemble_probs,"ensemble_probabilities"),(consensus,"deterministic_consensus"),
        (air,"air_quality_aerosols"),(cams_direct,"cams_direct_forecast"),(best_air,"best_match_enriched"),
        (sun_windows,"best_sun_windows"),(tan_hourly,"tan_forecast_hourly"),(tan_30,"tan_forecast_30min"),
        (daily_tan,"tan_daily_summary"),(tan_windows,"best_tan_windows")]:
        write_frame(frame, table_dir, name)

    source_health = [{
        "name": r.name, "ok": r.payload is not None, "error": r.error, "elapsed_ms": r.elapsed_ms,
        "status_code": r.status_code, "from_cache": r.from_cache, "endpoint": r.endpoint,
    } for r in results]
    source_health.append({"name":"cams_direct_ads","ok":not cams_direct.empty,"error":None if not cams_direct.empty else "empty/not available","elapsed_ms":None,"status_code":None,"from_cache":False,"endpoint":"Copernicus ADS"})
    summary = {
        "run": stamp, "created_at": datetime.now().astimezone().isoformat(), "coordinates": [config.LATITUDE, config.LONGITUDE],
        "timezone": config.TIMEZONE, "site_slug": site.slug if site else config.default_site().slug,
        "site_name": site.name if site else config.default_site().name,
        "strict": strict, "skin_type": skin_type,
        "min_tan_temperature_f": float(config.MIN_TAN_TEMP_F if min_temp_f is None else min_temp_f),
        "successful_openmeteo_feeds": len(successes), "total_openmeteo_feeds": len(results),
        "direct_cams_used": not cams_direct.empty, "calibration_available": (calibration_dir / "uva_uvb_models.joblib").exists(),
        "source_health": source_health, "validation_issues": _issue_dicts(source_issues + cams_issues + score_issues),
        "score_semantics": {
            "absolute": "global physical melanogenic intensity; not locally normalized",
            "local": "historical local seasonal percentile",
            "atmospheric": "local percentile at similar season and solar elevation",
            "confidence": "forecast/model confidence",
            "overall": "weighted geometric merge of the four components, absolute-dominant/capped, then multiplied by outdoor feasibility",
            "overall_weights": config.OVERALL_SCORE_WEIGHTS,
        },
        "hard_blocks": {"active_rain": True, "active_snow": True, "thunderstorm": True, "temperature_below_f": float(config.MIN_TAN_TEMP_F if min_temp_f is None else min_temp_f), "temperature_at_or_above_f": config.MAX_TAN_TEMP_F},
        "rows": {"tan_forecast_hourly":len(tan_hourly),"tan_forecast_30min":len(tan_30),"tan_daily_summary":len(daily_tan),"cams_direct_forecast":len(cams_direct)},
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    # Single latest-run pointer: a directory copy. (A former LATEST marker file
    # is gone: on case-insensitive filesystems it collides with this directory.)
    latest = site_root / "latest"
    if latest.is_symlink() or latest.is_file(): latest.unlink()
    elif latest.exists(): shutil.rmtree(latest)
    _latest_copy: Path = shutil.copytree(run_dir, latest)

    LOG.info("Run written to %s", run_dir)
    if not daily_tan.empty:
        cols=[c for c in ["date","day_status","day_overall_peak_0_100","day_absolute_peak_0_100","day_local_peak_0_100","day_atmospheric_peak_0_100","day_confidence_at_peak_0_100","best_window_start","best_window_end","best_hour_start"] if c in daily_tan]
        print("\nBest tanning times by day:")
        print(daily_tan[cols].to_string(index=False))
    if not tan_windows.empty:
        cols=[c for c in ["time","overall_tan_opportunity_0_100","tan_score_absolute_0_100","local_tan_score_0_100","atmospheric_quality_percentile_0_100","tan_forecast_confidence_0_100","outdoor_feasibility_0_100","outdoor_block_reason","uv_index","predicted_uva_wm2"] if c in tan_windows]
        print("\nTop hourly tanning opportunities:")
        print(tan_windows[cols].head(15).to_string(index=False))
    return run_dir


def doctor(root: Path, probe: bool = False) -> bool:
    _, calibration_dir, _ = _calibration_paths(root)
    checks = {
        "ADS/CAMS credentials": cds_credentials_present(),
        "UVA/UVB model": (calibration_dir / "uva_uvb_models.joblib").exists(),
        "local climatology": (calibration_dir / "local_reference.parquet").exists(),
        "model skill table": (calibration_dir / "openmeteo_model_skill.parquet").exists(),
    }
    print("SunStack doctor")
    print(f"  location: {config.LATITUDE}, {config.LONGITUDE} ({config.TIMEZONE})")
    for k,v in checks.items(): print(f"  {k}: {'OK' if v else 'MISSING'}")
    ok = all(checks.values()) if config.REQUIRE_DIRECT_CAMS else all(v for k,v in checks.items() if k != "ADS/CAMS credentials")
    if probe:
        print("\nProbing live Open-Meteo APIs (3 tiny parallel probes)...", flush=True)
        results = probe_live()
        for r in results: print(f"  {'OK' if r.payload is not None else 'FAIL':4} {r.name:48} {r.elapsed_ms or 0:8.1f} ms {r.error or ''}", flush=True)
        if any(r.payload is None for r in results): ok = False
    if not cds_credentials_present() and config.REQUIRE_DIRECT_CAMS:
        print("\nCAMS setup required: create a Copernicus ADS account, accept dataset terms, and configure ~/.cdsapirc.")
    return ok


def debug_report(root: Path) -> None:
    print("SunStack debug")
    latest = root / "latest"
    print("  latest:", latest.resolve() if latest.exists() else "MISSING")
    log = root / "logs" / "sunstack.log"
    print("  log:", log.resolve() if log.exists() else "MISSING")
    if latest.exists():
        summary = latest / "summary.json"
        if summary.exists(): print(summary.read_text())
        manifest = latest / "raw" / "manifest.json"
        if manifest.exists():
            print("\nOpen-Meteo manifest:")
            print(manifest.read_text())


def main() -> None:
    from argparse import Namespace

    parser = argparse.ArgumentParser(description="SunStack: calibrated absolute/local TanScore + outdoor opportunity UI")
    parser.add_argument("command", nargs="?", default="run", choices=["run","setup","bootstrap","ui","export","doctor","debug","show-config"])
    parser.add_argument("--out", default="data", help="Repository-local output root")
    parser.add_argument("--force", action="store_true", help="Refetch/rebuild historical calibration source data")
    parser.add_argument("--skip-cams-history", action="store_true")
    parser.add_argument("--no-auto-calibrate", action="store_true")
    parser.add_argument("--force-cams", action="store_true")
    parser.add_argument("--allow-degraded", action="store_true", help="Continue without critical/full-tier sources; errors remain visible")
    parser.add_argument("--skin-type", type=int, choices=range(1,7), default=None, help="Optional Fitzpatrick I-VI context")
    parser.add_argument("--min-temp", type=float, default=None, help="Outdoor tanning temperature floor in F")
    parser.add_argument("--cached-live", action="store_true", help="Allow cached live Open-Meteo responses (default is real fresh requests)")
    parser.add_argument("--probe", action="store_true", help="Doctor: make real live API probe requests")
    parser.add_argument("--host", default=None); parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true"); parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--site", default=None, help="Run for one location slug (default: all enabled sites)")
    parser.add_argument("--site-dir", default="docs", help="Static site output dir for the export command")
    args: Namespace = parser.parse_args()
    root = Path(args.out)
    _setup_logging(root, debug=args.verbose)
    strict = config.STRICT_DEFAULT and not args.allow_degraded
    try:
        sites = config.active_sites()
        if args.site:
            sites = [s for s in sites if s.slug == args.site]
            if not sites:
                raise DataValidationError(f"unknown site slug: {args.site}")
        if args.command == "show-config": _print_config()
        elif args.command == "doctor":
            if not doctor(root, probe=args.probe): sys.exit(2)
        elif args.command == "debug": debug_report(root)
        elif args.command in {"setup","bootstrap"}:
            for site in sites:
                bootstrap(root, force=args.force, skip_cams_history=args.skip_cams_history, strict=strict, site=site)
            if args.command == "setup":
                for site in sites:
                    run_live(root, auto_calibrate=False, force_cams=True, strict=strict, skin_type=args.skin_type, min_temp_f=args.min_temp, fresh=True, site=site)
                print("\nSetup complete. Launch the dashboard with: uv run sunstack ui")
        elif args.command == "ui":
            from .ui import serve
            serve(root, host=args.host, port=args.port, open_browser=not args.no_browser)
        elif args.command == "export":
            from .output import export_static_site
            for site in sites:
                dest = Path(args.site_dir) if site.slug == config.default_site().slug else Path(args.site_dir) / "sites" / site.slug
                info = export_static_site(root, dest, skin_type=args.skin_type, min_temp_f=args.min_temp or 50.0, site_slug=site.slug)
                print(f"Static site {site.slug}: {info['out_dir']} ({info['hourly_rows']} hourly, {info['half_rows']} half-hour, {info['days']} days, {info['events']} events)")
        else:
            for site in sites:
                run_live(root, auto_calibrate=not args.no_auto_calibrate, force_cams=args.force_cams, strict=strict, skin_type=args.skin_type, min_temp_f=args.min_temp, fresh=not args.cached_live, site=site)
    except Exception as exc:
        LOG.exception("FATAL")
        print(f"\nSUNSTACK FATAL: {exc}", file=sys.stderr)
        print(f"Full debug log: {(root / 'logs' / 'sunstack.log').resolve()}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__": main()
