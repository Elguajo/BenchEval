# BenchEval

Instruction-aware benchmark runner for LLMs and coding agents.

BenchEval measures whether a model or agent achieves the goal, produces a correct
response, and acts according to the supplied instructions. Its three evaluation
axes are **Outcome**, **Instruction fidelity**, and **Behavior**. A hard-rule
violation fails a scenario even when its outcome is correct.

## Project status

The first executable response slice is implemented (0.1.0). It runs Codex CLI
using an existing ChatGPT subscription login, without an API-key fallback.
This is **not yet the full v1**: coding-agent scenarios, Claude, LLM judges,
suite comparison, and the report UI are pending.

- [Current status and evidence](docs/current-status.md).

- [Implementation plan](docs/implementation-plan.md): product contract,
  architecture, delivery stages, and acceptance criteria.
- [Upstream inventory](docs/upstream-inventory.md): specific DeepEval and
  AgentEval sources to reuse, adaptations, and provenance requirements.

The planned first release supports response scenarios and coding-agent scenarios
through locally authenticated Codex CLI and Claude Code CLI. Authentication stays
with the official tools; BenchEval does not extract subscription credentials.

The project builds on selected ideas and interfaces from
[DeepEval](https://github.com/confident-ai/deepeval) and
[AgentEval](https://github.com/lukasmetzler/agenteval). Adoption is incremental,
with source revisions and tests recorded for each reused component.

## Quick start

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Codex CLI on macOS
or Linux. BenchEval checks CLI capabilities rather than guessing from its version;
the live smoke run was verified with Codex CLI 0.147.0.

From the repository root:

```sh
uv sync --locked
uv run bencheval doctor
uv run bencheval validate examples/response/arithmetic.yaml
uv run bencheval run examples/response/arithmetic.yaml
```

`doctor` and `validate` do not call a model. If subscription login is missing,
authenticate yourself with `codex login` using ChatGPT, then rerun `doctor`.
BenchEval neither logs you in nor reads/copies your credential files.
The official CLI handles authentication. Each `run` consumes subscription usage;
the scenario prompt and explicit instructions are sent to the selected provider.

Create your own scenario with `uv run bencheval init scenario.yaml`. Existing
files are never overwritten. Change its prompt, instructions, policies, and
explicit checks; prose policies alone do **not** create automatic checks.
Instruction files must stay inside the scenario directory. Their contents and
hashes are snapshotted before execution.

Supported checks: `equals` (exact text, including whitespace), `contains`, `regex`,
`json_schema` (inline draft 2020-12; no references; `format` is an annotation), and
`no_tools` (observed CLI tool actions, including planning and collaboration).
Every check declares its axes and `hard` or `advisory` severity. At least one hard
outcome check is required. Invalid YAML, duplicate keys, unknown fields, malformed
schemas, and conflicting hard exact-answer checks are rejected before a model call.

## Results and evidence

There is no universal averaged score. A proven hard violation produces `FAIL`;
missing mandatory evidence, checker errors, or an incomplete execution produce
`INCONCLUSIVE`, unless a hard violation is already proven. An axis with no checks
is `NOT_OBSERVABLE`. Explicitly inapplicable checks use `NOT_APPLICABLE`.
Advisory failures remain visible on their axes but do not fail the overall result.
Execution status (authentication, quota, timeout, cancellation, error, completed)
is separate from the evaluation verdict.

Each run prints its artifact directory under `.bencheval/runs/`. It contains the
exact prompt, scenario/instruction snapshots, response, raw CLI streams, normalized
events, checks, metadata and `result.json`. Inspect a directory without a new call:

```sh
uv run bencheval inspect .bencheval/runs/<run-id>
```

`inspect` verifies evidence hashes. These detect accidental evidence changes, not
forgery of both the evidence and its manifest. Artifacts are local and Git-ignored;
they can contain private prompts/responses. No automatic upload is implemented.
Reported token usage is retained when available; subscription quota consumption
and monetary cost remain `null`, never a fabricated zero.

Exit codes: `0` overall pass, `1` hard failure, `2` invalid input/local artifact
error, `3` inconclusive/unavailable runtime. `inspect` returns `0` for a valid saved
artifact regardless of its recorded verdict; invalid/tampered artifacts return `2`.

## Validation

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

Default tests use fake executors and real fake CLI subprocesses, not provider
calls. Live tests are excluded by default and additionally require opt-in:

```sh
BENCHEVAL_LIVE=1 uv run pytest -m live -q
```

This command consumes subscription usage. Do not enable it in unattended CI.

## Known boundaries

Codex runs in a temporary working directory with read-only sandboxing, ignored
user config/rules, and restricted tool features. BenchEval does not change your
global Codex configuration or source repositories. A complete recognized event
stream is necessary to pass `no_tools`; unknown/truncated streams cannot prove it.
Read-only mode is not a security boundary for untrusted benchmark workloads.

Global skills may still be discovered by the native CLI despite ignored user
config. The live run emitted a skill-catalog warning, preserved in its evidence
and runtime metadata. Ambient skills are explicitly marked **not isolated**.
This smoke test proves the transport and checks, not clean causal A/B comparisons
of instruction variants or the absence of every hidden side effect. CLI harness
defaults, model updates and managed configuration can affect results. Requested
model is recorded; an unreported effective model remains unknown.

The Codex adapter is an adapted local addition from the DeepEval checkout, not a
DeepEval runtime dependency. AgentEval is currently a design reference; no code
has been ported from it yet. See [provenance](docs/provenance.md) and [NOTICE](NOTICE).
