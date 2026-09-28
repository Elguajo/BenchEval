import json
import sys

import pytest

from bencheval.contracts import Scenario


@pytest.fixture
def scenario():
    return Scenario.model_validate(
        {
            "id": "example",
            "prompt": "Return 4.",
            "checks": [
                {"id": "answer", "axes": ["outcome"], "type": "equals", "expected": "4"}
            ],
        }
    )


@pytest.fixture
def scenario_file(tmp_path, scenario):
    path = tmp_path / "scenario.json"
    path.write_text(scenario.model_dump_json(), encoding="utf-8")
    return path


@pytest.fixture
def fake_codex(tmp_path):
    def create(*, login=True, exit_code=0, response="4", trace=None, delay=0):
        settings = {
            "login": login,
            "exit_code": exit_code,
            "response": response,
            "trace": trace
            if trace is not None
            else [
                {"type": "thread.started", "thread_id": "fake"},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {"id": "a", "type": "agent_message", "text": response},
                },
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                },
            ],
            "delay": delay,
        }
        path = tmp_path / "codex-fake"
        # A real subprocess exercises argv, environment, pipes and timeouts offline.
        script = """
import json, os, sys, time
settings = json.loads(SETTINGS)
args = sys.argv[1:]
if args == ['--version']:
    print('codex-cli fake')
elif args == ['exec', '--help']:
    print('--ignore-user-config --ignore-rules --ephemeral --json '
          '--output-schema --output-last-message')
elif args == ['login', 'status']:
    print('Logged in using ChatGPT' if settings['login'] else 'Not logged in')
    sys.exit(0 if settings['login'] else 1)
else:
    assert 'OPENAI_API_KEY' not in os.environ
    assert 'ANTHROPIC_API_KEY' not in os.environ
    assert 'CODEX_API_KEY' not in os.environ
    assert sys.stdin.read().endswith('Return 4.')
    for event in settings['trace']:
        print(json.dumps(event), flush=True)
    print('local diagnostic', file=sys.stderr, flush=True)
    time.sleep(settings['delay'])
    if settings['response'] is not None:
        from pathlib import Path
        Path(args[args.index('--output-last-message') + 1]).write_text(
            settings['response'], encoding='utf-8')
    sys.exit(settings['exit_code'])
""".replace("SETTINGS", repr(json.dumps(settings)))
        path.write_text(f"#!{sys.executable}\n" + script, encoding="utf-8")
        path.chmod(0o700)
        return str(path)

    return create
