<p align="center">
  <img src="src/openchip/ui/static/logo.svg" alt="OpenChip chip logo" width="64" height="64">
</p>
<h1 align="center">OpenChip</h1>
<p align="center">Describe hardware. Generate RTL. Inspect the verification evidence.</p>

OpenChip turns a natural-language hardware request into a Verilog project with a behavioral contract, executable reference models, and a verification report. Use the browser interface or CLI to build a design, inspect the generated files, and request changes.

**OpenChip is experimental.** A passing result applies to the recorded contract, checks, and bounds. Review the contract and evidence before using a design; generated RTL is not a production-ready chip.

## Quick start

[Open the hosted app](https://13f5f45067271.notebooksn.jarvislabs.net) — no local installation required.

1. Open **Settings**, choose your model provider, and enter the model name and API key. Test the connection. Model usage is billed to your provider account.
2. Describe your hardware and give the project a name. Include signal widths, clock and reset behavior, and what should happen each cycle.
3. Select **Build & verify**. Review the contract, verification report, and generated files. Download the project or submit a change request.

Try this request:

> Create a Verilog module named counter with inputs clk, rst, and enable, and an 8-bit unsigned output count. Update on the rising edge of clk. A synchronous active-high reset sets count to zero and takes priority over enable. When enabled, increment with wraparound; otherwise hold the count.

For more detailed requests and example designs, browse [examples](examples/).

### Hosted privacy and access

Each browser receives a separate session. Download your work before clearing cookies: clearing them removes access to your session, but does not delete data retained by the service.

API keys remain in server memory and are not saved in browser storage, project files, or activity records. You may need to re-enter your key after a service restart or session expiry. Model requests are sent to the provider you configure.

The hosted service retains submitted prompts, generated designs, verification evidence, and session activity to operate and improve the product. Do not submit confidential designs. Hosted connections use the listed public provider endpoints; use a self-hosted installation for local or private model endpoints.

## What a build produces

- A versioned **behavioral contract** describing the interface and expected behavior.
- **Verilog RTL** and executable reference models used to check the design.
- **Tool evidence** from lint, simulation, synthesis, synthesized-netlist checks, and bounded formal checks where supported.
- A readable **`report.md`** and machine-readable **`outcome.json`**, with retained files and logs for inspection.

OpenChip uses tool failures to guide a bounded repair loop and reruns verification after changes. Interrupted builds can be resumed from checkpoints.

The contract matters: a design can satisfy an incorrect interpretation of your request. Check assumptions, reset behavior, priorities, and edge cases as well as the final verdict. Formal results are bounded, and skipped or timed-out checks are not proofs. Timing closure, physical implementation, and silicon validation are outside this workflow.

## Self-hosting

### Requirements

- Linux with Python 3.10 or newer. Use a Linux virtual machine for full verification on macOS or Windows.
- Icarus Verilog, Verilator, Yosys, SymbiYosys, and an SMT solver available on `PATH`.
- Bubblewrap with working user namespaces to sandbox generated reference code.
- A model provider account or a compatible model endpoint you operate.

The [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) bundles hardware verification tools. Install and activate the tools, and install Bubblewrap through your Linux package manager, before building designs.

### Install and open the interface

```sh
git clone https://github.com/harrrshall/openchip.git
cd openchip
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
openchip ui --open
```

The interface runs at [localhost:8765](http://127.0.0.1:8765). Configure your model in Settings and follow the quick start above. Browser settings and CLI configuration are separate; configure the CLI as described below before using it for builds.

Run `openchip doctor` to inspect tool availability, sandbox support, and the CLI model connection. Resolve missing prerequisites before building. If the sandbox check fails, check whether your host or container permits Bubblewrap user namespaces. Reference execution has no unsandboxed fallback.

### Configure the CLI model

Supported provider adapters are `openai`, `openai-responses`, `openai-compatible`, `openrouter`, and `anthropic`. Select the adapter that matches your endpoint. Model inference can run remotely; a local GPU is not required when using a remote provider.

Create `openchip.toml` in the repository root. This template is for an OpenAI-style chat-completions API; replace the endpoint and model placeholders with values from your provider:

```toml
[model]
provider = "openai"
base_url = "https://YOUR-PROVIDER-ENDPOINT/v1"
model = "YOUR-MODEL-ID"
api_key_env = "OPENCHIP_MODEL_API_KEY"
```

Load `OPENCHIP_MODEL_API_KEY` into your shell environment using your preferred secret-management method. Keep credentials out of configuration files and version control. Then check the connection:

```sh
openchip --config openchip.toml doctor
```

The CLI discovers `openchip.toml` automatically from the current directory; `--config` selects a different file. See [configs](configs/) for further options, including generation limits, verification settings, and build budgets. Example configurations target specific endpoints and may need adjustment for your model.

### Build from the command line

Save your hardware description in `request.md`, then run:

```sh
openchip init work/counter --request request.md --name counter
openchip build --project work/counter --budget 20m
openchip report --project work/counter
```

Inspect progress, request a change, or recover an interrupted build:

```sh
openchip status --project work/counter
openchip revise --project work/counter --change "Increase count to 16 bits." --budget 20m
openchip resume --project work/counter
```

Run `openchip verify --project work/counter` to recheck delivered artifacts, or `openchip --help` to explore all commands. Model configuration saved in `openchip.toml` applies to these commands when run from the repository root.

### Serve multiple users

For a public installation, set `OPENCHIP_HOSTED_ORIGIN` to the public HTTPS origin and place the UI behind an HTTPS reverse proxy that preserves the host header. This enables separate browser sessions. Set `OPENCHIP_WORKSPACES` to a private, persistent data directory and back it up outside the repository.

A browser session authorizes access to projects; a provider API key authorizes model calls. Configure retention and privacy disclosures for your installation before accepting other users' designs.

## Development and contributions

The implementation lives in [src/openchip](src/openchip/): contracts define behavior, model adapters connect providers, the runtime coordinates builds and repairs, and verification and reporting retain tool evidence. The browser interface is in [src/openchip/ui](src/openchip/ui/).

For evaluation workflows, see [src/openchip/evals](src/openchip/evals/) and the task definitions in [evals/suite](evals/suite/). Deployment and benchmark helpers live in [scripts/cloud](scripts/cloud/); read their prerequisites before running them.

To contribute, open an issue with a reproducible hardware request or steps to reproduce a problem. For pull requests, explain the user-visible change and include relevant tool evidence and regression checks. On a configured Linux verification host:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
```

Keep changes focused, and distinguish generated output from behavior verified by tools.

## License

[Apache License 2.0](LICENSE).
