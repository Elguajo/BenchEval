"""BenchEval-owned contracts; execution and evaluation are separate decisions."""

import json
import re
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Axis(StrEnum):
    OUTCOME = "outcome"
    INSTRUCTIONS = "instruction_fidelity"
    BEHAVIOR = "behavior"


class State(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_OBSERVABLE = "NOT_OBSERVABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_OBSERVABLE = "NOT_OBSERVABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CleanSuccess(StrEnum):
    YES = "YES"
    NO = "NO"
    INCONCLUSIVE = "INCONCLUSIVE"


class EvidenceType(StrEnum):
    RESPONSE = "response"
    INSTRUCTION = "instruction"
    TOOL_EVENT = "tool_event"
    GIT_DIFF = "git_diff"
    FILE_SNAPSHOT = "file_snapshot"
    COMMAND_LOG = "command_log"
    TEST_RESULT = "test_result"
    JUDGE_FINDING = "judge_finding"
    RUNTIME_METADATA = "runtime_metadata"
    GENERIC_ARTIFACT = "generic_artifact"


class ExecutionStatus(StrEnum):
    COMPLETED = "completed"
    AUTH_REQUIRED = "auth_required"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ERROR = "execution_error"


Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")]


def validate_schema(schema: dict[str, Any]) -> dict[str, Any]:
    # JSON Schema's format keyword is intentionally an annotation here.
    try:
        json.dumps(schema, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(
            "JSON Schema must contain finite, serializable JSON values"
        ) from error

    def inline_only(value):
        if isinstance(value, dict):
            if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                raise ValueError(
                    "Use inline JSON Schemas; references are not supported"
                )
            draft = value.get("$schema")
            if (
                draft is not None
                and draft != "https://json-schema.org/draft/2020-12/schema"
            ):
                raise ValueError("Only JSON Schema draft 2020-12 is supported")
            for item in value.values():
                inline_only(item)
        elif isinstance(value, list):
            for item in value:
                inline_only(item)

    inline_only(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid JSON Schema: {error.message}") from error
    return schema


class Instructions(Contract):
    variant: Identifier = "default"
    text: str = ""
    files: list[str] = Field(default_factory=list)


class ExecutorConfig(Contract):
    provider: Literal["codex"] = "codex"
    model: str | None = None
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    context_mode: Literal["controlled", "ambient"] = "controlled"


class Check(Contract):
    id: Identifier
    axes: list[Axis] = Field(min_length=1)
    severity: Literal["hard", "advisory"] = "hard"
    type: Literal["equals", "contains", "regex", "json_schema", "no_tools"]
    expected: str | None = None
    pattern: str | None = None
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def valid_parameters(self):
        if len(set(self.axes)) != len(self.axes):
            raise ValueError("Check axes must be unique")
        needed = {
            "equals": "expected",
            "contains": "expected",
            "regex": "pattern",
            "json_schema": "json_schema",
            "no_tools": None,
        }[self.type]
        for name in ("expected", "pattern", "json_schema"):
            value = getattr(self, name)
            if name == needed and value is None:
                raise ValueError(f"{self.type} requires {name}")
            if name != needed and value is not None:
                raise ValueError(f"{name} is not a parameter of {self.type}")
        if self.type == "regex":
            try:
                re.compile(self.pattern)
            except re.error as error:
                raise ValueError(f"Invalid regular expression: {error}") from error
        if self.type == "contains" and not self.expected:
            raise ValueError("contains requires a nonempty expected string")
        if self.json_schema is not None:
            validate_schema(self.json_schema)
        return self


class Scenario(Contract):
    version: Literal[1] = 1
    id: Identifier
    kind: Literal["response"] = "response"
    prompt: str = Field(min_length=1, max_length=100_000)
    instructions: Instructions = Field(default_factory=Instructions)
    policies: list[str] = Field(default_factory=list)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    checks: list[Check] = Field(min_length=1)
    response_schema: dict[str, Any] | None = None

    @field_validator("response_schema")
    @classmethod
    def schema_valid(cls, value):
        if value is not None:
            validate_schema(value)
            if value.get("type") != "object":
                raise ValueError("Codex response_schema must have an object root")
        return value

    @model_validator(mode="after")
    def scorable(self):
        if len({check.id for check in self.checks}) != len(self.checks):
            raise ValueError("Check IDs must be unique")
        if not any(
            Axis.OUTCOME in c.axes and c.severity == "hard" for c in self.checks
        ):
            raise ValueError("At least one hard outcome check is required")
        exact_answers = {
            c.expected
            for c in self.checks
            if c.type == "equals" and c.severity == "hard"
        }
        if len(exact_answers) > 1:
            raise ValueError("Hard equals checks require contradictory responses")
        return self


class InstructionSource(Contract):
    source: str
    text: str
    sha256: str


class InstructionBundle(Contract):
    variant: str
    sources: list[InstructionSource]
    policies: list[str]
    sha256: str
    delivery: str = "explicit prompt envelope"


class Event(Contract):
    id: str
    kind: str
    tool_action: bool


class Execution(Contract):
    status: ExecutionStatus
    provider: str = "codex"
    cli_version: str | None = None
    requested_model: str | None = None
    effective_model: str | None = None
    response: str = ""
    duration_seconds: float = 0
    exit_code: int | None = None
    reason: str | None = None
    events: list[Event] = Field(default_factory=list)
    trace_complete: bool = False
    usage: dict[str, int] = Field(default_factory=dict)
    quota_consumed: float | None = None
    cost_usd: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceRef(Contract):
    id: Identifier
    type: EvidenceType
    source: str = Field(min_length=1)
    locator: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CheckResult(Contract):
    id: str
    axes: list[Axis]
    severity: Literal["hard", "advisory"]
    state: State
    expected: str
    actual: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    checker_version: str = "1"

    @model_validator(mode="after")
    def established_finding_has_evidence(self):
        if self.state in (State.PASS, State.FAIL) and not self.evidence:
            raise ValueError("PASS/FAIL checks require evidence")
        if len({ref.id for ref in self.evidence}) != len(self.evidence):
            raise ValueError("Evidence IDs within a check must be unique")
        return self


class Verdicts(Contract):
    axes: dict[Axis, Verdict]
    overall: Verdict


class RunResult(Contract):
    version: Literal[2] = 2
    run_id: str
    created_at: str
    bencheval_version: str
    scenario: Scenario
    scenario_sha256: str
    instructions: InstructionBundle
    execution: Execution
    checks: list[CheckResult]
    verdicts: Verdicts
    clean_success: CleanSuccess
    evidence_hashes: dict[str, str]

    @property
    def advisories(self) -> list[CheckResult]:
        return [check for check in self.checks if check.severity == "advisory"]

    @model_validator(mode="after")
    def consistent_success(self):
        expected = {
            Verdict.PASS: CleanSuccess.YES,
            Verdict.FAIL: CleanSuccess.NO,
            Verdict.INCONCLUSIVE: CleanSuccess.INCONCLUSIVE,
        }
        if self.verdicts.overall not in expected:
            raise ValueError("Overall must be PASS, FAIL, or INCONCLUSIVE")
        if self.clean_success != expected[self.verdicts.overall]:
            raise ValueError("Clean Success must agree with Overall")
        if (
            self.clean_success == CleanSuccess.YES
            and self.execution.status != ExecutionStatus.COMPLETED
        ):
            raise ValueError("Clean Success YES requires completed execution")
        if any(
            ref.source not in self.evidence_hashes
            for check in self.checks
            for ref in check.evidence
        ):
            raise ValueError("Check evidence source is absent from artifact manifest")
        return self


class SuiteResult(Contract):
    version: Literal[1] = 1
    suite_id: Identifier
    scheduled_attempts: int = Field(ge=0)
    completed_attempts: int = Field(ge=0)
    clean_successes: int = Field(ge=0)
    failures: int = Field(ge=0)
    inconclusive: int = Field(ge=0)
    execution_failures: int = Field(ge=0)
    clean_success_rate: float | None = Field(default=None, ge=0, le=1)

    @classmethod
    def from_attempts(
        cls, suite_id: str, scheduled_attempts: int, attempts: list[RunResult]
    ) -> Self:
        """Partition hard failures, successes, completed unknowns, then run errors.

        An established hard failure keeps its failure bucket even if execution
        also stopped early. Per-attempt execution status remains in RunResult.
        """
        if len(attempts) > scheduled_attempts:
            raise ValueError("More recorded attempts than scheduled attempts")
        successes = sum(r.clean_success == CleanSuccess.YES for r in attempts)
        failures = sum(r.clean_success == CleanSuccess.NO for r in attempts)
        inconclusive = sum(
            r.clean_success == CleanSuccess.INCONCLUSIVE
            and r.execution.status == ExecutionStatus.COMPLETED
            for r in attempts
        )
        execution_failures = scheduled_attempts - successes - failures - inconclusive
        return cls(
            suite_id=suite_id,
            scheduled_attempts=scheduled_attempts,
            completed_attempts=sum(
                r.execution.status == ExecutionStatus.COMPLETED for r in attempts
            ),
            clean_successes=successes,
            failures=failures,
            inconclusive=inconclusive,
            execution_failures=execution_failures,
        )

    @model_validator(mode="after")
    def valid_counts(self):
        if self.completed_attempts > self.scheduled_attempts:
            raise ValueError("Completed attempts exceed scheduled attempts")
        if (
            self.clean_successes
            + self.failures
            + self.inconclusive
            + self.execution_failures
            != self.scheduled_attempts
        ):
            raise ValueError("Attempt categories must cover all scheduled attempts")
        if self.clean_successes + self.inconclusive > self.completed_attempts:
            raise ValueError("Completed result counts exceed completed attempts")
        expected = (
            self.clean_successes / self.scheduled_attempts
            if self.scheduled_attempts
            else None
        )
        if self.clean_success_rate is not None and self.clean_success_rate != expected:
            raise ValueError("CSR must equal clean successes / scheduled attempts")
        self.clean_success_rate = expected
        return self
