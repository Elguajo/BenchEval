import http.client
import json
import threading

import pytest

from bencheval.contracts import Check, Execution, ExecutionStatus
from bencheval.runner import run_scenario
from bencheval.ui import ArtifactBrowser, make_server


def test_artifact_browser_lists_actor_and_judge_without_inference(make_job):
    job, directory, source = make_job()
    browser = ArtifactBrowser(source.parent, directory.parent)
    entries = browser.list_runs()
    assert entries["total"] == 2
    assert {run["overall"] for run in entries["runs"]} == {"PASS", "PENDING"}
    actor = browser.detail("actor", source.name)
    assert actor["verified"] and actor["evidence"]["response"] == "4"
    assert actor["clean_success"] == "YES"
    assert actor["checks"][0]["evidence"][0]["type"] == "response"
    assert any("ambient" in warning for warning in actor["warnings"])
    judge = browser.detail("judge", directory.name)
    assert judge["actor_run_id"] == job.actor_run_id


def test_browser_separates_advisory_from_hard_checks(scenario, tmp_path):
    scenario.checks.append(
        Check(
            id="style",
            axes=["instruction_fidelity"],
            severity="advisory",
            type="equals",
            expected="5",
        )
    )
    path = tmp_path / "scenario.json"
    path.write_text(scenario.model_dump_json())

    class OfflineExecutor:
        def run(self, scenario, prompt, artifact_dir):
            return Execution(status=ExecutionStatus.COMPLETED, response="4")

    _, directory = run_scenario(path, tmp_path / "runs", executor=OfflineExecutor())
    detail = ArtifactBrowser(directory.parent, tmp_path / "judges").detail(
        "actor", directory.name
    )
    assert [check["id"] for check in detail["checks"]] == ["answer"]
    assert [check["id"] for check in detail["advisories"]] == ["style"]
    assert detail["clean_success"] == "YES"


def test_path_traversal_and_symlinks_are_not_served(tmp_path):
    browser = ArtifactBrowser(tmp_path / "runs", tmp_path / "judges")
    with pytest.raises(ValueError):
        browser.detail("actor", "../../secrets")
    root = tmp_path / "runs"
    root.mkdir()
    target = tmp_path / "private"
    target.mkdir()
    identifier = "20260928T000000-123456abcdef"
    (root / identifier).symlink_to(target)
    with pytest.raises(ValueError):
        browser.detail("actor", identifier)
    assert browser.list_runs()["total"] == 0


def test_loopback_web_security_headers_origin_and_invalid_evidence(make_job):
    _, directory, source = make_job(response='<img src=x onerror="alert(1)">')
    with make_server(source.parent, directory.parent, 0) as server:
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        thread.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=2
        )
        try:
            assert server.server_address[0] == "127.0.0.1"
            connection.request("GET", "/")
            response = connection.getresponse()
            assert response.status == 200
            assert "script-src 'self'" in response.getheader("Content-Security-Policy")
            assert response.getheader("Cache-Control") == "no-store"
            assert b"BenchEval" in response.read()
            connection.request("GET", f"/api/runs/actor/{source.name}")
            response = connection.getresponse()
            assert json.loads(response.read())["evidence"]["response"].startswith(
                "<img"
            )
            connection.request("GET", "/api/runs", headers={"Host": "attacker.example"})
            response = connection.getresponse()
            assert response.status == 403
            response.read()
            connection.request(
                "GET", "/api/runs", headers={"Origin": "https://attacker.example"}
            )
            response = connection.getresponse()
            assert response.status == 403
            response.read()
            (source / "response.txt").write_text("tampered")
            connection.request("GET", f"/api/runs/actor/{source.name}")
            response = connection.getresponse()
            assert response.status == 409
            response.read()
        finally:
            connection.close()
            server.shutdown()
            thread.join(timeout=2)
