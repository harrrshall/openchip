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

## Quick start (bring your own key)
```bash
pip install -e .            # Python 3.10+; install Icarus Verilog, Verilator and Yosys (OSS CAD Suite) for verification
openchip ui --open          # http://127.0.0.1:8765
```
In **Settings** choose OpenRouter, OpenAI, Anthropic or a local OpenAI-compatible server (vLLM), pick a model, paste your key, press **Test connection**, then describe your module and press **Build & verify**. Keys are stored only in `~/.config/openchip/keys.env` (mode 600); the environment variables `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `OPENCHIP_MODEL_API_KEY` work too. The run view shows the contract to review, live progress, the RTL and the final report; **Request a change** creates a new contract version and re-verifies.

For OpenCode Go chat-completion models, choose **OpenAI**, set the base URL to
`https://opencode.ai/zen/go/v1`, and enter the Go model ID and key. OpenChip sends
its own user agent and a session ID. Responses-only models are not supported.

Network binding requires `OPENCHIP_UI_TOKEN`, a secret of at least 32 characters.
Keep it in your protected environment file, then run `openchip ui --host 0.0.0.0`.
Access the deployment over HTTPS (or an SSH tunnel); the browser login uses
username `openchip` and that token as its password. API clients may use a Bearer
token. The default loopback UI needs no token. Cross-origin requests are rejected.
Generated reference Python requires Linux with the system Bubblewrap package
and permission to create namespaces. `openchip doctor` and the UI check this
prerequisite; execution stops if isolation is unavailable. References receive
only their inputs and a result file, with no host network or credential
environment. Restricted GPU containers may need a VM-based deployment.
EDA tools also run in isolated namespaces with a clean environment, explicit
read-only source inputs, and a private work-directory copy. Only regular output
files are collected; symlinks and special files are rejected. Install the trusted
toolchain in a traversable dedicated prefix such as `/opt/openchip-cad` and put
its `bin` directory on PATH. Namespace setup must work for the service account;
there is no unisolated fallback. Public multi-user hosting remains unsupported;
per-tenant authorization and aggregate resource quotas are not implemented.

## Command line
```bash
openchip doctor                                   # tools, model connectivity, features
openchip build --project ws/fifo --request "Create a synchronous FIFO ..." --budget 20m
openchip report --project ws/fifo                 # human report; --json for outcome.json
openchip verify --project ws/fifo                 # re-run the checks on the delivered artifacts
openchip revise --project ws/fifo --change "make dout registered"   # contract v2, re-verify
openchip resume --project ws/fifo                 # after an interruption
openchip eval --suite core-v1 --budget 15m        # locked golden suite
openchip assemble --system system.json --out top.v  # validate connections and generate a new top
openchip compose --project ws/registered-sum --request examples/registered_sum_request.md --budget 20m
```
Configuration: `configs/default.toml` (model endpoint, budgets, verification layers); alternative models in `configs/models/` (`--config`). Providers: `openai-compatible` (vLLM or any OpenAI-style server), `openai`, `openrouter`, `anthropic` (`OPENCHIP_PROVIDER`). An optional second model (`OPENCHIP_ALT_MODEL`, `OPENCHIP_ALT_BASE_URL`) supplies the cross-family reference used to corroborate acceptance, and an independent spec-review step checks the contract against the request before any code is written. No credentials in the repo.

`assemble` is an initial multi-module capability: supply a top contract, two to
four named instances with pinned leaf contracts and parameter bindings, and explicit
connections. It rejects floating inputs, conflicting drivers, incompatible widths
or signedness, stale contract pins, and combinational cycles. It generates named-port
wiring and refuses to overwrite an existing output file. It does not generate or
accept leaf RTL, or verify system behavior. Top widths are fixed at the top contract's
default parameter values; leaf parameter overrides are emitted explicitly.
`examples/composition_demo.py` builds a complete system JSON and demonstrates real
integration simulation and synthesis of two arithmetic leaves on the cloud toolchain.

`compose` starts from a natural-language request, builds two to four leaves through
the ordinary contract/reference/RTL workflow, and assembles their checked RTL.
Integration references receive the top contract without leaf RTL or references.
Failed or provisional leaves prevent system acceptance; an integration failure
preserves the assembly for diagnosis. This initial workflow supports fixed top
widths, shared clock/reset, and fresh workspaces; whole-system resume and automatic
wiring repair are not implemented. Each leaf and the integration retain reports
and evidence, with an aggregate `outcome.json` at the project root.
`openchip report --project PROJECT` displays the system verdict, individual stage
results, reference disagreement and artifact links; `--json` returns the saved
aggregate outcome. New compositions also save a top-level `report.md`, including
when a build fails. Reading a report never changes acceptance or reruns checks.

The registered saturating-sum development example passed a separate oracle over
all 65,536 operand pairs plus reset, hold, and enable checks on JarvisLabs using
`openai/gpt-oss-120b`. Run `examples/check_registered_sum.py PROJECT
examples/check_registered_sum.v` with the EDA toolchain to check that example's
delivered RTL independently. This is one development design, not the three-design
held-out composition gate or a guarantee for other requests.

## Repository
`src/openchip/` product · `tests/` (30 tests; real-tool tests need the EDA toolchain) · `evals/suite/core-v1/` locked tasks + goldens · `evals/results/` recorded runs · `outputs/demo/` delivered example packages (two successes, one useful failure) · `scripts/cloud/` provisioning/serving/eval scripts · `docs/` architecture, decisions, research, operations, product, project (STATUS, ROADMAP, BACKLOG, HANDOFF).

## Limitations (measured, not hypothetical)
- Single-clock synchronous designs only; no CDC, bus protocols, timing, power, or physical implementation.
- Two model-derived artifacts agreeing is evidence, not proof: the timer task shows all three derivations sharing one misreading. Human review of the contract remains part of delivery.
- Formal layer is bounded (depth 20) and uses immediate assertions only; the model's checkers still contain timing errors, so counterexamples are reported as non-blocking evidence.
- Public benchmarks (VerilogEval) not yet run; contamination of any public benchmark is unknowable.

License: Apache-2.0 (see `pyproject.toml`); third-party model and tool licenses apply to their artifacts.
