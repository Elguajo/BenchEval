from bencheval.contracts import (
    Axis,
    CheckResult,
    ExecutionStatus,
    State,
    Verdict,
    Verdicts,
)


def aggregate(checks: list[CheckResult], status: ExecutionStatus) -> Verdicts:
    """Established hard failures dominate errors; missing evidence cannot pass."""
    axes = {}
    for axis in Axis:
        hard = [c for c in checks if axis in c.axes and c.severity == "hard"]
        if any(c.state == State.FAIL for c in hard):
            axes[axis] = Verdict.FAIL
        elif any(c.state == State.ERROR for c in hard):
            axes[axis] = Verdict.INCONCLUSIVE
        elif any(c.state == State.NOT_OBSERVABLE for c in hard):
            axes[axis] = Verdict.NOT_OBSERVABLE
        elif any(c.state == State.PASS for c in hard):
            axes[axis] = Verdict.PASS
        elif hard:
            axes[axis] = Verdict.NOT_APPLICABLE
        else:
            axes[axis] = Verdict.NOT_OBSERVABLE
        if hard and status != ExecutionStatus.COMPLETED and axes[axis] == Verdict.PASS:
            axes[axis] = Verdict.INCONCLUSIVE

    hard = [c for c in checks if c.severity == "hard"]
    if any(c.state == State.FAIL for c in hard):
        overall = Verdict.FAIL
    elif status != ExecutionStatus.COMPLETED or any(
        c.state in (State.ERROR, State.NOT_OBSERVABLE) for c in hard
    ):
        overall = Verdict.INCONCLUSIVE
    elif not any(Axis.OUTCOME in c.axes and c.state == State.PASS for c in hard):
        overall = Verdict.INCONCLUSIVE
    else:
        overall = Verdict.PASS
    return Verdicts(axes=axes, overall=overall)
