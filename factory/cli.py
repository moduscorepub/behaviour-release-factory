# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""`python -m factory <command>`: the same commands run locally, in CI and from agent hooks."""

import argparse
import json
import os
import sys
from pathlib import Path

from factory.canon import PROJECT, Workspace


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="factory", description="Behaviour-release factory for chat-driven trading-message behaviours.")
    ap.add_argument("--root", type=Path, default=Path(os.environ.get("FACTORY_ROOT", PROJECT)), help="workspace root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cmd(name: str, help: str, *args: tuple) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help)
        for flags, kw in args:
            p.add_argument(*flags, **kw)
        return p

    b = (("behaviour",), {})
    rt = (("--runtime-root",), {"type": Path, "help": "candidate runtime tree (default: workspace)"})
    by = (("--by",), {"required": True})

    # authority
    cmd("trust-init", "(authority) generate runner key, pin policy, evaluator and sandbox boundary")
    cmd("approve-spec", "(authority) approve the current spec revision of a behaviour", b, by)
    cmd("approve-promotion", "(authority) authorise one candidate digest to promote", (("digest",), {}), by,
        (("--reason",), {"required": True}), (("--hours",), {"type": int, "default": 24}))
    # builder loop
    cmd("context", "task packet: requirements, evidence state, composition, blast radius", b)
    cmd("compile", "compile a behaviour into a canonical release package", b, rt)
    cmd("check", "unsigned run of every obligation except mutation (builder feedback)", b, rt)
    cmd("explore", "search fault schedules; --save keeps the minimised counterexample as a regression scenario", b, rt,
        (("--save",), {"action": "store_true"}))
    # protected CI
    cmd("evidence", "(runner) execute every required obligation and sign the evidence", b, rt, (("--skip",), {"action": "append", "default": []}))
    cmd("gate", "evaluate the promotion gate; exit 0 only on PASS", b)
    cmd("qualify-gate", "run the adversarial gate-qualification benchmark", (("--case",), {"action": "append"}))
    cmd("sandbox-check", "prove the builder sandbox policy is within the pinned boundary (openshell-prover)", (("--candidate",), {"type": Path}))
    # release control
    cmd("activate", "gate, store immutably, compare-and-swap the active pointer", b, (("--mode",), {"choices": ("live", "shadow"), "required": True}), by,
        (("--expect-generation",), {"type": int}))
    cmd("rollback", "revoke the live release, restore the previous one, report unretractable effects", b, by)
    cmd("status", "desired vs observed release state")
    cmd("impact", "active releases invalidated by the current runtime tree", rt)
    cmd("feed", "run the deployed runtime (live + shadow) over a JSONL event file", (("events",), {"type": Path}), (("--instance",), {"default": "i1"}))
    cmd("shadow-report", "compare live and shadow outcomes per message", (("--instance",), {"default": "i1"}))
    # delivery systems
    cmd("jira-plan", "reconcile work-item state into Jira operations", (("--actual",), {"type": Path, "help": "Jira issues snapshot JSON; default: fetch"}),
        (("--jira-url",), {}))
    cmd("jira-apply", "apply the reconciliation plan (needs ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN)", (("--jira-url",), {"required": True}))
    cmd("spec-snapshot", "snapshot an approved Confluence page version into intent.md", b, (("--confluence-url",), {"required": True}),
        (("--page-id",), {"required": True}), (("--version",), {"type": int, "required": True}))
    cmd("hook", "Claude Code hook entry point (reads the hook JSON on stdin)", (("event",), {"choices": ("pre-tool-use", "stop")}))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    ws = Workspace(args.root.resolve())
    c = args.cmd

    if c == "trust-init":
        from factory.gate import init_trust
        _print(init_trust(ws))
    elif c == "approve-spec":
        from factory.gate import approve_spec
        _print(approve_spec(ws, args.behaviour, args.by))
    elif c == "approve-promotion":
        from factory.gate import approve_promotion
        _print(approve_promotion(ws, args.digest, args.by, args.reason, args.hours))
    elif c == "context":
        from factory.impact import context
        print(context(ws, args.behaviour))
    elif c == "compile":
        from factory.runner import compile_behaviour
        out = compile_behaviour(ws, args.behaviour, args.runtime_root)
        _print(out)
        return 1 if out["diagnostics"] else 0
    elif c in ("check", "evidence"):
        from factory.runner import check, produce_evidence
        bundle = check(ws, args.behaviour, args.runtime_root) if c == "check" else produce_evidence(ws, args.behaviour, args.runtime_root, tuple(args.skip))
        failing = {r["obligation"]: r["details"] for r in bundle["records"] if r["status"] != "passed"}
        _print({"candidate_digest": bundle["candidate_digest"], "signed": c == "evidence",
                "records": {r["obligation"]: f"{r['status']} ({r['seconds']}s)" for r in bundle["records"]}, "failing": failing})
        return 1 if failing else 0
    elif c == "explore":
        from factory.runner import explore
        out = explore(ws, args.behaviour, args.runtime_root, args.save)
        _print(out)
        return 0 if out["status"] == "passed" else 1
    elif c == "gate":
        from factory.activation import Store
        from factory.gate import evaluate
        decision = evaluate(ws, args.behaviour, Store(ws))
        _print(decision)
        return 0 if decision["outcome"] == "PASS" else 1
    elif c == "qualify-gate":
        from factory.adversarial import qualify
        out = qualify(ws.root, args.case)
        _print(out)
        return 0 if out["qualified"] else 1
    elif c == "sandbox-check":
        from factory.isolation import sandbox_check
        out = sandbox_check(ws, args.candidate)
        _print(out)
        return 0 if out["ok"] else 1
    elif c == "activate":
        from factory.activation import Refused, activate
        try:
            _print(activate(ws, args.behaviour, args.mode, args.by, args.expect_generation))
        except Refused as e:
            _print({"refused": e.decision})
            return 1
    elif c == "rollback":
        from factory.activation import rollback
        _print(rollback(ws, args.behaviour, args.by))
    elif c == "status":
        from factory.activation import status
        _print(status(ws))
    elif c == "impact":
        from factory.impact import impact
        out = impact(ws, args.runtime_root)
        _print(out)
        return 1 if out["affected"] else 0
    elif c == "feed":
        from factory.activation import feed
        events = [json.loads(line) for line in args.events.read_text().splitlines() if line.strip()]
        out = feed(ws, args.instance, events)
        _print(out)
        return 1 if any(out[m]["invariant_violations"] for m in ("live", "shadow") if m in out) else 0
    elif c == "shadow-report":
        from factory.activation import shadow_report
        _print(shadow_report(ws, args.instance))
    elif c in ("jira-plan", "jira-apply"):
        import yaml

        from factory.atlassian import jira_actual, jira_apply, jira_desired, jira_plan
        cfg = yaml.safe_load(ws.policy_file.read_text())["jira"]
        actual = json.loads(args.actual.read_text()) if getattr(args, "actual", None) else jira_actual(args.jira_url, cfg["project"])
        ops = jira_plan(jira_desired(ws), actual, cfg["status"])
        _print({"desired": jira_desired(ws), "plan": ops} if c == "jira-plan" else jira_apply(args.jira_url, cfg["project"], ops))
    elif c == "spec-snapshot":
        from factory.atlassian import confluence_snapshot
        _print(confluence_snapshot(args.confluence_url, args.page_id, args.version, ws.behaviours / args.behaviour / "intent.md"))
    elif c == "hook":
        from factory import isolation
        payload = json.loads(sys.stdin.read() or "{}")
        if args.event == "pre-tool-use":
            code, message = isolation.pre_tool_use(ws, payload)
            if message:
                print(message, file=sys.stderr)
            return code
        verdict = isolation.stop(ws, payload)
        if verdict:
            print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
