# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-29

First tagged release.

### Added

- Behaviour-release compiler: canonical packages binding approved intent, profile, contracts, scenarios
  and corpus to the exact runtime files they execute; composition, permitted-effects, traceability and
  exact trigger-interference checks.
- Scenario and counterexample lab: at-least-once transport, crash points, trader-ack replay and release
  switches, eight business invariants, and shrunk counterexamples saved as regression scenarios.
- Slice-level evaluation: Wilson lower bounds against protected floors, zero-harm slices and a paired
  exact McNemar test against the live baseline.
- Domain mutation testing within each behaviour's runtime closure.
- Isolated worker, runner-signed evidence and a fail-closed promotion gate with change classification
  and candidate-bound promotion approvals.
- Release store with compare-and-swap activation, shadow mode, runtime-binding adoption and rollback
  consequence reports.
- Context packets, runtime impact analysis, Confluence snapshot and Jira reconciliation adapters.
- Builder isolation: Claude Code hooks and an OpenShell sandbox policy proven within a pinned boundary.
- `qualify-gate`: a 22-case adversarial benchmark for the gate itself.
- Two example behaviours (NYC UST and LDN gilt RFQ capture) with labelled corpora.

### Changed

- Licensed under the MIT License. The untagged initial commit (`b5257db`) was published under
  Apache-2.0; every tagged release is MIT.

[0.1.0]: https://github.com/moduscorepub/behaviour-release-factory/releases/tag/v0.1.0
