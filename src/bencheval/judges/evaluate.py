import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from bencheval.artifacts import hash_evidence, save_result, verify_evidence
from bencheval.contracts import CheckResult, Execution, ExecutionStatus, State
from bencheval.json_utils import strict_json_loads
from bencheval.judges.contracts import JudgeConfig, JudgeResult
from bencheval.judges.jobs import JudgeError, read_job, sha
from bencheval.judges.providers import CodexJudge, HTTPJudge
from bencheval.verdicts import aggregate


class JudgeProvider(Protocol):
    def invoke(
        self, config: JudgeConfig, prompt: str, schema: dict, directory: Path
    ) -> Execution: ...


def finish_job(path: Path, invocation: Execution) -> JudgeResult:
    job = read_job(path)
    directory = path if path.is_dir() else path.parent
    if (directory / "result.json").exists():
        raise JudgeError("Judge job already finalized; create a new job to re-evaluate")
    error = None
    decisions = {}
    if invocation.status == ExecutionStatus.COMPLETED:
        try:
            if invocation.provider == "codex" and (
                not invocation.trace_complete
                or any(e.tool_action for e in invocation.events)
            ):
                raise ValueError("Judge trace is incomplete or contains tool actions")
            value = strict_json_loads(invocation.response)
            Draft202012Validator(job.response_schema).validate(value)
            for decision in value["criteria"]:
                identifier = decision["id"]
                if identifier in decisions or not decision["explanation"].strip():
                    raise ValueError("Duplicate criterion or missing explanation")
                if len(set(decision["evidence"])) != len(decision["evidence"]):
                    raise ValueError("Duplicate evidence reference")
                if not set(decision["evidence"]).issubset(job.evidence):
                    raise ValueError("Unknown evidence reference")
                if decision["state"] != "NOT_OBSERVABLE" and not decision["evidence"]:
                    raise ValueError("PASS/FAIL requires cited evidence")
                decisions[identifier] = decision
            if set(decisions) != {c.id for c in job.config.criteria}:
                raise ValueError("Missing rubric criteria")
        except (ValueError, KeyError, TypeError, RecursionError) as failure:
            error = str(failure)[:300]
        except ValidationError:
            error = "Judge JSON does not satisfy the output schema"
    else:
        error = invocation.reason or invocation.status.value
    checks = []
    for criterion in job.config.criteria:
        available = all(job.availability[k] for k in criterion.requires)
        if not available:
            state, actual, refs = (
                State.NOT_OBSERVABLE,
                "Required actor evidence unavailable",
                [],
            )
        elif error:
            state, actual, refs = State.ERROR, error, []
        else:
            decision = decisions[criterion.id]
            state = State(decision["state"])
            actual = decision["explanation"]
            refs = ["job.json#evidence/" + ref for ref in decision["evidence"]]
            if state != State.NOT_OBSERVABLE and not set(criterion.requires).issubset(
                decision["evidence"]
            ):
                state, actual, refs = State.ERROR, "Required evidence was not cited", []
        checks.append(
            CheckResult(
                id="llm." + criterion.id,
                axes=criterion.axes,
                severity=criterion.severity,
                state=state,
                expected=criterion.requirement,
                actual=actual,
                evidence=refs,
                checker_version="llm-judge-1",
            )
        )
    (directory / "response.txt").write_text(invocation.response, encoding="utf-8")
    warnings = []
    if job.actor_provider == invocation.provider:
        warnings.append("Same-provider judging; correlated mistakes are possible")
    if invocation.provider == "desktop":
        warnings.append(
            "Manual desktop import: judge identity, auth and ambient context unverified"
        )
    result = JudgeResult(
        job_id=job.id,
        actor_run_id=job.actor_run_id,
        source_sha256=job.source_sha256,
        job_sha256=sha(job.model_dump_json()),
        rubric_sha256=sha(job.config.model_dump_json()),
        invocation=invocation,
        checks=checks,
        verdicts=aggregate(
            job.source_checks + checks, ExecutionStatus(job.actor_status)
        ),
        warnings=warnings,
        evidence_hashes=hash_evidence(directory),
    )
    save_result(directory, result)
    return result


@contextmanager
def job_lock(directory: Path):
    descriptor = os.open(
        directory / "judge.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise JudgeError(
                "Judge job is already running in another process"
            ) from error
        yield
    finally:
        os.close(descriptor)


def run_job(path: Path, *, provider: JudgeProvider | None = None) -> JudgeResult:
    job = read_job(path)
    directory = path if path.is_dir() else path.parent
    if (directory / "result.json").exists():
        raise JudgeError("Judge job already finalized")
    if job.config.provider == "desktop":
        raise JudgeError(
            "Desktop mode is interactive: export the job, then import its JSON verdict"
        )
    with job_lock(directory):
        if (directory / "result.json").exists():
            raise JudgeError("Judge job already finalized")
        provider = provider or (
            CodexJudge() if job.config.provider == "codex" else HTTPJudge()
        )
        invocation = provider.invoke(
            job.config,
            (directory / "prompt.txt").read_text(encoding="utf-8"),
            job.response_schema,
            directory,
        )
        return finish_job(path, invocation)


def import_verdict(path: Path, reply: Path) -> JudgeResult:
    job = read_job(path)
    if job.config.provider != "desktop":
        raise JudgeError(
            "Manual imports require an explicit desktop judge configuration"
        )
    if reply.stat().st_size > 2_000_000:
        raise JudgeError("Desktop verdict exceeds 2 MB")
    invocation = Execution(
        status=ExecutionStatus.COMPLETED,
        provider="desktop",
        requested_model=job.config.model,
        response=reply.read_text(encoding="utf-8"),
        metadata={"transport": "manual file hand-off", "identity_verified": False},
    )
    directory = path if path.is_dir() else path.parent
    with job_lock(directory):
        return finish_job(path, invocation)


def read_judge_result(path: Path) -> JudgeResult:
    path = path / "result.json" if path.is_dir() else path
    try:
        result = JudgeResult.model_validate(
            strict_json_loads(path.read_text(encoding="utf-8"))
        )
        verify_evidence(path.parent, result.evidence_hashes)
        job = read_job(path.parent)
        if (
            result.job_id != job.id
            or result.actor_run_id != job.actor_run_id
            or result.job_sha256 != sha(job.model_dump_json())
            or result.rubric_sha256 != sha(job.config.model_dump_json())
            or result.source_sha256 != job.source_sha256
        ):
            raise JudgeError("Judge result does not match its job")
        return result
    except (OSError, ValueError, RecursionError) as error:
        raise JudgeError(f"{path}: {error}") from error
