# Implementation status — 2026-09-28

Session classification: **IN PROGRESS**. The initial response slice works, but
M0/M1 have open schema/judge work and the complete v1 (M0–M4) is not delivered.
This repository has no Progressive Context Kit or `HANDOFF_PROTOCOL.md`; this file
holds the compact implementation evidence and continuation context.

## Delivered

- Installable Python package and locked environment; `init`, `validate`, `doctor`,
  response `run`, artifact `inspect`, and `version` commands.
- Strict unknown-field/duplicate-key handling, instruction path containment,
  content snapshots and SHA-256 hashes; inline JSON Schema validation with no
  remote-reference resolution.
- Independent outcome, instruction-fidelity and behavior verdicts. Hard violations
  dominate; missing required evidence cannot become a pass; no averaged score.
- Codex executor using the official CLI and existing ChatGPT login. No API-key
  fallback or credential-file extraction. Temporary read-only execution, controlled
  config overrides, per-user provider lock, timeout/cancellation of process groups,
  captured streams and recognized JSONL tool events.
- Exact-text, substring, regex, JSON Schema and observed no-tools checks. Local,
  versioned, atomic final results and evidence-hash verification.
- Attribution and exact source hashes for the local DeepEval Codex adaptation.
  No AgentEval code port and no DeepEval runtime dependency yet.

## Observed verification

- `uv sync --python 3.12`: environment installed and `uv.lock` created.
- Python 3.12.10; Codex CLI 0.147.0; `doctor` reported a ChatGPT login and all
  required CLI flags available.
- `uv run pytest -q`: **848 passed, 1 deselected**. Of these, 750 are the complete
  3-axis hard-check state / execution-status decision-table permutations.
  Default tests made no provider calls. The opt-in pytest live test was not run;
  live verification used the CLI directly below.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv build`: source distribution and wheel built successfully; distributions
  include Apache-2.0, NOTICE and the retained upstream license.
- `validate examples/response/arithmetic.yaml`: valid, 3 checks.
- Live `run examples/response/arithmetic.yaml`: **completed / PASS**, all three
  axes PASS. JSON response satisfied both correctness and format checks; the
  recognized complete event stream contained no tool actions.
- `inspect` of that run: passed and verified saved evidence hashes.

Successful live artifact, local and ignored by Git:
`.bencheval/runs/20260928T054858-76df5b810503/result.json`.

The initial live attempt
`.bencheval/runs/20260928T054559-8660b6006dc4/result.json` remains unchanged:
completed / INCONCLUSIVE because the parser initially did not recognize a nonfatal
Codex `error` item. The raw trace identified the cause; a regression test now
distinguishes those warning items from fatal top-level errors. Unknown item types,
truncated streams, missing lifecycle markers and unfinished items still cannot
establish complete observation. Both attempts consumed subscription usage.

## Important boundaries

This is a **Codex actor plus deterministic evaluation**, not a Codex LLM judge.
Claude, subjective rubric judging, coding-agent worktrees, protected filesystem
checks, suites/comparison, the DeepEval bridge, and a web UI are not implemented.

Codex still discovers global skills despite ignored user config and a temporary
working directory. The live attempt emitted a skill-catalog warning. Metadata
explicitly marks ambient skills as not isolated and preserves CLI warnings.
Consequently this is not a controlled instruction-variant A/B baseline yet. Do not
silently fix this by copying authentication into another home or modifying global
skills/configuration. The official CLI's auth store remains authoritative.

Read-only mode and feature restrictions are not isolation for hostile workloads.
No-tools checks establish observed CLI activity only, not every hidden side effect.
Scenario authors are trusted: checks use Python regex without a regex time budget,
and cross-check contradiction detection currently covers hard `equals` conflicts,
not arbitrary prose/regex/schema contradictions. JSON `format` is not asserted.
The effective model, dollar cost and consumed subscription quota remain unknown
unless the CLI actually reports them. Local evidence may contain private data.

Changes are local and uncommitted. No push, PR, publication, instruction-directory
import or source-repository changes were performed in this implementation slice.

## Next single-focus target

Establish controlled Codex instruction delivery before a comparative benchmark:
discover a supported way to disable/snapshot ambient skills for one invocation,
without changing global configuration or moving/extracting credentials. Verify the
chosen approach offline and with an explicit small live test. If the native CLI
cannot establish this, retain the limitation in capability/comparison eligibility
rather than claiming clean isolation. Coding-agent implementation remains queued
as M2 in the [implementation plan](implementation-plan.md).

Copyable continuation prompt:

> Continue BenchEval from docs/current-status.md. Focus only on controlled Codex
> instruction delivery: prevent or explicitly snapshot ambient skills/config for
> one response run without changing global setup or copying credentials. Add
> regression tests and verify a short live scenario if needed. Preserve existing
> evidence and do not start coding-agent work or instruction comparisons yet.
