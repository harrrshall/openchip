# OpenChip

**Natural-language request → RTL project with reproducible verification evidence.**

OpenChip is an autonomous hardware-development agent. You describe a module; it derives a reviewable design contract, an independent executable reference, Verilog RTL, and a formal property checker; runs real tools (Verilator lint, Icarus simulation against the reference, Yosys synthesis, SymbiYosys bounded model checking); repairs from tool evidence within a budget; and delivers a package whose every claim is tied to a tool result and an artifact hash.

Status: **Milestone 2 path works end to end; Milestone 3 partially; runtime model chosen by measurement (ADR 0006).** Ten open-weight models were run through the identical protocol on JarvisLabs. Default is now `openai/gpt-oss-120b` (VerilogEval v2 direct 114/156 = 73.1%, OpenChip agent mode 28/39, project suites 9/10 and 8/10); runner-up `Qwen/Qwen3.8-27B` (project suites 10/10 and 8/10 with zero false acceptances, VerilogEval 76/156). Full table: `evals/results/model-comparison.md`; evidence per run in `evals/results/`. This is an RTL generator with verification evidence, not a chip.

## How it works
```
request → contract (JSON, versioned, requirement provenance)
        → reference model (Python, derived without seeing the RTL)
        → property checker (Verilog immediate assertions, optional)
        → RTL (Verilog-2001)
        → lint · sim vs reference (3 seeds × 400 cycles) · generic synth · BMC
        → repair loop (bounded, every attempt kept) with reference cross-check (2-of-3)
        → report.md + outcome.json (requirement-to-evidence index, hashes, tool/model manifest)
```
Design: `docs/architecture/overview.md`. Decisions: `docs/decisions/`.

## Running it (cloud instance; see `docs/operations/cloud.md`)
```bash
openchip doctor                                   # tools, model connectivity, features
openchip build --project ws/fifo --request "Create a synchronous FIFO ..." --budget 20m
openchip report --project ws/fifo                 # human report; --json for outcome.json
openchip verify --project ws/fifo                 # re-run the checks on the delivered artifacts
openchip revise --project ws/fifo --change "make dout registered"   # contract v2, re-verify
openchip resume --project ws/fifo                 # after an interruption
openchip eval --suite core-v1 --budget 15m        # locked golden suite
```
Configuration: `configs/default.toml` (model endpoint, budgets, verification layers); alternative models in `configs/models/` (`--config`). Model: any OpenAI-compatible endpoint; the reference setup is vLLM on a JarvisLabs instance (`scripts/cloud/model-envs/*.env` + `serve.sh`). No credentials in the repo.

## Repository
`src/openchip/` product · `tests/` (30 tests; real-tool tests need the EDA toolchain) · `evals/suite/core-v1/` locked tasks + goldens · `evals/results/` recorded runs · `outputs/demo/` delivered example packages (two successes, one useful failure) · `scripts/cloud/` provisioning/serving/eval scripts · `docs/` architecture, decisions, research, operations, product, project (STATUS, ROADMAP, BACKLOG, HANDOFF).

## Limitations (measured, not hypothetical)
- Single-clock synchronous designs only; no CDC, bus protocols, timing, power, or physical implementation.
- Two model-derived artifacts agreeing is evidence, not proof: the timer task shows all three derivations sharing one misreading. Human review of the contract remains part of delivery.
- Formal layer is bounded (depth 20) and uses immediate assertions only; the model's checkers still contain timing errors, so counterexamples are reported as non-blocking evidence.
- Public benchmarks (VerilogEval) not yet run; contamination of any public benchmark is unknowable.

License: Apache-2.0 (see `pyproject.toml`); third-party model and tool licenses apply to their artifacts.
