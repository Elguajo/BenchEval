import json
import os
import tomllib

import pytest

from bencheval.codex_context import controlled_context, list_skills, skills_override
from bencheval.contracts import ExecutionStatus
from bencheval.executors.codex import CodexExecutor


def test_toml_override_preserves_paths():
    paths = ['/tmp/space and "quote"/SKILL.md', "/tmp/already-disabled/SKILL.md"]
    config = tomllib.loads(skills_override(paths))
    assert config["skills"]["config"] == [{"path": p, "enabled": False} for p in paths]


def test_native_preflight_disables_all_without_global_writes(fake_codex, tmp_path):
    skills = [
        {"path": "/tmp/one/SKILL.md", "enabled": True},
        {"path": "/tmp/two/SKILL.md", "enabled": False},
    ]
    global_config = tmp_path / "config.toml"
    global_config.write_text("# unchanged user settings\n")
    context = controlled_context(
        fake_codex(skills=skills), tmp_path, os.environ.copy(), {}
    )
    assert context["discovered_skills"] == 2
    assert context["enabled_skills"] == 0
    assert context["disabled_paths"] == [s["path"] for s in skills]
    assert not context["global_config_modified"]
    assert global_config.read_text() == "# unchanged user settings\n"


@pytest.mark.parametrize(
    "settings",
    [
        {
            "skills": [{"path": "/tmp/a/SKILL.md", "enabled": True}],
            "ignore_disabling": True,
        },
        {"skill_errors": [{"message": "catalog failure"}]},
        {"skills": [{"path": "relative/SKILL.md", "enabled": True}]},
        {"skills": [{"path": "/tmp/SKILL.md", "enabled": "false"}]},
    ],
)
def test_uncertain_context_refuses_actor_inference(
    fake_codex, tmp_path, scenario, settings
):
    result = CodexExecutor(fake_codex(**settings)).run(scenario, "Return 4.", tmp_path)
    assert result.status == ExecutionStatus.ERROR
    assert not (tmp_path / "stdout.jsonl").exists()


def test_rpc_timeout_terminates_child(fake_codex, tmp_path):
    binary = fake_codex(rpc_delay=2)
    with pytest.raises(OSError, match="timed out"):
        list_skills(binary, tmp_path, os.environ.copy(), {}, timeout=0.05)


def test_catalog_change_refuses_controlled_context(monkeypatch, tmp_path):
    calls = iter(
        [
            [{"path": "/tmp/one/SKILL.md", "enabled": True}],
            [{"path": "/tmp/new/SKILL.md", "enabled": False}],
        ]
    )
    monkeypatch.setattr(
        "bencheval.codex_context.list_skills", lambda *a, **k: next(calls)
    )
    with pytest.raises(OSError, match="catalog changed"):
        controlled_context("codex", tmp_path, {}, {})


def test_ambient_mode_is_explicit_and_skips_catalog(fake_codex, tmp_path, scenario):
    scenario.executor.context_mode = "ambient"
    binary = fake_codex(skill_errors=[{"message": "bad catalog"}])
    result = CodexExecutor(binary).run(scenario, "Return 4.", tmp_path)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.metadata["context"]["mode"] == "ambient"
    assert not any(arg.startswith("skills.config=") for arg in result.metadata["argv"])
    assert (
        json.loads((tmp_path / "codex-context.json").read_text())["enabled_skills"]
        is None
    )
