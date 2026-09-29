"""Isolation boundary: candidate runtime code only ever executes in this subprocess.

The parent passes a JSON request on stdin and receives JSON on stdout. The subprocess runs
with cwd = candidate runtime root, so `import runtime` resolves to the candidate tree while
`factory` comes from the trusted install. The parent never imports candidate code.
"""

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from factory.canon import PROJECT


def call(runtime_root: Path, request: dict) -> dict | list:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FACTORY_")}  # candidate code never sees factory secrets
    env |= {"PYTHONPATH": str(PROJECT), "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "factory.worker"], cwd=runtime_root, env=env, input=json.dumps(request), capture_output=True, text=True, timeout=3600
    )
    if proc.returncode != 0:
        raise RuntimeError(f"worker failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def _compile(req: dict) -> dict:
    from factory import compiler
    from runtime.components import REGISTRY

    pkg = compiler.read_behaviour(Path(req["behaviour_dir"]))
    pkg["manifest"] = compiler.manifest(pkg, Path.cwd(), REGISTRY, req["policy"])
    return {"package": pkg, "diagnostics": _static(pkg, req["policy"])}


STATIC = ("static:schema", "static:traceability", "static:composition", "static:effects")


def _static(pkg: dict, policy: dict) -> dict:
    out = {}
    for ob in STATIC:
        r = _one(ob, pkg, policy, [], None)
        if r["status"] != "passed":
            out[ob] = r["details"].get("errors") or r["details"]
    return out


def _one(ob: str, pkg: dict, policy: dict, others: list[dict], baseline: dict | None) -> dict:
    from factory import compiler, evaluation, lab, mutation
    from runtime.components import REGISTRY
    from runtime.engine import triggers
    from runtime.model import ChatMessage
    from runtime.refdata import UNIVERSES

    static = {
        "static:schema": lambda: compiler.check_schema(pkg),
        "static:traceability": lambda: compiler.check_traceability(pkg),
        "static:composition": lambda: compiler.check_composition(pkg, REGISTRY, UNIVERSES),
        "static:effects": lambda: compiler.check_effects(pkg, REGISTRY, policy),
    }
    started = time.perf_counter()
    try:
        if ob in static:
            errors = static[ob]()
            result = {"status": "failed" if errors else "passed", "errors": errors}
        else:
            release = lab.release_of(pkg, compiler.package_digest(pkg))
            contracts = lab.contracts_of([pkg])
            trig = pkg["profile"]["trigger"]
            room, firm = trig["rooms"][0], next((f for f in trig["sender_firms"] if f != "*"), "ANY-FIRM")
            if ob == "interference":
                result = compiler.check_interference(pkg, others, triggers, ChatMessage)
            elif ob.startswith("scenario:"):
                failures = lab.run_scenario([release], contracts, pkg["scenarios"][ob.split(":", 1)[1]])
                result = {"status": "failed" if failures else "passed", "failures": failures}
            elif ob == "eval":
                base = lab.release_of(baseline, compiler.package_digest(baseline)) if baseline else None
                result = evaluation.evaluate(release, base, contracts, pkg["corpus"], policy["evaluation"]) | {"thresholds": policy["evaluation"]}
            elif ob == "explore":
                result = lab.explore([release], contracts, pkg["pools"], room, firm, policy["exploration"]["max_examples"])
            elif ob == "mutation":
                result = mutation.run(pkg, policy, Path.cwd())
            else:
                result = {"status": "error", "error": f"unknown obligation {ob}"}
    except Exception as e:  # an obligation that cannot run is inconclusive, never a pass
        result = {"status": "error", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)}
    status = result.pop("status")
    return {"obligation": ob, "status": status, "details": result, "seconds": round(time.perf_counter() - started, 3)}


def main() -> None:
    req = json.loads(sys.stdin.read())
    if req["mode"] == "compile":
        out = _compile(req)
    else:
        out = [_one(ob, req["package"], req["policy"], req["others"], req["baseline"]) for ob in req["obligations"]]
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
