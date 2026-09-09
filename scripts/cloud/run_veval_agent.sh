#!/usr/bin/env bash
# VerilogEval v2 agent-mode on a fixed, unbiased subset (every 4th problem) with a per-problem budget.
. /home/openchip-env/env.sh; . /home/openchip-env/secrets.env; export OPENCHIP_MODEL_API_KEY
cd /home/openchip
DS=/home/openchip-env/verilog-eval/dataset_spec-to-rtl
SUBSET=$(ls $DS | grep _prompt.txt | sed 's/_prompt.txt//' | awk 'NR%4==1' | paste -sd, -)
.venv/bin/openchip veval --dataset $DS --mode agent --budget ${1:-6m} --problems "$SUBSET" --out /home/openchip-runs/evals
