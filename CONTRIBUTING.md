# Contributing

Thanks for helping. This project is licensed under the [MIT License](LICENSE), and contributions are
accepted under the same licence (inbound = outbound). There is no separate contributor licence agreement.

## Developer Certificate of Origin

Every commit must be signed off, certifying the [Developer Certificate of Origin 1.1](https://developercertificate.org/):
you wrote the change or otherwise have the right to submit it under the project's licence.

```bash
git commit -s -m "Describe the change"
```

This adds a `Signed-off-by: Your Name <you@example.com>` trailer that must match the commit author.
A CI check rejects pull requests containing commits without it. To fix a branch:

```bash
git rebase --signoff origin/main && git push --force-with-lease
```

## Development setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m factory --help
```

## Before opening a pull request

```bash
uv run python -m factory qualify-gate      # must report "qualified": true
```

For behaviour changes, also run `uv run python -m factory check <behaviour>` and
`uv run python -m factory explore <behaviour>`. See the README for the full lifecycle.

## Ground rules

- **Never weaken the gate to make something pass.** Changes under `factory/` or `policy/` change what
  the gate accepts. Explain why in the pull request, and add or update a case in
  `factory/adversarial.py` that proves the new behaviour.
- **Behaviours carry their evidence.** A new or changed behaviour includes its spec, scenarios and
  corpus, and every requirement maps to a verification.
- **Keep dependencies few and permissively licensed** (MIT, BSD, Apache-2.0, PSF, MPL-2.0).
- **Security issues go through [SECURITY.md](SECURITY.md)**, never public issues.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating you agree to uphold it.
