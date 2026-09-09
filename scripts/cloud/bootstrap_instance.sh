#!/usr/bin/env bash
# Local helper: push everything a benchmark instance needs and launch bench_all. Usage: bootstrap_instance.sh <machine_id> <ip> <model-env-file>
set -euo pipefail
ID=$1; IP=$2; ENVF=$3
S=/private/tmp/claude-501/-Users-harshalsingh-Desktop-experiment-openchip/da4ea623-8f4e-4e7d-b390-c8da5a45ff33/scratchpad
SSH="ssh -o StrictHostKeyChecking=no -o LogLevel=ERROR -o ConnectTimeout=40"
$SSH root@$IP 'mkdir -p /home/openchip-env /home/openchip /home/openchip-runs/vllm'
scp -o StrictHostKeyChecking=no -o LogLevel=ERROR -o ConnectTimeout=40 scripts/cloud/provision.sh root@$IP:/home/provision.sh
scp -o StrictHostKeyChecking=no -o LogLevel=ERROR -o ConnectTimeout=40 $S/secrets.env root@$IP:/home/openchip-env/secrets.env
scp -o StrictHostKeyChecking=no -o LogLevel=ERROR -o ConnectTimeout=40 "$ENVF" root@$IP:/home/openchip-env/model.env
scp -o StrictHostKeyChecking=no -o LogLevel=ERROR -o ConnectTimeout=40 scripts/cloud/serve.sh root@$IP:/home/openchip-env/serve.sh
$SSH root@$IP 'chmod 600 /home/openchip-env/secrets.env; chmod +x /home/openchip-env/serve.sh'
rsync -a --delete --timeout=120 --exclude .git --exclude work --exclude runs --exclude .venv --exclude __pycache__ --exclude '.pytest_cache' -e "$SSH" ./ root@$IP:/home/openchip/
source ~/.config/openchip/credentials.env
jl run --on $ID --json --yes -- bash -lc "HF_TOKEN=$HF_TOKEN bash /home/openchip/scripts/cloud/bench_all.sh" | python3 -c "import sys,json; d=json.load(sys.stdin); print('$ID bench run_id', d.get('run_id'), d.get('error',''))"
