# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Run the checks in a separate worker process, and sign the record of the checks that ran.

In production, `evidence` runs in protected CI, which holds the signing key, and the agent that writes the change never
has the key. The agent runs the same checks without a signature through `check` for quick feedback. The agent can also
run `explore --save` to turn a failing sequence of events into a permanent regression scenario.
"""

import platform
import shutil
import tempfile
from pathlib import Path

import yaml

from factory import worker
from factory.activation import Store, now
from factory.canon import Workspace, digest, evaluator_digest, load_json, runner_key, sha, sign, write_json
from factory.compiler import package_digest, required_obligations


def compile_behaviour(ws: Workspace, behaviour: str, runtime_root: Path | None = None) -> dict:
    out = worker.call(runtime_root or ws.root, {"mode": "compile", "behaviour_dir": str(ws.behaviours / behaviour), "policy": yaml.safe_load(ws.policy_file.read_bytes())})
    write_json(ws.package_path(behaviour), out["package"])
    return {"behaviour": behaviour, "candidate_digest": package_digest(out["package"]), "diagnostics": out["diagnostics"]}


def _execute(ws: Workspace, behaviour: str, runtime_root: Path | None, skip: tuple[str, ...]) -> dict:
    pkg = load_json(ws.package_path(behaviour))
    policy_bytes = ws.policy_file.read_bytes()
    policy = yaml.safe_load(policy_bytes)
    store = Store(ws)
    obligations = [o for o in required_obligations(pkg, policy) if o not in skip]
    started = now()
    with tempfile.TemporaryDirectory() as tmp:  # The checks run on a copy of the engine code, so the code can't change while the checks run.
        shutil.copytree((runtime_root or ws.root) / "runtime", Path(tmp) / "runtime", ignore=shutil.ignore_patterns("__pycache__"))
        runtime = {f: sha((Path(tmp) / f).read_bytes()) for f in pkg["manifest"]["runtime"]["files"] if (Path(tmp) / f).exists()}
        records = worker.call(Path(tmp), {
            "mode": "obligations", "package": pkg, "policy": policy, "obligations": obligations,
            "others": [p for p in store.active_packages() if p["behaviour_id"] != behaviour],
            "baseline": store.live_package(behaviour),
        })
    return {
        "format": "release-evidence/1", "behaviour_id": behaviour, "candidate_digest": package_digest(pkg), "runtime": runtime,
        "evaluator_digest": evaluator_digest(), "policy_digest": sha(policy_bytes), "obligations": obligations, "records": records,
        "started_at": started, "finished_at": now(), "runner_host": platform.node(),
    }


def produce_evidence(ws: Workspace, behaviour: str, runtime_root: Path | None = None, skip: tuple[str, ...] = ()) -> dict:
    bundle = _execute(ws, behaviour, runtime_root, skip)
    bundle["signature"] = sign(runner_key(ws.trust), bundle)
    write_json(ws.evidence_path(behaviour), bundle)
    return bundle


def check(ws: Workspace, behaviour: str, runtime_root: Path | None = None, skip: tuple[str, ...] = ("mutation",)) -> dict:
    """Run the same checks as `evidence` for builder feedback. The results aren't signed, so the gate never accepts them."""
    compiled = compile_behaviour(ws, behaviour, runtime_root)
    bundle = _execute(ws, behaviour, runtime_root, skip) | {"diagnostics": compiled["diagnostics"]}
    write_json(ws.package_path(behaviour).with_name("check.json"), bundle)
    return bundle


def explore(ws: Workspace, behaviour: str, runtime_root: Path | None = None, save: bool = False) -> dict:
    compile_behaviour(ws, behaviour, runtime_root)
    pkg = load_json(ws.package_path(behaviour))
    [record] = worker.call(runtime_root or ws.root, {"mode": "obligations", "package": pkg, "policy": yaml.safe_load(ws.policy_file.read_bytes()),
                                                     "obligations": ["explore"], "others": [], "baseline": None})
    out = {"status": record["status"], **record["details"]}
    if save and record["status"] == "failed":
        cex = record["details"]["counterexample"]
        sid = "regression-" + digest(cex["events"])[7:19]
        path = ws.behaviours / behaviour / "scenarios" / f"{sid}.json"
        write_json(path, {"id": sid, "requirements": [], "origin": {"found_by": "explore", "violations": cex["violations"]},
                          "room": cex["room"], "firm": cex["firm"], "events": cex["events"], "expect": {}})
        out["saved"] = str(path.relative_to(ws.root))
    return out
