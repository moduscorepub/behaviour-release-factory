# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Summarise a desk, and find the releases that a change to the engine code affects.

`impact` lists the active releases that a change to the engine code makes out of date. A release depends on
exactly the engine files that its package lists. If one of the files uses dynamic imports, the release depends
on the whole runtime/ folder instead. Releases that the change doesn't affect keep their evidence.

`context` prints a short summary for an agent or an engineer who works on one desk. The summary shows the
approved requirements, the status of their checks and the components of the desk. It also shows the desks that
share engine code or chat rooms with the desk, and it ends with the scenarios and the last answer of the gate.
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
        "required": [f"run compile, evidence and gate for {a['behaviour']}, and get a named person to approve the package, because the engine code changed"
                     for a in affected],
    }


def context(ws: Workspace, behaviour: str) -> str:
    store = Store(ws)
    pkg_path = ws.package_path(behaviour)
    if not pkg_path.exists():
        return f"# {behaviour}\n\nThe desk isn't compiled yet. Run `factory compile {behaviour}` first.\n"
    pkg = load_json(pkg_path)
    spec, profile, manifest = pkg["spec"], pkg["profile"], pkg["manifest"]
    gate = store.last_gate(behaviour) or {}
    approvals = load_json(ws.trust / "approvals.json")["specs"] if (ws.trust / "approvals.json").exists() else []
    approved = any(a["spec_digest"] == digest(spec) for a in approvals)
    src = f"behaviours/{behaviour}"
    out = [
        f"# Summary of {behaviour}",
        f"The requirements are revision {spec['revision']} of {spec['spec_id']}, from version {spec['source']['page_version']} of Confluence page "
        f"{spec['source']['confluence_page_id']}, and they're {'approved' if approved else 'not approved'}. The file is {src}/spec.yaml.",
        "",
        "## Requirements, with their status from the last gate answer",
    ]
    for r in spec["requirements"]:
        state = gate.get("requirements", {}).get(r["id"], "the gate hasn't run yet")
        out.append(f"- {r['id']} ({r['criticality']}): {r['statement']}\n  Checks: {', '.join(r['verified_by'])}. Status: {state}.")
    out += ["", f"## Components of the desk, from {src}/profile.json",
            f"- Trigger: desk {profile['desk']}, rooms {profile['trigger']['rooms']}, firms {profile['trigger']['sender_firms']}, "
            f"pattern {profile['trigger'].get('pattern')!r}",
            f"- Pipeline: {' -> '.join([*profile['enrichment'], profile['parser']['component']])}, with the {profile['parser']['universe']} universe "
            f"and sizes from {profile['parser']['min_size']:,} to {profile['parser']['max_size']:,}",
            f"- Outputs: {[o['destination'] for o in profile['outputs']]}, and the policy allows {manifest['permitted_destinations']}",
            "", "## Engine files that the desk runs, without the imports in the component list"]
    out += [f"- {f} {d[:19]}" for f, d in manifest["runtime"]["files"].items()]
    if manifest["runtime"]["dynamic_edges"]:
        out.append("- Warning: a file uses dynamic imports or exec, so the list may be incomplete. Treat any change to the engine as a change that affects the desk.")
    out += ["", "## Active releases that share engine files with the desk"]
    mine = set(manifest["runtime"]["files"])
    for other in store.active_packages():
        if other["behaviour_id"] != behaviour:
            shared = sorted(mine & set(other["manifest"]["runtime"]["files"]))
            out.append(f"- {other['behaviour_id']} shares {shared}")
    out += ["", "## Active desks that listen in the same chat rooms"]
    for other in store.active_packages():
        if other["behaviour_id"] != behaviour:
            rooms = sorted(set(profile["trigger"]["rooms"]) & set(other["profile"]["trigger"]["rooms"]))
            out.append(f"- {other['behaviour_id']}: {'shares the rooms ' + str(rooms) if rooms else 'shares no rooms'}")
    out += ["", "## Message formats that receivers expect"] + [f"- {n} is read by {c.get('consumer')}, which requires {c['required']}" for n, c in pkg["contracts"].items()]
    out += ["", "## Scenarios, where each regression-* scenario is a failing sequence that fault exploration found and reduced"]
    out += [f"- {sid} checks {s.get('requirements', [])}" for sid, s in sorted(pkg["scenarios"].items())]
    out += ["", f"## Last gate answer: {gate.get('outcome', 'none')}"] + [f"- {r}" for r in gate.get("reasons", [])]
    out += ["", "## Commands to run after a change", f"factory compile {behaviour} && factory explore {behaviour} && factory evidence {behaviour} && factory gate {behaviour}"]
    return "\n".join(out) + "\n"
