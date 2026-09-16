#!/usr/bin/env bash
# Forced-interruption recovery demo (Milestone 3 exit gate).
# Starts a build, kills it with SIGKILL once verification has begun, then resumes from the checkpoint.
# Usage: interrupt_demo.sh <workspace> <task-id>
set -uo pipefail
. /home/openchip-env/env.sh
. /home/openchip-env/secrets.env
export OPENCHIP_MODEL_API_KEY
cd /home/openchip
WS=${1:?Missing workspace directory}
TASK=${2:?Missing task ID}
# A recovery demo must start fresh without erasing an earlier run or its log.
if [[ -e "$WS" || -L "$WS" || -e "$WS.build.log" || -L "$WS.build.log" ]]; then
  echo "Workspace and build log must not already exist: $WS" >&2
  exit 1
fi
REQ=$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["request"])' \
  "evals/suite/core-v1/$TASK/task.json") || exit $?
set -C  # Reserve the fresh log without overwriting a racing file or symlink.
: > "$WS.build.log" || exit $?
.venv/bin/openchip build --project "$WS" --request "$REQ" --budget 15m >> "$WS.build.log" 2>&1 &
PID=$!
echo "build pid $PID"
# wait until the reference step has completed (checkpoint 'properties'/'rtl'), then kill hard mid-generation
for i in $(seq 1 600); do
  if grep -q "\[reference\] executable reference model accepted" "$WS.build.log" 2>/dev/null; then break; fi
  if ! kill -0 "$PID" 2>/dev/null; then echo "build finished before interruption"; break; fi
  sleep 1
done
sleep 2
if kill -0 "$PID" 2>/dev/null; then
  echo "== SIGKILL at $(date -u +%T) — last log lines:"
  tail -3 "$WS.build.log"
  kill -9 "$PID"
  sleep 1
fi
echo "== state after kill:"
.venv/bin/openchip status --project "$WS"
echo "== resume:"
.venv/bin/openchip resume --project "$WS" 2>&1 | tail -12
echo "== final state:"
.venv/bin/openchip status --project "$WS"
echo "== integrity: reverify delivered artifacts"
.venv/bin/openchip verify --project "$WS" 2>&1 | tail -8
