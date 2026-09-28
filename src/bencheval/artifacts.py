import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bencheval.contracts import RunResult


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


def save_result(directory: Path, result: RunResult) -> None:
    temporary = directory / "result.json.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(result.model_dump_json(indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "result.json")


def read_result(path: Path) -> RunResult:
    path = path / "result.json" if path.is_dir() else path
    try:
        result = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        for name, expected in result.evidence_hashes.items():
            evidence = path.parent / name
            if Path(name).name != name or evidence.is_symlink():
                raise ArtifactError(f"Unsafe evidence reference: {name}")
            if hashlib.sha256(evidence.read_bytes()).hexdigest() != expected:
                raise ArtifactError(f"Evidence changed since evaluation: {name}")
        return result
    except (OSError, ValueError) as error:
        raise ArtifactError(f"{path}: {error}") from error
