#!/usr/bin/env bash
# Export the curated, publishable subset of this repository to the private GitHub repo.
# Internal material never leaves this machine: OPENCHIP_PROJECT_BRIEF.md, AGENTS.md, docs/ (status, handoff,
# backlog, research, decisions), outputs/, work/, runs/, per-task eval workspaces, logs, credentials.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="${OPENCHIP_PUBLIC_DIR:-$SRC/../openchip-public}"
REMOTE="${OPENCHIP_PUBLIC_REMOTE:-https://github.com/harrrshall/openchip.git}"
MSG="${1:-Sync from internal repository}"
if [ ! -d "$DST/.git" ]; then git clone -q "$REMOTE" "$DST" 2>/dev/null || { mkdir -p "$DST" && git -C "$DST" init -q -b main && git -C "$DST" remote add origin "$REMOTE"; }; fi
# curated tree
rsync -a --delete \
  --exclude '.git' --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude '.venv' \
  --include '/README.md' --include '/LICENSE' --include '/pyproject.toml' --include '/.gitignore' \
  --include '/src/***' --include '/tests/***' --include '/configs/***' --include '/scripts/***' --include '/examples/***' --include '/ui/***' --include '/assets/***' \
  --include '/evals/' --include '/evals/suite/***' --include '/evals/results/' --include '/evals/results/model-comparison.md' \
  --include '/evals/results/*/' --include '/evals/results/*/summary.md' --include '/evals/results/*/summary.json' \
  --exclude '*' \
  "$SRC/" "$DST/"
# belt and braces: nothing internal may be present
for f in OPENCHIP_PROJECT_BRIEF.md AGENTS.md docs outputs work runs; do rm -rf "$DST/$f"; done
find "$DST" -name '*.env' ! -path '*/model-envs/*' -delete
find "$DST" -name 'records.jsonl' -delete
cd "$DST"
git add -A
if git diff --cached --quiet; then echo "nothing to publish"; exit 0; fi
git -c user.name="Harshal Singh" -c user.email="harshalsingh1223@gmail.com" commit -q -m "$MSG"
git push -q -u origin main
echo "published: $(git rev-parse --short HEAD) -> $REMOTE"
