# Adopted components

This records implemented adoption, not the future candidates in
[upstream-inventory.md](upstream-inventory.md).

## Codex executor

- Source project: [DeepEval](https://github.com/confident-ai/deepeval), Apache-2.0.
- Local checkout: `../deepeval`, version 4.2.6, upstream revision
  `385117c9c46e6935866422b7aa1f67e5e2824472`.
- Source: `deepeval/models/llms/codex_cli_model.py`, a local uncommitted addition,
  **not** code supplied by that upstream revision.
- Source SHA-256:
  `2d43ed26374fe035e37e9e029e0e616e04f70b14d9b46ee3848490e2873fa6db`.
- Associated local tests: `tests/test_core/test_models/test_codex_cli_model.py`, SHA-256
  `deccfb3659dccf86998f7a14a3517c6ed1dbc164ba6e9f7c70a26bfbda86fda9`.
- Destination: `src/bencheval/executors/codex.py`.
- Retained design: official CLI subprocess, ephemeral read-only run, stdin prompt,
  schema-constrained output, isolated temporary directory, final-response file.
- Changes: executor/result contracts independent of DeepEval; subscription-only
  login preflight; environment allowlist with no API-key fallback; controlled user
  config; per-user provider lock; explicit timeout/cancellation/status handling;
  JSONL evidence and normalized tool events; unknown price/quota rather than zero.
- Tests are newly authored BenchEval tests, not copied upstream tests:
  `tests/test_codex.py`, `tests/test_runtime.py`, `tests/test_events.py`, and the
  opt-in `tests/test_live.py`.
- Attribution: [NOTICE](../NOTICE) and
  [upstream license](../licenses/deepeval-apache-2.0.txt).

## AgentEval

Reference revision: `b3eace62a7e169f02d8e18b7c918c480c8c5ea05`, version 0.8.14,
MIT. Scenario/check separation and the future worktree runner are design references.
No source code has been copied or ported from AgentEval in this slice. License
copying and source-specific attribution are required before an actual code port.

## BenchEval-owned components

Scenario contracts, verdict aggregation, instruction snapshots, deterministic
checks, CLI, artifacts, and the test suite are newly implemented here. Core has
no runtime dependency on DeepEval or AgentEval. Python dependencies and their exact
resolved versions are recorded in `uv.lock`.

For future adoption, inspect the specific component, review licensing, record its
revision/content hash and tests, and adapt it separately. Do not bulk merge either
upstream repository or copy its aggregate scoring assumptions.
