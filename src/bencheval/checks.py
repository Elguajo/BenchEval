import re

from jsonschema import Draft202012Validator

from bencheval.contracts import Check, CheckResult, Execution, ExecutionStatus, State
from bencheval.json_utils import strict_json_loads


def evaluate(check: Check, execution: Execution) -> CheckResult:
    state, actual, evidence = State.ERROR, "Execution did not complete", []
    expected = check.expected or check.pattern or check.type
    if check.type == "no_tools":
        tools = [event for event in execution.events if event.tool_action]
        evidence = ["events.json#" + event.id for event in tools]
        expected = "No observed tool actions"
        if tools:
            state, actual = State.FAIL, ", ".join(event.kind for event in tools)
        elif execution.trace_complete:
            state, actual = (
                State.PASS,
                "Complete CLI event stream contains no tool action",
            )
            evidence = ["events.json", "stdout.jsonl"]
        else:
            state, actual = State.NOT_OBSERVABLE, "CLI trace is absent or incomplete"
    elif execution.status == ExecutionStatus.COMPLETED:
        response = execution.response
        evidence = ["response.txt"]
        if check.type == "equals":
            passed = response == check.expected
            actual = "Response equals expected text" if passed else "Response differs"
        elif check.type == "contains":
            passed = check.expected in response
            actual = "Expected text found" if passed else "Expected text absent"
        elif check.type == "regex":
            passed = re.search(check.pattern, response) is not None
            actual = "Pattern matched" if passed else "Pattern not matched"
        else:
            expected = "Response is JSON satisfying the declared JSON Schema"
            try:
                value = strict_json_loads(response)
                error = next(
                    Draft202012Validator(check.json_schema).iter_errors(value), None
                )
                passed = error is None
                actual = error.message if error else "JSON Schema satisfied"
            except (ValueError, RecursionError):
                passed, actual = False, "Response is not valid JSON"
        state = State.PASS if passed else State.FAIL
    return CheckResult(
        id=check.id,
        axes=check.axes,
        severity=check.severity,
        state=state,
        expected=expected,
        actual=actual,
        evidence=evidence,
    )
