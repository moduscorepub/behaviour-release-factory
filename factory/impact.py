# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Context and impact engine over the release store.

Impact: which active releases are invalidated by a runtime change. A release depends on
exactly the runtime files in its manifest closure; files with dynamic edges widen the
dependency to the whole runtime tree. Unaffected releases keep their evidence.

Context: a compact, provenance-carrying task packet for an agent or engineer working on one
behaviour: approved requirements and their evidence state, executable composition, blast
radius through shared runtime code, trigger neighbours, contracts, scenarios and the last gate.
"""

from pathlib import Path

from factory.activation import Store, compatible
from factory.canon import Workspace, digest, load_json
from factory.compiler import runtime_tree_digest


def impact(ws: Workspace, runtime_root: Path | None = None) -> dict:
    root = runtime_root or ws.root
    store = Store(ws)
    tree = runtime_tree_digest(root)
    affected, unaffected = [], []
    for mode in ("live", "shadow"):
        for behaviour, dig, _ in store.pointers(mode):
            pkg = store.release(dig)[0]
            changed = compatible(pkg, root)
            dynamic = pkg["manifest"]["runtime"]["dynamic_edges"] and pkg["manifest"]["runtime"]["tree_digest"] != tree
            entry = {"behaviour": behaviour, "mode": mode, "digest": dig}
            if changed or dynamic:
                affected.append(entry | {"changed_files": changed, "dynamic_edges": dynamic})
            else:
                unaffected.append(entry)
    return {
        "affected": affected,
        "unaffected": unaffected,
        "required": [f"compile + evidence + gate {a['behaviour']} (runtime change: authorised promotion required)" for a in affected],
    }


def context(ws: Workspace, behaviour: str) -> str:
    store = Store(ws)
    pkg_path = ws.package_path(behaviour)
    if not pkg_path.exists():
        return f"# {behaviour}\n\nNot compiled. Run `factory compile {behaviour}` first.\n"
    pkg = load_json(pkg_path)
    spec, profile, manifest = pkg["spec"], pkg["profile"], pkg["manifest"]
    gate = store.last_gate(behaviour) or {}
    approvals = load_json(ws.trust / "approvals.json")["specs"] if (ws.trust / "approvals.json").exists() else []
    approved = any(a["spec_digest"] == digest(spec) for a in approvals)
    src = f"behaviours/{behaviour}"
    out = [
        f"# Task packet: {behaviour}",
        f"Contract {spec['spec_id']} rev {spec['revision']} — Confluence page {spec['source']['confluence_page_id']} v{spec['source']['page_version']} "
        f"({'APPROVED' if approved else 'NOT APPROVED'}) [{src}/spec.yaml]",
        "",
        "## Requirements (authority: approved spec; evidence: last gate)",
    ]
    for r in spec["requirements"]:
        state = gate.get("requirements", {}).get(r["id"], "no gate yet")
        out.append(f"- {r['id']} [{r['criticality']}] {r['statement']}\n  verified by {', '.join(r['verified_by'])} — {state}")
    out += ["", f"## Executable composition [{src}/profile.json]",
            f"- desk {profile['desk']}; rooms {profile['trigger']['rooms']}; firms {profile['trigger']['sender_firms']}; pattern {profile['trigger'].get('pattern')!r}",
            f"- enrichment {' -> '.join(profile['enrichment'])} -> {profile['parser']['component']} ({profile['parser']['universe']}, "
            f"{profile['parser']['min_size']:,}..{profile['parser']['max_size']:,})",
            f"- outputs {[o['destination'] for o in profile['outputs']]} (policy permits {manifest['permitted_destinations']})",
            "", "## Runtime closure (statically established; registry imports excluded)"]
    out += [f"- {f} {d[:19]}" for f, d in manifest["runtime"]["files"].items()]
    if manifest["runtime"]["dynamic_edges"]:
        out.append("- WARNING: dynamic import/exec in closure; dependency set is incomplete, treat any runtime change as impacting")
    out += ["", "## Blast radius: active releases sharing runtime files"]
    mine = set(manifest["runtime"]["files"])
    for other in store.active_packages():
        if other["behaviour_id"] != behaviour:
            shared = sorted(mine & set(other["manifest"]["runtime"]["files"]))
            out.append(f"- {other['behaviour_id']}: shares {shared}")
    out += ["", "## Trigger neighbours (exact scope check)"]
    for other in store.active_packages():
        if other["behaviour_id"] != behaviour:
            rooms = sorted(set(profile["trigger"]["rooms"]) & set(other["profile"]["trigger"]["rooms"]))
            out.append(f"- {other['behaviour_id']}: {'OVERLAPPING rooms ' + str(rooms) if rooms else 'disjoint rooms'}")
    out += ["", "## Consumer contracts"] + [f"- {n}: consumer {c.get('consumer')}, requires {c['required']}" for n, c in pkg["contracts"].items()]
    out += ["", "## Scenarios (regression-* are minimised counterexamples)"] + [f"- {sid} -> {s.get('requirements', [])}" for sid, s in sorted(pkg["scenarios"].items())]
    out += ["", f"## Last gate: {gate.get('outcome', 'none')}"] + [f"- {r}" for r in gate.get("reasons", [])]
    out += ["", "## Commands", f"factory compile {behaviour} && factory explore {behaviour} && factory evidence {behaviour} && factory gate {behaviour}"]
    return "\n".join(out) + "\n"
