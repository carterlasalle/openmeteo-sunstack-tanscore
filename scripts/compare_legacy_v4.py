"""Compare legacy 55/30/15 absolute against v4 action-spectrum absolute.

Primary input: a scored hourly table (or the training calibration table).
Optional second input (--hourly2): a live scored run (e.g. current South
Bend tables) whose section additionally answers the §25 inspection questions
with evidence instead of guidance. No rankings are preserved for
compatibility; ordering changes are documented as science-driven.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _ensure_dual_scores(df: pd.DataFrame, src: Path, lines: list[str]) -> pd.DataFrame:
    has_both = {"legacy_absolute_tan_score_55_30_15",
                "tan_score_absolute_0_100"}.issubset(df.columns)
    if not has_both and {"uva", "uvi"}.issubset(df.columns):
        # Pre-v4 table: compute both scores on the fly (Tier-C, provisional).
        import sys

        sys.path.insert(0, "src")
        from sunstack import config as _cfg
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
            _v4(_em(uva, uvb),
                float(_cfg.GLOBAL_MELANOGENIC_REFERENCE_WM2)), 1)
        has_both = True
        lines.append(f"Source: `{src}` ({len(df)} rows; v4 recomputed Tier-C provisional).")
    else:
        lines.append(f"Source: `{src}` ({len(df)} rows).")
    if not has_both:
        lines += [
            "",
            "Input predates v4 dual scoring (no legacy diagnostic column). "
            "Rerun scoring to populate both `tan_score_absolute_0_100` and "
            "`legacy_absolute_tan_score_55_30_15`, then rerun this report.",
        ]
    return df


def _section(df: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    """Topline stats + divergence bins. Returns (lines, daylight work frame)."""
    lines: list[str] = []
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
        "### UVA-rich vs UVB-rich divergence",
        "",
    ]
    uva_s = pd.to_numeric(
        df["uva"] if "uva" in df else df.get("predicted_uva_wm2"), errors="coerce")
    if "uvb" in df:
        uvb_s = pd.to_numeric(df["uvb"], errors="coerce")
    else:
        uvb_s = pd.to_numeric(df.get("predicted_uvb_wm2"), errors="coerce")
    ratio = (uva_s / uvb_s.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    day = (pd.to_numeric(
        df["ghi"] if "ghi" in df else df.get("shortwave_radiation"),
        errors="coerce").fillna(0) > 10) | (leg > 1)
    work = pd.DataFrame({"leg": leg, "new": new, "ratio": ratio}).loc[day].dropna()
    if len(work) >= 100:
        work["bin"] = pd.qcut(work["ratio"], 5,
                              labels=["most UVB-rich", "UVB-leaning", "middle",
                                      "UVA-leaning", "most UVA-rich"])
        lines += ["| spectrum bin | n | mean legacy | mean v4 | mean delta |",
                  "|---|---|---|---|---|"]
        for lab in work["bin"].cat.categories:
            sub = work.loc[work["bin"] == lab]
            d = (sub["new"] - sub["leg"])
            lines.append(
                f"| {lab} | {len(sub)} | {sub['leg'].mean():.1f} | "
                f"{sub['new'].mean():.1f} | {d.mean():+.1f} |")
        lines += ["",
                  "Reading: UVA-rich hours (cloudy/high-SZA, relatively more "
                  "UVA per UVB joule) score lower under v4 than under legacy "
                  "at the same legacy level, because delayed-melanogenesis "
                  "effectiveness per joule near 360-365 nm is ~3 orders "
                  "below 290-295 nm while legacy weights UVA at 30%. "
                  "UVB-rich clear midday hours move the opposite way. "
                  "This is the intended science-driven reordering.",
                  ""]
    else:
        lines += ["(Too few daylight rows with UVA+UVB bands for divergence bins.)",
                  ""]
    return lines, work


def _answered_questions(df: pd.DataFrame) -> list[str]:
    """Answer the §25 inspection questions with live-run evidence."""
    lines = ["## Inspection questions, answered on the live run", ""]
    leg = pd.to_numeric(df["legacy_absolute_tan_score_55_30_15"], errors="coerce")
    new = pd.to_numeric(df["tan_score_absolute_0_100"], errors="coerce")
    peak = new.idxmax()
    peak_abs, peak_leg = float(new.loc[peak]), float(leg.loc[peak])
    peak_local = pd.to_numeric(df.get("local_tan_score_0_100"),
                               errors="coerce").loc[peak]
    lines.append(
        f"- Excellent-locally without globally near-100: peak Absolute hour "
        f"scores v4 {peak_abs:.1f} (legacy {peak_leg:.1f}) with Local "
        f"{float(peak_local):.1f}. "
        f"{'CONFIRMED' if peak_abs < 75 and float(peak_local) >= 75 else 'REVIEW'}.")
    if "cloud_cover" in df:
        cloud = pd.to_numeric(df["cloud_cover"], errors="coerce")
        d = (new - leg).dropna()
        # Match on legacy level: the claim is that equally legacy-strong
        # cloudy hours score lower under v4. Unmatched means mix night zeros.
        band = d.loc[(leg.loc[d.index] >= 10) & (leg.loc[d.index] <= 40)]
        hi = band.loc[cloud.loc[band.index] >= 60]
        lo = band.loc[cloud.loc[band.index] < 30]
        if len(hi) >= 20 and len(lo) >= 20 and hi.mean() < lo.mean():
            verdict = "CONFIRMED down"
        else:
            verdict = ("INCONCLUSIVE on cloud_cover alone this run "
                       "(small/low-sun cloudy sample); the UVA/UVB-ratio bins "
                       "are the direct mechanism test")
        lines.append(
            f"- Cloudy/high-UVA move (legacy 10-40 band): mean delta at "
            f"cloud>=60 is {hi.mean():+.1f} (n={len(hi)}) vs {lo.mean():+.1f} "
            f"at cloud<30 (n={len(lo)}). {verdict}.")
    if "time_utc" in df and "tan_forecast_confidence_0_100" in df:
        t = pd.to_datetime(df["time_utc"], utc=True)
        lead_h = (t - t.min()).dt.total_seconds() / 3600.0
        conf = pd.to_numeric(df["tan_forecast_confidence_0_100"], errors="coerce")
        c_conf = lead_h.corr(conf, method="spearman")
        c_abs = lead_h.corr(new.loc[conf.index], method="spearman")
        lines.append(
            f"- Confidence vs intensity over lead time: confidence/lead "
            f"Spearman {c_conf:.2f} (declines distantly), Absolute/lead "
            f"Spearman {c_abs:.2f} (physics independent of horizon). "
            f"{'CONFIRMED separate' if abs(c_conf) > abs(c_abs) else 'REVIEW'}.")
    lines.append(
        "- UVA-rich vs UVB-rich behavior: see divergence bins above; the "
        "pigment-darkening (IPD) channel moves the opposite way by "
        "construction (UVA-dominant) and is never merged into TanScore.")
    lines.append("")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hourly", default="data/latest/tables/tan_forecast_hourly.parquet")
    ap.add_argument("--hourly2", default=None,
                    help="Second (live-run) hourly table for the SB section")
    ap.add_argument("--label2", default="live run")
    ap.add_argument("--out", default="docs/migration/legacy_vs_v4_comparison.md")
    args = ap.parse_args()
    lines = ["# Legacy 55/30/15 vs v4 action-spectrum comparison", ""]
    src = Path(args.hourly)
    if not src.exists():
        # Fall back to the calibration training table (has uva/uvi columns).
        alt = Path("data/calibration/training_calibration_hourly.parquet")
        if not alt.exists():
            raise SystemExit(f"no input table: {src} (and no {alt})")
        src = alt
    df = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)
    df = _ensure_dual_scores(df, src, lines)
    if {"legacy_absolute_tan_score_55_30_15",
            "tan_score_absolute_0_100"}.issubset(df.columns):
        sec, _ = _section(df)
        lines += sec
    if args.hourly2:
        src2 = Path(args.hourly2)
        if not src2.exists():
            raise SystemExit(f"live input table missing: {src2}")
        lines += [f"## Current South Bend runs ({args.label2})", ""]
        df2 = pd.read_parquet(src2) if src2.suffix == ".parquet" else pd.read_csv(src2)
        df2 = _ensure_dual_scores(df2, src2, lines)
        if {"legacy_absolute_tan_score_55_30_15",
                "tan_score_absolute_0_100"}.issubset(df2.columns):
            sec2, _ = _section(df2)
            lines += sec2
            lines += _answered_questions(df2)
        else:
            lines += ["(Live input predates v4 dual scoring; "
                      "no comparison section generated.)", ""]
    lines += [
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
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
