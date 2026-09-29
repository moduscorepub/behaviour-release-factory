# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Test the gate itself with prepared cases, which the `qualify-gate` command runs.

You should only let the gate release changes automatically after it rejects every bad case and
passes every good case. Each case runs in its own copy of a prepared workspace, where the US
Treasury desk is live and a correct gilt desk has signed evidence. The case then makes one
change, e.g., it edits the evidence, adds a defect or makes a change that needs approval.
Finally, the case checks the answer of the gate and the reason that the gate gives.

The cases that expect PASS catch a gate that simply rejects everything.
"""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from factory import gate, runner
from factory.activation import Store, activate
from factory.canon import Workspace, load_json, runner_key, sign, write_json
from factory.isolation import sandbox_check
from factory.mutation import MUTANTS

UST, GILT = "ust-rfq-nyc", "gilt-rfq-ldn"
FAST = ("mutation",)  # Defect cases skip mutation testing, so the FAIL must come from the check that the case targets.


@dataclass(frozen=True)
class Case:
    id: str
    attack: str
    expect: str  # The expected answer, which is PASS, FAIL or INCONCLUSIVE.
    reason: str  # Text that must appear in one of the reasons that the gate gives.
    run: Callable[[Workspace], dict]


def _gate(ws: Workspace, behaviour: str = GILT) -> dict:
    return gate.evaluate(ws, behaviour, Store(ws))


def _build(ws: Workspace, behaviour: str = GILT, skip: tuple[str, ...] = ()) -> None:
    runner.compile_behaviour(ws, behaviour)
    runner.produce_evidence(ws, behaviour, skip=skip)


def _profile(ws: Workspace, change: Callable[[dict], None]) -> None:
    path = ws.behaviours / GILT / "profile.json"
    data = load_json(path)
    change(data)
    write_json(path, data)


def _patch_runtime(ws: Workspace, mutant_id: str) -> None:
    m = next(m for m in MUTANTS if m.id == mutant_id)
    path = ws.root / m.path
    path.write_text(path.read_text().replace(m.find, m.replace))


def _evidence_edit(ws: Workspace, change: Callable[[dict], None], resign: bool) -> None:
    path = ws.evidence_path(GILT)
    ev = load_json(path)
    ev.pop("signature")
    change(ev)
    ev["signature"] = sign(runner_key(ws.trust), ev) if resign else "0" * 64
    write_json(path, ev)


def _defect(profile_change=None, mutant=None) -> Callable[[Workspace], dict]:
    def run(ws: Workspace) -> dict:
        if profile_change:
            _profile(ws, profile_change)
        if mutant:
            _patch_runtime(ws, mutant)
        _build(ws, skip=FAST)
        return _gate(ws)
    return run


def _stale(ws):
    _profile(ws, lambda p: p["parser"].update(max_size=200_000_000))
    runner.compile_behaviour(ws, GILT)  # The package is new, but the evidence is still from the previous package.
    return _gate(ws)


def _artifact_changed(ws):
    pkg = load_json(ws.package_path(GILT))
    pkg["profile"]["outputs"][0]["destination"] = "bus:rfq/nyc/ust"
    write_json(ws.package_path(GILT), pkg)
    return _gate(ws)


def _forged(ws):
    _profile(ws, lambda p: p["outputs"][0].update(destination="bus:rfq/nyc/ust"))
    _build(ws, skip=FAST)
    _evidence_edit(ws, lambda ev: [r.update(status="passed") for r in ev["records"]], resign=False)
    return _gate(ws)


def _requirement_removed(ws):
    path = ws.behaviours / GILT / "spec.yaml"
    spec = yaml.safe_load(path.read_text())
    spec["requirements"] = [r for r in spec["requirements"] if r["id"] != "GILT-RFQ-002"]
    for w in spec["work_items"]:
        w["satisfies"] = [r for r in w["satisfies"] if r != "GILT-RFQ-002"]
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    _build(ws, skip=FAST)
    return _gate(ws)


def _threshold_lowered(ws):
    ws.policy_file.write_text(ws.policy_file.read_text().replace("min_wilson_lower: 0.55", "min_wilson_lower: 0.10"))
    return _gate(ws)


def _evaluator_altered(ws):
    _evidence_edit(ws, lambda ev: ev.update(evaluator_digest="sha256:" + "ab" * 32), resign=True)
    return _gate(ws)


def _go_live_then(change: Callable[[Workspace], None], approve: bool = False) -> Callable[[Workspace], dict]:
    def run(ws: Workspace) -> dict:
        activate(ws, GILT, "live", "qualification")
        change(ws)
        _build(ws)
        if approve:
            gate.approve_promotion(ws, _gate(ws)["candidate_digest"], "engineering-approver", "qualification", 1)
        return _gate(ws)
    return run


def _widen_scope(ws):
    _profile(ws, lambda p: p["trigger"]["rooms"].append("GILT-CLIENT-3"))


def _benign_runtime_change(ws):
    path = ws.root / "runtime" / "components" / "gilt.py"
    path.write_text(path.read_text() + "\n# A change to formatting alone still counts as a change to the engine.\n")


def _sandbox(widen: str | None) -> Callable[[Workspace], dict]:
    def run(ws: Workspace) -> dict:
        candidate = ws.root / "sandbox" / "builder-policy.yaml"
        if widen == "network":
            candidate.write_text(candidate.read_text() + "  jira:\n    endpoints:\n      - host: acme.atlassian.net\n        port: 443\n"
                                 "        protocol: rest\n        enforcement: enforce\n        access: read-write\n    binaries:\n      - path: /usr/local/bin/claude\n")
        elif widen == "boundary":
            b = ws.root / "policy" / "builder-boundary.yaml"
            b.write_text(b.read_text().replace("  read_write:\n", "  read_write:\n    - /sandbox/workspace/trust\n", 1))
        res = sandbox_check(ws, candidate)
        return {"outcome": "PASS" if res["ok"] else "FAIL", "reasons": [f"{res['result']}: {res.get('counterexample') or res.get('reason')}"]}
    return run


CASES = (
    Case("good-candidate", "A builder adds a correct new desk, with no attack.", "PASS", "", lambda ws: _gate(ws)),
    Case("stale-evidence", "The profile changes, but the evidence is from the previous package.", "FAIL", "is for a different package", _stale),
    Case("artifact-changed-after-verification", "Someone edits the package after the evidence is signed.", "FAIL", "is for a different package", _artifact_changed),
    Case("forged-results", "Someone changes failed results to passed without the signing key.", "FAIL", "the signature is invalid", _forged),
    Case("skipped-critical-scenario", "The runner skips the scenario with a late reply after a cancellation.", "INCONCLUSIVE",
         "scenario:cancel-then-late-ack: the required check never ran",
         lambda ws: (runner.produce_evidence(ws, GILT, skip=("scenario:cancel-then-late-ack",)), _gate(ws))[1]),
    Case("model-eval-never-executed", "The runner skips the accuracy check.", "INCONCLUSIVE", "eval: the required check never ran",
         lambda ws: (runner.produce_evidence(ws, GILT, skip=("eval",)), _gate(ws))[1]),
    Case("requirement-removed", "A builder deletes the cancellation requirement from spec.yaml.", "FAIL", "isn't an approved revision", _requirement_removed),
    Case("threshold-lowered", "Someone lowers an accuracy minimum in the policy file.", "FAIL", "policy.yaml differs from the version that approvers recorded",
         _threshold_lowered),
    Case("evaluator-altered", "The evidence comes from changed checks, and a runner with the key signs it.", "FAIL", "comes from checks that differ",
         _evaluator_altered),
    Case("wrong-routing", "The gilt desk sends its RFQs to the Treasury traders.", "FAIL", "static:effects",
         _defect(lambda p: p["outputs"][0].update(destination="bus:rfq/nyc/ust"))),
    Case("over-broad-trigger", "The gilt desk also listens in a Treasury client room.", "FAIL", "interference",
         _defect(lambda p: p["trigger"]["rooms"].append("UST-CLIENT-1"))),
    Case("quoted-history-unhandled", "The gilt profile stops removing quoted chat history.", "FAIL", "static:composition",
         _defect(lambda p: p["enrichment"].remove("strip_quoted_history"))),
    Case("runtime-late-ack-reactivates", "The engine lets a late reply from a trader reactivate a cancelled RFQ.", "FAIL", "scenario:cancel-then-late-ack",
         _defect(mutant="late-ack-reactivates")),
    Case("runtime-duplicate-publication", "After a crash, the engine resends messages that it may already have sent.", "FAIL", "I1 duplicate message",
         _defect(mutant="recovery-republishes")),
    Case("runtime-message-loss", "The engine confirms a message to the chat platform before it saves the message.", "FAIL", "I6",
         _defect(mutant="transport-ack-before-commit")),
    Case("extraction-regression", "The engine reads the gilt slang for 2032 as the 2038 bond.", "FAIL", "eval", _defect(mutant="gilt-32s-mismapped")),
    Case("scope-widening-needs-authority", "A live desk starts to listen in more chat rooms.", "INCONCLUSIVE", "trigger_scope_widened", _go_live_then(_widen_scope)),
    Case("scope-widening-approved", "A live desk starts to listen in more chat rooms, with an approval for the exact package.", "PASS", "",
         _go_live_then(_widen_scope, approve=True)),
    Case("runtime-change-needs-authority", "Someone changes shared engine code while a desk is live.", "INCONCLUSIVE", "runtime change",
         _go_live_then(_benign_runtime_change)),
    Case("builder-sandbox-contained", "The agent uses the approved sandbox settings, with no attack.", "PASS", "", _sandbox(None)),
    Case("builder-sandbox-widened", "The sandbox settings of the agent add a route to Jira.", "FAIL", "exceeds_boundary", _sandbox("network")),
    Case("boundary-edited", "Someone widens the approved sandbox limits in the repository without running trust-init again.", "FAIL", "boundary_not_pinned",
         _sandbox("boundary")),
)


def prepare(source: Path) -> Path:
    base = Path(tempfile.mkdtemp(prefix="factory-qual-base-"))
    for d in ("behaviours", "policy", "runtime", "sandbox"):
        shutil.copytree(source / d, base / d, ignore=shutil.ignore_patterns("__pycache__"))
    ws = Workspace(base)
    gate.init_trust(ws)
    for b in (UST, GILT):
        gate.approve_spec(ws, b, "qualification")
    _build(ws, UST)
    activate(ws, UST, "live", "qualification")
    _build(ws, GILT)
    return base


def qualify(source: Path, only: list[str] | None = None) -> dict:
    base = prepare(source)
    rows = []
    try:
        for case in CASES:
            if only and case.id not in only:
                continue
            ws = Workspace(Path(tempfile.mkdtemp(prefix=f"factory-qual-{case.id}-")))
            shutil.copytree(base, ws.root, dirs_exist_ok=True)
            try:
                decision = case.run(ws)
                reasons = decision.get("reasons", [])
                matched = decision["outcome"] == case.expect and (not case.reason or any(case.reason in r for r in reasons))
                rows.append({"case": case.id, "attack": case.attack, "expected": case.expect, "actual": decision["outcome"],
                             "ok": matched, "evidence": reasons[:2]})
            except Exception as e:  # A case that can't run counts as a failed case, never as a passed one.
                rows.append({"case": case.id, "attack": case.attack, "expected": case.expect, "actual": f"ERROR {type(e).__name__}: {e}", "ok": False, "evidence": []})
            finally:
                shutil.rmtree(ws.root, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return {"qualified": all(r["ok"] for r in rows), "passed": sum(r["ok"] for r in rows), "cases": len(rows), "results": rows}
