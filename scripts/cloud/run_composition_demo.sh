#!/usr/bin/env bash
# Run one real NL composition and the independent development oracle on JarvisLabs.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT_DIR="${1:?supply a new absolute project directory}"
. /home/openchip-env/env.sh
. /home/openchip-env/secrets.env
export OPENCHIP_MODEL_API_KEY
export PYTHONPATH="$REPO_DIR/src"
PYTHON_BIN="${OPENCHIP_PYTHON:-/home/openchip/.venv/bin/python}"
cd "$REPO_DIR"
set +e
"$PYTHON_BIN" -m openchip.cli.main compose --project "$PROJECT_DIR" \
  --request "$REPO_DIR/examples/registered_sum_request.md" --budget 20m
BUILD_EXIT=$?
"$PYTHON_BIN" "$REPO_DIR/examples/check_registered_sum.py" \
  "$PROJECT_DIR" "$REPO_DIR/examples/check_registered_sum.v"
CHECK_EXIT=$?
set -e
printf 'composition_exit=%s independent_check_exit=%s\n' "$BUILD_EXIT" "$CHECK_EXIT"
if [ "$BUILD_EXIT" -ne 0 ] || [ "$CHECK_EXIT" -ne 0 ]; then exit 1; fi
