<p align="center">
  <img src="src/openchip/ui/static/logo.svg" alt="openchip logo" width="64" height="64">
</p>
<h1 align="center">openchip</h1>
<p align="center">describe hardware. generate rtl. inspect the verification evidence.</p>

openchip turns a hardware request into a project with a behavioral contract, a reference model, verilog source, and a verification report. use the browser interface to create a design, review its files, and request changes.

## start using openchip

[open the hosted app](https://13f5f45067271.notebooksn.jarvislabs.net).

this deployment requires credentials from its owner. after signing in:

1. open settings and configure your model provider, model, and api key. test the connection.
2. create a project and describe the hardware, including ports, clock, reset, and expected behavior.
3. run build & verify. review the contract and report, then download the project or request a change.

try a request like:

> create an 8-bit counter with a rising-edge clock, synchronous active-high reset, and an enable input. reset sets the count to zero. enable increments the count with wraparound; otherwise it holds its value.

## run locally

use linux with python 3.10 or newer. full verification needs bubblewrap with working user namespaces, icarus verilog, verilator, yosys, symbiyosys, and an smt solver. the [oss cad suite](https://github.com/YosysHQ/oss-cad-suite-build) provides the hardware tools; follow its installation instructions and activate its environment first. install bubblewrap through your linux package manager. on macos or windows, use a linux virtual machine for verification.

```sh
git clone https://github.com/harrrshall/openchip.git
cd openchip
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
openchip doctor
openchip ui --open
```

resolve missing tools reported by `openchip doctor` before building. the interface opens at [localhost:8765](http://127.0.0.1:8765). configure your model connection in settings, then follow the same project workflow above. model inference can use a remote provider or a compatible endpoint you run yourself.

## how it works

1. a request becomes a versioned contract describing the interface and behavior.
2. openchip prepares a reference model and generates rtl against the contract.
3. verification runs lint, source simulation, synthesis, synthesized-netlist checks, and bounded formal checks where supported.
4. a bounded repair loop uses tool failures to revise the design and rerun verification.
5. the project retains source files, logs, `report.md`, and `outcome.json` so you can inspect each result.

a passing result is limited to the recorded contract, checks, and bounds. openchip is experimental; general production readiness is still being evaluated. review the contract and evidence before using a design. timing closure and silicon validation remain outside this workflow.

## architecture

- `src/openchip/contracts/` defines the design contract and its validation.
- `src/openchip/models/` connects to model providers.
- `src/openchip/runtime/` coordinates generation, repair, and project state.
- `src/openchip/tools/` and `src/openchip/verification/` run hardware tools and evaluate their results.
- `src/openchip/reporting/` records evidence; `src/openchip/ui/` serves the browser interface.

browse [examples](examples/) for sample requests and projects, and [configs](configs/) for configuration files.

## contribute

open an issue describing the user problem, or submit a focused pull request with:

- the behavior you changed and why it helps a user.
- a reproducible request or steps that demonstrate the problem.
- tool evidence showing the result before and after your change, with relevant regression checks.

keep verification gates intact. never change acceptance fixtures or expected results just to make a run pass. changes to locked acceptance assets require a separate reviewed rationale. keep credentials, private logs, and generated workspaces out of commits.

for this repository, run tests, inference, simulation, synthesis, and evals on jarvislabs. local contributor work is limited to editing, inspection, and syncing. coordinate cloud access with the maintainer before running those checks.

## license

[apache-2.0](LICENSE).
