"""Offline end-to-end v4 re-score of a committed latest run (no network).

Feeds a site's committed best_match_enriched + cams_direct_forecast tables
through the CURRENT v4 pipeline (score_forecast -> feasibility -> interval
doses -> 30-min -> daily summary -> calendar/UI payload builders) and writes
a verification report. Proves the v4 path works on real forecast data while
live runs are unavailable. Outputs go to a scratch dir; committed run data
is never overwritten.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")

from sunstack import config  # noqa: E402
from sunstack.doses import add_interval_doses  # noqa: E402
from sunstack.opportunity import (  # noqa: E402
    apply_outdoor_feasibility,
    attach_fitzpatrick,
    attach_personalization,
    build_30min_forecast,
    build_daily_summary,
)
from sunstack.tanscore import best_tan_windows, score_forecast  # noqa: E402
from sunstack.ui import build_calendar_ics, build_interval_ics  # noqa: E402
from sunstack.validation import validate_action_spectra, validate_scored_hourly  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="pacific-palisades")
    ap.add_argument("--root", default="data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--report", default="docs/validation/v4_rescore_verification.md")
    args = ap.parse_args()

    site = next(s for s in config.load_sites() if s.slug == args.site)
    base = Path(args.root) / (Path("sites") / site.slug if not site.default else Path(""))
    latest, caldir = base / "latest", base / "calibration"
    out_dir = Path(args.out) if args.out else Path("/tmp/v4_rescore") / site.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    with config.use_site(site):
        best_air = pd.read_parquet(latest / "tables" / "best_match_enriched.parquet")
        cams = pd.read_parquet(latest / "tables" / "cams_direct_forecast.parquet")
        conf = pd.read_parquet(latest / "tables" / "best_sun_windows.parquet")
        hrrr = pd.read_parquet(latest / "tables" / "hrrr_native_15min.parquet")

        scored = score_forecast(best_air, caldir, cams, conf)
        scored = apply_outdoor_feasibility(scored, None)
        scored = attach_fitzpatrick(scored, None)
        scored = attach_personalization(scored)
        scored = add_interval_doses(scored)
        photo_issues = validate_action_spectra(False)
        score_issues = validate_scored_hourly(scored)
        errors = [i for i in photo_issues + score_issues if i.severity == "ERROR"]
        if errors:
            raise SystemExit(f"v4 validation errors: {errors}")

        half = build_30min_forecast(scored, hrrr)
        half = attach_fitzpatrick(half, None)
        daily = build_daily_summary(half)
        windows = best_tan_windows(scored)
        daily_ics = build_calendar_ics(daily, "v4rescore", scored,
                                       site_slug=site.slug, tz_name=site.timezone)
        ics30 = build_interval_ics(half, "v4rescore",
                                   site_slug=site.slug, tz_name=site.timezone)

        scored.to_parquet(out_dir / "tan_forecast_hourly_v4.parquet", index=False)
        half.to_parquet(out_dir / "tan_forecast_30min_v4.parquet", index=False)
        daily.to_parquet(out_dir / "tan_daily_summary_v4.parquet", index=False)
        (out_dir / "calendar-v4.ics").write_text(daily_ics, encoding="utf-8")
        (out_dir / "calendar-30min-v4.ics").write_text(ics30, encoding="utf-8")

        v4 = pd.to_numeric(scored["tan_score_absolute_0_100"], errors="coerce")
        leg = pd.to_numeric(scored["legacy_absolute_tan_score_55_30_15"], errors="coerce")
        emel = pd.to_numeric(scored["melanogenic_effective_irradiance_wm2"], errors="coerce")
        day_dose = pd.to_numeric(daily["tan_dose_day_j_m2"], errors="coerce")
        day_sed = pd.to_numeric(daily["sed_day_total"], errors="coerce")
        lines = [
            "# v4 offline re-score verification (real forecast data, no network)",
            "",
            f"Site: {site.slug}; input rows: hourly={len(scored)}, "
            f"half-hour={len(half)}, days={len(daily)}.",
            f"Validators: photobiology + scored-hourly ERROR count = {len(errors)}.",
            "",
            "## Score migration on this run",
            "",
            f"v4 Absolute mean/max: {v4.mean():.1f} / {v4.max():.1f}; "
            f"legacy mean/max: {leg.mean():.1f} / {leg.max():.1f}; "
            f"Spearman: {v4.corr(leg, method='spearman'):.3f}.",
            f"E_mel max: {emel.max():.3f} W/m^2 "
            f"(global ref {config.GLOBAL_MELANOGENIC_REFERENCE_WM2}).",
            "",
            "## Doses",
            "",
            f"Daily TanDose range: {day_dose.min():.0f}-{day_dose.max():.0f} J/m^2 mel; "
            f"daily SED range: {day_sed.min():.2f}-{day_sed.max():.2f}.",
            f"tan_dose_complete all: {bool(daily['tan_dose_complete'].all())}; "
            f"coverage min: {daily['tan_dose_coverage_fraction'].min():.3f}.",
            "",
            "## Windows (intensity-ranked, dose-reported)",
            "",
            f"Top hourly window overall: "
            f"{windows.iloc[0]['overall_tan_opportunity_0_100']:.1f}; "
            f"best-window TanDose example (day 1): "
            f"{daily.iloc[0]['tan_dose_best_window_j_m2']:.0f} J/m^2, "
            f"SED {daily.iloc[0]['sed_best_window']:.2f}.",
            f"Daily ICS events: {daily_ics.count('BEGIN:VEVENT')}; "
            f"30-min ICS events: {ics30.count('BEGIN:VEVENT')}.",
            "",
            f"Artifacts (scratch, not committed): {out_dir}",
            "",
            "## Coverage (pre-existing data-availability behavior, unchanged by v4)",
            "",
            f"Local scores non-null: "
            f"{pd.to_numeric(scored['local_tan_score_0_100'], errors='coerce').notna().mean():.3f} "
            f"(rebuilt v4 reference); atmosphere: "
            f"{pd.to_numeric(scored['atmospheric_quality_percentile_0_100'], errors='coerce').notna().mean():.3f}; "
            f"confidence: "
            f"{pd.to_numeric(scored['tan_forecast_confidence_0_100'], errors='coerce').notna().mean():.3f}; "
            f"CAMS UVI present: "
            f"{pd.to_numeric(scored['uvi_cams'], errors='coerce').notna().mean():.3f} "
            f"(5-day CAMS horizon vs 14-day forecast).",
        ]
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))


if __name__ == "__main__":
    main()
