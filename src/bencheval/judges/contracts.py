import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from bencheval.contracts import (
    Axis,
    CheckResult,
    Contract,
    Execution,
    Identifier,
    Verdicts,
)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Criterion(Contract):
    id: Identifier
    axes: list[Axis] = Field(min_length=1)
    requirement: str = Field(min_length=1, max_length=5000)
    severity: Literal["hard", "advisory"] = "advisory"
    requires: list[Literal["response", "instructions", "trace"]] = Field(
        default_factory=lambda: ["response"], min_length=1
    )

    @model_validator(mode="after")
    def observable(self):
        if len(set(self.axes)) != len(self.axes) or len(set(self.requires)) != len(
            self.requires
        ):
            raise ValueError("Criterion axes and evidence requirements must be unique")
        if Axis.BEHAVIOR in self.axes and "trace" not in self.requires:
            raise ValueError("Behavior criteria require trace evidence")
        return self


class JudgeConfig(Contract):
    provider: Literal["codex", "desktop", "ollama", "openai_compatible"] = "codex"
    model: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    allow_remote: bool = False
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    criteria: list[Criterion] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_provider(self):
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Criterion IDs must be unique")
        if self.provider in ("codex", "desktop"):
            if self.base_url or self.api_key_env or self.allow_remote:
                raise ValueError(
                    "Codex/desktop use subscription login, not API settings"
                )
        else:
            if not self.model:
                raise ValueError("HTTP judges require an explicit model")
            if self.provider == "ollama" and self.base_url is None:
                self.base_url = "http://127.0.0.1:11434"
            if not self.base_url:
                raise ValueError("HTTP judges require base_url")
            url = urlsplit(self.base_url)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "Use a clean HTTP(S) base_url without credentials/query"
                )
            # Validate port now, not after sending evidence.
            _ = url.port
            local = is_loopback(url.hostname)
            if not local and (url.scheme != "https" or not self.allow_remote):
                raise ValueError("Remote judges require HTTPS and allow_remote: true")
            if self.api_key_env and url.scheme != "https":
                raise ValueError(
                    "API credentials require HTTPS even for local endpoints"
                )
        return self


class JudgeJob(Contract):
    version: Literal[1] = 1
    id: str
    source_path: str
    source_sha256: str
    actor_run_id: str
    actor_provider: str
    actor_status: str
    source_checks: list[CheckResult]
    config: JudgeConfig
    evidence: dict[str, str]
    evidence_sha256: dict[str, str]
    availability: dict[str, bool]
    response_schema: dict
    prompt_sha256: str


class JudgeResult(Contract):
    version: Literal[1] = 1
    job_id: str
    actor_run_id: str
    source_sha256: str
    job_sha256: str
    rubric_sha256: str
    invocation: Execution
    checks: list[CheckResult]
    verdicts: Verdicts
    warnings: list[str]
    evidence_hashes: dict[str, str]
