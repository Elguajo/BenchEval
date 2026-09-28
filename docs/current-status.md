# Implementation status — 2026-09-28

Session classification: **M0.5 RESULT SEMANTICS IMPLEMENTED** after the earlier
Codex-first judge/context/UI increment. The broader project is **IN PROGRESS**:
coding-agent scenarios, suites/comparison, Claude and the DeepEval bridge remain
undelivered. This checkout has no Progressive Context Kit, QUALITY_PROTOCOL.md
or HANDOFF_PROTOCOL.md; this file preserves compact acceptance evidence.

## M0.5 result semantics freeze

- `RunResult` stores execution separately from axis/Overall verdicts and explicit
  `CleanSuccess` (`YES`, `NO`, `INCONCLUSIVE`). A hard failure gives `NO`; without
  one, incomplete execution or unresolved required evidence gives
  `INCONCLUSIVE`; complete applicable hard success gives `YES`.
- Axes aggregate only hard checks. Advisory findings remain in checks and appear
  separately in CLI/UI; they do not affect axes, Overall or Clean Success.
  Response behavior with no declared hard behavior check remains
  `NOT_OBSERVABLE`, not an invented pass.
- Check evidence uses typed `EvidenceRef` values. Response checks cite
  `response.txt`; observed tool actions cite indexed `events.json` entries;
  a no-tools pass cites the event stream and preserved `trace_complete` runtime
  metadata. Existing artifact file hashes are integrity checks, not attestations.
- The minimal `SuiteResult` contract defines CSR as `clean_successes /
  scheduled_attempts`, including failed, inconclusive, execution-failed and
  unexecuted attempts in the denominator. Zero scheduled attempts give null CSR.
  Suite execution and comparison remain pending.
- Actor result, judge job and judge result schemas are now version 2. Old version
  1 artifacts are rejected rather than reinterpreted; scenario schema is still
  version 1. Existing ignored local artifacts remain untouched.
- Offline tests cover decision-table cases A–I and actor/judge/CLI/UI paths.
  No live inference was used for this increment. Full M2 worktree and
  coding-agent execution have not begun.

Observed M0.5 verification: `uv run pytest` **928 passed, 1 live test
deselected**; `uv run ruff check .` passed; `uv run ruff format --check .`,
`node --check src/bencheval/web/app.js`, `git diff --check`, and
`uv run bencheval validate examples/response/arithmetic.yaml` passed. A temporary
offline actor artifact was inspected with the actual `bencheval inspect` command.
The counts below document the *earlier* judge/context/UI increment.

## Delivered

- Installable Python package, locked environment, response scenarios and fixed
  exact/contains/regex/JSON-schema/no-tools checks.
- Independent Outcome, Instruction fidelity and Behavior verdicts. Proven hard
  failures dominate; missing mandatory evidence never becomes a guessed pass.
- Codex actor and independent Codex LLM judge using official CLI ChatGPT login.
  Ephemeral read-only invocations, ignored user config/rules, restricted tools,
  per-user provider lock, process-group timeout/cancellation and captured JSONL.
- Controlled context by default: app-server skills/list discovery, per-invocation
  skills.config disabling, second read-only verification with zero enabled skills.
  No global settings/auth edits. Explicit ambient mode prints a warning.
- Versioned judge jobs bound to verified actor artifacts and a rubric. Strict
  structured verdicts with complete unique criterion IDs, explanations and
  evidence references. Missing required evidence => NOT_OBSERVABLE; invalid
  required decisions => INCONCLUSIVE. Existing hard failures are preserved.
- Judge commands: export/run/import/inspect. Codex subscription automation,
  actual desktop manual JSON hand-off, native Ollama and explicit
  OpenAI-compatible Chat Completions API adapters. No automatic retries,
  redirects, credential extraction or API fallback; job locks prevent concurrent
  evaluation of the same job.
- Loopback-only read-only web inspector: list/search/filter actor and judge
  artifacts, three axes, combined findings, evidence and context metadata.
  Pending exported jobs are represented explicitly. Text-only evidence rendering,
  restrictive CSP, Host/Origin checks and no remote assets.
- README rewritten with product positioning, working quick start, scenario/rubric
  examples, provider workflows, UI preview, limitations, development and roadmap.
  Layout/content inspiration from the upstream READMEs; original BenchEval text.
- New judge/context/UI code is BenchEval-owned. Exact source attribution for the
  local DeepEval Codex adaptation is retained. No source checkout was modified.

## Observed verification

- Python 3.12.10, uv 0.10.12, Codex CLI 0.147.0.
- `uv run bencheval doctor`: ChatGPT subscription login, required flags present;
  **136 discovered skill paths, zero enabled at verified preflight**.
- `uv run pytest -q`: **915 passed, 1 deselected**. Includes the 750 existing
  verdict decision-table permutations and offline fake CLI/HTTP integration tests.
  Covers context refusal/timeouts, immutable actor evidence, malformed/duplicate/
  incomplete judge decisions, hard-fail preservation, missing trace, job locking,
  native Codex judge transport, desktop imports, HTTP auth/quota/refusal/redirect/
  timeout/oversize/truncation handling and local UI boundary checks.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv build`: source distribution and wheel built. Wheel inventory includes
  the three web assets, judge modules and retained license/NOTICE files.
- Live arithmetic actor: **completed / PASS**, all three axes PASS, recognized
  complete trace with no tool actions; controlled skill metadata recorded.
- Separate live Codex subscription judge: **completed / PASS**, both rubric
  criteria PASS with evidence citations. Same-provider bias warning recorded.
- Actor `inspect` and judge `inspect`: passed, including source/evidence hashes.
- In-app browser: actor/judge detail rendering, source-actor navigation, search
  empty state, role filtering and keyboard disclosure activation verified.
  Desktop (1200 px) and narrow (375 px) layouts inspected; narrow DOM showed no
  horizontal overflow. Console warning/error log query returned none.
  In-app pointer automation was unreliable for some controls; keyboard activation
  supplied functional evidence. No claim of cross-browser/full accessibility QA.
- Ollama executable is installed, but `127.0.0.1:11434` refused connection.
  Native/API adapters were exercised against local HTTP fixtures, not real
  Ollama inference or paid external APIs. Actual desktop-app judging was not
  performed; the manual import workflow was tested offline.

Live artifacts, local and ignored:

- Actor: `.bencheval/runs/20260928T062356-2255d4a7bac7/result.json`.
- Judge: `.bencheval/judges/20260928T062815-bd5d24d0592d/result.json`.

Both calls consumed subscription usage. Earlier actor attempts
`20260928T054559-8660b6006dc4` (INCONCLUSIVE) and
`20260928T054858-76df5b810503` (PASS) remain unchanged.

## Important decisions and boundaries

- Codex CLI automation and actual desktop use are distinct transports. Desktop
  mode is export/new-chat/import, not automation of an open app window. Identity,
  auth, effective model and ambient desktop context cannot be verified.
- Skill controls are a preflight snapshot, not a context-free model guarantee.
  Native base/managed instructions remain; new skill files can race with exec.
  Existing auth stays in the official CLI store; no credential copying.
- Judge evidence contains explicit request/response/instructions and normalized
  event kinds. Tool arguments/effects and filesystem history are not available.
  Detailed protected-file/trajectory claims must not be inferred from that trace.
- Same-provider judgments may share mistakes. Prompt-injection boundaries and
  schema validation do not prove semantic accuracy; calibration is still needed.
- HTTP providers require explicit models. Remote evidence transfer requires HTTPS
  plus allow_remote; keys are environment-only and never logged. Compatibility
  requires the documented strict structured-output contract, not every provider.
  Proxy support is absent; DNS/header timing can exceed the body-read deadline.
- UI is a trusted local developer inspector, not a public/multi-user service.
  It performs no inference or configuration writes and must not be tunneled
  publicly. Artifact hashes detect accidental change, not malicious re-signing.
- Read-only execution is not a hostile-code sandbox. Scenario authors are trusted.
  Python regex checks have no regex time budget; schema format is an annotation.
- Effective model, billed cost and subscription quota stay unknown unless actually
  reported. Local evidence and context metadata can contain private data.

## Git and running services

The previous bootstrap snapshot was committed/pushed to main as
`597e49510de7b42a5cd34421aae977fdf0d92fd0`.

This new increment is **local and uncommitted**; no new push/PR/publication occurred.
No private instruction-directory import or upstream source edits occurred.

The user-facing inspector is running at `http://127.0.0.1:8765/`.
Restart from the repository root with `uv run bencheval ui --port 8765`;
stop its local process with Ctrl+C. The in-app tab is kept as a deliverable.

## Single-focus continuation

Next unresolved product target: implement one trusted coding-agent scenario for
Codex with a fixed repository base, isolated worktree, fixed runner-owned tests
and protected-file evidence. Do not label the existing response runner as a
coding-agent benchmark. Claude remains deferred at the user's request.

> Continue BenchEval from docs/current-status.md. Focus on one Codex coding-agent
> vertical slice: a fixed trusted local fixture, controlled worktree/instructions,
> runner-owned verification tests and protected-file checks with honest trace
> coverage. Preserve existing response/judge artifacts and unrelated changes.
> Keep Claude, suite comparison and hosted UI outside this increment.
