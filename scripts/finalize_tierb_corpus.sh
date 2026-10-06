#!/bin/bash
# Wait for all 8 corpus shards, merge them, retrain the Tier-B emulator and
# record the §8.4 gate verdict. Long-running; run with nohup.
set -u
cd "$(dirname "$0")/.." || exit 1
C=data/research/spectral_corpus_v2
LOG=/tmp/tierb_finalize.log
: > "$LOG"
echo "waiting for 8 shards at $(date)" >> "$LOG"
for _ in $(seq 1 480); do
  n=$(ls "$C"/shard_*.npz 2>/dev/null | wc -l | tr -d ' ')
  echo "$(date +%H:%M) shards=$n" >> "$LOG"
  [ "$n" -ge 8 ] && break
  sleep 30
done
echo "=== merge $(date)" >> "$LOG"
uv run python scripts/merge_spectral_shards.py --corpus "$C" >> "$LOG" 2>&1
echo "=== train $(date)" >> "$LOG"
uv run python scripts/train_spectral_emulator.py --corpus "$C" --out data/calibration/spectral_emulator >> "$LOG" 2>&1
echo "=== done rc=$? $(date)" >> "$LOG"
