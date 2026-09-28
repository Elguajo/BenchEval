import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from bencheval import __version__
from bencheval.artifacts import hash_evidence, new_directory, save_result
from bencheval.checks import evaluate
from bencheval.contracts import CleanSuccess, Execution, RunResult, Scenario, Verdict
from bencheval.executors.codex import CodexExecutor
from bencheval.scenarios import digest, load_instructions, load_scenario, render_prompt
from bencheval.verdicts import aggregate


class Executor(Protocol):
    def run(self, scenario: Scenario, prompt: str, artifact_dir: Path) -> Execution: ...


def run_scenario(
    path: Path, output: Path, *, executor: Executor | None = None
) -> tuple[RunResult, Path]:
    # All configuration and instruction paths validated before creating an attempt.
    scenario = load_scenario(path)
    bundle = load_instructions(scenario, path.parent)
    prompt = render_prompt(scenario, bundle)
    directory = new_directory(output)
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    (directory / "instructions.json").write_text(
        bundle.model_dump_json(indent=2), encoding="utf-8"
    )
    (directory / "scenario.json").write_text(
        scenario.model_dump_json(indent=2), encoding="utf-8"
    )
    execution = (executor or CodexExecutor()).run(scenario, prompt, directory)
    (directory / "response.txt").write_text(execution.response, encoding="utf-8")
    (directory / "events.json").write_text(
        json.dumps([e.model_dump() for e in execution.events], indent=2),
        encoding="utf-8",
    )
    (directory / "runtime.json").write_text(
        json.dumps(
            {
                "status": execution.status.value,
                "trace_complete": execution.trace_complete,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    checks = [evaluate(check, execution) for check in scenario.checks]
    verdicts = aggregate(checks, execution.status)
    result = RunResult(
        run_id=directory.name,
        created_at=datetime.now(UTC).isoformat(),
        bencheval_version=__version__,
        scenario=scenario,
        scenario_sha256=digest(scenario.model_dump(mode="json")),
        instructions=bundle,
        execution=execution,
        checks=checks,
        verdicts=verdicts,
        clean_success={
            Verdict.PASS: CleanSuccess.YES,
            Verdict.FAIL: CleanSuccess.NO,
            Verdict.INCONCLUSIVE: CleanSuccess.INCONCLUSIVE,
        }[verdicts.overall],
        evidence_hashes=hash_evidence(directory),
    )
    save_result(directory, result)
    return result, directory
