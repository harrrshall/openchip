<p align="center">
  <img src="src/openchip/ui/static/logo.svg" alt="openchip logo" width="64" height="64">
</p>
<h1 align="center">openchip</h1>
<p align="center">describe hardware. generate rtl. inspect the verification evidence.</p>

openchip turns a hardware request into a project with a behavioral contract, a reference model, verilog source, and a verification report. use the browser interface to create a design, review its files, and request changes.

## start using openchip

[open the hosted app](https://13f5f45067271.notebooksn.jarvislabs.net).

deployed on 17 september 2026: the [verified cleanup release](https://github.com/harrrshall/openchip/commit/c4da68ca2ba1f0c8fece5e4f7cf065332240a117).

no owner-issued login is needed. each browser gets a private session. to start:

1. open settings and enter your own model provider, model, and api key. test the connection. provider usage is billed to your provider account.
2. create a project and describe the hardware, including ports, clock, reset, and expected behavior.
3. run build & verify. review the contract and report, then download the project or request a change.

try a request like:

> create an 8-bit counter with a rising-edge clock, synchronous active-high reset, and an enable input. reset sets the count to zero. enable increments the count with wraparound; otherwise it holds its value.

### privacy and session data

projects, settings, and downloads are isolated by a secure, httponly browser cookie. other browser sessions cannot list or access your projects. api keys stay in server memory; they are not saved in browser storage, project files, or activity records. re-enter your key after a service restart or an inactive session expires. download your work before clearing cookies: clearing them removes your access, while retained data remains on the service.

openchip retains submitted prompts, generated designs, build evidence, and session activity to operate and improve the product. do not submit confidential designs. hosted connections support the listed public provider endpoints; arbitrary local or private server urls are available only in a self-hosted installation.

### operate a hosted installation

set `OPENCHIP_HOSTED_ORIGIN` to the public https origin and put the ui behind an https reverse proxy that preserves the host header. `OPENCHIP_WORKSPACES` selects a persistent data directory. this enables private browser sessions instead of the shared owner login. existing owner projects remain outside the public sessions directory. the browser session authorizes access; an api key authorizes model calls only.

session data is retained under `OPENCHIP_WORKSPACES/sessions/<opaque-id>/`: `activity.sqlite3` records request time, method, route category, and response status; `settings.json` contains non-secret model settings; `projects/` retains prompts, model-generated artifacts, run databases, usage, and verification evidence. keep this directory private and back it up outside the published repository. request headers, cookies, and submitted api-key fields are excluded from activity records. hosted builds are limited to one per session and two concurrent builds overall.

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

`openchip doctor` must report `sandbox ok`. reference models execute inside a bubblewrap sandbox and there is no unsandboxed fallback, so a host where bubblewrap cannot create user namespaces fails every build at reference generation. on ubuntu 24.04 (including fresh cloud images and docker/colima virtual machines) the default apparmor restriction blocks this; allow it with:

```sh
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
echo kernel.apparmor_restrict_unprivileged_userns=0 | sudo tee /etc/sysctl.d/99-openchip-bwrap.conf
```

plain docker containers also block user namespaces through seccomp; use a virtual machine instead.

## use a hosted model through opencode go

[opencode go](https://opencode.ai/docs/go/) exposes kimi, deepseek, glm, qwen and minimax models behind one openai-style endpoint. openchip supports it out of the box and adds the required `x-opencode-session` header automatically. put the key in your environment and point a config at the gateway with the `openai` provider:

```sh
export OPENCODE_GO_API_KEY=sk-...
```

```toml
# openchip.toml
[model]
provider = "openai"                       # not "openai-compatible": the gateway rejects vllm-only request fields
base_url = "https://opencode.ai/zen/go/v1"
model = "kimi-k3"                         # fast and schema-clean; deepseek-v4-pro and glm-5.3-flash also work
api_key_env = "OPENCODE_GO_API_KEY"
max_tokens = 32000
temperature = 0.2
context_window = 128000
timeout_s = 600.0
thinking = true
```

```sh
openchip --config openchip.toml doctor          # model line must read ok
openchip --config openchip.toml init work/lfsr8 --request request.md --name lfsr8
openchip --config openchip.toml build --project work/lfsr8 --budget 25m
openchip --config openchip.toml report --project work/lfsr8
```

in the browser interface choose provider `openai`, enter the same base url, model and key in settings, and test the connection.

## how it works

1. a request becomes a versioned contract describing the interface and behavior.
2. openchip prepares a reference model and generates rtl against the contract.
3. verification runs lint, source simulation, synthesis, synthesized-netlist checks, and bounded formal checks where supported.
4. a bounded repair loop uses tool failures to revise the design and rerun verification.
5. the project retains source files, logs, `report.md`, and `outcome.json` so you can inspect each result.

the browser report preview supports headings, tables, bullet lists, fenced code, inline code and bold text. raw html is displayed as text. the project retains the original markdown report for download and further inspection.

a passing result is limited to the recorded contract, checks, and bounds. openchip is experimental; general production readiness is still being evaluated. review the contract and evidence before using a design. timing closure and silicon validation remain outside this workflow.

## cloud demo helpers

on a provisioned jarvislabs instance, the [demo launcher](scripts/cloud/run_demo.sh) accepts a core-v1 task id, request file, or request text:

```sh
bash scripts/cloud/run_demo.sh /home/openchip-runs/counter-demo updown_counter 20m
```

these helpers expect the repository at `/home/openchip` and environment/credentials in `/home/openchip-env/{env.sh,secrets.env}`. keep credentials outside the repository.

[interrupt_demo.sh](scripts/cloud/interrupt_demo.sh) exercises checkpoint recovery: it starts a build, interrupts it after reference generation, resumes, and reverifies the delivered artifacts. choose a fresh workspace; it refuses an existing workspace or `<workspace>.build.log`, including symlinks, and retains the log. it never deletes an earlier run.

```sh
bash scripts/cloud/interrupt_demo.sh /home/openchip-runs/counter-recovery updown_counter
```

### benchmark helpers

these scripts use the same provisioned cloud layout as the demo helpers:

- [bench_all.sh](scripts/cloud/bench_all.sh) provisions tools, serves the model configured in `model.env`, then runs core-v1, heldout-v1, VerilogEval direct and the agent subset.
- [bench_remote.sh](scripts/cloud/bench_remote.sh) runs that evaluation sequence against a remote provider. set `BENCH_FROM` to `core-v1`, `heldout-v1`, `veval-direct` or `veval-agent` to start at that stage; earlier stages are skipped.
- [experiment_fa.sh](scripts/cloud/experiment_fa.sh) compares review and alternate-reference configurations against the same primary model.
- [speed_compare.sh](scripts/cloud/speed_compare.sh) serves each supplied model configuration in turn on the same gpu, warms it up and runs core-v1.

see each script's usage comment for arguments. retain the logs and result summaries, and use their recorded verdicts to judge acceptance; `DONE` markers indicate script completion, not verification success.

### summarize recorded results

on the linux verification host, generate reports from retained result copies without new model calls:

```sh
python -m openchip.evals.compare /path/to/results-copy /path/to/model-comparison.md
python -m openchip.evals.fa_report /path/to/fa-experiment-copy /path/to/fa-report.md
```

the comparison reads run summaries and keeps the last directory in name order for each model/revision and protocol. the false-acceptance report reads configurations `D`, `A`, `B`, and `C`, using the first matching directory in name order for each protocol; it also writes `fa-report.json` inside the experiment copy. these commands summarize recorded evidence; they do not rerun verification.

### recheck evaluation results

on the linux verification host, use a copy of an evaluation results directory when rerunning these tools: they write verification artifacts and reports into that directory.

```sh
python -m openchip.evals.rescore /path/to/results-copy /path/to/suite
python -m openchip.evals.mutate /path/to/results-copy /path/to/suite
```

rescoring checks saved rtl against the suite reference without new model calls. mutation checking introduces small rtl faults and measures whether the model-derived and suite references detect them. both use the highest numbered contract snapshot, so `contract.v10.json` takes precedence over `contract.v9.json`. mutation sensitivity is not a completeness proof.

## architecture

- `src/openchip/contracts/` defines the design contract and its validation.
- `src/openchip/models/` connects to model providers.
- `src/openchip/runtime/` coordinates generation, repair, and project state.
- `src/openchip/tools/` and `src/openchip/verification/` run hardware tools and evaluate their results.
- `src/openchip/reporting/` records evidence; `src/openchip/ui/` serves the browser interface.
- `src/openchip/evals/` runs evaluations and summarizes or rechecks recorded results.

browse [examples](examples/) for sample requests and projects, and [configs](configs/) for configuration files.

## contribute

open an issue describing the user problem, or submit a focused pull request with:

- the behavior you changed and why it helps a user.
- a reproducible request or steps that demonstrate the problem.
- tool evidence showing the result before and after your change, with relevant regression checks.

## license

[apache-2.0](LICENSE).
