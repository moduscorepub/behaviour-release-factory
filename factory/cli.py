# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Command line interface for the factory, which you run as `python -m factory <command>`.

The same commands run on your own computer, in CI and from the Claude Code hooks.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from factory.canon import PROJECT, Workspace


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="factory", description="Check, approve and release changes to the desks of a chat parsing engine.")
    ap.add_argument("--root", type=Path, default=Path(os.environ.get("FACTORY_ROOT", PROJECT)),
                    help="The root folder of the workspace. The default is FACTORY_ROOT if it's set, and the repository folder otherwise.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cmd(name: str, help: str, *args: tuple) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help, description=help)
        for flags, kw in args:
            p.add_argument(*flags, **kw)
        return p

    b = (("behaviour",), {"help": "The name of a desk folder under behaviours/, e.g., ust-rfq-nyc."})
    rt = (("--runtime-root",), {"type": Path, "help": "The folder that holds the runtime/ code to use. The default is the workspace root."})
    by = (("--by",), {"required": True, "help": "The name of the person or system that performs the action."})

    # Commands for approvers.
    cmd("trust-init", "Create the signing key, and record hashes of the policy, the checks and the sandbox limits. Only approvers run the command.")
    cmd("approve-spec", "Approve the current revision of the requirements of a desk. Only approvers run the command.", b, by)
    cmd("approve-promotion", "Allow one release package, which is named by its hash, to be released. Only approvers run the command.",
        (("digest",), {"help": "The hash of the release package."}), by,
        (("--reason",), {"required": True, "help": "The reason for the approval."}),
        (("--hours",), {"type": int, "default": 24, "help": "The number of hours that the approval lasts. The default is 24."}))
    # Commands for builders.
    cmd("context", "Print a summary of a desk, with its requirements, the status of their checks and the engine code that it shares with other desks.", b)
    cmd("compile", "Compile a desk into a release package.", b, rt)
    cmd("check", "Run every check except mutation testing, without signing the results. Builders use the command for feedback.", b, rt)
    cmd("explore", "Search for a sequence of events that breaks a business rule.", b, rt,
        (("--save",), {"action": "store_true", "help": "Save the smallest failing sequence as a new scenario of the desk."}))
    # Commands for protected CI.
    cmd("evidence", "Run every required check and sign the results. Only the runner in protected CI runs the command.", b, rt,
        (("--skip",), {"action": "append", "default": [], "help": "Skip the named check. The gate answers INCONCLUSIVE if a required check is skipped."}))
    cmd("gate", "Decide whether a desk can be released. The command exits with 0 only when the answer is PASS.", b)
    cmd("qualify-gate", "Test the gate itself with prepared cases that the gate must pass or reject.",
        (("--case",), {"action": "append", "help": "Run only the named case. You can repeat the option."}))
    cmd("sandbox-check", "Use openshell-prover to prove that the sandbox settings of the agent stay within the approved limits.",
        (("--candidate",), {"type": Path, "help": "The sandbox settings to check. The default is sandbox/builder-policy.yaml."}))
    # Commands that control releases.
    cmd("activate", "Run the gate and store the release. Then switch the live or shadow version, unless someone else switched it first.", b,
        (("--mode",), {"choices": ("live", "shadow"), "required": True, "help": "Switch the live version or the shadow version."}), by,
        (("--expect-generation",), {"type": int, "help": "Switch only if the generation number, which goes up by one with each switch, still has the given value."}))
    cmd("rollback", "Stop the live release of a desk and go back to the previous release. The command lists the messages that the release already sent, "
        "because a rollback can't unsend them.", b, by)
    cmd("status", "Compare the releases that should run with the releases that each engine instance has loaded.")
    cmd("impact", "List the active releases that the engine code in the runtime folder would make out of date.", rt)
    cmd("feed", "Run the deployed engine in live and shadow mode over a file of chat events.",
        (("events",), {"type": Path, "help": "A JSON Lines file with one chat event on each line."}),
        (("--instance",), {"default": "i1", "help": "The name of the engine instance. The default is i1."}))
    cmd("shadow-report", "Compare the output of the live release and the shadow release for each message.",
        (("--instance",), {"default": "i1", "help": "The name of the engine instance. The default is i1."}))
    # Commands for Jira, Confluence and Claude Code.
    cmd("jira-plan", "Work out the Jira changes that follow from the current release state.",
        (("--actual",), {"type": Path, "help": "A JSON snapshot of the Jira issues. Without the option, the command fetches the issues from Jira."}),
        (("--jira-url",), {"help": "The address of the Jira site."}))
    cmd("jira-apply", "Make the planned Jira changes. The command needs the ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN environment variables.",
        (("--jira-url",), {"required": True, "help": "The address of the Jira site."}))
    cmd("spec-snapshot", "Save one version of an approved Confluence page as the intent.md file of a desk.", b,
        (("--confluence-url",), {"required": True, "help": "The address of the Confluence site."}),
        (("--page-id",), {"required": True, "help": "The ID of the Confluence page."}),
        (("--version",), {"type": int, "required": True, "help": "The version of the page to save."}))
    cmd("hook", "Handle a Claude Code hook. The command reads the JSON of the hook from standard input.",
        (("event",), {"choices": ("pre-tool-use", "stop"), "help": "The hook event to handle."}))
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
