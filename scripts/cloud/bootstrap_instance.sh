#!/usr/bin/env bash
# Local helper: push everything a benchmark instance needs and launch bench_all. Usage: bootstrap_instance.sh <machine_id> <ip> <model-env-file>
set -euo pipefail
ID=${1:?Usage: bootstrap_instance.sh <machine_id> <ip> <model-env-file>}
REMOTE="root@${2:?Missing instance IP}"
MODEL_ENV=${3:?Missing model environment file}
CREDENTIALS=~/.config/openchip/credentials.env
[[ -r $MODEL_ENV && -r $CREDENTIALS ]] || { echo "Model environment and canonical credentials must be readable." >&2; exit 1; }
MODEL_ENV="$(cd "$(dirname "$MODEL_ENV")" && pwd)/$(basename "$MODEL_ENV")"
cd "$(dirname "$0")/../.."
SSH_OPTIONS=(-o StrictHostKeyChecking=yes -o LogLevel=ERROR -o ConnectTimeout=40)

ssh "${SSH_OPTIONS[@]}" "$REMOTE" 'mkdir -p /home/openchip-env /home/openchip /home/openchip-runs/vllm'
scp "${SSH_OPTIONS[@]}" scripts/cloud/provision.sh "$REMOTE:/home/provision.sh"
# Transfer directly to the protected canonical file, never through command text.
ssh "${SSH_OPTIONS[@]}" "$REMOTE" '
  set -eu
  umask 077
  secrets=/home/openchip-env/secrets.env
  touch "$secrets"
  chmod 600 "$secrets"
  cat > "$secrets"
' < "$CREDENTIALS"
scp "${SSH_OPTIONS[@]}" "$MODEL_ENV" "$REMOTE:/home/openchip-env/model.env"
scp "${SSH_OPTIONS[@]}" scripts/cloud/serve.sh "$REMOTE:/home/openchip-env/serve.sh"
ssh "${SSH_OPTIONS[@]}" "$REMOTE" 'chmod +x /home/openchip-env/serve.sh'
rsync -a --timeout=120 --exclude .git --exclude work --exclude runs --exclude outputs --exclude evals/results \
  --exclude .venv --exclude __pycache__ --exclude .pytest_cache -e "ssh ${SSH_OPTIONS[*]}" ./ "$REMOTE:/home/openchip/"

source "$CREDENTIALS"
jl run --on "$ID" --json --yes -- bash -lc '
  set -ae
  . /home/openchip-env/secrets.env
  set +a
  exec bash /home/openchip/scripts/cloud/bench_all.sh
' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(sys.argv[1], "bench run_id", d.get("run_id"), d.get("error", ""))' "$ID"
