"""Local CLI. Exit codes: 0 pass, 1 fail, 2 invalid input, 3 inconclusive."""

import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from bencheval import __version__
from bencheval.artifacts import ArtifactError, read_result
from bencheval.contracts import RunResult, Verdict
from bencheval.executors.codex import probe_codex
from bencheval.runner import run_scenario
from bencheval.scenarios import ScenarioError, load_instructions, load_scenario

app = typer.Typer(no_args_is_help=True, help="Instruction-aware LLM evaluation.")

STARTER = """version: 1
id: arithmetic
kind: response
prompt: "What is 2 + 2?"
instructions:
  variant: concise-json
  text: "Return only a JSON object with the integer field answer. Do not use tools."
policies:
  - "Do not call tools."
executor:
  provider: codex
  timeout_seconds: 120
response_schema:
  type: object
  properties:
    answer: {type: integer}
  required: [answer]
  additionalProperties: false
checks:
  - id: correct-answer
    axes: [outcome]
    severity: hard
    type: json_schema
    json_schema:
      type: object
      properties:
        answer: {const: 4}
      required: [answer]
      additionalProperties: false
  - id: response-format
    axes: [instruction_fidelity]
    severity: hard
    type: json_schema
    json_schema:
      type: object
      properties:
        answer: {type: integer}
      required: [answer]
      additionalProperties: false
  - id: no-tool-actions
    axes: [instruction_fidelity, behavior]
    severity: hard
    type: no_tools
"""


def fail(error: Exception) -> None:
    typer.echo(str(error), err=True)
    raise typer.Exit(2)


def summarize(result: RunResult, path: Path) -> None:
    typer.echo(f"Overall: {result.verdicts.overall}")
    typer.echo(f"Execution: {result.execution.status}")
    for axis, verdict in result.verdicts.axes.items():
        typer.echo(f"{axis}: {verdict}")
    for check in result.checks:
        typer.echo(f"  {check.id}: {check.state} ({check.actual})")
    if result.execution.reason:
        typer.echo(f"Reason: {result.execution.reason}")
    typer.echo(f"Artifacts: {path.resolve()}")


@app.command()
def version() -> None:
    """Print the installed BenchEval version."""
    typer.echo(__version__)


@app.command()
def init(path: Annotated[Path, typer.Argument()] = Path("scenario.yaml")) -> None:
    """Create a response scenario without overwriting an existing file."""
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(STARTER)
    except OSError as error:
        fail(error)
    typer.echo(f"Created {path}")


@app.command()
def validate(path: Path) -> None:
    """Validate the scenario and referenced instruction files, without a model call."""
    try:
        scenario = load_scenario(path)
        bundle = load_instructions(scenario, path.parent)
    except ScenarioError as error:
        fail(error)
    typer.echo(f"Valid: {scenario.id} ({len(scenario.checks)} checks)")
    typer.echo(f"Instruction snapshot: {bundle.sha256}")


@app.command()
def doctor() -> None:
    """Check local CLI capabilities and subscription login; make no model call."""
    try:
        with tempfile.TemporaryDirectory(prefix="bencheval-doctor-") as name:
            probe = probe_codex("codex", Path(name))
    except OSError as error:
        fail(error)
    typer.echo(json.dumps(probe, indent=2))
    if not probe["available"]:
        raise typer.Exit(3)


@app.command()
def run(
    path: Path,
    output: Annotated[Path, typer.Option(help="Local artifact root.")] = Path(
        ".bencheval/runs"
    ),
) -> None:
    """Run a response scenario through the locally authenticated Codex CLI."""
    try:
        result, directory = run_scenario(path, output)
    except (ScenarioError, OSError) as error:
        fail(error)
    summarize(result, directory)
    if result.verdicts.overall == Verdict.FAIL:
        raise typer.Exit(1)
    if result.verdicts.overall != Verdict.PASS:
        raise typer.Exit(3)


@app.command()
def inspect(path: Path) -> None:
    """Read a saved result and verify its evidence hashes; make no model call."""
    try:
        result = read_result(path)
    except ArtifactError as error:
        fail(error)
    summarize(result, path if path.is_dir() else path.parent)
