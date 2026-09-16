#!/usr/bin/env bash
# Archive results and available logs, download and extract without overwriting,
# then pause. Keep both archives. Usage: harvest.sh <machine_id> <model-slug>
set -euo pipefail
ID=${1:?Usage: harvest.sh <machine_id> <model-slug>}
SLUG=${2:?Usage: harvest.sh <machine_id> <model-slug>}
if [[ ! $ID =~ ^[0-9]+$ || ! $SLUG =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Expected a numeric machine id and a model slug containing letters, digits, dots, underscores or hyphens." >&2
  exit 2
fi
source ~/.config/openchip/credentials.env
cd "$(dirname "$0")/../.."
mkdir -p evals/results work
DEST=$(mktemp -d "work/harvest-$SLUG.XXXXXX")
REMOTE="/home/openchip-runs/${DEST##*/}"
ARCHIVE="$DEST/results.tgz"
trap 'echo "Harvest failed; retained files: $DEST. Check the instance state before retrying." >&2' ERR

# Pass values as arguments, not interpolated shell source. Stage optional logs
# separately so earlier snapshots in evals/ remain untouched.
jl exec "$ID" -- bash -lc '
  set -euo pipefail
  slug=$1; stage=$2
  cd /home/openchip-runs/evals
  shopt -s nullglob
  results=(./*-$slug-*)
  if ((${#results[@]} == 0)); then
    echo "No results found for $slug" >&2
    exit 1
  fi
  mkdir "$stage"
  if [[ -f ../bench-$slug.log ]]; then cp "../bench-$slug.log" "$stage/bench-$slug.log"; fi
  if [[ -f ../vllm/server.log ]]; then cp ../vllm/server.log "$stage/vllm-$slug.log"; fi
  if [[ -f DONE-$slug ]]; then results+=("./DONE-$slug"); fi
  logs=("$stage"/*.log)
  for i in "${!logs[@]}"; do logs[$i]="./${logs[$i]##*/}"; done
  args=(czf "$stage/results.tgz" "${results[@]}")
  if ((${#logs[@]})); then args+=(-C "$stage" "${logs[@]}"); fi
  tar "${args[@]}"
' harvest "$SLUG" "$REMOTE"
jl download "$ID" "$REMOTE/results.tgz" "$ARCHIVE"
tar tzf "$ARCHIVE" > "$DEST/contents.txt"
# BSD tar can silently skip existing files with -k. Refuse any top-level
# collision first, so success means these results were actually imported.
while IFS= read -r entry; do
  entry=${entry#./}
  target="evals/results/${entry%%/*}"
  if [[ -e $target || -L $target ]]; then
    echo "Result already exists: $target. Archive retained at $ARCHIVE; instance not paused." >&2
    exit 1
  fi
done < "$DEST/contents.txt"
tar xzkf "$ARCHIVE" -C evals/results
echo "Extracted into evals/results; archive retained at $ARCHIVE"
jl pause "$ID" --yes --json
