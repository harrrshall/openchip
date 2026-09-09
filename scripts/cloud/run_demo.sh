#!/usr/bin/env bash
# Run one end-to-end OpenChip build on the cloud instance from a task request file.
# Usage: run_demo.sh <workspace-dir> <request-file-or-task-id> [budget]
set -euo pipefail
. /home/openchip-env/env.sh
. /home/openchip-env/secrets.env
export OPENCHIP_MODEL_API_KEY
WS=$1; REQ=$2; BUDGET=${3:-20m}
cd /home/openchip
if [ -f "evals/suite/core-v1/$REQ/task.json" ]; then
  REQ_TEXT=$(.venv/bin/python -c "import json,sys; print(json.load(open('evals/suite/core-v1/$REQ/task.json'))['request'])")
  .venv/bin/openchip build --project "$WS" --request "$REQ_TEXT" --budget "$BUDGET"
else
  .venv/bin/openchip build --project "$WS" --request "$REQ" --budget "$BUDGET"
fi
