#!/usr/bin/env bash
# Same-GPU speed comparison: serve each model in turn on THIS instance and time core-v1 (10 tasks) with the
# identical pipeline (review on, no alt). Usage: speed_compare.sh <model-env-file>... (weights must be cached)
set -uo pipefail
. /home/openchip-env/env.sh; . /home/openchip-env/secrets.env; export OPENCHIP_MODEL_API_KEY
cd /home/openchip
OUT=/home/openchip-runs/evals/speed-compare; mkdir -p $OUT
for ENVF in "$@"; do
  cp "$ENVF" /home/openchip-env/model.env; . /home/openchip-env/model.env
  export OPENCHIP_MODEL OPENCHIP_MODEL_REVISION OPENCHIP_THINKING_ROLES OPENCHIP_EXTRA_BODY
  SLUG=$(echo "${OPENCHIP_MODEL##*/}" | tr -c 'A-Za-z0-9.\n' '-')
  a="vllm ser"; pkill -f "${a}ve" 2>/dev/null; sleep 6
  nohup bash /home/openchip-env/serve.sh > /home/openchip-runs/vllm/serve-$SLUG.out 2>&1 &
  for i in $(seq 1 120); do curl -sf -H "Authorization: Bearer $OPENCHIP_MODEL_API_KEY" http://127.0.0.1:8000/v1/models 2>/dev/null | grep -q "$OPENCHIP_MODEL" && break; sleep 10; done
  echo "== $SLUG served on $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1) at $(date -u +%T)"
  # warm-up (kernel/graph capture, cache) then the timed suite
  curl -s -H "Authorization: Bearer $OPENCHIP_MODEL_API_KEY" -H "Content-Type: application/json" http://127.0.0.1:8000/v1/chat/completions -d "{\"model\":\"$OPENCHIP_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK.\"}],\"max_tokens\":8}" >/dev/null
  .venv/bin/openchip eval --suite core-v1 --budget 15m --repeats 1 --out $OUT 2>&1 | grep -E "^- golden|^- false|^n = "
  d=$(ls -dt $OUT/core-v1-$SLUG-* | head -1); python3 - "$d" <<PY
import json, sys, statistics
d = sys.argv[1]; recs = [json.loads(l) for l in open(d + "/records.jsonl")]
print(f"{d.split('/')[-1]}: mean wall {statistics.mean(r['wall_s'] for r in recs):.1f} s, median {statistics.median(r['wall_s'] for r in recs):.1f} s, tokens/task {statistics.mean(r['tokens'] for r in recs):.0f}, model latency/task {statistics.mean(r['model_latency_s'] for r in recs):.1f} s")
PY
done
echo "== speed compare done $(date -u +%T)"; touch $OUT/DONE
