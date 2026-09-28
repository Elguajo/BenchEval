import json
import sys

import pytest

from bencheval.contracts import Execution, ExecutionStatus, Scenario
from bencheval.judges.jobs import prepare_job
from bencheval.runner import run_scenario


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
    def create(
        *,
        login=True,
        exit_code=0,
        response="4",
        trace=None,
        delay=0,
        skills=None,
        skill_errors=None,
        ignore_disabling=False,
        rpc_delay=0,
        expected_prompt="Return 4.",
    ):
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
            "skills": skills or [],
            "skill_errors": skill_errors or [],
            "ignore_disabling": ignore_disabling,
            "rpc_delay": rpc_delay,
            "expected_prompt": expected_prompt,
        }
        path = tmp_path / "codex-fake"
        # A real subprocess exercises argv, environment, pipes and timeouts offline.
        script = """
import json, os, sys, time, tomllib
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
elif args[0] == 'app-server':
    for line in sys.stdin:
        request = json.loads(line)
        if request.get('method') == 'initialize':
            print(json.dumps({'id':1,'result':{}}), flush=True)
        elif request.get('method') == 'skills/list':
            time.sleep(settings['rpc_delay'])
            overrides = [arg for arg in args if arg.startswith('skills.config=')]
            disabled = ({item['path'] for item in
                tomllib.loads(overrides[0])['skills']['config']}
                if overrides else set())
            skills = [{**skill, 'enabled': (skill['enabled'] and
                (settings['ignore_disabling'] or skill['path'] not in disabled))
                if type(skill['enabled']) is bool else skill['enabled']}
                for skill in settings['skills']]
            print(json.dumps({'id':2,'result':{'data':[{
                'cwd':os.getcwd(),'skills':skills,
                'errors':settings['skill_errors']}]}}), flush=True)
else:
    assert 'OPENAI_API_KEY' not in os.environ
    assert 'ANTHROPIC_API_KEY' not in os.environ
    assert 'CODEX_API_KEY' not in os.environ
    prompt = sys.stdin.read()
    if settings['expected_prompt'] is not None:
        assert prompt.endswith(settings['expected_prompt'])
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


@pytest.fixture
def make_job(tmp_path, scenario_file):
    def create(
        *, provider="codex", severity="hard", trace=True, response="4", behavior=False
    ):
        class Actor:
            def run(self, *args):
                return Execution(
                    status=ExecutionStatus.COMPLETED,
                    response=response,
                    trace_complete=trace,
                )

        _, source = run_scenario(scenario_file, tmp_path / "runs", executor=Actor())
        config = tmp_path / "judge.yaml"
        criterion = {
            "id": "quality",
            "axes": ["behavior" if behavior else "outcome"],
            "requirement": "Answer follows the request.",
            "severity": severity,
            "requires": ["trace"] if behavior else ["response"],
        }
        config.write_text(json.dumps({"provider": provider, "criteria": [criterion]}))
        job, directory = prepare_job(source, config, tmp_path / "judges")
        return job, directory, source

    return create
