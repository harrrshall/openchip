#!/usr/bin/env bash
# OpenChip cloud provisioning for a JarvisLabs *container* instance.
# Everything is installed under /home (the only persistent path on containers).
# Idempotent: safe to re-run after pause/resume.
set -euo pipefail
export HOME=/home
ROOT=/home/openchip-env
TOOLS=$ROOT/tools
mkdir -p "$ROOT" "$TOOLS" /home/hf-cache /home/openchip-runs
cd "$ROOT"
echo "== provision start $(date -u +%FT%TZ) on $(hostname)"

# 1. OSS CAD Suite (yosys, sby, verilator, iverilog, solvers) -----------------
if [ ! -x "$TOOLS/oss-cad-suite/bin/yosys" ]; then
  TAG=$(curl -s https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest | python3 -c 'import sys,json;print(json.load(sys.stdin)["tag_name"])')
  STAMP=${TAG//-/}
  URL="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${TAG}/oss-cad-suite-linux-x64-${STAMP}.tgz"
  echo "== downloading $URL"
  curl -L -o "$TOOLS/oss-cad-suite.tgz" "$URL"
  tar -xzf "$TOOLS/oss-cad-suite.tgz" -C "$TOOLS"
  rm -f "$TOOLS/oss-cad-suite.tgz"
  echo "$TAG" > "$TOOLS/oss-cad-suite/OPENCHIP_RELEASE_TAG"
fi
export PATH="$TOOLS/oss-cad-suite/bin:$PATH"
echo "== oss-cad-suite $(cat $TOOLS/oss-cad-suite/OPENCHIP_RELEASE_TAG)"
yosys -V; iverilog -V | head -1; verilator --version; sby --help >/dev/null && echo "sby ok"

# 2. vLLM serving venv ----------------------------------------------------------
if [ ! -x "$ROOT/venvs/vllm/bin/vllm" ]; then
  uv venv --clear "$ROOT/venvs/vllm" --python 3.12
  uv pip install --python "$ROOT/venvs/vllm/bin/python" "vllm" "huggingface_hub[cli]" "hf_transfer"
fi
"$ROOT/venvs/vllm/bin/python" -c "import vllm, torch; print('vllm', vllm.__version__, 'torch', torch.__version__, torch.version.cuda)"

# 3. Model weights (from model.env when present; default = provisional model, ADR 0003) ---
[ -f "$ROOT/model.env" ] && source "$ROOT/model.env"
MODEL="${OPENCHIP_MODEL:-Qwen/Qwen3-8B}"
export HF_HOME=/home/hf-cache HF_HUB_ENABLE_HF_TRANSFER=1
"$ROOT/venvs/vllm/bin/hf" download "$MODEL" --revision "${OPENCHIP_MODEL_REVISION:-main}" 2>&1 | tail -3
"$ROOT/venvs/vllm/bin/python" - <<PY
import os
from huggingface_hub import HfApi
info = HfApi().model_info("$MODEL", revision=os.environ.get("OPENCHIP_MODEL_REVISION","main"))
print("model", info.id, "sha", info.sha)
PY

# 4. Environment file for later shells ------------------------------------------
cat > "$ROOT/env.sh" <<ENV
export HOME=/home
export PATH="$TOOLS/oss-cad-suite/bin:\$PATH"
export HF_HOME=/home/hf-cache
export OPENCHIP_ENV_ROOT=$ROOT
export OPENCHIP_MODEL_BASE_URL=http://127.0.0.1:8000/v1
ENV
df -h /home | tail -1
echo "== provision done $(date -u +%FT%TZ)"
