# BenchEval implementation plan

Status: initial design contract with M0.5 result semantics frozen; implementation evidence lives in
[current-status.md](current-status.md). The approved incremental scope now includes
Codex-first judging, controlled skills and a read-only local web inspector.
Prepared: 2026-09-28.

## 1. Product contract

**BenchEval is an instruction-aware benchmark runner for LLMs and coding agents.**
It measures whether an executor achieves the goal, responds correctly, and behaves
according to the supplied instructions and policies.

| Axis | Question | Typical evidence |
| --- | --- | --- |
| Outcome | Was the requested result achieved? | Answer, fixed verification tests, produced artifacts |
| Instruction fidelity | Were applicable instructions and explicit requirements followed? | Response structure, instruction snapshots, rule checks |
| Behavior | Did observable actions stay within the permitted scope? | Tool events, commands, file snapshots, diff, response claims |

Keep axis verdicts and optional rubric scores separate. BenchEval has no averaged
global AI quality score. One check can support several axes without being
counted as multiple independent pieces of evidence.

V1 supports two scenario kinds:

- `response`: a prompt and instructions produce a response; tools are disabled
  when the adapter can enforce that capability. Otherwise declare the capability
  limitation rather than advertise a pure tool-free model evaluation.
- `coding-agent`: an agent works on a fixed repository snapshot in a temporary
  worktree; BenchEval checks responses, filesystem changes, and available events.

A CLI run measures the model together with its harness, loaded instructions,
permissions, tools, and settings. Report that configuration; do not label such a
run as a controlled measurement of the underlying model alone.

Out of scope for v1: task generation, git-history harvesting, multi-turn scenario
simulation, cloud CI using personal subscriptions, dozens of agent frameworks,
automatic instruction rewriting, hosted accounts, and a web dashboard. A local
HTML report can follow once the artifact contract is stable.

## 2. Current sources and transfer strategy

At the initial inspection, `/Users/elguajo/Documents/DEV/03_TOOLS/BenchEval` was an
empty Git repository on `main`. Its origin is
`https://github.com/Elguajo/BenchEval.git`.

Source paths, revisions, relevant files, and known limitations are recorded in
[the upstream inventory](upstream-inventory.md). That document owns provenance;
this document owns the product and implementation sequence.

Implement one Python package with its own contracts and CLI. Port selected
AgentEval behavior to Python. Integrate DeepEval through an optional adapter
instead of copying its package, provider registry, tracing stack, or CLI.

Use the locally developed Codex judge adapter as a starting point, then remove its
dependency on DeepEval from the core runtime. It is a local addition, not an
upstream DeepEval feature. Adapt its tests alongside the code. Preserve unrelated
source changes; do not reset, move, or delete either source repository.

Recommended implementation baseline: Python 3.12+, `uv`, Pydantic v2 for strict
contracts, a safe YAML loader, Typer for CLI, and pytest for verification. Use the
standard library for subprocesses, hashing, JSON artifacts, and filesystem work.
Pin dependencies after the first compatibility check. DeepEval belongs in an
optional `deepeval` extra; normal installation and deterministic checks must work
without it or an API key.

## 3. Architecture and ownership

```text
Scenario + instruction variant + policies + fixed initial state
                         |
                 validate and preflight
                         |
               executor: Codex / Claude
                         |
       response + observed events + snapshots + verification logs
                         |
         deterministic checks + optional structured rubric judge
                         |
         Outcome / Instruction fidelity / Behavior / Overall
                         |
                artifact and suite comparison
```

Proposed package layout:

```text
src/bencheval/
  cli.py                       # init, doctor, validate, run, inspect, compare
  contracts.py                 # Scenario, InstructionBundle, CheckResult, RunResult
  scenarios.py                 # YAML loading, validation, variant resolution
  instructions.py              # effective instruction bundle and hashes
  runtime.py                   # process groups, stream collection, cancellation
  executors/{base,codex,claude}.py
  events.py                    # normalized observed events and capability coverage
  workspace.py                 # fixed base, injection, snapshots, owned cleanup
  checks.py                    # deterministic check implementations
  judges/{base,rubric}.py       # schema, payload construction, evidence validation
  verdicts.py                  # axis decisions and hard-rule gate
  artifacts.py                 # local storage and evidence references
  comparison.py                # compatible suite/variant comparisons
  integrations/deepeval.py      # optional metric bridge; lazy import
tests/{unit,integration,fixtures}/
examples/{response,coding-agent}/
docs/
```

Executors run scenarios. Judges receive a bounded evidence payload in a separate
session. Checks interpret evidence. Verdict aggregation uses check results; it
cannot be overridden by an executor's own success claim or a judge's average.

`InstructionBundle` records the scenario instructions, user request, policies,
project/scoped instruction files, delivery mechanism, and known ambient settings.
Explicit scenario policies define hard boundaries. Contradictory declared hard
requirements are configuration errors; do not ask the evaluated agent to decide
which benchmark rule counts. Full instruction text remains the source of meaning;
manually authored checks cover a declared subset, not every possible interpretation.

For fair A/B comparisons, inject the same variant at each provider's documented
instruction surface (`AGENTS.md` or `CLAUDE.md`) and record any wrapper text. Detect
other scoped instructions and either include them as fixed context or reject an
uncontrolled comparison. Do not silently add a provider-specific second variant.

## 4. Results and hard-rule semantics

Separate execution status from evaluation verdict. Execution statuses include
`completed`, `auth_required`, `quota_exhausted`, `timeout`, `cancelled`, and
`execution_error`. A clean process exit only means execution completed.

Check states: `PASS`, `FAIL`, `NOT_OBSERVABLE`, `NOT_APPLICABLE`, `ERROR`.
Checks carry an ID, axes, `hard` or `advisory` severity, expected condition, actual
finding, evidence references, and checker/version metadata.

Overall aggregation, in precedence order:

1. Any established hard-rule violation yields `FAIL`, even if another check errors.
2. Otherwise, incomplete execution or an unresolved required check yields
   `INCONCLUSIVE`; a configuration failure is reported before execution.
3. Otherwise, all required outcome criteria and applicable hard-rules passing
   yields `PASS`. Advisory rubric findings remain visible and cannot turn a
   verified hard-rule failure into a pass.

Axis results can be `PASS`, `FAIL`, `INCONCLUSIVE`, `NOT_OBSERVABLE`, or
`NOT_APPLICABLE`. An axis with no evidence is never automatically `PASS`. A rubric
may be a required criterion only when the scenario explicitly declares that
requirement and its threshold; invalid output or absent supporting evidence makes
that criterion unresolved.

Example: correct patch plus a forbidden edit:

```text
Outcome:              PASS
Instruction fidelity: FAIL — rule keep-billing, billing/payment.py changed
Behavior:             FAIL — forbidden file change observed
Overall:              FAIL
```

Response-level behavior such as unsupported completion claims can be observable
without tools. Tool behavior in a response-only scenario is `NOT_OBSERVABLE` when
there is no tool trace. Final snapshots prove final-state differences, not that a
file was never temporarily edited. A rule forbidding any edit requires suitable
events or monitoring; absence of that coverage makes the rule unresolved.

Primary suite metric: Clean Success Rate (`CleanSuccess.YES attempts / all scheduled
attempts`), alongside counts of hard failures, inconclusive results, and execution
failures or unexecuted attempts. Zero scheduled attempts yield undefined/null CSR.
Never hide failed
infrastructure by shrinking the denominator. Also show unique-scenario coverage
and per-scenario repeat results; attempts are not independent new scenarios.

Counter-metrics: actor and judge wall time, observed token usage, subscription
quota consumption where available, unobservable required-check rate, and missed
violations on a labeled calibration set. Unknown quota or cost is `null`, not zero.
Token counts and Claude's reported cost estimates do not establish actual
subscription quota consumption or billed dollars.

## 5. Scenario contract

Finalize the schema in milestone M0. The following is a design example, not an
implemented CLI format. Paths resolve against an explicit scenario/suite root;
repository paths refer only to the worktree. Absolute local source paths must not
become runtime dependencies of the distributed package.

```yaml
version: 1
id: fix-role-without-billing-changes
kind: coding-agent
workspace:
  repository: ./fixtures/roles
  base_commit: "<full commit SHA, resolved before execution>"
instructions:
  variant: candidate
  files: [./instructions/candidate.md]
executor:
  provider: codex
  timeout_seconds: 300
prompt: "Fix role selection for an empty string. Do not change billing/."
checks:
  - id: role-tests
    axes: [outcome]
    severity: hard
    type: command
    argv: [python, -m, pytest, tests/test_roles.py, -q]
    timeout_seconds: 60
  - id: keep-billing
    axes: [instruction_fidelity, behavior]
    severity: hard
    type: files_unchanged
    paths: ["billing/**"]
judge:
  provider: claude
  required: false
  rubric: "Assess whether the explanation is accurate and supported by evidence."
```

V1 deterministic checks: expected response/regex/JSON structure, required and
forbidden final file changes, workspace unchanged, command exit/results, and
observed tool constraints where trace coverage is sufficient. Define glob and
regex semantics explicitly and use compatibility fixtures when porting AgentEval.
Require at least one outcome criterion for a scored scenario. Reject empty checks,
duplicate IDs, unsupported kinds, invalid paths, missing command arguments, and
requirements the executor cannot support before consuming inference quota. Reports
identify which instructions have explicit checks and which remain unassessed.
Tests come from fixed runner-owned verification definitions. Command checks use
argument arrays, `shell=False`, a declared working directory, bounded execution,
and captured output. A task file is executable configuration and must be trusted.

## 6. Runtime, evidence, and subscription adapters

- Keep authentication with official CLI login. Do not read OAuth files, extract
  tokens, proxy private endpoints, or fall back to paid API access automatically.
  Detect or remove API-credential overrides only in the child environment for the
  requested subscription mode; do not mutate the user's shell or login settings.
- Codex: inspect CLI capabilities, use ephemeral sessions, JSONL events, separate
  final output, strict output schemas for judges, and the narrowest sandbox that
  supports the scenario. The installed 0.147.0 exposes these options. Record the
  effective model/settings, or mark them unknown if the CLI does not expose them.
- Claude: inspect installed version and capabilities before enabling an adapter.
  Use print mode, structured/stream output, explicit tool permissions and controlled
  ambient settings. `--bare` omits `CLAUDE.md` too; deliver the scenario instructions
  explicitly if that mode is used. Validate this behavior with real CLI fixtures.
- One active inference per provider/account by default; actor and judge calls share
  that queue. Rate-limit failures stop or bound retries without duplicating an
  already completed actor attempt. No parallel quota-consuming default.
- Drain stdout and stderr while the process runs. Cancellation/timeouts terminate
  the owned process group, collect remaining output, and preserve partial evidence.
- Worktrees isolate Git state, not hostile code or all filesystem/network access.
  V1 runs trusted local fixtures. Use provider restrictions; unsupported restrictions
  are capability errors. Do not copy permission-bypass defaults from AgentEval.
- Pin the base commit; explicitly prepare declared dependencies before the actor.
  Never inherit the source working tree's uncommitted edits, `.env`, or ignored
  runtime files. Snapshot after instruction injection/setup, before the actor.
- Capture tracked, staged, untracked, renamed, deleted, binary, and policy-covered
  ignored files. Collect changes even if the agent commits them. Fixed base hashes
  and snapshots, not `git diff HEAD` alone, define what changed.
- Store verification definitions outside the evaluated checkout; validate protected
  test hashes and evaluate with the original verification set. Record attempts to
  alter tests. Same-user worktrees are not protection against a hostile process.
- Preserve artifacts before cleanup. Remove only owned inactive worktrees after a
  terminal state; recovery never deletes active work based only on directory age.
- Store local manifests, responses, normalized events, snapshots/diff, check logs,
  rubric versions, instruction hashes, execution metadata, and evidence hashes.
  Use atomic final writes and unique attempt IDs. Hashes detect changes; they do
  not provide tamper-proof attestation. Reports reference the preserved evidence.
- Judge input is untrusted data. Delimit it, use separate rubric instructions,
  restrict judge tools, validate its schema and evidence references, and test
  instruction-injection examples. Read-only sandboxing alone is not tool disabling.
- Bounded judge payloads include an evidence-selection manifest. If omitted data
  is needed for a required decision, return unresolved; do not silently truncate
  evidence or invent a fallback score. Keep secrets out of exported/judge payloads.
- Local artifacts stay ignored by Git by default. Sending evidence to an enabled
  judge is an explicit run configuration choice. DeepEval integration disables its
  telemetry before import and does not use Confident AI upload paths.

## 7. Delivery milestones

Implementation has started: core verdicts and the Codex response slice are working.
See [current status](current-status.md) for observed verification and limitations.
The complete v1 remains pending. Each milestone ends with an independently
reviewable change.

### M0 — Contracts and provenance

- [x] Create package metadata, minimal dependencies, development checks, and
  artifact/worktree ignore rules; recommend Apache-2.0 for original BenchEval code.
- [ ] Finalize scenario, instruction bundle, event, result, and verdict schemas.
  Response contracts are implemented; coding/judge extensions remain pending.
- [x] Add provenance records and the required upstream licenses/attributions before
  the first code adaptation; snapshot local Codex additions by content hash.
- [x] Implement verdict aggregation against a full decision-table fixture set.

Acceptance: a correct outcome plus any forbidden billing change is `FAIL`; a
missing mandatory trace is `INCONCLUSIVE`; advisory scores cannot affect either.

### M1 — Executable response slice with Codex

- [x] Implement `validate`, `doctor`, response `run`, and artifact `inspect`.
- [ ] Extract the local Codex adapter into BenchEval's executor/judge interfaces;
  add event parsing, process lifecycle, capability reporting, and unknown usage.
  Executor portion is implemented; the judge interface is not implemented yet.
- [x] Implement response checks and runner-owned instruction snapshots.
- [x] Add a deterministic fake executor for ordinary tests and an explicit live
  Codex smoke test for subscription authentication and schema output.

Acceptance: an installed CLI can run a small response scenario without an API key;
no CLI/login yields an actionable execution status; malformed responses never pass.
Fake-executor tests work offline. The live test is never part of default pytest.

### M0.5 — Result semantics freeze (completed before full M2)

- [x] Store `CleanSuccess` (`YES`, `NO`, `INCONCLUSIVE`) alongside Overall.
  A hard failure dominates errors; incomplete execution or missing required
  evidence without a hard failure is inconclusive. Completed applicable hard
  success passes.
- [x] Axis verdicts use hard checks only. Advisory findings remain visible and
  cannot change axes, Overall, or Clean Success. An undeclared response behavior
  axis is `NOT_OBSERVABLE`; explicit inapplicability is `NOT_APPLICABLE`.
- [x] Use typed evidence references for deterministic and judge checks, with
  stable IDs, preserved source/locator and artifact hashes. These hashes are
  integrity references, not tamper-proof attestation.
- [x] Add a minimal suite result contract. CSR uses every scheduled attempt;
  execution failures and unexecuted attempts remain in its denominator. Counts
  partition attempts with established hard failure taking precedence; original
  execution status remains available on each run.
- [x] Freeze cases A–I in offline decision-table and integration tests.

Actor results and judge jobs/results use internal schema version 2. Version 1
artifacts are rejected during inspection; they are not silently reinterpreted.
The scenario schema remains version 1. Full suite execution/comparison remains M4.

### M2 — Coding-agent slice

- [ ] Port worktree lifecycle and file/command assertions from the AgentEval design,
  with fixed base resolution, post-injection baseline, ownership and recovery.
- [ ] Add complete filesystem evidence, bounded verification commands, and protected
  verification definitions; preserve user checkouts and unrelated worktrees.
- [ ] Add positive fixtures plus forbidden edits, untracked files, self-commits,
  renamed/binary files, cancelled processes, and tampered tests.

Acceptance: a real trusted coding fixture produces a patch, test logs, and a
verdict with evidence; all forbidden-change fixtures fail despite passing tests.
Failed/cancelled runs retain usable artifacts and do not leave running children.

### M3 — Claude and subjective judging

- [ ] Implement Claude executor and judge after CLI installation/authentication is
  available; do not install or log in as a side effect of scenario evaluation.
- [ ] Add per-criterion rubric schema, evidence IDs, optional/required handling,
  and judge re-evaluation of preserved artifacts without rerunning the actor.
- [ ] Prefer a different provider for judging when available; record same-provider
  judging instead of forbidding it. Keep a fixed rubric and human-labeled examples.
- [ ] Provide the optional DeepEval bridge for `LLMTestCase` and explicit-model
  `GEval`; freeze evaluation steps. Enable other metrics only with valid data.

Acceptance: both providers have verified live subscription smoke tests; invalid
JSON, missing evidence, unavailable quota, and injected instructions have explicit
non-success handling. Core runs without DeepEval; opt-in metrics make no telemetry
or upload requests. Provider/tool permissions are tested, not inferred from prompts.

### M4 — Suites, variants, and first benchmark

- [ ] Implement suite runs and comparisons across providers/instruction variants.
- [ ] Bind compatibility to scenario/check/base/rubric hashes and runtime metadata.
  For instruction comparisons hold the executor configuration fixed; for provider
  comparisons show the harness differences. Changed criteria invalidate paired A/B.
- [ ] Show hard-rule failures, coverage, inconclusive counts, repeats, timings, and
  available usage. Add JSON/Markdown reports; no universal weighted score.
- [ ] Build the first labeled suite from review-only, diagnose-without-fixing,
  ambiguous-requirement, response-format, and forbidden-file-change scenarios.
- [ ] Import the user's instruction variants explicitly from the local directory,
  preserving names/content hashes. Include Claude's variant only in a declared
  provider-specific experiment. Do not publish those files by default.

Acceptance: the same frozen suite runs against baseline/candidate; repeated results
and labeled-check false negatives are visible. Previous informal v1/v3/v4 trials
are exploratory context, not a statistical baseline or proof of superiority.
V1 is complete when M0–M4 satisfy their acceptance criteria.

### M5 — Compatibility and instruction diagnostics

- [ ] Import supported AgentEval task fields with a migration report. Convert
  shell-string assertions only through explicit reviewed mappings, never silently.
- [ ] Add selected instruction lint rules: broken references, duplication, structure
  and approximate token budgets. Heuristics are advisory, not instruction truth.
- [ ] Add more DeepEval metrics only when their required fields/traces are available.
- [ ] Add a local evidence report UI after CLI and artifact formats stabilize.

### M6 — Further development

- [ ] Multi-turn scenarios with instruction changes and explicit conversation state.
- [ ] Assisted task generation/harvesting with human review and fixed ground truth.
- [ ] External sandbox environments for untrusted benchmark workloads.
- [ ] CI exports and managed-machine authentication as a separate operating mode.
  Offline fixtures and deterministic checks can run in CI from the start.

## 8. Verification, limitations, and rollout

Test contracts, verdict truth tables, parser compatibility, and failure behavior
with offline fixtures. Use temporary Git repositories and fake CLI processes for
workspace/process integration tests. Live provider tests are opt-in, small, and
sequential; record installed versions and authentication mode without credentials.

Calibrate judges against human-labeled cases, including accurate results that break
instructions and plausible answers that are incorrect. Measure missed known
violations on this set; production false negatives cannot be inferred from logs
alone. Freeze suite/check/rubric versions before comparing instruction variants.

No baseline yet. The first labeled suite establishes measurement behavior before
claiming that a model or instruction version is better. Keep a change when it
improves strict-pass outcomes on comparable scenarios without worsening missed
known violations or coverage; publish uncertainty and run effort alongside it.

Provider limits, model updates, ambient instructions, and incomplete traces can
change results. A request to ignore user config must not silently defeat the
instructions being tested. Snapshot detectable configuration and invalidate
comparisons that cannot establish the intended controlled difference.

Implementation stays within BenchEval. Roll back a failed adapter/metric change
independently and retain existing artifacts. Future upstream adoption follows the
inventory process. This planning change does not authorize publishing source code,
user instructions, logs, or results to GitHub, and does not commit or push files.

## 9. Documentation consulted

- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive):
  execution, permissions, JSONL events, schema output, and configuration controls.
- [Codex authentication](https://developers.openai.com/codex/auth): subscription
  login and CLI authentication status; machine authentication is a separate mode.
- [Claude Code programmatic runs](https://code.claude.com/docs/en/headless): print
  mode, streams, schemas, ambient context, permissions, and cost estimate caveats.
- [Claude Code authentication](https://code.claude.com/docs/en/authentication):
  subscription login and competing credential configuration.

Documentation was consulted on 2026-09-28. Implementation must verify capabilities
against the installed binaries; Claude was not found on PATH during this review.
