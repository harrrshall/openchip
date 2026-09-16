#!/usr/bin/env bash
# One-shot model benchmark on a JarvisLabs instance: provision (idempotent), serve, run the full protocol.
# Requires /home/openchip-env/{secrets.env,model.env} and the repo at /home/openchip.
# Protocol (identical for every model): core-v1 (10x1) -> heldout-v1 (5x2) -> VerilogEval direct (156) -> VerilogEval agent (every 4th, 39).
set -uo pipefail
export HOME=/home
ROOT=/home/openchip-env
. "$ROOT/secrets.env"
. "$ROOT/model.env"
export OPENCHIP_MODEL_API_KEY OPENCHIP_MODEL OPENCHIP_MODEL_REVISION OPENCHIP_THINKING_ROLES OPENCHIP_EXTRA_BODY
SLUG=$(echo "${OPENCHIP_MODEL##*/}" | tr -c 'A-Za-z0-9.\n' '-')
LOG=/home/openchip-runs/bench-$SLUG.log
mkdir -p /home/openchip-runs/evals
echo "== bench_all $OPENCHIP_MODEL @ $OPENCHIP_MODEL_REVISION start $(date -u +%FT%TZ)" | tee -a "$LOG"
bash /home/provision.sh 2>&1 | tail -5 | tee -a "$LOG"
. "$ROOT/env.sh"
cd /home/openchip
[ -x .venv/bin/openchip ] || {
  uv venv .venv --python 3.12 -q && uv pip install --python .venv/bin/python -q -e ".[dev]"
}
# serve (background) unless the RIGHT model is already being served
SERVED=$(curl -sf -H "Authorization: Bearer $OPENCHIP_MODEL_API_KEY" http://127.0.0.1:8000/v1/models 2>/dev/null | grep -o "\"id\":\"[^\"]*\"" | head -1)
if [ "$SERVED" != "\"id\":\"$OPENCHIP_MODEL\"" ]; then
  pkill -f "vllm serve" 2>/dev/null
  sleep 5
  nohup bash "$ROOT/serve.sh" > /home/openchip-runs/vllm/serve.out 2>&1 &
  for i in $(seq 1 240); do
    curl -sf -H "Authorization: Bearer $OPENCHIP_MODEL_API_KEY" http://127.0.0.1:8000/v1/models >/dev/null && break
    sleep 10
  done
fi
.venv/bin/openchip doctor 2>&1 | tee -a "$LOG"
DS=/home/openchip-env/verilog-eval/dataset_spec-to-rtl
[ -d "$DS" ] || (cd /home/openchip-env && git clone -q --depth 1 https://github.com/NVlabs/verilog-eval.git)
SUBSET=$(ls $DS | grep _prompt.txt | sed 's/_prompt.txt//' | awk 'NR%4==1' | paste -sd, -)
run() {
  echo "== $1 $(date -u +%T)" | tee -a "$LOG"
  shift
  "$@" 2>&1 | tee -a "$LOG" | grep -E "=>|^- |^n = |\[[0-9]+/[0-9]+\]|pass = "
}
run core-v1      .venv/bin/openchip eval --suite core-v1    --budget 15m --repeats 1 --out /home/openchip-runs/evals
run heldout-v1   .venv/bin/openchip eval --suite heldout-v1 --budget 15m --repeats 2 --out /home/openchip-runs/evals
run veval-direct .venv/bin/openchip veval --dataset $DS --mode direct --out /home/openchip-runs/evals
run veval-agent  .venv/bin/openchip veval --dataset $DS --mode agent --budget 6m --problems "$SUBSET" --out /home/openchip-runs/evals
echo "== bench_all done $(date -u +%FT%TZ)" | tee -a "$LOG"
touch "/home/openchip-runs/evals/DONE-$SLUG"
