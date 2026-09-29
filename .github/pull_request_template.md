## What and why

<!-- The change and the problem it solves. Link issues. -->

## Checklist

- [ ] Every commit is signed off (`git commit -s`, see CONTRIBUTING.md)
- [ ] `uv run python -m factory qualify-gate` reports `"qualified": true`
- [ ] If this changes what the gate accepts or rejects, `factory/adversarial.py` has a case proving it
- [ ] Behaviour changes include spec, scenarios and corpus updates
- [ ] CHANGELOG.md updated under an "Unreleased" heading for user-visible changes
