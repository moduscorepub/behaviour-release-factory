# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""The release gate, and the records of approvals.

The gate answers PASS only when all of the following conditions hold:

- The requirements are approved and current, and the runner signed the evidence for the exact package and engine code.
- Every check that the policy requires ran and passed, and every requirement has passing evidence.
- The policy and the checks match the versions that approvers recorded.
- The policy allows the kind of change, or a named person approved the exact package, and the approval hasn't expired.

Any other result is FAIL or INCONCLUSIVE, and neither answer allows a release. FAIL means that there is evidence of a
defect or of tampering, and INCONCLUSIVE means that something required wasn't shown. The requirements, the thresholds and
the list of checks come from the approved requirements and the protected policy, and never from the evidence that the
gate judges.
"""

import secrets
from datetime import UTC, datetime, timedelta

import yaml

from factory.canon import Workspace, digest, evaluator_digest, load_json, load_yaml, runner_key, sha, verify, write_json
from factory.compiler import package_digest, required_obligations


# Approvals. Approvers own the trust/ folder, and builders can't change it.
def init_trust(ws: Workspace) -> dict:
    ws.trust.mkdir(parents=True, exist_ok=True)
    key = ws.trust / "runner.key"
    if not key.exists():
        key.write_bytes(secrets.token_bytes(32))
        key.chmod(0o600)
    boundary = ws.root / "policy" / "builder-boundary.yaml"
    pins = {"policy_digest": sha(ws.policy_file.read_bytes()), "evaluator_digest": evaluator_digest(),
            "boundary_digest": sha(boundary.read_bytes()) if boundary.exists() else None, "pinned_at": _now().isoformat(timespec="seconds")}
    write_json(ws.trust / "pins.json", pins)
    if not (ws.trust / "approvals.json").exists():
        write_json(ws.trust / "approvals.json", {"specs": [], "promotions": []})
    return pins


def approve_spec(ws: Workspace, behaviour: str, approver: str) -> dict:
    """Record that a person approved the requirements.

    The approval covers the exact revision of spec.yaml and the Confluence content that the revision came from.
    """
    spec = load_yaml(ws.behaviours / behaviour / "spec.yaml")
    intent = (ws.behaviours / behaviour / "intent.md").read_text()
    if sha(intent.encode()) != spec["source"]["content_digest"]:
        raise ValueError("intent.md doesn't match spec.source.content_digest, so the approval can't be tied to the approved content")
    record = {"spec_id": spec["spec_id"], "revision": spec["revision"], "spec_digest": digest(spec),
              "content_digest": spec["source"]["content_digest"], "approved_by": approver, "at": _now().isoformat(timespec="seconds")}
    approvals = load_json(ws.trust / "approvals.json")
    approvals["specs"].append(record)
    write_json(ws.trust / "approvals.json", approvals)
    return record


def approve_promotion(ws: Workspace, candidate_digest: str, approver: str, reason: str, hours: int) -> dict:
    """Record that a person approved the release of one package, which is named by its hash.

    The approval expires after the given number of hours.
    """
    record = {"candidate_digest": candidate_digest, "approved_by": approver, "reason": reason,
              "expires_at": (_now() + timedelta(hours=hours)).isoformat(timespec="seconds"), "at": _now().isoformat(timespec="seconds")}
    approvals = load_json(ws.trust / "approvals.json")
    approvals["promotions"].append(record)
    write_json(ws.trust / "approvals.json", approvals)
    return record


def _now() -> datetime:
    return datetime.now(UTC)


# Classifying a change.
def classify(pkg: dict, live: dict | None) -> tuple[str, list[str]]:
    """Classify a change by what it changes and by who must approve it. The size of the diff doesn't matter."""
    if live is None:
        return "behaviour", ["new_behaviour"]
    change_class = "runtime" if pkg["manifest"]["runtime"]["files"] != live["manifest"]["runtime"]["files"] else "behaviour"
    flags = []
    if {o["destination"] for o in pkg["profile"]["outputs"]} - {o["destination"] for o in live["profile"]["outputs"]}:
        flags.append("new_destination")
    t, u = pkg["profile"]["trigger"], live["profile"]["trigger"]
    widened = (
        set(t["rooms"]) - set(u["rooms"])
        or ("*" in t["sender_firms"] and "*" not in u["sender_firms"])
        or ("*" not in u["sender_firms"] and set(t["sender_firms"]) - set(u["sender_firms"]))
        or (u["keywords_any"] and (not t["keywords_any"] or set(t["keywords_any"]) - set(u["keywords_any"])))
        or (u.get("pattern") and t.get("pattern") != u.get("pattern"))  # Any change to a pattern counts, because nobody can prove that a new pattern is narrower.
    )
    if widened:
        flags.append("trigger_scope_widened")
    return change_class, flags


def _summary(record: dict) -> str:
    d = record["details"]
    for key in ("errors", "failures", "collisions", "uncertain", "error"):
        if d.get(key):
            items = d[key] if isinstance(d[key], list) else [d[key]]
            return "; ".join(str(i) for i in items[:3]) + (f" (and {len(items) - 3} more)" if len(items) > 3 else "")
    if "counterexample" in d:
        cex = d["counterexample"]
        return f"the sequence of events {cex['events']} breaks {cex['violations']}"
    if "mutants" in d:
        bad = [f"{m['mutant']} ({m['result']})" for m in d["mutants"] if m["result"] != "killed"]
        return "the tests don't catch the following faults: " + ", ".join(bad)
    return record["status"]


def evaluate(ws: Workspace, behaviour: str, store) -> dict:
    fail: list[str] = []
    inconclusive: list[str] = []
    pkg_path, ev_path = ws.package_path(behaviour), ws.evidence_path(behaviour)
    if not pkg_path.exists():
        return {"outcome": "INCONCLUSIVE", "behaviour": behaviour, "candidate_digest": "", "reasons": ["the desk has no compiled package"]}
    pkg = load_json(pkg_path)
    candidate = package_digest(pkg)
    pins = load_json(ws.trust / "pins.json")
    key = runner_key(ws.trust)
    approvals = load_json(ws.trust / "approvals.json")
    policy_bytes = ws.policy_file.read_bytes()
    policy = yaml.safe_load(policy_bytes)

    # The policy and the checks must match the versions that approvers recorded.
    if sha(policy_bytes) != pins["policy_digest"]:
        fail.append("control: policy.yaml differs from the version that approvers recorded with trust-init")
    if evaluator_digest() != pins["evaluator_digest"]:
        fail.append("control: the code of the checks in factory/ differs from the version that approvers recorded with trust-init")

    # The requirements must be approved.
    spec = pkg["spec"]
    spec_digest = digest(spec)
    if not any(a["spec_id"] == spec["spec_id"] and a["spec_digest"] == spec_digest for a in approvals["specs"]):
        fail.append(f"contract: revision {spec['revision']} of {spec['spec_id']} ({spec_digest[:23]}) isn't an approved revision")
    if sha(pkg["intent"].encode()) != spec["source"]["content_digest"]:
        fail.append("contract: intent.md doesn't match the hash of the approved Confluence page")

    records: dict[str, dict] = {}
    requirements: dict[str, str] = {}
    if not ev_path.exists():
        inconclusive.append("evidence: the runner hasn't produced evidence for the package")
    else:
        ev = load_json(ev_path)
        signature = ev.pop("signature", None)
        if not verify(key, ev, signature):
            fail.append("evidence: the signature is invalid, so either the trusted runner didn't produce the evidence or someone changed it after signing")
        if ev.get("evaluator_digest") != pins["evaluator_digest"]:
            fail.append("evidence: the evidence comes from checks that differ from the version that approvers recorded")
        if ev.get("policy_digest") != pins["policy_digest"]:
            fail.append("evidence: the evidence comes from a policy that differs from the version that approvers recorded")
        if ev.get("candidate_digest") != candidate:
            fail.append("evidence: the evidence is for a different package, so either the evidence is out of date or someone changed the package after the checks ran")
        if ev.get("runtime") != pkg["manifest"]["runtime"]["files"]:
            fail.append("evidence: the checks ran against different engine code from the code that the package records")
        records = {r["obligation"]: r for r in ev.get("records", [])}

        for ob in required_obligations(pkg, policy):
            r = records.get(ob)
            if r is None:
                inconclusive.append(f"{ob}: the required check never ran")
            elif r["status"] == "failed":
                fail.append(f"{ob}: {_summary(r)}")
            elif r["status"] != "passed":
                inconclusive.append(f"{ob}: the check ended with the status {r['status']} ({_summary(r)})")

    for req in spec["requirements"]:
        state = "established"
        for v in req["verified_by"]:
            kind, _, ref = v.partition(":")
            r = records.get(v if kind == "scenario" else kind)
            if r is None or r["status"] != "passed":
                state = f"not established ({v} is {r['status'] if r else 'missing'})"
                break
            if kind == "eval" and ref not in r["details"].get("slices", {}):
                state = f"not established ({v} wasn't scored)"
                inconclusive.append(f"{req['id']}: the category in {v} wasn't scored")
                break
        requirements[req["id"]] = state

    # Decide whether the policy lets the kind of change go live without approval from a named person.
    change_class, flags = classify(pkg, store.live_package(behaviour))
    rule = policy["promotion"][change_class]
    blocking = [f for f in flags if f in rule.get("blocking_flags", [])]
    grant = None
    if not rule["auto"] or blocking:
        grant = next((g for g in approvals["promotions"] if g["candidate_digest"] == candidate and datetime.fromisoformat(g["expires_at"]) > _now()), None)
        if grant is None:
            why = f"{change_class} change" + (f" with {', '.join(blocking)}" if blocking else "")
            inconclusive.append(f"approval: a {why} needs a named person to approve the exact package")

    outcome = "FAIL" if fail else "INCONCLUSIVE" if inconclusive else "PASS"
    decision = {
        "outcome": outcome, "behaviour": behaviour, "candidate_digest": candidate, "change_class": change_class, "risk_flags": flags,
        "authorised_by": grant["approved_by"] if grant else ("policy" if outcome == "PASS" else None),
        "requirements": requirements, "reasons": fail + inconclusive, "evaluated_at": _now().isoformat(timespec="seconds"),
    }
    store.log_gate(behaviour, decision)
    return decision
