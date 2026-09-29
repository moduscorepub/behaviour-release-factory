## Summary of the change

<!-- Describe the change and the problem that it solves, and link any related issues. -->

## Checks for every pull request

- [ ] Every commit is signed off with `git commit -s`, as CONTRIBUTING.md explains.
- [ ] `uv run python -m factory qualify-gate` reports `"qualified": true`.
- [ ] New or changed prose follows the plain-writing skill in `.claude/skills/plain-writing/SKILL.md`.

## Checks that apply to some pull requests

- [ ] If the pull request changes what the gate accepts or rejects, `factory/adversarial.py` has a case that proves the new behaviour.
- [ ] If the pull request changes a desk, the requirements, scenarios and example messages of the desk are up to date.
- [ ] If users will notice the change, CHANGELOG.md has an entry under Unreleased.
