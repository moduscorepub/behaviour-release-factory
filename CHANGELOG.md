# Changelog

The changelog lists the notable changes in each release. It follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, and the version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added the plain-writing skill from [docwriter-org/plain-writing-skill](https://github.com/docwriter-org/plain-writing-skill) as the writing style for the repository. CI now rejects dashes, middle dots and curly quotes, which the skill forbids.

### Changed

- Rewrote the documentation, templates, code comments, docstrings, command help and tool messages to follow the plain-writing skill.

### Fixed

- The README now lists the business rules with the IDs that the gate reports, e.g., I6 for a lost message.
- The README and CI no longer describe all 22 `qualify-gate` cases as attempts to fool the gate, because three of the cases are correct changes that the gate must pass.

### Removed

- Removed the code of conduct.

## [0.1.0] - 2026-09-29

Version 0.1.0 is the first tagged release.

### Added

- Building and checking a release
  - A compiler that combines the approved requirements, the profile and the test data of a desk into one release package. The package records the exact engine files that the desk depends on.
  - Static checks in the compiler, which confirm that the components of a profile fit together and that messages only go to allowed destinations. The compiler also confirms that no desk can pick up the messages of another desk.
  - A test harness that replays scripted conversations and searches for unusual sequences of events, e.g., duplicate messages, crashes, late replies and release switches. When the harness finds a failing sequence, it reduces the sequence to the smallest example, and it can save the example as a permanent test.
  - Accuracy scoring for each category of example message, with stricter limits for the riskiest categories and a comparison with the live release.
  - Mutation testing, which deliberately breaks the engine to confirm that the tests catch each break.
- Signing, gating and release
  - A separate worker process that runs the checks, and a runner that signs the results.
  - A release gate that answers PASS, FAIL or INCONCLUSIVE. Some changes also need a named person to approve the exact release.
  - Release tools that store releases, switch the live version safely, run a release in shadow mode and roll a release back.
  - `qualify-gate`, which tests the gate itself with 22 prepared cases.
- Tools for people and agents
  - Commands that summarise a desk, find the releases that an engine change affects, read approved pages from Confluence and plan Jira updates.
  - Sandbox settings for AI coding agents, which `sandbox-check` checks with the OpenShell policy prover, and Claude Code hooks that give agents quick feedback.
- Two example desks, one for US Treasuries in New York and one for UK gilts in London, with labelled example messages.

### Changed

- The project is released under the MIT License. The first commit (`b5257db`), which has no tag, was published under the Apache-2.0 licence, and every tagged release uses the MIT License.

[Unreleased]: https://github.com/moduscorepub/behaviour-release-factory/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/moduscorepub/behaviour-release-factory/releases/tag/v0.1.0
