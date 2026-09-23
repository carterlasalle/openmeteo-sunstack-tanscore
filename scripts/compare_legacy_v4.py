"""Compare legacy 55/30/15 absolute against v4 action-spectrum absolute.

Reads a scored hourly table (or the training calibration table) and reports
how the migration moves South-Bend-like hours, cloudy/high-UVA cases, and
UVA-rich vs UVB-rich spectra. No rankings are preserved for compatibility;
ordering changes are documented as science-driven.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hourly", default="data/latest/tables/tan_forecast_hourly.parquet")
    ap.add_argument("--out", default="docs/migration/legacy_vs_v4_comparison.md")
    args = ap.parse_args()
    src = Path(args.hourly)
    if not src.exists():
        # Fall back to the calibration training table (has uva/uvi columns).
        alt = Path("data/calibration/training_calibration_hourly.parquet")
        if not alt.exists():
            raise SystemExit(f"no input table: {src} (and no {alt})")
        src = alt
    df = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)
    has_both = {"legacy_absolute_tan_score_55_30_15", "tan_score_absolute_0_100"}.issubset(df.columns)
    if not has_both and {"uva", "uvi"}.issubset(df.columns):
        # Pre-v4 table: compute both scores on the fly (Tier-C, provisional).
        import sys

        sys.path.insert(0, "src")
        from sunstack.calibrate import absolute_tan_score as _legacy
        from sunstack.photobiology import absolute_tan_score_from_melanogenic_irradiance as _v4
        from sunstack.spectral import melanogenic_from_broadband as _em

        uva = pd.to_numeric(df["uva"], errors="coerce").fillna(0).to_numpy()
        uvb = (pd.to_numeric(df["uvb"], errors="coerce").fillna(0).to_numpy()
               if "uvb" in df else pd.to_numeric(df["uvi"], errors="coerce").fillna(0).to_numpy() * 0.15)
        uvi = pd.to_numeric(df["uvi"], errors="coerce").fillna(0).to_numpy()
        df = df.copy()
        df["legacy_absolute_tan_score_55_30_15"] = np.round(_legacy(uvi, uva), 1)
        df["tan_score_absolute_0_100"] = np.round(
            _v4(_em(uva, uvb), 1.6), 1)
        has_both = True
        lines = ["# Legacy 55/30/15 vs v4 action-spectrum comparison", ""]
        lines.append(f"Source: `{src}` ({len(df)} rows; v4 recomputed Tier-C provisional).")
    else:
        lines = ["# Legacy 55/30/15 vs v4 action-spectrum comparison", ""]
        lines.append(f"Source: `{src}` ({len(df)} rows).")
    if has_both:
        leg = pd.to_numeric(df["legacy_absolute_tan_score_55_30_15"], errors="coerce")
        new = pd.to_numeric(df["tan_score_absolute_0_100"], errors="coerce")
        diff = (new - leg).dropna()
        lines += [
            "",
            f"Mean legacy: {leg.mean():.1f}; mean v4: {new.mean():.1f}; "
            f"mean delta (v4-legacy): {diff.mean():+.1f}.",
            f"Median delta: {diff.median():+.1f}; p10 {diff.quantile(0.1):+.1f}; "
            f"p90 {diff.quantile(0.9):+.1f}.",
            f"Rank correlation (Spearman): {leg.corr(new, method='spearman'):.3f}.",
            "",
            "## What to inspect",
            "- September-11-like excellent-local hours should remain excellent "
            "locally without becoming globally near-100 (Absolute stays anchored "
            "to the fixed melanogenic reference).",
            "- Cloudy/high-UVA cases move down relative to UVB-rich clear cases "
            "because delayed-melanogenesis effectiveness per joule is orders of "
            "magnitude higher near 290-295 nm than near 360-365 nm.",
            "- UVA-rich vs UVB-rich spectra separate for delayed melanogenesis "
            "while IPD (pigment-darkening channel) moves the opposite way.",
            "- Distant-forecast confidence stays separate from physical intensity.",
            "",
            "Ordering changes are science-driven (photoaddition per Keong 1990, "
            "no sqrt interaction) and are not preserved for compatibility.",
        ]
    else:
        lines += [
            "",
            "Input predates v4 dual scoring (no legacy diagnostic column). "
            "Rerun scoring to populate both `tan_score_absolute_0_100` and "
            "`legacy_absolute_tan_score_55_30_15`, then rerun this report.",
        ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
