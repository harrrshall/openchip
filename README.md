<p align="center">
  <img src="assets/logo.svg" width="96" height="96" alt="openchip logo">
</p>

<h1 align="center">openchip</h1>

<p align="center">describe a hardware module in plain language. get verilog rtl with tool-backed evidence that it does what you asked.</p>

<p align="center">
  <a href="https://13f5f45067272.notebooksn.jarvislabs.net">try it</a> ·
  <a href="#start-in-two-minutes">start</a> ·
  <a href="#how-it-works">how it works</a> ·
  <a href="#what-the-numbers-say">numbers</a> ·
  <a href="#contributing">contribute</a>
</p>

---

## what it does

you write a request like "a synchronous fifo with depth 16, 8-bit words, full and empty flags". openchip turns it into a reviewable contract, an independent reference model, verilog rtl and a report. every claim in the report points at a tool result: verilator lint, icarus simulation against the reference, yosys synthesis and, when available, symbiyosys bounded model checking. when the tools disagree with the design, openchip repairs within a budget. when the request does not determine the answer, it asks instead of guessing.

the web ui shows the whole process as it happens: which stage is running, what each stage found, and anything that blocks it such as a missing key, a rate limit or an exhausted quota.

## start in two minutes

hosted version: https://13f5f45067272.notebooksn.jarvislabs.net

open it, press settings, paste your own model key and start describing modules. the verilog tools are already installed there. the page has no login, so treat it as a shared demo: do not paste a key you cannot rotate, and expect other visitors to see the session list.

to run it on your own machine instead:

requirements: python 3.10 or newer, and the open-source verilog tools (icarus verilog, verilator, yosys). on macos: `brew install icarus-verilog verilator yosys`. on linux the oss cad suite bundle gives you all of them: https://github.com/YosysHQ/oss-cad-suite-build/releases

```bash
git clone https://github.com/harrrshall/openchip.git
cd openchip
pip install -e .
openchip doctor        # checks the tools
openchip ui --open     # opens http://127.0.0.1:8765
```

in the ui press settings, pick a provider (opencode go, openrouter, openai or anthropic), paste your key and press test connection. then describe your module and press build and verify. type `/` in the request box for commands: `/resume` lists every past session and lets you open or continue one.

keys are stored only in `~/.config/openchip/keys.env` with mode 600. nothing is sent anywhere except to the model provider you chose.

command line, if you prefer it:

```bash
openchip build --project ws/fifo --request "create a synchronous fifo ..." --budget 20m
openchip report --project ws/fifo
openchip revise --project ws/fifo --change "make dout registered"
openchip resume --project ws/fifo
```

## how it works

```
request
  -> contract        json, versioned, one entry per requirement, plus explicit state machines,
                     update priorities and timing conventions when the request describes them
  -> reference       an executable python model written from the contract, never from the rtl
  -> rtl             verilog-2001
  -> checks          lint, simulation against the reference (3 seeds x 400 cycles), synthesis,
                     bounded model checking, replay of any table or waveform printed in the request
  -> sign-off        accepted only when independent references agree and no gate objects;
                     otherwise withheld with the reason, or provisional with the open questions
  -> report          report.md and outcome.json with hashes of every artifact
```

the parts that matter most for correctness:

- the request's printed interface is authoritative. rtl with an extra or missing port is rejected before simulation.
- tables, karnaugh maps and waveforms in the request are parsed mechanically and replayed against the reference and the rtl, so a misread axis or a missed wrap point is caught rather than silently agreed on.
- state machines are written as explicit transition tables, and the reference is checked against the table before sign-off.
- a design is never signed off on a split reference vote or on an unanswered question about the request.

architecture notes live in `docs/architecture/`, every decision in `docs/decisions/` as an adr with the measurement that justified it.

## what the numbers say

all runs use the identical protocol and the recorded evidence is in `evals/results/`.

- verilogeval v2 spec-to-rtl, all 156 problems twice, self-hosted `openai/gpt-oss-120b`: 76% pass; of the designs openchip signs off, 89% are correct. two problems in that benchmark contradict their own hidden reference and are counted as misses.
- the project's own realistic suites (core-v1 and heldout-v1): 15 of 20 tasks correct, and 0 wrong designs among those signed off.
- hosted frontier models score higher on the same harness (deepseek v4 flash reached 32 of 39 with 1 false sign-off on the standard subset). the harness matrix in `configs/matrix/` runs any set of models and pipeline variants side by side and ranks them by false sign-offs first.

this is an rtl generator with verification evidence. it is single-clock synchronous designs only, no clock domain crossing, bus protocols, timing or physical implementation. two model-derived artifacts agreeing is evidence, not proof; read the contract before you trust the rtl.

## repository

```
src/openchip/       product: contracts, models, runtime, verification, reporting, ui, evals
tests/              real-behaviour tests; the ones marked cloud need the verilog tools
evals/suite/        locked tasks and goldens (never edited to make a run pass)
evals/results/      every recorded run
configs/            default config, model configs, harness matrix specs
scripts/cloud/      provisioning and benchmarking on gpu instances
docs/               architecture, decisions, research, operations, product, project
```

## contributing

contributions are welcome. the rules keep the evidence honest.

1. open an issue first for anything that changes behaviour. say what failure you measured and what you expect to change.
2. never edit `evals/suite/` goldens or locked tasks to make a run pass.
3. a change to the pipeline needs a pre-registered success threshold in `docs/project/THRESHOLDS.md` before the run, a measurement on the recorded data or a live run, and an adr in `docs/decisions/` whether it is kept or reverted.
4. write tests that exercise real behaviour. a test that only proves the code was called is not wanted.
5. no third-party runtime dependencies in the product without an adr. the ui stays a single page with no build step.
6. no credentials in the repository, ever. keys come from the environment or `~/.config/openchip/`.
7. keep prose direct, keep functions small, and run `pytest` before you push.
8. one topic per pull request, with the measurement in the description.

## license

apache 2.0. model and tool licenses apply to their own artifacts.
