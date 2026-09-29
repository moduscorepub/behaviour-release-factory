# Contributing

Thank you for helping with behaviour-release-factory. The sections below explain how to set up the project and sign off your commits, and they also explain the writing style and the checks to run before you open a pull request.

## Licence

The project uses the [MIT License](LICENSE), and by contributing, you agree that your contribution is released under the same licence. You don't need to sign a separate agreement.

## Sign off your commits

Every commit must include a sign-off line. The sign-off confirms that you wrote the change, or that you have the right to submit it, under the [Developer Certificate of Origin 1.1](https://developercertificate.org/).

Add the sign-off with the `-s` flag:

```bash
git commit -s -m "Describe the change"
```

The flag adds a line such as `Signed-off-by: Your Name <you@example.com>` to the commit message, and the name and email must match the author of the commit. A check on every pull request rejects any commit that doesn't have a matching sign-off.

If you forgot to sign off, you can add the sign-off to every commit on your branch with the following commands:

```bash
git rebase --signoff origin/main
git push --force-with-lease
```

## Set up the project

You need Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m factory --help
```

## Writing style

All prose in the repository follows the plain-writing skill in [`.claude/skills/plain-writing/SKILL.md`](.claude/skills/plain-writing/SKILL.md). The prose includes the documentation, code comments, docstrings, command help and messages that the tools print, and it also includes commit messages and pull request descriptions. The skill doesn't apply to code itself, e.g., the names of functions, or to the example chat messages under `behaviours/`.

Claude Code loads the skill from `.claude/skills/` automatically. If you use a different tool, give the tool the rules in the skill file as instructions.

CI checks rules 15 and 17 of the skill, so it rejects any en dash, em dash, middle dot or curly quote outside the skill folder. Reviewers check the other rules.

The skill file is an unchanged copy of [docwriter-org/plain-writing-skill](https://github.com/docwriter-org/plain-writing-skill). To update the skill, copy the new `skills/plain-writing/SKILL.md` from the upstream repository without any changes, and record the new commit in the README.

## Before you open a pull request

Run `qualify-gate`, which tests the gate itself, and confirm that it reports `"qualified": true`.

```bash
uv run python -m factory qualify-gate
```

If you changed a desk under `behaviours/`, also run the following commands for the desk:

```bash
uv run python -m factory check <desk>
uv run python -m factory explore <desk>
```

## Rules for changes

- Don't weaken the gate to make a change pass. A change to `factory/` or `policy/` changes what the gate accepts, so explain the reason in your pull request. Also add or update a case in `factory/adversarial.py` that proves the new behaviour.
- Keep each desk and its tests together. A new or changed desk must include its requirements, scenarios and example messages, and every requirement must say how it's checked.
- Keep the number of dependencies small. A new dependency must use one of the following licences: MIT, BSD, Apache-2.0, PSF or MPL-2.0.
- Report security problems privately, as [SECURITY.md](SECURITY.md) describes, and don't open a public issue for them.
