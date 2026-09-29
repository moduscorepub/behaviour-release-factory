# Builder agent instructions

You implement behaviour releases for a chat → RFQ engine. You do not decide whether they ship.

- Yours: `behaviours/<id>/` (profile, scenarios, corpus, contracts) and `runtime/`.
- Not yours: `policy/`, `factory/`, `sandbox/`, `trust/`, `state/`. Changes there are control releases; hooks and the sandbox block them.
- `spec.yaml` + `intent.md` are the approved contract. Never edit a requirement to make a check pass; if intent is ambiguous, stop and report the smallest concrete ambiguity (two readings, two outputs).

Loop: `uv run python -m factory context <id>` → edit → `uv run python -m factory check <id>` → `uv run python -m factory explore <id> --save`.
`check` is unsigned feedback. Signed evidence, gating and activation run in protected CI (`factory evidence|gate|activate`).
Done means the latest `check` passes on your final edit. If it does not after a bounded attempt, stop and report what fails and why.
