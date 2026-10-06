"""Merge per-shard uvspec corpus files into one spectra.npz + manifest.

``scripts/run_uvspec_corpus.py`` can write one npz per shard
(``--npz-name shard_N.npz --manifest-name manifest_N.json``) so several
processes can fill a corpus in parallel without racing on a single file. This
merges those shards into the ``spectra.npz`` + ``manifest.json`` the trainer
reads, and records the shard hashes in the merged manifest.

Usage:
  uv run python scripts/merge_spectral_shards.py --corpus data/research/spectral_corpus_v2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    import numpy as np

    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/research/spectral_corpus_v2")
    ap.add_argument("--pattern", default="shard_*.npz")
    ap.add_argument("--out-npz", default="spectra.npz")
    ap.add_argument("--out-manifest", default="manifest.json")
    ns = ap.parse_args(argv)
    cdir = Path(str(ns.corpus))
    shards = sorted(cdir.glob(str(ns.pattern)))
    if not shards:
        raise SystemExit(f"ERROR: no shards matching {ns.pattern} in {cdir}")

    merged: dict[str, np.ndarray] = {}
    wave: np.ndarray | None = None
    runs: dict[int, dict[str, object]] = {}
    shard_hashes: list[dict[str, object]] = []
    for shard in shards:
        raw = shard.read_bytes()
        shard_hashes.append({
            "file": shard.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        })
        with np.load(str(shard), allow_pickle=True) as z:
            names = [str(k) for k in z.files]
            for k in names:
                if k == "wavelength_nm":
                    wave = np.asarray(z[k], dtype=np.float64)
                    continue
                merged[k] = np.asarray(z[k], dtype=np.float64)
        shard_man = shard.with_name(shard.name.replace("shard_", "manifest_")).with_suffix(".json")
        if shard_man.exists():
            data = json.loads(shard_man.read_text(encoding="utf-8"))
            for row in data.get("samples_run", []):
                runs[int(row["sample_id"])] = {
                    "sample_id": int(row["sample_id"]),
                    "status": str(row["status"]),
                }
    if wave is not None:
        merged["wavelength_nm"] = wave

    n_ok = sum(1 for r in runs.values() if r["status"] == "ok")
    n_fail = sum(1 for r in runs.values() if r["status"] != "ok")
    out_npz = cdir / str(ns.out_npz)
    from typing import Any as _Any

    payload: dict[str, _Any] = dict(merged)
    np.savez_compressed(str(out_npz), **payload)  # type: ignore[arg-type]

    # §8.2 provenance: the corpus must record which radiative-transfer binary
    # produced it, not just that "some" uvspec ran.
    uvspec = os.getenv("SUNSTACK_UVSPEC_BIN", "/tmp/libRadtran-2.0.6/bin/uvspec")
    provenance: dict[str, object] = {"uvspec_binary": uvspec}
    bin_path = Path(uvspec)
    if bin_path.exists():
        provenance["uvspec_sha256"] = hashlib.sha256(bin_path.read_bytes()).hexdigest()
        try:
            v = subprocess.run([uvspec, "-v"], capture_output=True, text=True,
                               timeout=30, check=False)
            provenance["uvspec_version"] = (v.stdout or v.stderr or "").strip().splitlines()[:1]
        except (OSError, subprocess.SubprocessError):
            provenance["uvspec_version"] = "unknown"
    else:
        provenance["uvspec_sha256"] = None

    man_path = cdir / str(ns.out_manifest)
    man: dict[str, object] = (
        json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    )
    man.update(provenance)
    man.update({
        "shards": shard_hashes,
        "samples_run": [runs[k] for k in sorted(runs)],
        "n_ok": n_ok,
        "n_fail": n_fail,
        "status": "spectra-complete" if n_fail == 0 and n_ok else "spectra-partial",
        "merged_sha256": hashlib.sha256(out_npz.read_bytes()).hexdigest(),
        "units_note": "edir/edn/eup mW/m2/nm; divide by 1000 for W/m2/nm",
    })
    man_path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(f"merged {len(shards)} shards -> {out_npz} ({n_ok} ok / {n_fail} fail)")


if __name__ == "__main__":
    main()