#!/usr/bin/env bash
# Wait for a finished benchmark (DONE-<slug> marker), then switch model.env and run bench_all for the next model.
# Usage: bench_chain.sh <done-marker-slug> <next-model-env-file-on-instance>
set -uo pipefail
WAIT=$1; NEXT=$2
for i in $(seq 1 720); do [ -f "/home/openchip-runs/evals/DONE-$WAIT" ] && break; sleep 30; done
[ -f "/home/openchip-runs/evals/DONE-$WAIT" ] || { echo "timed out waiting for DONE-$WAIT"; exit 1; }
echo "== chain: $WAIT done at $(date -u +%T); switching to $(grep OPENCHIP_MODEL= "$NEXT")"
cp "$NEXT" /home/openchip-env/model.env
pkill -f "vllm serve" 2>/dev/null; sleep 5
exec bash /home/openchip/scripts/cloud/bench_all.sh
