"""A CI gate: does a fix you already proved still work in the code you are about to ship?

You found that changing one agent fixed a failing run (an experiment: say 8 of 8 right with the change). Before
a deploy, run that experiment again against the new code, and stop the deploy if the fix no longer holds.

    agenttrace gate <experiment> --min-pass 0.75

It starts the experiment again (the same run, fork point, change and N), waits for it, and exits:

    0  the fix held: the runs with the change came out right at least --min-pass of the time
    1  it regressed: they came out right less often
    2  it could not tell: it did not finish in time, hit the token ceiling, or errored. Treat it as a failure.

How much to trust it: live steps are sampled, never deterministic, and N is small, so a single flaky run moves
the rate. The result is directional. With N of 8 and --min-pass 0.75, up to two runs may fail. Use a larger N or
a lower bar if your workflow is noisy. The gate only judges the runs WITH the change; it does not ask whether the
runs without it still fail.

The experiment runs where it always runs: on our server for a registered workflow, or through your worker for
your own. In CI, start the worker before the gate, so there is something to take the jobs.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agenttrace_sdk._http import ApiClient

PASSED, REGRESSED, UNKNOWN = 0, 1, 2
_WAITING = ("queued", "running")


@dataclass(frozen=True)
class GateResult:
    code: int
    message: str
    experiment: dict[str, Any]


def judge(exp: dict[str, Any], min_pass: float) -> GateResult:
    """The verdict on a finished experiment."""
    c, t = exp["control"], exp["treatment"]
    sides = f"with the change {t['pass']} of {t['total']} right, without it {c['pass']} of {c['total']}"
    p = (exp.get("stats") or {}).get("fisher_p")
    note = f" (p = {p:.4f}, directional)" if p is not None else " (directional)"
    if exp["status"] == "error":
        return GateResult(UNKNOWN, f"The experiment errored: {exp.get('error') or 'unknown'}. {sides}.", exp)
    if exp["status"] == "capped":
        return GateResult(UNKNOWN, f"The experiment stopped at the token ceiling before it finished. {sides}.", exp)
    if t["total"] == 0:
        return GateResult(UNKNOWN, "The experiment finished with no runs with the change, so there is nothing to judge.", exp)
    rate = t["pass"] / t["total"]
    if rate >= min_pass:
        return GateResult(PASSED, f"The fix held: {sides}{note}. Needed at least {min_pass:.0%} right with the change.", exp)
    return GateResult(REGRESSED, f"The fix regressed: {sides}{note}. Needed at least {min_pass:.0%} right with the change.", exp)


def run_gate(
    client: ApiClient, experiment_id: str, *, min_pass: float = 0.75, rerun: bool = True, timeout: float = 900.0,
    poll: float = 5.0, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
) -> GateResult:
    """Start the experiment again (unless `rerun` is False, which judges the experiment as it already stands),
    wait for it to finish, and return the verdict. `sleep` and `clock` are there so tests need not wait."""
    if not 0 < min_pass <= 1:
        raise ValueError("min_pass must be more than 0 and at most 1")
    target = client.request("POST", f"/v1/agent/experiments/{experiment_id}/rerun")["id"] if rerun else experiment_id
    deadline = clock() + timeout
    while True:
        exp = client.request("GET", f"/v1/agent/experiments/{target}")
        if exp["status"] not in _WAITING:
            return judge(exp, min_pass)
        if clock() >= deadline:
            waiting = ""
            if exp.get("mode") == "worker" and exp["status"] == "queued":
                waiting = " No worker has asked for a job lately. Is your worker running?" if not exp.get("workers_online") else " A worker is connected but has not taken a job."
            return GateResult(UNKNOWN, f"Experiment {target} had not finished after {int(timeout)} seconds.{waiting}", exp)
        sleep(poll)
