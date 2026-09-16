#!/usr/bin/env bash
# False-acceptance experiment: same model (primary), four configurations, identical tasks.
#   D  baseline (no review, no alt)      A  independent spec review
#   B  review + cross-family alt refs    C  cross-family alt refs only
# Usage: experiment_fa.sh <alt-base-url> <alt-model>   (alt API key from secrets.env OPENCHIP_MODEL_API_KEY)
set -uo pipefail
. /home/openchip-env/env.sh
. /home/openchip-env/secrets.env
. /home/openchip-env/model.env
export OPENCHIP_MODEL_API_KEY OPENCHIP_MODEL OPENCHIP_MODEL_REVISION OPENCHIP_THINKING_ROLES OPENCHIP_EXTRA_BODY
export OPENCHIP_ALT_API_KEY="$OPENCHIP_MODEL_API_KEY"
ALT_URL=$1
ALT_MODEL=$2
cd /home/openchip
DS=/home/openchip-env/verilog-eval/dataset_spec-to-rtl
SUBSET=$(ls $DS | grep _prompt.txt | sed 's/_prompt.txt//' | awk 'NR%4==1' | paste -sd, -)
OUT=/home/openchip-runs/evals/fa-experiment
mkdir -p $OUT
run_cfg() { # label review(0/1) alt(0/1)
  local L=$1 R=$2 A=$3
  echo "== config $L review=$R alt=$A $(date -u +%T)"
  (
    export OPENCHIP_REVIEW=$([ "$R" = 1 ] && echo on || echo off)
    [ "$A" = 1 ] && export OPENCHIP_ALT_MODEL="$ALT_MODEL" OPENCHIP_ALT_BASE_URL="$ALT_URL/v1" OPENCHIP_ALT_PROVIDER=openai-compatible
    .venv/bin/openchip veval --dataset $DS --mode agent --budget 6m --problems "$SUBSET" --out $OUT/$L 2>&1 | grep -E "^n = |pass = |\[39/39\]"
    .venv/bin/openchip eval --suite core-v1 --budget 15m --out $OUT/$L 2>&1 | grep -E "^- (golden|false)|^n = "
    .venv/bin/openchip eval --suite heldout-v1 --budget 15m --repeats 2 --out $OUT/$L 2>&1 | grep -E "^- (golden|false)|^n = "
  )
}
run_cfg D 0 0
run_cfg A 1 0
run_cfg B 1 1
run_cfg C 0 1
echo "== experiment done $(date -u +%T)"
touch $OUT/DONE
