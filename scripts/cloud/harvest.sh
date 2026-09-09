#!/usr/bin/env bash
# Local helper: archive every result directory + logs for a model on an instance, download the single archive,
# extract into evals/results/, then PAUSE the instance (never delete). Usage: harvest.sh <machine_id> <model-slug>
set -uo pipefail
ID=$1; SLUG=$2
source ~/.config/openchip/credentials.env
cd "$(dirname "$0")/../.."
mkdir -p evals/results work
jl exec $ID -- bash -lc "cd /home/openchip-runs && cp -f bench-$SLUG.log evals/bench-$SLUG.log 2>/dev/null; cp -f vllm/server.log evals/vllm-$SLUG.log 2>/dev/null; cd evals && tar czf /home/openchip-runs/harvest-$SLUG.tgz \$(ls -d *-$SLUG-* 2>/dev/null) bench-$SLUG.log vllm-$SLUG.log DONE-$SLUG 2>/dev/null; ls -la /home/openchip-runs/harvest-$SLUG.tgz" 2>&1 | grep -E "harvest-$SLUG.tgz" | tail -1
jl download $ID "/home/openchip-runs/harvest-$SLUG.tgz" "work/harvest-$SLUG.tgz" >/dev/null 2>&1
if [ -s "work/harvest-$SLUG.tgz" ]; then
  tar xzf "work/harvest-$SLUG.tgz" -C evals/results && echo "extracted: $(tar tzf work/harvest-$SLUG.tgz | grep -E '^[^/]+/$' | tr -d / | tr '\n' ' ')"
  rm -f "work/harvest-$SLUG.tgz"
else
  echo "DOWNLOAD FAILED for $SLUG (instance left running)"; exit 1
fi
jl pause $ID --yes --json 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); print('pause', '$ID', '->', d.get('success', d.get('error')))"
