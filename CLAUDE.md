# Instructions for AI coding agents

You make changes to a chat parsing engine and to the configurations of its desks. A separate process that you can't access decides whether your changes are released.

## What you may change

- The files in `behaviours/<desk>/`, e.g., the profile, the scenarios, the example messages and the message formats of a desk. The requirements are an exception, and the next section explains why.
- The engine code in `runtime/`.

## What you must not change

- The folders `policy/`, `factory/`, `sandbox/`, `trust/`, `state/`, `.github/` and `.claude/`. A change to any of the folders needs a separate approval, and the hooks and the sandbox block your edits to them.
- The requirements in `spec.yaml` and the text of `intent.md`, because an approver has approved them. Never edit a requirement to make a check pass. If a requirement is unclear, stop and describe the smallest example where two readings of the requirement give different results.

## How to work

1. Run `uv run python -m factory context <desk>` to see the requirements of the desk and their current status.
2. Make your change.
3. Run `uv run python -m factory check <desk>` to run the checks. The results aren't signed, so they're only for your own feedback.
4. Run `uv run python -m factory explore <desk> --save` to search for sequences of events that break a business rule.

You're finished when the latest `check` passes on your final change. If the check still fails after a reasonable attempt, stop and report what fails and why.

## How to write

Follow the plain-writing skill in `.claude/skills/plain-writing/SKILL.md` for all prose that you write, e.g., comments, docstrings, command help, tool messages, commit messages and reports. The skill doesn't apply to code itself.
