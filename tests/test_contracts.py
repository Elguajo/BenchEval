import pytest
from pydantic import ValidationError

from bencheval.contracts import Scenario
from bencheval.scenarios import ScenarioError, load_instructions, load_scenario


@pytest.mark.parametrize(
    "update",
    [
        {"kind": "coding-agent"},
        {"executor": {"provider": "claude"}},
        {"executor": {"timeout_seconds": 0}},
        {"unexpected": True},
        {"checks": []},
        {"id": "../../escape"},
        {"response_schema": {"type": "no-such-type"}},
        {"response_schema": {"type": "array"}},
        {"checks": [{"id": "x", "axes": ["behavior"], "type": "no_tools"}]},
        {"checks": [{"id": "x", "axes": ["outcome"], "type": "equals"}]},
        {
            "checks": [
                {"id": "x", "axes": ["outcome"], "type": "contains", "expected": ""}
            ]
        },
        {"checks": [{"id": "x", "axes": ["outcome"], "type": "regex", "pattern": "["}]},
        {"checks": [{"id": "x", "axes": ["outcome", "outcome"], "type": "no_tools"}]},
        {
            "checks": [
                {
                    "id": "x",
                    "axes": ["outcome"],
                    "type": "no_tools",
                    "expected": "unused",
                }
            ]
        },
    ],
)
def test_invalid_configuration_rejected(scenario, update):
    with pytest.raises(ValidationError):
        Scenario.model_validate(scenario.model_dump() | update)


def test_duplicate_and_contradictory_checks_rejected(scenario):
    data = scenario.model_dump()
    data["checks"].append(data["checks"][0].copy())
    with pytest.raises(ValidationError, match="IDs must be unique"):
        Scenario.model_validate(data)
    data["checks"][1].update(id="other", expected="5")
    with pytest.raises(ValidationError, match="contradictory"):
        Scenario.model_validate(data)


@pytest.mark.parametrize(
    "content",
    [
        "id: one\nid: two\n",
        "1: value\n",
        "[broken",
        "null",
        "id: 2026-09-28",
    ],
)
def test_invalid_yaml(content, tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(content)
    with pytest.raises(ScenarioError):
        load_scenario(path)


def test_paths_and_symlinks_cannot_escape(scenario, tmp_path):
    root = tmp_path / "scenarios"
    root.mkdir()
    private = tmp_path / "private.txt"
    private.write_text("private")
    (root / "link").symlink_to(private)
    for name in ["../private.txt", str(private), "link"]:
        scenario.instructions.files = [name]
        with pytest.raises(ScenarioError, match="escapes"):
            load_instructions(scenario, root)


def test_instruction_content_is_snapshotted(scenario, tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text("First version")
    scenario.instructions.files = ["AGENTS.md"]
    first = load_instructions(scenario, tmp_path)
    path.write_text("Second version")
    second = load_instructions(scenario, tmp_path)
    assert first.sha256 != second.sha256
    assert first.sources[0].text == "First version"
    assert first.sources[0].sha256 != second.sources[0].sha256


def test_instruction_size_and_encoding(scenario, tmp_path):
    path = tmp_path / "instruction.txt"
    scenario.instructions.files = [path.name]
    path.write_text("x" * 100001)
    with pytest.raises(ScenarioError, match="100 KB"):
        load_instructions(scenario, tmp_path)
    path.write_bytes(b"\xff")
    with pytest.raises(ScenarioError, match="Cannot read"):
        load_instructions(scenario, tmp_path)
