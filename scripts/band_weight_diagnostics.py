"""§7.2 stratified band-weight diagnostics over a true-spectrum corpus.

For every spectrum in the corpus, compute the dynamic effective band weights

    w_band = integral(E_lambda * S) / integral(E_lambda)

(UVA and UVB) against the shipped delayed-pigmentation spectrum, plus the
Tier-C fixed-band proxy error for the same row. Then stratify by the regimes
the contract names — SZA, total ozone, AOD, SSA, cloud state, altitude,
surface albedo — so the fixed-band error is quantified per regime instead of
asserted as "secondary".

Writes a markdown report (default ``docs/validation/band_weight_diagnostics.md``).

Usage:
  uv run python scripts/band_weight_diagnostics.py --corpus data/research/spectral_corpus_v2
"""

from __future__ import annotations

import argparse
import sys
from itertools import pairwise
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

STRATA: dict[str, tuple[float, ...]] = {
    "sza_deg": (0.0, 40.0, 60.0, 75.0, 90.0),
    "ozone_du": (0.0, 280.0, 340.0, 400.0, 500.0),
    "aod340": (0.0, 0.15, 0.35, 0.60, 1.01),
    "ssa340": (0.84, 0.90, 0.94, 1.001),
    "total_cloud_cover": (0.0, 0.05, 0.35, 0.75, 1.001),
    "altitude_m": (0.0, 500.0, 1500.0, 2500.0, 4001.0),
    "albedo": (0.0, 0.15, 0.35, 0.60, 1.001),
}


def _bin_labels(edges: tuple[float, ...]) -> list[str]:
    labels: list[str] = []
    for lo, hi in pairwise(edges):
        labels.append(f"{lo:g}-{hi:g}")
    return labels


def main(argv: list[str] | None = None) -> None:
    import numpy as np
    import pandas as pd

    from sunstack.photobiology import effectiveness_at, load_action_spectrum
    from sunstack.spectral import (
        SPECTRAL_WAVES_NM,
        band_effective_weights,
        dynamic_band_weights,
    )

    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/research/spectral_corpus_v2")
    ap.add_argument("--out", default="docs/validation/band_weight_diagnostics.md")
    ap.add_argument("--limit", type=int, default=0, help="0 = all samples")
    ns = ap.parse_args(argv)
    cdir = Path(str(ns.corpus))
    npz = cdir / "spectra.npz"
    if not npz.exists():
        raise SystemExit(f"ERROR: {npz} not found (merge shards first)")
    z = np.load(str(npz), allow_pickle=True)
    names: list[str] = [str(k) for k in z.files]
    ids: list[int] = sorted({int(x.split("_")[1]) for x in names if x.startswith("sample_")})
    limit = int(ns.limit)
    if limit:
        ids = ids[:limit]

    design = pd.read_csv(cdir / "design.csv").sort_values("sample_id")
    # design.csv is written with sample_id == positional index; index arrays by
    # position so a row lookup never touches the pandas Scalar union.
    col_arr: dict[str, np.ndarray] = {
        c: design[c].to_numpy(dtype=float) for c in STRATA
    }
    n_rows = len(col_arr["sza_deg"])

    grid = np.asarray(SPECTRAL_WAVES_NM, dtype=float)
    dp_s = effectiveness_at(load_action_spectrum("parrish_fda_3630"), grid)
    waves = np.asarray(z["wavelength_nm"], dtype=float)
    fixed_uvb, fixed_uva = band_effective_weights()
    uvb_m = (grid >= 280) & (grid < 315)
    uva_m = (grid >= 315) & (grid <= 400)

    rows: list[dict[str, float]] = []
    for i in ids:
        if i >= n_rows:
            continue
        try:
            edir = np.asarray(z[f"sample_{i}_edir_mw"], dtype=float) / 1000.0
            edn = np.asarray(z[f"sample_{i}_edn_mw"], dtype=float) / 1000.0
        except KeyError:
            continue
        g = np.clip(np.interp(grid, waves, edir + edn, left=0.0, right=0.0), 0, None)
        true_emel = float(np.sum(g * dp_s))
        if true_emel < 0.01:
            continue
        uva = float(np.sum(g[uva_m]))
        uvb = float(np.sum(g[uvb_m]))
        w_uvb, w_uva = dynamic_band_weights(g)
        proxy = uvb * fixed_uvb + uva * fixed_uva
        rec: dict[str, float] = {
            "w_uvb": w_uvb,
            "w_uva": w_uva,
            "proxy_rel_err": (proxy - true_emel) / true_emel,
            "e_dp": true_emel,
        }
        for col in STRATA:
            rec[col] = float(col_arr[col][i])
        rows.append(rec)

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("ERROR: no qualified rows (E_DP >= 0.01) in corpus")

    out = Path(str(ns.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    med = df["proxy_rel_err"].median()
    p05 = df["proxy_rel_err"].quantile(0.05)
    p95 = df["proxy_rel_err"].quantile(0.95)
    lines: list[str] = [
        "# §7.2 band-weight diagnostics (dynamic vs fixed-band proxy)",
        "",
        f"Corpus: `{cdir}` · qualified rows: **{len(df)}** (E_DP >= 0.01 W/m²).",
        "",
        f"Fixed-band Tier-C weights: `w_uvb={fixed_uvb:.5f}`, `w_uva={fixed_uva:.7f}`.",
        "",
        (
            "`w_band = sum(E_lambda*S)/sum(E_lambda)` over each true spectrum; "
            "`proxy_rel_err` is the Tier-C fixed-band E_DP relative error on the same row."
        ),
        "",
        "## Overall",
        "",
        "| metric | median | p05 | p95 |",
        "|---|---|---|---|",
        (
            f"| w_uvb | {df['w_uvb'].median():.5f} | "
            f"{df['w_uvb'].quantile(0.05):.5f} | {df['w_uvb'].quantile(0.95):.5f} |"
        ),
        (
            f"| w_uva | {df['w_uva'].median():.7f} | "
            f"{df['w_uva'].quantile(0.05):.7f} | {df['w_uva'].quantile(0.95):.7f} |"
        ),
        f"| proxy_rel_err | {med:+.4f} | {p05:+.4f} | {p95:+.4f} |",
        "",
        (
            f"The fixed-band proxy is biased by a median **{med:+.1%}** with a "
            f"p05-p95 span of {p05:+.1%} to {p95:+.1%} — the band-shape error is "
            "NOT secondary."
        ),
        "",
    ]
    for col, edges in STRATA.items():
        lines += [
            f"## Stratum: `{col}`",
            "",
            "| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |",
            "|---|---|---|---|---|---|---|",
        ]
        vals = df[col].to_numpy(dtype=float)
        for k, lab in enumerate(_bin_labels(edges)):
            lo, hi = edges[k], edges[k + 1]
            sub = df[(vals >= lo) & (vals < hi)]
            if sub.empty:
                lines.append(f"| {lab} | 0 | — | — | — | — | — |")
                continue
            lines.append(
                f"| {lab} | {len(sub)} | {sub['w_uvb'].median():.4f} | "
                f"{sub['w_uva'].median():.6f} | {sub['proxy_rel_err'].median():+.3f} | "
                f"{sub['proxy_rel_err'].quantile(0.95):+.3f} | "
                f"{sub['proxy_rel_err'].abs().median():.3f} |"
            )
        lines.append("")
    lines += [
        "## Reading",
        "",
        (
            "- A single fixed `w_band` cannot hold across SZA/ozone/aerosol/cloud; "
            "the per-regime columns show how far it moves."
        ),
        (
            "- This is why Tier-C is labelled a *proxy* and why a gate-passing Tier-B "
            "emulator is required before any validated-spectral claim."
        ),
        "",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"band weights: {len(df)} rows -> {out}")


if __name__ == "__main__":
    main()