import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bencheval.contracts import Contract, RunResult


class ArtifactError(ValueError):
    pass


def new_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:12]
    directory = root / run_id
    directory.mkdir(mode=0o700)
    return directory


def hash_evidence(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file() and path.name != "result.json"
    }


def save_result(directory: Path, result: Contract) -> None:
    temporary = directory / "result.json.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(result.model_dump_json(indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "result.json")


def read_result(path: Path) -> RunResult:
    path = path / "result.json" if path.is_dir() else path
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ArtifactError("Actor result must be a JSON object")
        if value.get("version") != 2:
            raise ArtifactError(
                f"Unsupported actor result version {value.get('version')}; expected 2"
            )
        result = RunResult.model_validate(value)
        verify_evidence(path.parent, result.evidence_hashes)
        return result
    except (OSError, ValueError) as error:
        raise ArtifactError(f"{path}: {error}") from error


def verify_evidence(directory: Path, hashes: dict[str, str]) -> None:
    for name, expected in hashes.items():
        evidence = directory / name
        if Path(name).name != name or evidence.is_symlink():
            raise ArtifactError(f"Unsafe evidence reference: {name}")
        if hashlib.sha256(evidence.read_bytes()).hexdigest() != expected:
            raise ArtifactError(f"Evidence changed since evaluation: {name}")
