# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Atlassian adapters. Confluence owns approved intent; Jira is a projection of delivery state.

- `confluence_snapshot` binds to an exact page version and records its content digest; the
  spec compiler later refuses any intent that does not match that digest.
- `jira_desired` derives each work item's state from protected facts (gate log, active
  releases), never from "a linked PR merged". `jira_plan` reconciles desired vs actual Jira
  state into idempotent operations keyed by a stable external-id label; it never rewrites
  human-owned fields after creation. `jira_apply` executes the plan via Jira Cloud REST v3.
"""

import base64
import json
import os
import urllib.request
from pathlib import Path

from factory.activation import Store
from factory.canon import Workspace, digest, load_json, load_yaml, sha

STATES = ("todo", "in_progress", "blocked", "qualified", "activated")


def _request(base: str, path: str, method: str = "GET", body: dict | None = None):
    token = base64.b64encode(f"{os.environ['ATLASSIAN_EMAIL']}:{os.environ['ATLASSIAN_API_TOKEN']}".encode()).decode()
    req = urllib.request.Request(
        base.rstrip("/") + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {token}", "Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return json.loads(data) if data else None


def confluence_snapshot(base: str, page_id: str, version: int, out: Path) -> dict:
    page = _request(base, f"/wiki/api/v2/pages/{page_id}?body-format=storage&version={version}")
    if page["version"]["number"] != version:
        raise ValueError(f"Confluence returned version {page['version']['number']}, not the approved version {version}")
    body = page["body"]["storage"]["value"]
    out.write_text(body)
    return {"confluence_page_id": page_id, "page_version": version, "content_digest": sha(body.encode()), "title": page["title"]}


def jira_desired(ws: Workspace) -> list[dict]:
    store = Store(ws)
    items = []
    for spec_path in sorted(ws.behaviours.glob("*/spec.yaml")):
        behaviour = spec_path.parent.name
        spec = load_yaml(spec_path)
        live = store.live_package(behaviour)
        gate = store.last_gate(behaviour)
        pkg_path = ws.package_path(behaviour)
        current = load_json(pkg_path) if pkg_path.exists() else None
        for w in spec["work_items"]:
            established = gate and all(gate["requirements"].get(r) == "established" for r in w["satisfies"])
            if live and digest(live["spec"]) == digest(spec):
                state, why = "activated", f"live release {store.pointer(behaviour, 'live')[0][:19]} carries this revision"
            elif gate and current and gate["candidate_digest"] == digest(current) and gate["outcome"] == "PASS" and established:
                state, why = "qualified", "gate PASS on the current candidate; awaiting activation"
            elif gate and gate["outcome"] == "FAIL":
                state, why = "blocked", "; ".join(gate["reasons"][:2])
            elif current:
                state, why = "in_progress", f"candidate compiled; gate {gate['outcome'] if gate else 'not run'}"
            else:
                state, why = "todo", "not compiled"
            items.append({"external_id": f"factory.{spec['spec_id']}.{w['id']}", "jira_key": w.get("jira_key"), "summary": w["summary"], "state": state, "why": why})
    return items


def jira_actual(base: str, project: str) -> list[dict]:
    res = _request(base, "/rest/api/3/search/jql", "POST", {"jql": f'project = "{project}" AND labels ~ "factory.*"', "fields": ["status", "labels"], "maxResults": 500})
    return [{"key": i["key"], "status": i["fields"]["status"]["name"], "labels": i["fields"]["labels"]} for i in res["issues"]]


def jira_plan(desired: list[dict], actual: list[dict], status_map: dict[str, str]) -> list[dict]:
    by_label = {label: issue for issue in actual for label in issue["labels"]}
    by_key = {issue["key"]: issue for issue in actual}
    ops = []
    for d in desired:
        target = status_map[d["state"]]
        issue = by_label.get(d["external_id"]) or by_key.get(d["jira_key"])
        if issue is None:
            ops.append({"op": "create", "external_id": d["external_id"], "summary": d["summary"], "status": target, "why": d["why"]})
        elif d["external_id"] not in issue["labels"]:
            ops.append({"op": "label", "key": issue["key"], "external_id": d["external_id"]})
        if issue is not None and issue["status"] != target:
            ops.append({"op": "transition", "key": issue["key"], "from": issue["status"], "to": target, "why": d["why"]})
    return ops


def jira_apply(base: str, project: str, ops: list[dict]) -> list[dict]:
    results = []
    for op in ops:
        if op["op"] == "create":
            created = _request(base, "/rest/api/3/issue", "POST", {"fields": {
                "project": {"key": project}, "issuetype": {"name": "Task"}, "summary": op["summary"], "labels": [op["external_id"]]}})
            key = created["key"]
            results.append({"op": "create", "key": key})
            if _request(base, f"/rest/api/3/issue/{key}?fields=status")["fields"]["status"]["name"] == op["status"]:
                continue
            op = {"op": "transition", "key": key, "to": op["status"]}
        elif op["op"] == "label":
            _request(base, f"/rest/api/3/issue/{op['key']}", "PUT", {"update": {"labels": [{"add": op["external_id"]}]}})
            results.append({"op": "label", "key": op["key"]})
            continue
        transitions = _request(base, f"/rest/api/3/issue/{op['key']}/transitions")["transitions"]
        match = next((t for t in transitions if t["to"]["name"] == op["to"]), None)
        if match is None:  # never force a workflow; surface it
            results.append({"op": "transition", "key": op["key"], "result": f"no workflow transition to '{op['to']}'"})
            continue
        _request(base, f"/rest/api/3/issue/{op['key']}/transitions", "POST", {"transition": {"id": match["id"]}})
        results.append({"op": "transition", "key": op["key"], "result": op["to"]})
    return results
