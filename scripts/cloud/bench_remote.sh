#!/usr/bin/env bash
# Full OpenChip protocol against a REMOTE provider (no local vLLM): core-v1 -> heldout-v1 -> VerilogEval direct -> agent subset.
# Usage: bench_remote.sh <provider> <base_url> <model> <api-key-env-name> [user-agent] [out-dir]
set -uo pipefail
. /home/openchip-env/env.sh; [ -f /home/openchip-env/secrets.env ] && . /home/openchip-env/secrets.env
PROVIDER=$1; BASE=$2; MODEL=$3; KEYENV=$4; UA=${5:-}; OUT=${6:-/home/openchip-runs/evals/remote}
export OPENCHIP_PROVIDER=$PROVIDER OPENCHIP_MODEL_BASE_URL=$BASE OPENCHIP_MODEL=$MODEL OPENCHIP_MODEL_API_KEY_ENV=$KEYENV OPENCHIP_THINKING_ROLES="" OPENCHIP_MODEL_REVISION=remote
[ -n "$UA" ] && export OPENCHIP_USER_AGENT="$UA"
cd /home/openchip
SLUG=$(echo "${MODEL##*/}" | tr -c 'A-Za-z0-9.\n' '-'); mkdir -p $OUT; LOG=$OUT/bench-$SLUG.log
echo "== bench_remote $PROVIDER $MODEL via $BASE start $(date -u +%FT%TZ)" | tee -a "$LOG"
.venv/bin/openchip doctor 2>&1 | grep -E "model " | tee -a "$LOG"
DS=/home/openchip-env/verilog-eval/dataset_spec-to-rtl
SUBSET=$(ls $DS | grep _prompt.txt | sed 's/_prompt.txt//' | awk 'NR%4==1' | paste -sd, -)
run() { echo "== $1 $(date -u +%T)" | tee -a "$LOG"; shift; "$@" 2>&1 | tee -a "$LOG" | grep -E "=>|^- |^n = |\[[0-9]+/[0-9]+\]|pass = " ; }
run core-v1      .venv/bin/openchip eval --suite core-v1    --budget 15m --repeats 1 --out $OUT
run heldout-v1   .venv/bin/openchip eval --suite heldout-v1 --budget 15m --repeats 2 --out $OUT
run veval-direct .venv/bin/openchip veval --dataset $DS --mode direct --out $OUT
run veval-agent  .venv/bin/openchip veval --dataset $DS --mode agent --budget 6m --problems "$SUBSET" --out $OUT
echo "== bench_remote done $(date -u +%FT%TZ)" | tee -a "$LOG"; touch "$OUT/DONE-$SLUG"
