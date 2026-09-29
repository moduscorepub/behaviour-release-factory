# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Promotion gate and authority records. Fail-closed: PASS only when

  the approved contract is current, evidence is runner-signed and applies to this exact
  candidate and runtime, every policy-derived obligation actually passed, every requirement
  maps to passing evidence, assurance controls match their pinned versions, and policy (or
  an explicit, candidate-bound, unexpired approval) authorises this class of change.

Everything else is FAIL (evidence of a defect or tampering) or INCONCLUSIVE (something required
was not established). Neither permits promotion. Requirements, thresholds and obligations come
from the approved spec and protected policy, never from the report being judged.
"""

import secrets
from datetime import UTC, datetime, timedelta

import yaml

from factory.canon import Workspace, digest, evaluator_digest, load_json, load_yaml, runner_key, sha, verify, write_json
from factory.compiler import package_digest, required_obligations


# ---- authority (trust/ is owned by the approving function, not the builder) ------------------
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
    """Human approval of meaning: binds the exact spec revision and the Confluence content it came from."""
    spec = load_yaml(ws.behaviours / behaviour / "spec.yaml")
    intent = (ws.behaviours / behaviour / "intent.md").read_text()
    if sha(intent.encode()) != spec["source"]["content_digest"]:
        raise ValueError("intent.md does not match spec.source.content_digest; approval must bind to the approved content")
    record = {"spec_id": spec["spec_id"], "revision": spec["revision"], "spec_digest": digest(spec),
              "content_digest": spec["source"]["content_digest"], "approved_by": approver, "at": _now().isoformat(timespec="seconds")}
    approvals = load_json(ws.trust / "approvals.json")
    approvals["specs"].append(record)
    write_json(ws.trust / "approvals.json", approvals)
    return record


def approve_promotion(ws: Workspace, candidate_digest: str, approver: str, reason: str, hours: int) -> dict:
    """Exceptional authority: scoped to one candidate digest, with an expiry."""
    record = {"candidate_digest": candidate_digest, "approved_by": approver, "reason": reason,
              "expires_at": (_now() + timedelta(hours=hours)).isoformat(timespec="seconds"), "at": _now().isoformat(timespec="seconds")}
    approvals = load_json(ws.trust / "approvals.json")
    approvals["promotions"].append(record)
    write_json(ws.trust / "approvals.json", approvals)
    return record


def _now() -> datetime:
    return datetime.now(UTC)


# ---- change classification ------------------------------------------------------------------
def classify(pkg: dict, live: dict | None) -> tuple[str, list[str]]:
    """Classify by altered behaviour and authority, not diff size."""
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
        or (u.get("pattern") and t.get("pattern") != u.get("pattern"))  # any pattern change: narrowing is unprovable
    )
    if widened:
        flags.append("trigger_scope_widened")
    return change_class, flags


def _summary(record: dict) -> str:
    d = record["details"]
    for key in ("errors", "failures", "collisions", "uncertain", "error"):
        if d.get(key):
            items = d[key] if isinstance(d[key], list) else [d[key]]
            return "; ".join(str(i) for i in items[:3]) + (f" (+{len(items) - 3} more)" if len(items) > 3 else "")
    if "counterexample" in d:
        cex = d["counterexample"]
        return f"counterexample {cex['events']} violates {cex['violations']}"
    if "mutants" in d:
        bad = [f"{m['mutant']} ({m['result']})" for m in d["mutants"] if m["result"] != "killed"]
        return "suite does not reject: " + ", ".join(bad)
    return record["status"]


def evaluate(ws: Workspace, behaviour: str, store) -> dict:
    fail: list[str] = []
    inconclusive: list[str] = []
    pkg_path, ev_path = ws.package_path(behaviour), ws.evidence_path(behaviour)
    if not pkg_path.exists():
        return {"outcome": "INCONCLUSIVE", "behaviour": behaviour, "candidate_digest": "", "reasons": ["no compiled package"]}
    pkg = load_json(pkg_path)
    candidate = package_digest(pkg)
    pins = load_json(ws.trust / "pins.json")
    key = runner_key(ws.trust)
    approvals = load_json(ws.trust / "approvals.json")
    policy_bytes = ws.policy_file.read_bytes()
    policy = yaml.safe_load(policy_bytes)

    # controls: the assurance system itself must be the ratified one
    if sha(policy_bytes) != pins["policy_digest"]:
        fail.append("control: policy.yaml differs from the pinned, ratified policy")
    if evaluator_digest() != pins["evaluator_digest"]:
        fail.append("control: factory evaluator code differs from the pinned version")

    # contract: approved meaning
    spec = pkg["spec"]
    spec_digest = digest(spec)
    if not any(a["spec_id"] == spec["spec_id"] and a["spec_digest"] == spec_digest for a in approvals["specs"]):
        fail.append(f"contract: {spec['spec_id']} revision {spec['revision']} ({spec_digest[:23]}) is not an approved revision")
    if sha(pkg["intent"].encode()) != spec["source"]["content_digest"]:
        fail.append("contract: intent does not match the approved Confluence content digest")

    records: dict[str, dict] = {}
    requirements: dict[str, str] = {}
    if not ev_path.exists():
        inconclusive.append("evidence: none produced for this candidate")
    else:
        ev = load_json(ev_path)
        signature = ev.pop("signature", None)
        if not verify(key, ev, signature):
            fail.append("evidence: signature invalid (not produced by the trusted runner, or modified after signing)")
        if ev.get("evaluator_digest") != pins["evaluator_digest"]:
            fail.append("evidence: produced by an evaluator that differs from the pinned version")
        if ev.get("policy_digest") != pins["policy_digest"]:
            fail.append("evidence: produced under a policy that differs from the pinned policy")
        if ev.get("candidate_digest") != candidate:
            fail.append("evidence: applies to a different candidate (stale evidence, or artifact changed after verification)")
        if ev.get("runtime") != pkg["manifest"]["runtime"]["files"]:
            fail.append("evidence: produced against different runtime code than the package binds")
        records = {r["obligation"]: r for r in ev.get("records", [])}

        for ob in required_obligations(pkg, policy):
            r = records.get(ob)
            if r is None:
                inconclusive.append(f"{ob}: required obligation was never executed")
            elif r["status"] == "failed":
                fail.append(f"{ob}: {_summary(r)}")
            elif r["status"] != "passed":
                inconclusive.append(f"{ob}: {r['status']}: {_summary(r)}")

    for req in spec["requirements"]:
        state = "established"
        for v in req["verified_by"]:
            kind, _, ref = v.partition(":")
            r = records.get(v if kind == "scenario" else kind)
            if r is None or r["status"] != "passed":
                state = f"not established ({v}: {r['status'] if r else 'missing'})"
                break
            if kind == "eval" and ref not in r["details"].get("slices", {}):
                state = f"not established ({v}: slice not evaluated)"
                inconclusive.append(f"{req['id']}: {v} slice was not evaluated")
                break
        requirements[req["id"]] = state

    # authority: may this class of change promote without a human?
    change_class, flags = classify(pkg, store.live_package(behaviour))
    rule = policy["promotion"][change_class]
    blocking = [f for f in flags if f in rule.get("blocking_flags", [])]
    grant = None
    if not rule["auto"] or blocking:
        grant = next((g for g in approvals["promotions"] if g["candidate_digest"] == candidate and datetime.fromisoformat(g["expires_at"]) > _now()), None)
        if grant is None:
            why = f"{change_class} change" + (f" with {', '.join(blocking)}" if blocking else "")
            inconclusive.append(f"authority: {why} requires an authorised promotion approval bound to this candidate")

    outcome = "FAIL" if fail else "INCONCLUSIVE" if inconclusive else "PASS"
    decision = {
        "outcome": outcome, "behaviour": behaviour, "candidate_digest": candidate, "change_class": change_class, "risk_flags": flags,
        "authorised_by": grant["approved_by"] if grant else ("policy" if outcome == "PASS" else None),
        "requirements": requirements, "reasons": fail + inconclusive, "evaluated_at": _now().isoformat(timespec="seconds"),
    }
    store.log_gate(behaviour, decision)
    return decision
