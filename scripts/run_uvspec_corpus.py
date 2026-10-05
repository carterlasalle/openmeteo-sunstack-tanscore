"""Run one stratified-design uvspec sample -> 1nm spectra + channels (Tier-B corpus).

Reads design.csv + manifest.json from scripts/build_spectral_corpus.py,
runs /tmp/libRadtran-2.0.6/bin/uvspec per sample (override with
SUNSTACK_UVSPEC_BIN), integrates UVA/UVB/erythemal/E_DP against the shipped
action spectra, and appends spectra to spectra.npz.

Usage:
  uv run python scripts/run_uvspec_corpus.py --corpus data/research/spectral_corpus --start 0 --count 50
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

UVSPEC_BIN = os.getenv("SUNSTACK_UVSPEC_BIN", "/tmp/libRadtran-2.0.6/bin/uvspec")
DATA_PATH = os.getenv("SUNSTACK_LIBRADTRAN_DATA", "/tmp/libRadtran-2.0.6/data")

ATM_PROFILES = {
    "tropical": f"{DATA_PATH}/atmmod/afglt.dat",
    "midlatitude_summer": f"{DATA_PATH}/atmmod/afglms.dat",
    "midlatitude_winter": f"{DATA_PATH}/atmmod/afglmw.dat",
    "subarctic_summer": f"{DATA_PATH}/atmmod/afglss.dat",
    "subarctic_winter": f"{DATA_PATH}/atmmod/afglsw.dat",
    "us-standard": f"{DATA_PATH}/atmmod/afglus.dat",
}
SOLAR_SRC = f"{DATA_PATH}/solar_flux/atlas_plus_modtran"


def pick_atmosphere(sza: float, ozone: float, seed: int) -> str:
    if sza > 70:
        key = "subarctic_winter" if (seed % 2) else "midlatitude_winter"
    elif ozone < 260:
        key = "tropical"
    elif ozone > 380:
        key = "subarctic_summer"
    else:
        key = "midlatitude_summer" if (seed % 2) else "us-standard"
    return ATM_PROFILES[key]

_CLOUD_TEMPLATE = Path("/tmp/libRadtran-2.0.6/examples/WC50_A.DAT")


def _scaled_cloud_file(liq_g_m2: float, idx: int, dest_dir: Path) -> Path:
    """Scale the example water-cloud LWC profile to the sampled liquid column."""
    import re

    text = _CLOUD_TEMPLATE.read_text(encoding="utf-8")
    scale = max(liq_g_m2, 1.0) / 50.0
    out_lines: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^(\s*\S+\s+)(\S+)(\s+\S+\s*)$", line)
        if m and not line.lstrip().startswith("#"):
            try:
                lwc = float(m.group(2)) * scale
                out_lines.append(f"{m.group(1)}{lwc:.6f}{m.group(3)}")
                continue
            except ValueError:
                pass
        out_lines.append(line)
    dest = dest_dir / f"sunstack_wc_{idx}.DAT"
    dest.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return dest



def write_input(row: dict[str, float], idx: int, path: Path, workdir: Path | None = None) -> Path | None:
    sza, o3 = row["sza_deg"], row["ozone_du"]
    aod340, ang = row["aod340"], row["angstrom"]
    ssa, gg = row["ssa340"], row["asymmetry"]
    alb = row["albedo"]
    cloud = row["total_cloud_cover"]
    liq, ice = row["cloud_liquid_g_m2"], row["cloud_ice_g_m2"]
    alt = row["altitude_m"]
    atm = pick_atmosphere(sza, o3, idx)
    lines = [
        f"data_files_path {DATA_PATH}",
        f"atmosphere_file {atm}",
        f"source solar {SOLAR_SRC}",
        f"mol_modify O3 {o3:.1f} DU",
        "day_of_year 182",
        f"albedo {alb:.4f}",
        f"altitude {alt / 1000.0:.4f}",
        f"sza {sza:.2f}",
        "rte_solver disort",
        "number_of_streams 6",
        "wavelength 280 400",
        "spline 280 400 1",
        "aerosol_default",
        "aerosol_haze 6",
        "aerosol_vulcan 1",
        "aerosol_season 1",
        f"aerosol_angstrom {ang:.3f} {aod340 * (0.34) ** ang:.5f}",
        f"aerosol_modify ssa set {ssa:.4f}",
        f"aerosol_modify gg set {gg:.4f}",
    ]
    cloud_file: Path | None = None
    if cloud >= 0.05 and (liq > 1 or ice > 1):
        base = workdir if workdir is not None else Path(tempfile.gettempdir())
        cloud_file = _scaled_cloud_file(liq, idx, base)
        lines += [
            f"wc_file 1D {cloud_file}",
            f"cloudcover wc {min(cloud, 1.0):.3f}",
        ]
    lines += ["output_user lambda edir edn eup", "quiet", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return cloud_file


def run_sample(row: dict[str, float], idx: int) -> dict[str, object] | None:
    import numpy as np

    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "uv.inp"
        outp = Path(td) / "uv.out"
        write_input(row, idx, inp, Path(td))
        try:
            with open(inp) as fh, open(outp, "w") as oh:
                r = subprocess.run([UVSPEC_BIN], stdin=fh, stdout=oh,
                                   stderr=subprocess.PIPE, text=True, timeout=300, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"sample_id": idx, "status": f"exec-fail: {exc}"}
        if r.returncode != 0:
            return {"sample_id": idx, "status": f"uvspec-rc-{r.returncode}: {(r.stderr or '')[:200]}"}
        try:
            d = np.loadtxt(str(outp))
        except OSError as exc:
            return {"sample_id": idx, "status": f"parse-fail: {exc}"}
    if d.ndim != 2 or d.shape[1] < 4 or len(d) < 100:
        return {"sample_id": idx, "status": f"short-output: {d.shape}"}
    return {"sample_id": idx, "status": "ok",
            "wavelength_nm": d[:, 0].tolist(),
            "edir_mw": d[:, 1].tolist(), "edn_mw": d[:, 2].tolist(), "eup_mw": d[:, 3].tolist()}
def main(argv: list[str] | None = None) -> None:
    import numpy as np
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/research/spectral_corpus")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--seed-offset", type=int, default=0)
    ns = ap.parse_args(argv)
    cdir = Path(ns.corpus)
    design = pd.read_csv(cdir / "design.csv")
    sub = design.iloc[ns.start:ns.start + ns.count]
    out_npz = cdir / "spectra.npz"
    from numpy.typing import NDArray

    existing: dict[str, NDArray[np.float64]] = {}
    done_ids: set[int] = set()
    if out_npz.exists():
        with np.load(str(out_npz), allow_pickle=True) as z:
            names: list[str] = [str(k) for k in z.files]
            for k in names:
                existing[k] = np.asarray(z[k], dtype=np.float64)
            done_ids = {int(x.split("_")[1]) for x in names if x.startswith("sample_")}
    n_ok = n_fail = n_skip = 0
    man_path = cdir / "manifest.json"
    man: dict[str, object] = (
        json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    )
    prev_samples: object = man.get("samples_run", [])
    prev: dict[int, dict[str, object]] = (
        {int(r["sample_id"]): {"sample_id": int(r["sample_id"]), "status": str(r["status"])} for r in prev_samples}
        if isinstance(prev_samples, list)
        else {}
    )
    for _, srow in sub.iterrows():
        idx = int(srow["sample_id"])
        if idx in done_ids:
            n_skip += 1
            continue
        row = {k: float(srow[k]) for k in design.columns if k != "sample_id"}
        res = run_sample(row, idx + ns.seed_offset)
        assert res is not None
        if res["status"] == "ok":
            for comp in ("edir_mw", "edn_mw", "eup_mw"):
                existing[f"sample_{idx}_{comp}"] = np.asarray(res[comp], dtype=np.float64)
            if "wavelength_nm" not in existing:
                existing["wavelength_nm"] = np.asarray(res["wavelength_nm"], dtype=np.float64)
            n_ok += 1
            prev[idx] = {"sample_id": idx, "status": "ok"}
        else:
            n_fail += 1
            prev[idx] = {"sample_id": idx, "status": res["status"]}
            print(f"sample {idx}: {res['status']}", flush=True)
    from typing import Any as _Any

    save_kwargs: dict[str, _Any] = {k: v for k, v in existing.items()}
    np.savez_compressed(str(out_npz), **save_kwargs)  # type: ignore[arg-type]
    ordered: list[dict[str, object]] = sorted(
        prev.values(), key=lambda r: int(str(r["sample_id"]))
    )
    man["samples_run"] = ordered
    man["n_ok"] = sum(1 for r in prev.values() if r["status"] == "ok")
    man["n_fail"] = sum(1 for r in prev.values() if r["status"] != "ok")
    man["status"] = "spectra-partial" if man["n_fail"] else "spectra-complete"
    man["uvspec_binary"] = UVSPEC_BIN
    man["units_note"] = "edir/edn/eup in mW/m2/nm (uvspec native); divide by 1000 for W/m2/nm"
    man_path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(f"done: ok={n_ok} fail={n_fail} skip={n_skip} total_ok={man['n_ok']}")


if __name__ == "__main__":
    main()
