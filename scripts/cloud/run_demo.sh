#!/usr/bin/env bash
# Run one end-to-end OpenChip build on the cloud instance from a task request file.
# Usage: run_demo.sh <workspace-dir> <request-file-or-task-id> [budget]
set -euo pipefail
. /home/openchip-env/env.sh
. /home/openchip-env/secrets.env
export OPENCHIP_MODEL_API_KEY
WS=${1:?Missing workspace directory}
REQ=${2:?Missing request file or task ID}
BUDGET=${3:-20m}
cd /home/openchip
TASK_FILE="evals/suite/core-v1/$REQ/task.json"
if [ -f "$TASK_FILE" ]; then
  REQ=$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["request"])' "$TASK_FILE")
fi
.venv/bin/openchip build --project "$WS" --request "$REQ" --budget "$BUDGET"
