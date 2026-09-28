# Upstream adoption inventory

Prepared: 2026-09-28. This is a transfer plan, not a record of completed imports.

## Source snapshots

| Source | Local path | Inspected base | State |
| --- | --- | --- | --- |
| DeepEval | `/Users/elguajo/Documents/DEV/03_TOOLS/deepeval` | `385117c9c46e6935866422b7aa1f67e5e2824472`, package 4.2.6 | Dirty; local Codex adapter additions and unrelated changes |
| AgentEval | `/Users/elguajo/Documents/DEV/03_TOOLS/agenteval` | `b3eace62a7e169f02d8e18b7c918c480c8c5ea05`, package 0.8.14 | Clean at inspection |
| BenchEval | `/Users/elguajo/Documents/DEV/03_TOOLS/BenchEval` | No commits at initial inspection | New target; origin `https://github.com/Elguajo/BenchEval.git` |

Upstreams: [DeepEval](https://github.com/confident-ai/deepeval) and
[AgentEval](https://github.com/lukasmetzler/agenteval).

The local DeepEval additions are not contained in its inspected commit:

| File | SHA-256 |
| --- | --- |
| `deepeval/models/llms/codex_cli_model.py` | `2d43ed26374fe035e37e9e029e0e616e04f70b14d9b46ee3848490e2873fa6db` |
| `tests/test_core/test_models/test_codex_cli_model.py` | `deccfb3659dccf86998f7a14a3517c6ed1dbc164ba6e9f7c70a26bfbda86fda9` |

Recheck these hashes immediately before adoption. Avoid treating all dirty
DeepEval changes as BenchEval work; particularly, its `.gitignore` change is outside
the planned transfer.

## DeepEval: selected reuse

| Source files | Target responsibility | Adoption | Milestone |
| --- | --- | --- | --- |
| `deepeval/models/llms/codex_cli_model.py`; `tests/test_core/test_models/test_codex_cli_model.py` | Codex process/schema behavior and judge compatibility tests | Adapt local additions into the independent runtime; split executor from judge | M1 |
| `deepeval/models/base_model.py` | Metric-model bridge | Implement `DeepEvalBaseLLM` only in the optional integration; do not make core classes inherit its tracing hooks | M3 |
| `deepeval/test_case/llm_test_case.py` | Response metric inputs and observed tool calls | Map BenchEval evidence to public `LLMTestCase`/`ToolCall` APIs | M3 |
| `deepeval/metrics/g_eval/{g_eval.py,schema.py,utils.py}` | Subjective rubric metrics | Invoke explicitly configured `GEval` through optional dependency; freeze evaluation steps and preserve reasons | M3 |
| `deepeval/metrics/tool_correctness/tool_correctness.py`; `deepeval/metrics/task_completion/task_completion.py` | Additional behavior/outcome metrics | Optional later mapping; supply required tools/traces or report unavailable | M5 |
| `deepeval/test_case/conversational_test_case.py`; `deepeval/metrics/conversational_g_eval/` | Multi-turn evidence and metrics | Reference only for future conversation mode | M6 |

Do not copy DeepEval's API provider registry, cloud uploads, pytest plugin, global
run manager, telemetry, full tracing instrumentation, voice stack, RAG stack, or
documentation UI into BenchEval. These are not required for the accepted v1.

Required changes to the local Codex adapter before reuse:

- Unknown subscription cost must be represented as unknown in BenchEval. The
  local adapter's `0.0` return is an upstream-interface convention, not billing
  evidence; a compatibility wrapper must never leak that into the core result.
- Add process-group cancellation and event streaming; `asyncio.to_thread` around
  a blocking process does not establish cancellation of that process.
- Control ambient configuration and tools. A prompt saying not to use tools and a
  read-only sandbox do not enforce a tool-free judge or isolate host instructions.
- Validate nested JSON schemas against real CLI capabilities, including optional
  fields/required-property rules; schema rewriting alone is insufficient evidence.
- Capture useful, redacted error classifications and partial evidence instead of
  losing all subprocess context in a shortened exception string.

## AgentEval: selected ports

| Source files | Target responsibility | Adoption | Milestone |
| --- | --- | --- | --- |
| `src/run/{types.ts,task-loader.ts}`; `src/config/schema.ts` | Scenario/check contracts | Translate relevant concepts into BenchEval's own versioned schema with explicit axes and hard-rules | M0 |
| `src/harness/{types.ts,generic.ts,claude-code.ts}` | CLI adapter lifecycle | Reuse adapter separation and real-process fixtures; implement current provider-specific commands independently | M1–M3 |
| `src/run/{index.ts,worktree.ts}` | Workspace orchestration | Port flow with fixed bases, complete snapshots, ownership checks and preserved artifacts | M2 |
| `src/run/assertions.ts`; `tests/unit/assertions.test.ts` | File and command checks | Port semantics/tests with explicit glob rules, argv commands and protected verification inputs | M2 |
| `src/store/{index.ts,compare.ts,types.ts}`; `tests/unit/{store,compare}.test.ts` | Local storage/comparison | Port user behavior; replace persistence with atomic versioned artifacts and compatible paired comparisons | M4 |
| `src/lint/{driftDetector.ts,overlapDetector.ts,skillValidator.ts,contextBudgetChecker.ts}` | Instruction diagnostics | Selective advisory Python ports; keep false-positive tests | M5 |
| `src/harvest/{detect.ts,snapshot.ts,emit.ts}` | Reviewed task suggestions | Learn from the approach after v1; no automatic copying into the first benchmark | M6 |

Do not transfer the CLI wholesale, Bun runtime/build system, self-update/install
scripts, automatic stale-worktree deletion, or weighted scorer.

Corrections established by source inspection:

- `src/harness/registry.ts` has no Codex adapter and maps `AGENTS.md` to OpenCode.
  BenchEval requires explicit executor selection.
- `src/commands/run.ts` and `src/run/task-loader.ts` restrict harness names even
  though the registry accepts custom config keys. Use one capability registry and
  validate against it; do not reproduce incompatible whitelists.
- `src/run/index.ts` captures `git diff HEAD`, which misses untracked files and
  changes an agent commits. Snapshot against the pinned baseline instead.
- Worktrees start at current `HEAD`; harvested `sourceCommit` is metadata rather
  than the checkout base in that path. BenchEval's scenario base is operational.
- `src/run/scorer.ts` averages dimensions. Replace it with hard-rule verdicts.
- `src/harvest/llm-rubrics.ts` substitutes score 5 when output cannot be parsed.
  BenchEval reports unresolved judging instead of fabricating a neutral score.
- `src/run/index.ts` executes command assertions through `sh -c` without per-check
  bounds. BenchEval uses trusted argv definitions, explicit timeouts and logs.
- `src/harness/claude-code.ts` skips permissions. BenchEval verifies declared
  permissions/capabilities for the installed CLI and trusted scenario.

## Provenance and future upstream intake

AgentEval's inspected source includes the MIT license in `LICENSE`. DeepEval's
inspected source includes Apache-2.0 in `LICENSE.md`. Before adopting code or
translated substantial portions, preserve applicable source notices, include the
license texts, mark adaptations, and check for any relevant upstream NOTICE files.
Choosing a license for original BenchEval code does not replace source obligations.

For each actual adaptation, add a small provenance record with repository URL,
commit or local content hash, source/target files, adoption kind (dependency, port,
or adaptation), purpose, local changes, license path, and covering tests. Purely
conceptual inspiration can be recorded as such; do not claim copied functionality
has been imported when it has only been studied.

Future intake is manual and demand-driven:

1. Inspect changes since the last reviewed revision in relevant source areas.
2. Record the concrete BenchEval problem the upstream change would solve.
3. Adopt the smallest change on its own branch with compatibility and failure tests.
4. Check provenance/notices and any artifact/schema migration requirements.
5. Advance the reviewed revision only after validation; retain local interface
   ownership and release notes for the changed behavior.

Do not add upstreams as submodules or merge their whole histories. Do not create
an automatic monitoring schedule as part of this plan. Dependency updates and
source ports remain reviewable changes with separate rollback paths.
