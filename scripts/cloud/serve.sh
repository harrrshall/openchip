#!/usr/bin/env bash
# Start the vLLM OpenAI-compatible server on the cloud instance.
# Model/serving settings come from /home/openchip-env/model.env (OPENCHIP_MODEL, OPENCHIP_MODEL_REVISION,
# VLLM_MAX_MODEL_LEN, VLLM_EXTRA_ARGS); the API key from /home/openchip-env/secrets.env.
set -euo pipefail
export HOME=/home
ROOT=/home/openchip-env
source "$ROOT/secrets.env"
[ -f "$ROOT/model.env" ] && source "$ROOT/model.env"
export HF_HOME=/home/hf-cache HF_HUB_OFFLINE=1
MODEL="${OPENCHIP_MODEL:-Qwen/Qwen3-8B}"
REV="${OPENCHIP_MODEL_REVISION:-b968826d9c46dd6066d109eabc6255188de91218}"
MAXLEN="${VLLM_MAX_MODEL_LEN:-32768}"
mkdir -p /home/openchip-runs/vllm
RP="${VLLM_REASONING_PARSER-qwen3}"          # unset -> qwen3; set to "" -> no reasoning parser
RP_ARGS=(); [ -n "$RP" ] && RP_ARGS=(--reasoning-parser "$RP")
DT_ARGS=(); [ -z "${VLLM_DTYPE_ARGS+x}" ] && DT_ARGS=(--dtype bfloat16)
exec "$ROOT/venvs/vllm/bin/vllm" serve "$MODEL" --revision "$REV" \
  --host 0.0.0.0 --port 8000 --api-key "$OPENCHIP_MODEL_API_KEY" \
  --served-model-name "$MODEL" \
  --max-model-len "$MAXLEN" --gpu-memory-utilization 0.90 --max-num-seqs 16 \
  "${RP_ARGS[@]}" "${DT_ARGS[@]}" --seed 0 \
  ${VLLM_EXTRA_ARGS:-} \
  2>&1 | tee -a /home/openchip-runs/vllm/server.log
