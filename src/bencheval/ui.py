"""Loopback-only, read-only artifact browser. Never launches inference."""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from bencheval.artifacts import ArtifactError, read_result
from bencheval.judges.evaluate import read_judge_result
from bencheval.judges.jobs import JudgeError, read_job

RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[a-f0-9]{12}$")
STATIC = Path(__file__).parent / "web"


class ArtifactBrowser:
    def __init__(self, runs: Path, judges: Path):
        self.roots = {"actor": runs.resolve(), "judge": judges.resolve()}

    def directory(self, kind: str, identifier: str) -> Path:
        if kind not in self.roots or not RUN_ID.fullmatch(identifier):
            raise ValueError("Unknown run")
        directory = self.roots[kind] / identifier
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Unknown run")
        return directory

    def detail(self, kind: str, identifier: str) -> dict:
        directory = self.directory(kind, identifier)
        if kind == "actor":
            result = read_result(directory)
            context = result.execution.metadata.get("context")
            return {
                "id": identifier,
                "kind": kind,
                "name": result.scenario.id,
                "status": result.execution.status.value,
                "verdicts": result.verdicts.model_dump(),
                "clean_success": result.clean_success.value,
                "checks": [
                    c.model_dump() for c in result.checks if c.severity == "hard"
                ],
                "advisories": [c.model_dump() for c in result.advisories],
                "evidence": {
                    "request": result.scenario.prompt,
                    "response": result.execution.response,
                    "instructions": result.instructions.model_dump_json(indent=2),
                    "trace": json.dumps(
                        [e.model_dump() for e in result.execution.events], indent=2
                    ),
                },
                "metadata": result.execution.model_dump(exclude={"response", "events"}),
                "warnings": (
                    []
                    if isinstance(context, dict) and context.get("mode") == "controlled"
                    else [
                        "Actor ambient skills/instructions were not verified; "
                        "this is not a controlled instruction-comparison baseline."
                    ]
                ),
                "actor_run_id": None,
                "verified": True,
            }
        job = read_job(directory)
        if not (directory / "result.json").exists():
            return {
                "id": identifier,
                "kind": kind,
                "name": job.actor_run_id,
                "status": "awaiting verdict",
                "verdicts": None,
                "clean_success": None,
                "checks": [],
                "advisories": [],
                "evidence": job.evidence,
                "metadata": {"provider": job.config.provider},
                "warnings": [
                    "Exported job; no judge verdict has been imported or run."
                ],
                "actor_run_id": job.actor_run_id,
                "verified": True,
            }
        result = read_judge_result(directory)
        return {
            "id": identifier,
            "kind": kind,
            "name": job.actor_run_id,
            "status": result.invocation.status.value,
            "verdicts": result.verdicts.model_dump(),
            "clean_success": result.clean_success.value,
            "checks": [
                c.model_dump()
                for c in job.source_checks + result.checks
                if c.severity == "hard"
            ],
            "advisories": [
                c.model_dump()
                for c in job.source_checks + result.checks
                if c.severity == "advisory"
            ],
            "evidence": {**job.evidence, "judge response": result.invocation.response},
            "metadata": result.invocation.model_dump(exclude={"response", "events"}),
            "warnings": result.warnings,
            "actor_run_id": job.actor_run_id,
            "verified": True,
        }

    def list_runs(self) -> dict:
        entries = []
        for kind, root in self.roots.items():
            if not root.exists():
                continue
            for directory in root.iterdir():
                if (
                    RUN_ID.fullmatch(directory.name)
                    and directory.is_dir()
                    and not directory.is_symlink()
                ):
                    entries.append((directory.name, kind))
        entries.sort(reverse=True)
        runs = []
        for identifier, kind in entries[:200]:
            try:
                detail = self.detail(kind, identifier)
                verdict = (
                    detail["verdicts"]["overall"] if detail["verdicts"] else "PENDING"
                )
                runs.append(
                    {
                        "id": identifier,
                        "kind": kind,
                        "name": detail["name"],
                        "status": detail["status"],
                        "overall": verdict,
                    }
                )
            except (ValueError, OSError):
                runs.append(
                    {
                        "id": identifier,
                        "kind": kind,
                        "name": identifier,
                        "status": "Invalid evidence; inspect with CLI",
                        "overall": "INVALID",
                    }
                )
        return {"runs": runs, "total": len(entries), "limit": 200}


def make_server(runs: Path, judges: Path, port: int = 8765) -> ThreadingHTTPServer:
    browser = ArtifactBrowser(runs, judges)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log private run URLs or evidence.

        def send_body(self, status: int, content: bytes, content_type: str) -> None:
            self.send_response(status)
            for key, value in {
                "Content-Type": content_type,
                "Content-Length": str(len(content)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'",
            }.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(content)

        def send_json(self, status: int, body: dict) -> None:
            self.send_body(
                status, json.dumps(body).encode(), "application/json; charset=utf-8"
            )

        def do_GET(self):
            allowed = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            host = self.headers.get("Host")
            origin = self.headers.get("Origin")
            if host not in allowed or (origin and origin != "http://" + host):
                self.send_json(
                    403, {"error": "Only same-origin loopback requests are allowed"}
                )
                return
            route = urlsplit(self.path).path
            assets = {
                "/": ("index.html", "text/html"),
                "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
            }
            try:
                if route in assets:
                    name, content_type = assets[route]
                    self.send_body(
                        200,
                        (STATIC / name).read_bytes(),
                        content_type + "; charset=utf-8",
                    )
                elif route == "/api/runs":
                    self.send_json(200, browser.list_runs())
                elif route.startswith("/api/runs/"):
                    parts = route.split("/")
                    if len(parts) != 5:
                        raise ValueError("Unknown run")
                    self.send_json(200, browser.detail(parts[3], parts[4]))
                else:
                    self.send_json(404, {"error": "Not found"})
            except (ArtifactError, JudgeError):
                self.send_json(
                    409,
                    {
                        "error": "Evidence is invalid or has changed. "
                        "Verify this run with CLI inspect."
                    },
                )
            except ValueError:
                self.send_json(404, {"error": "Unknown run"})
            except OSError:
                self.send_json(
                    409,
                    {"error": "Artifact unavailable. Check local files, then refresh."},
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
