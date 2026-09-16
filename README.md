# OpenChip

**Natural-language request → RTL project with reproducible verification evidence.**

OpenChip is an autonomous hardware-development agent. You describe a module; it derives a reviewable design contract, an independent executable reference, Verilog RTL, and a formal property checker; runs real tools (Verilator lint, Icarus simulation against the reference, Yosys synthesis, SymbiYosys bounded model checking); repairs from tool evidence within a budget; and delivers a package whose every claim is tied to a tool result and an artifact hash.

Status: **Experimental RTL development workflow with bounded verification evidence.** General production readiness is not established. Historical model benchmarks are retained in `evals/results/model-comparison.md`; those results are specific to their recorded models and protocols. OpenChip produces RTL projects, not manufacturable chips.

## How it works
```
request → contract (JSON, versioned, requirement provenance)
        → reference model (Python, derived and reviewed without candidate RTL)
        → property checker (Verilog immediate assertions, optional)
        → RTL (Verilog-2001)
        → lint · sim vs reference (3 seeds × 20000 cycles) · generic synth · BMC
        → repair loop (bounded, every attempt kept) with independent reference cross-check
        → report.md + outcome.json (requirement-to-evidence index, hashes, tool/model manifest)
```
Each reference is reviewed against the request and contract in its own context, without the candidate RTL or another generated reference. Drafts are retained. Reference disagreement still withholds sign-off; review and model agreement are not proofs.

Measured examples include a [UART transmitter](examples/uart_tx8n1/README.md),
[512-cell Rule 110 engine](examples/rule110/README.md),
[saturating event counter](examples/event_counter/README.md),
[reloadable timer](examples/reloadable_timer/README.md),
[serial programmable timer](examples/serial_timer/README.md),
[walking/falling/digging controller](examples/directional_controller/README.md),
[continuous packet framer](examples/ps2_framer/README.md), and
[counter with nonzero port indices](examples/range_counter/README.md), and its
[browser-revised subtraction variant](examples/range_down_counter/README.md). Each includes actual
RTL, a separate runnable bench, provenance and the limits of its measurements.
Complete explicit elementary-cell transition requests are checked against their
printed rows before generated references enter arbitration; power-up before a
load is not treated as initialized state.
The complete walking/falling/digging request in the controller example also has
an independent transition check and formal checker. Recognition is limited to
that complete specification; it is not a general natural-language FSM parser.


## Quick start (bring your own key)
```bash
pip install -e .            # Python 3.10+; install Icarus Verilog, Verilator and Yosys (OSS CAD Suite) for verification
openchip ui --open          # http://127.0.0.1:8765
```
In **Settings** choose OpenRouter, OpenAI (Chat Completions), a Responses-compatible endpoint, Anthropic or a local OpenAI-compatible server (vLLM), pick a model, paste your key, press **Test connection**, then describe your module and press **Build & verify**. Keys are stored only in `~/.config/openchip/keys.env` (mode 600); the environment variables `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `OPENCHIP_MODEL_API_KEY` work too. For the same credential variable, a key saved in Settings takes precedence over an inherited environment value, including after restart. The run view shows the contract to review, live progress, the RTL and the final report; **Request a change** creates a new contract version and re-verifies.

After a recorded transient provider failure, **Retry provider request** resumes
from the saved checkpoint when budget remains. It keeps the original model
configuration, elapsed time, token usage and call limits. It cannot replenish an
exhausted budget or restart a completed build.

For a Responses endpoint, use `provider = "openai-responses"` and its base URL
(without `/responses`) in the model configuration. The adapter sends
`max_output_tokens`; an optional `[model.extra_body] reasoning_effort = "low"`
selects a requested reasoning level when the endpoint supports it. Incomplete or
refused responses fail explicitly. Model support and data handling depend on the
chosen provider; selecting the protocol does not change the model automatically.

Experimental checker recovery is disabled by default. Set
`[verification] review_counterexamples = true` to allow one independent review
of a model-generated checker after an optional-formal counterexample. A configured
`[model.review]` supplies the reviewer; otherwise the main model is used. The
reviewer receives the request, contract, supporting documents and checker.
Original evidence is retained, and only a successful bounded formal recheck can
resolve that counterexample. This does not establish unbounded correctness.


For OpenCode Go chat-completion models, choose **OpenAI**, set the base URL to
`https://opencode.ai/zen/go/v1`, and enter the Go model ID and key. OpenChip sends
its own user agent and a session ID. For a Responses-only model, select the
Responses-compatible provider and use its documented endpoint and model ID.

The report's `thinking_requested` field (and legacy `thinking` alias) describes
configuration, not verified provider behavior. Effective reasoning is recorded
as unknown. Automatic retries with thinking disabled apply only to the
OpenAI-compatible route that sends `enable_thinking`; hosted routes that do not
send that toggle no longer repeat an identical request on truncation.


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

Generated RTL is restricted to clocked reset logic and synthesizable data-path
constructs. Simulator control, file/system tasks, initial blocks and cross-hierarchy
references are rejected after preprocessing. Value functions such as `$clog2`
remain supported. If formal checking is required, missing or failed formal
evidence blocks acceptance. A recorded formal counterexample always withholds
sign-off pending review of the RTL or property checker, even for optional formal
checking. Unresolved contract questions also withhold sign-off until clarified;
artifacts and tool evidence remain available for review. Timeouts and skipped
checks are never described as formal passes.

Formal checking requires at least one executable assertion in the elaborated
checker. Comments, disabled generate branches and cover-only modules cannot
produce a formal pass. This presence check does not establish that assertions
are sufficient or non-vacuous. A required-formal run with an invalid checker
withholds acceptance; optional formal reports the error without claiming a pass.


Single-clock designs may use a rising or falling active edge. Resetless designs
can declare `clock_reset.conditioning`: a bounded sequence of complete input
vectors that physically establishes state before simulation comparisons. The
harness applies the same sequence to the reference and RTL; it never initializes
DUT registers or ignores unknown outputs. The report records this startup scope;
power-up behavior is not verified. An empty sequence uses three zero-data edges.
Dual-edge logic and compositions mixing active clock edges remain unsupported.
General production readiness is not established.

Width expressions use bounded integer arithmetic; `/` truncates toward zero.
They accept parameter names, `clog2` of positive integers, and `min`/`max`.
Strings, floating-point values and excessively large or complex expressions are
rejected before tool execution. Limits are 4096 expression characters, 256 syntax
nodes, 64 nesting levels and 4096 bits per intermediate integer.

Imported and generated contracts must explicitly set `clock_reset.reset` to the
exact reset input name, or `null` for a resetless interface. Omitting it is a
validation error; OpenChip no longer assumes an undeclared `rst` port.


Descending packed ports can set `lsb` in the contract. For example, `width: 4,
lsb: 1` describes `[4:1]`. References still receive unsigned packed values: declared
bit `k` has integer weight `2**(k-lsb)`. The default lower index is zero. This does
not add support for ascending ranges.

The UI and `openchip report` compare current files with the recorded artifact
hashes. Changed, missing or unrecorded RTL files cannot inherit an earlier run's
sign-off. Downloads retain historical reports and include
`CURRENT_WORKSPACE_STATUS.json`; changed workspaces also include a warning.
Restoring the exact recorded files restores that historical acceptance view.

Simulation requires a positive integer `sim_cycles` and at least one integer
seed. Empty schedules are rejected; compiling and synthesizing a design without
simulation observations cannot produce acceptance.

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
Configuration: `configs/default.toml` (model endpoint, budgets, verification layers); alternative models in `configs/models/` (`--config`). Providers: `openai-compatible` (vLLM or any OpenAI-style server), `openai`, `openai-responses`, `openrouter`, `anthropic` (`OPENCHIP_PROVIDER`). An optional second model (`OPENCHIP_ALT_MODEL`, `OPENCHIP_ALT_BASE_URL`) supplies the cross-family reference used to corroborate acceptance, and an independent spec-review step checks the contract against the request before any code is written. No credentials in the repo.

A measured serially programmed timer, with a full-transaction bench and recovery
provenance, is available in [`examples/serial_timer`](examples/serial_timer/).

Formal depth must be an integer of at least 3 because initialization skips the
first two steps. The default remains 20. This minimum prevents an empty check;
it does not establish sufficient coverage or assertion non-vacuity.

CLI rechecks retain recorded formal counterexamples for unchanged RTL and
contract. Disabling formal or shortening its bound cannot clear those results.
A corrected checker must pass at least the recorded depth before the old
counterexample is resolved. Historical receipts remain unchanged.

New configurations default to 20000 simulation cycles per seed. Explicit
`[verification] sim_cycles` settings and saved-run configurations retain their
chosen values. Longer timers or transactions can require a larger window; set
`sim_cycles` in your build configuration or use `openchip verify --cycles` with
the desired count on an existing project.
This command preserves the original report and writes separate verification
evidence. Recorded simulation failures for the same RTL, reference and
contract identity continue to withhold sign-off, even when a shorter recheck
passes. The new evidence links the retained failing results. Check that the stimulus actually reaches completion, acknowledgment
and restart; more cycles alone do not establish those behaviors. Bounded formal
depth is also a limit, not a claim that a long transaction was completed.

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
Revisions retain hashed copies of generated sources and reports under
`retained/`, included in the downloaded bundle. Earlier verification directories
remain in place. Legacy files already overwritten before retention was introduced
cannot be reconstructed automatically; missing or changed bytes are recorded.

`src/openchip/` product · `tests/` verification checks · `examples/` runnable
designs and benches · `evals/suite/` locked acceptance tasks · `evals/results/`
recorded benchmark summaries · `scripts/cloud/` cloud operations.

## Limitations (measured, not hypothetical)
- Combinational and single-clock RTL are the main supported scope. Level-sensitive latches are not currently validated reliably. CDC, timing closure, power and physical implementation are outside the verified scope.
- Two model-derived artifacts agreeing is evidence, not proof: the timer task shows all three derivations sharing one misreading. Human review of the contract remains part of delivery.
- Formal checking is bounded (default depth 20) and uses immediate assertions. Generated checkers can contain timing or initialization errors; a counterexample withholds sign-off pending review, including when formal checking is optional.
- Public VerilogEval runs and historical model comparisons have been recorded. Results apply only to their model, source and protocol; training contamination is unknown. General production readiness remains unproven.

License: Apache-2.0 (see `pyproject.toml`); third-party model and tool licenses apply to their artifacts.
