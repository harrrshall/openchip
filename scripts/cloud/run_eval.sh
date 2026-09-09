#!/usr/bin/env bash
# Run an eval suite on the cloud instance. Usage: run_eval.sh <suite> <budget> [tasks] [config-toml]
set -euo pipefail
. /home/openchip-env/env.sh
. /home/openchip-env/secrets.env
export OPENCHIP_MODEL_API_KEY
cd /home/openchip
SUITE=$1; BUDGET=${2:-20m}; TASKS=${3:-}; CFG=${4:-}
ARGS=(eval --suite "$SUITE" --budget "$BUDGET" --out /home/openchip-runs/evals)
[ -n "$TASKS" ] && ARGS+=(--tasks "$TASKS")
[ -n "$CFG" ] && ARGS=(--config "$CFG" "${ARGS[@]}")
.venv/bin/openchip "${ARGS[@]}"
