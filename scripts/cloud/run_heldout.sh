#!/usr/bin/env bash
# Held-out suite (thresholds pre-registered in docs/project/THRESHOLDS.md): 5 tasks x 2 repeats.
. /home/openchip-env/env.sh; . /home/openchip-env/secrets.env; export OPENCHIP_MODEL_API_KEY
cd /home/openchip && .venv/bin/openchip eval --suite heldout-v1 --budget ${1:-15m} --repeats ${2:-2} --out /home/openchip-runs/evals
