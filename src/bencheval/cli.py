"""Local CLI. Exit codes: 0 pass, 1 fail, 2 invalid input, 3 inconclusive."""

import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from bencheval import __version__
from bencheval.artifacts import ArtifactError, read_result
from bencheval.codex_context import controlled_context
from bencheval.contracts import RunResult, Verdict
from bencheval.executors.codex import OVERRIDES, child_environment, probe_codex
from bencheval.judges.contracts import JudgeResult
from bencheval.judges.evaluate import import_verdict, read_judge_result, run_job
from bencheval.judges.jobs import JudgeError, prepare_job
from bencheval.runner import run_scenario
from bencheval.scenarios import ScenarioError, load_instructions, load_scenario
from bencheval.ui import make_server

app = typer.Typer(no_args_is_help=True, help="Instruction-aware LLM evaluation.")
judge_app = typer.Typer(
    no_args_is_help=True, help="Independent LLM judging of preserved actor runs."
)
app.add_typer(judge_app, name="judge")

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


def summarize_judge(result: JudgeResult, path: Path) -> None:
    typer.echo(f"Overall: {result.verdicts.overall} (actor checks + judge rubric)")
    typer.echo(f"Judge: {result.invocation.provider} / {result.invocation.status}")
    for axis, verdict in result.verdicts.axes.items():
        typer.echo(f"{axis}: {verdict}")
    for check in result.checks:
        typer.echo(f"  {check.id}: {check.state} ({check.actual})")
    for warning in result.warnings:
        typer.echo(f"WARNING: {warning}")
    if result.invocation.reason:
        typer.echo(f"Reason: {result.invocation.reason}")
    typer.echo(f"Artifacts: {path.resolve()}")


def exit_verdict(verdict: Verdict) -> None:
    if verdict == Verdict.FAIL:
        raise typer.Exit(1)
    if verdict != Verdict.PASS:
        raise typer.Exit(3)


@judge_app.command("export")
def judge_export(
    source: Path,
    config: Annotated[Path, typer.Option(help="Explicit judge YAML configuration.")],
    output: Path = Path(".bencheval/judges"),
) -> None:
    """Snapshot a verified actor run and rubric, without calling a model."""
    try:
        job, directory = prepare_job(source, config, output)
    except (JudgeError, ArtifactError, OSError) as error:
        fail(error)
    typer.echo(f"Judge job: {job.id} ({job.config.provider})")
    typer.echo(f"Prompt: {(directory / 'prompt.txt').resolve()}")
    typer.echo(
        "For desktop mode, paste this prompt into a NEW Codex chat, "
        "then import its JSON reply."
    )


@judge_app.command("run")
def judge_run(
    source: Path,
    config: Annotated[Path, typer.Option(help="Explicit judge YAML configuration.")],
    output: Path = Path(".bencheval/judges"),
) -> None:
    """Judge a saved run through Codex, Ollama or an OpenAI-compatible API."""
    try:
        job, directory = prepare_job(source, config, output)
        if job.config.allow_remote:
            typer.echo(
                "NOTICE: Sending snapshotted evidence to the "
                "explicitly configured remote judge."
            )
        typer.echo(f"Judge artifacts: {directory.resolve()}")
        result = run_job(directory)
    except (JudgeError, ArtifactError, OSError) as error:
        fail(error)
    summarize_judge(result, directory)
    exit_verdict(result.verdicts.overall)


@judge_app.command("import")
def judge_import(job: Path, reply: Path) -> None:
    """Validate a desktop JSON reply and finalize its exported job exactly once."""
    try:
        result = import_verdict(job, reply)
    except (JudgeError, OSError) as error:
        fail(error)
    summarize_judge(result, job if job.is_dir() else job.parent)
    exit_verdict(result.verdicts.overall)


@judge_app.command("inspect")
def judge_inspect(path: Path) -> None:
    """Verify a saved judge result and its source evidence, without model calls."""
    try:
        result = read_judge_result(path)
    except JudgeError as error:
        fail(error)
    summarize_judge(result, path if path.is_dir() else path.parent)


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
            if probe["available"]:
                try:
                    context = controlled_context(
                        probe["binary"], Path(name), child_environment(), OVERRIDES
                    )
                    probe["context"] = {
                        k: v for k, v in context.items() if k != "disabled_paths"
                    }
                except OSError:
                    probe["available"] = False
                    probe["reason"] = (
                        "Controlled context unavailable. Update Codex or explicitly "
                        "choose ambient mode; disable skills/global instructions "
                        "manually before comparisons."
                    )
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
        scenario = load_scenario(path)
        if scenario.executor.context_mode == "ambient":
            typer.echo(
                "WARNING: Ambient Codex context. Disable global skills/instructions "
                "before comparisons; this run is not controlled.",
                err=True,
            )
        result, directory = run_scenario(path, output)
    except (ScenarioError, OSError) as error:
        fail(error)
    summarize(result, directory)
    if result.verdicts.overall == Verdict.FAIL:
        raise typer.Exit(1)
    if result.verdicts.overall != Verdict.PASS:
        raise typer.Exit(3)


@app.command()
def ui(
    runs: Path = Path(".bencheval/runs"),
    judges: Path = Path(".bencheval/judges"),
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
) -> None:
    """Serve a loopback-only, read-only browser for actor/judge evidence."""
    try:
        with make_server(runs, judges, port) as server:
            typer.echo(f"BenchEval UI: http://127.0.0.1:{server.server_port}/")
            typer.echo("Read-only local artifacts. No model calls. Stop with Ctrl+C.")
            server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        typer.echo("UI stopped")
    except OSError as error:
        fail(error)


@app.command()
def inspect(path: Path) -> None:
    """Read a saved result and verify its evidence hashes; make no model call."""
    try:
        result = read_result(path)
    except ArtifactError as error:
        fail(error)
    summarize(result, path if path.is_dir() else path.parent)
