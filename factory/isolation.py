# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Keep the AI coding agent within its approved limits.

- The Claude Code hooks give the agent quick feedback when it tries to go outside its limits. An agent could get
  around the hooks, so the hooks don't enforce anything.
- The OpenShell sandbox enforces the limits with Landlock file rules, a separate process identity and a network proxy
  that blocks every connection that the settings don't allow. `sandbox_check` uses openshell-prover to prove that the
  sandbox settings of the agent stay within the limits that approvers recorded.
- The check only passes on the result `within_boundary` with full coverage. Every other result fails, e.g.,
  `exceeds_boundary`, `unsupported`, `inconclusive` or an error.
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
    """Handle the Claude Code PreToolUse hook. Exit code 2 blocks the tool call, and Claude Code shows the message to the agent."""
    tool, args = payload.get("tool_name", ""), payload.get("tool_input") or {}
    if tool == "Bash":
        cmd = args.get("command", "")
        if any(p in cmd for p in ("trust/", "runner.key", "FACTORY_RUNNER_KEY")):
            return 2, "factory: the signing key, the recorded hashes and the approvals belong to approvers, so builder sessions can't use them."
        if BASH_WRITE.search(cmd) and any(p in cmd for p in WRITE_PROTECTED):
            return 2, "factory: the command writes to a folder that only approvers or maintainers may change. Propose the change for their review instead."
        return 0, ""
    protected = READ_PROTECTED if tool == "Read" else WRITE_PROTECTED
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(args.get(key), str):
            rel = _relative(ws, args[key])
            if rel.startswith(protected):
                return 2, (f"factory: builders can't change {rel}. You can change behaviours/ and runtime/, but a change to the policy, the checks, "
                           "the sandbox or the trust files needs a separate approval.")
    return 0, ""


def _newest(path: Path) -> float:
    return max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=0.0)


def stop(ws: Workspace, payload: dict) -> dict | None:
    """Handle the Claude Code Stop hook.

    The hook stops the agent from reporting that it's finished while its latest changes are unchecked. The hook blocks
    the agent once, and after that, the agent must report what is still unresolved.
    """
    if payload.get("stop_hook_active"):
        return None  # The hook already blocked the agent once, so it lets the agent stop and report instead of looping.
    runtime_changed = _newest(ws.root / "runtime")
    problems = []
    for bdir in sorted(p for p in ws.behaviours.iterdir() if p.is_dir()):
        check = ws.package_path(bdir.name).with_name("check.json")
        evidence = ws.evidence_path(bdir.name)
        verified_at = max((f.stat().st_mtime for f in (check, evidence) if f.exists()), default=0.0)
        if max(_newest(bdir), runtime_changed) > verified_at:
            problems.append(f"{bdir.name} changed after its last check, so run `factory check {bdir.name}`")
        elif check.exists() and check.stat().st_mtime >= verified_at:
            failed = [r["obligation"] for r in load_json(check)["records"] if r["status"] != "passed"]
            if failed:
                problems.append(f"the latest check of {bdir.name} fails {failed}")
    if not problems:
        return None
    return {"decision": "block", "reason": "The latest checks don't show that the work is finished. The problems are: " + "; ".join(problems)
            + ". Fix the problems and run the checks again, or stop and report exactly what is still unresolved."}


def prover_path() -> str:
    return os.environ.get("OPENSHELL_PROVER") or shutil.which("openshell-prover") or str(PROJECT / ".tools" / "bin" / "openshell-prover")


def sandbox_check(ws: Workspace, candidate: Path | None = None) -> dict:
    candidate = candidate or ws.root / "sandbox" / "builder-policy.yaml"
    boundary = ws.root / "policy" / "builder-boundary.yaml"
    pinned = load_json(ws.trust / "pins.json").get("boundary_digest")
    if sha(boundary.read_bytes()) != pinned:
        return {"ok": False, "result": "boundary_not_pinned", "reason": "policy/builder-boundary.yaml differs from the version that approvers recorded with trust-init"}
    if not Path(prover_path()).exists():
        return {"ok": False, "result": "prover_unavailable", "reason": f"openshell-prover wasn't found at {prover_path()}"}
    proc = subprocess.run([prover_path(), "check", str(candidate), "--boundary", str(boundary), "--output", "json"], capture_output=True, text=True, timeout=120)
    try:
        res = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "result": "error", "reason": (proc.stderr or proc.stdout)[-500:]}
    missing = sorted(REQUIRED_DOMAINS - set(res.get("coverage", {}).get("domains", [])))
    ok = res["result"] == "within_boundary" and not missing
    return {"ok": ok, "result": res["result"], "counterexample": res.get("counterexample"), "reason": res.get("reason"), "uncovered_domains": missing}
