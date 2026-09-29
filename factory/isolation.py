# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Builder isolation: fast feedback in the agent, real authority below it.

- Claude Code hooks give immediate corrective feedback. They are not a security boundary.
- The boundary is the OpenShell sandbox: Landlock filesystem rules, process identity and a
  default-deny egress proxy. `sandbox_check` uses openshell-prover to prove the builder policy
  is contained in the authority's pinned boundary. Only `within_boundary` with full coverage
  passes; `exceeds_boundary`, `unsupported`, `inconclusive` and errors all fail closed.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from factory.canon import PROJECT, Workspace, load_json, sha

WRITE_PROTECTED = ("policy/", "trust/", "factory/", "state/", "sandbox/", ".tools/", ".github/", ".claude/")
READ_PROTECTED = ("trust/",)
BASH_WRITE = re.compile(r">|\btee\b|\bsed\s+-i|\brm\b|\bmv\b|\bcp\b|\btouch\b|\bchmod\b|\btruncate\b|\bln\b")
REQUIRED_DOMAINS = {"filesystem", "network_l4", "network_rest", "process", "landlock"}


def _relative(ws: Workspace, path: str) -> str:
    p = Path(path)
    p = p if p.is_absolute() else ws.root / p
    try:
        return str(p.resolve().relative_to(ws.root))
    except ValueError:
        return str(p)


def pre_tool_use(ws: Workspace, payload: dict) -> tuple[int, str]:
    """Claude Code PreToolUse: exit 2 blocks the call and feeds stderr back to the agent."""
    tool, args = payload.get("tool_name", ""), payload.get("tool_input") or {}
    if tool == "Bash":
        cmd = args.get("command", "")
        if any(p in cmd for p in ("trust/", "runner.key", "FACTORY_RUNNER_KEY")):
            return 2, "factory: trust material (runner key, pins, approvals) is authority-owned and not available to builder sessions."
        if BASH_WRITE.search(cmd) and any(p in cmd for p in WRITE_PROTECTED):
            return 2, "factory: this command writes to an authority- or factory-owned path. Propose a control release instead."
        return 0, ""
    protected = READ_PROTECTED if tool == "Read" else WRITE_PROTECTED
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(args.get(key), str):
            rel = _relative(ws, args[key])
            if rel.startswith(protected):
                return 2, (f"factory: {rel} is outside the builder's authority. Behaviours and runtime are yours; policy, evaluator, "
                           "sandbox and trust changes are control releases approved separately.")
    return 0, ""


def _newest(path: Path) -> float:
    return max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=0.0)


def stop(ws: Workspace, payload: dict) -> dict | None:
    """Claude Code Stop: refuse an unsupported "done". One enforced continuation, then the agent must report."""
    if payload.get("stop_hook_active"):
        return None  # bounded repair: do not loop; the agent reports the unresolved obstacle
    runtime_changed = _newest(ws.root / "runtime")
    problems = []
    for bdir in sorted(p for p in ws.behaviours.iterdir() if p.is_dir()):
        check = ws.package_path(bdir.name).with_name("check.json")
        evidence = ws.evidence_path(bdir.name)
        verified_at = max((f.stat().st_mtime for f in (check, evidence) if f.exists()), default=0.0)
        if max(_newest(bdir), runtime_changed) > verified_at:
            problems.append(f"{bdir.name}: changed since its last check (run `factory check {bdir.name}`)")
        elif check.exists() and check.stat().st_mtime >= verified_at:
            failed = [r["obligation"] for r in load_json(check)["records"] if r["status"] != "passed"]
            if failed:
                problems.append(f"{bdir.name}: latest check fails {failed}")
    if not problems:
        return None
    return {"decision": "block", "reason": "Completion is not supported by fresh evidence: " + "; ".join(problems)
            + ". Fix and re-check, or stop and report exactly what remains unresolved."}


def prover_path() -> str:
    return os.environ.get("OPENSHELL_PROVER") or shutil.which("openshell-prover") or str(PROJECT / ".tools" / "bin" / "openshell-prover")


def sandbox_check(ws: Workspace, candidate: Path | None = None) -> dict:
    candidate = candidate or ws.root / "sandbox" / "builder-policy.yaml"
    boundary = ws.root / "policy" / "builder-boundary.yaml"
    pinned = load_json(ws.trust / "pins.json").get("boundary_digest")
    if sha(boundary.read_bytes()) != pinned:
        return {"ok": False, "result": "boundary_not_pinned", "reason": "builder-boundary.yaml differs from the authority-pinned boundary"}
    if not Path(prover_path()).exists():
        return {"ok": False, "result": "prover_unavailable", "reason": f"openshell-prover not found (looked at {prover_path()})"}
    proc = subprocess.run([prover_path(), "check", str(candidate), "--boundary", str(boundary), "--output", "json"], capture_output=True, text=True, timeout=120)
    try:
        res = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "result": "error", "reason": (proc.stderr or proc.stdout)[-500:]}
    missing = sorted(REQUIRED_DOMAINS - set(res.get("coverage", {}).get("domains", [])))
    ok = res["result"] == "within_boundary" and not missing
    return {"ok": ok, "result": res["result"], "counterexample": res.get("counterexample"), "reason": res.get("reason"), "uncovered_domains": missing}
