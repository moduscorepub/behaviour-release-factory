# behaviour-release-factory

[![CI](https://github.com/moduscorepub/behaviour-release-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/moduscorepub/behaviour-release-factory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](pyproject.toml)
[![DCO](https://img.shields.io/badge/DCO-1.1-blue.svg)](CONTRIBUTING.md#sign-off-your-commits)

behaviour-release-factory is a set of command line tools that check the changes an AI coding agent makes and decide whether each change can be released. The repository includes an example chat parsing engine for bond trading desks, so you can run the whole process on your own computer.

## Why the checks run outside the agent

An AI coding agent can write a change quickly, but you still need a reliable way to know whether the change is safe to release. If the same agent writes a change and also reports that the change works, you only have the agent's word for it.

The factory keeps the writing and the checking apart in the following ways:

- The agent works in a sandbox, which is an isolated environment that only lets the agent change the files it's responsible for.
- A separate process runs the checks and signs the results with a private key that the agent never sees.
- The release gate is a program that reads the signed results and allows a release only when every required check has passed.

## The example chat parsing engine

The example engine reads chat messages from the clients of a trading desk and turns each request into a request for quote (RFQ) for the desk's traders. For example, a client might send `px on 25mm 10s bid`, which asks for a price on 25 million of the 10-year US Treasury note.

After the engine sends an RFQ to the traders, it posts an update in the chat when a trader picks up the RFQ. Clients can also change or cancel a request in later messages.

Each desk is described by a configuration file called a profile. The profile says which chat rooms the desk listens to and where the results go, and it also says how to read the desk's slang. Most of a desk's behaviour lives in its profile, so adding a desk is mostly a configuration change. The factory checks a profile change with the same release process that it uses for a change to the engine code.

The repository includes the following example desks:

- `ust-rfq-nyc`, a New York desk that trades US Treasuries.
- `gilt-rfq-ldn`, a London desk that trades UK government bonds, which are called gilts.

## How a change is released

A change to a desk is called a behaviour release, and every behaviour release goes through the steps below in order.

First, a product owner describes what the desk should do in `intent.md` and lists the requirements in `spec.yaml`. An approver then records the exact versions of both files, so if either file changes later, the approval no longer applies.

Second, the compiler combines the approved requirements, the profile and the desk's test data into one release package. The package also records a hash of every engine file that the desk uses. A hash is a short code that is computed from the contents of a file, and it changes whenever the contents change.

Third, a separate worker process runs every required check against the package. The next section describes the checks.

Fourth, the runner signs the results with a private key. The signature proves that the results came from the trusted runner and that nobody edited them afterwards.

Fifth, the gate reads the signed results and gives one of the following answers:

- PASS means that every required check ran and passed.
- FAIL means that a check failed, or that the evidence was edited, out-of-date or not approved.
- INCONCLUSIVE means that something required wasn't shown to be true, e.g., because a check never ran.

Only PASS allows a release. Some changes also need a named person to approve the exact release, e.g., a change to shared engine code, or a desk that starts to listen to new chat rooms.

Sixth, activation runs the gate again and stores the release so that nobody can change it. Activation then switches the live version, and the switch only succeeds if nobody else changed the live version in the meantime.

You can run a new release in shadow mode before it goes live. In shadow mode, the release processes real messages, but its output never reaches the traders. If a live release causes problems, rollback stops anyone from using the release again. Rollback can't unsend messages, so it lists the messages that the release has already sent.

## What the checks look for

The checks look for mistakes that ordinary unit tests often miss, e.g., a message that is sent twice after a crash.

- Checks on the release package
  - The profile is valid, and its components fit together. The profile only sends messages to destinations that the desk is allowed to use.
  - A new desk can't pick up messages that belong to another desk.
- Checks that run the engine
  - Scripted conversations, called scenarios, must produce exactly the expected results.
  - Fault exploration generates many unusual sequences of events, e.g., duplicate messages, crashes, late replies from traders and release switches in the middle of a conversation. If any sequence breaks a business rule, the checker reduces the sequence to the smallest failing example and reports it.
- Checks on accuracy and on the tests themselves
  - The labelled example messages are scored separately for each category, e.g., ordinary requests, unclear messages and messages meant for other desks. The accuracy in each category must reach a minimum that is set in the policy, and the riskiest categories must never produce a wrong or extra RFQ.
  - The new version is compared with the live version on the same messages, and the check fails if any category gets worse by a statistically significant amount.
  - Mutation testing deliberately breaks the engine in realistic ways and confirms that the tests catch every break.

## Business rules the engine must follow

The checker tests every run of the engine against the business rules in the table below. When a run breaks a rule, the gate reports the rule's ID.

| ID | Rule |
|---|---|
| I1 | The engine never sends the same message to the traders or to the chat more than once. |
| I2 | A cancelled RFQ is never reactivated, even when a trader's reply arrives late. |
| I3 | The original text of a client's message is never changed. |
| I4 | Messages only go to destinations that the desk is allowed to use. |
| I6 | No client message is lost after a crash. |
| I7 | Every outgoing message has the fields that its receiver needs. |
| I8 | A conversation stays on the same release until all of its RFQs are closed. |

## Repository layout

| Folder | What it contains | Who changes it |
|---|---|---|
| `runtime/` | The example chat parsing engine | Builders, who can be people or agents |
| `behaviours/` | One folder for each desk, with its intent, requirements, profile, scenarios and example messages | Builders, but the requirements need approval |
| `factory/` | The compiler, the checks, the gate and the release tools | Maintainers only |
| `policy/` | The rules that the gate enforces, e.g., allowed destinations and accuracy minimums | Approvers only |
| `sandbox/` | The sandbox settings for AI coding agents | Builders can propose changes |
| `.claude/` | The Claude Code hooks and the writing style for the repository | Maintainers only |
| `examples/` | Sample chat traffic, a Jira snapshot and a CI template | Anyone |

When you run the tools, they create the following folders, which git ignores:

- `trust/` holds the signing key and the approvals.
- `state/` holds the release history.
- `build/` holds the compiled packages and the check results.

## Quick start

You need Python 3.14 and [uv](https://docs.astral.sh/uv/). The sandbox check also needs `openshell-prover`, which you can download from the [OpenShell releases page](https://github.com/NVIDIA/OpenShell/releases) and put on your `PATH` or in `.tools/bin/`.

```bash
F="uv run python -m factory"

# Create a signing key and record the current policy. An approver normally runs the command.
$F trust-init

# Approve the requirements of both example desks.
$F approve-spec ust-rfq-nyc --by product-owner
$F approve-spec gilt-rfq-ldn --by product-owner

# Compile, check and gate the US Treasury desk, and then release it.
$F compile ust-rfq-nyc
$F evidence ust-rfq-nyc
$F gate ust-rfq-nyc
$F activate ust-rfq-nyc --mode live --by release-bot

# Run the gilt desk in shadow mode on sample chat traffic, and then release it.
$F compile gilt-rfq-ldn
$F evidence gilt-rfq-ldn
$F activate gilt-rfq-ldn --mode shadow --by release-bot
$F feed examples/feed-morning.jsonl --instance i1
$F shadow-report --instance i1
$F activate gilt-rfq-ldn --mode live --by release-bot

# Test the gate itself with 22 prepared cases. The test takes about 45 seconds.
$F qualify-gate
```

The table below lists other commands that you may need.

| Command | What it does |
|---|---|
| `context <desk>` | Prints a summary of a desk, with its requirements, their status and the engine code it shares with other desks |
| `impact --runtime-root <path>` | Lists the live releases that a change to the engine code affects |
| `explore <desk> --save` | Searches for a sequence of events that breaks a business rule, and saves it as a permanent test |
| `rollback <desk> --by <name>` | Returns a desk to its previous release |
| `jira-plan --actual examples/jira-snapshot.json` | Shows the Jira updates that follow from the current release state |
| `sandbox-check` | Proves that the agent's sandbox settings stay within the approved limits |

Run `uv run python -m factory --help` to see every command.

## Working with an AI coding agent

The agent should work inside an [OpenShell](https://github.com/NVIDIA/OpenShell) sandbox that uses the settings in `sandbox/builder-policy.yaml`. Inside the sandbox, the agent can edit `behaviours/` and `runtime/`, but it can't read the signing key, change the policy or reach outside systems such as Jira. The `sandbox-check` command uses the OpenShell policy prover to prove that the agent's settings stay within the limits in `policy/builder-boundary.yaml`, and only an approver can change the limits.

The Claude Code hooks in `.claude/settings.json` give the agent quick feedback. The hooks block edits to protected folders, and they stop the agent from reporting that it's finished while its latest changes are unchecked. An agent could get around the hooks, so the sandbox and the signing key are the controls that enforce the rules.

In a typical session, the agent works through the following steps:

1. Run `context <desk>` to see the desk's requirements and the engine code that it shares with other desks.
2. Edit the desk's files or the engine code.
3. Run `check <desk>` to run the same checks as the gate, without signing the results.
4. Run `explore <desk> --save` to search for sequences of events that break a business rule, and to save any that it finds as tests.

Signing, gating and release happen in protected CI, which the agent can't access.

## Using it with your own engine

1. Replace the example engine in `runtime/` with your own engine, or adapt the example. Your engine needs the following parts:
   - A list of components that says what data each component needs and what effects it may have.
   - A way to load approved releases.
   - A single place where the engine sends every outgoing message.
   - A database that keeps its data after a crash.
2. Describe each desk in its own folder under `behaviours/`, and list its allowed destinations in `policy/policy.yaml`.
3. Replace the deliberate faults in `factory/mutation.py` with faults that matter for your engine.
4. Before you let any change release automatically, add cases to `factory/adversarial.py` that repeat real defects from your engine's history. Then run `qualify-gate` and confirm that the gate rejects every one of them.

The CI template in `examples/ci/factory-gate.yml` shows how to run the gate on every pull request and in the merge queue of your own repository.

## What has been tested

- Both example desks pass every required check. For each desk, mutation testing adds ten realistic faults to the engine, and the tests catch all ten.
- `qualify-gate` passes all 22 of its cases, and each case expects a set answer from the gate.
  - Ten cases tamper with the evidence or the controls, e.g., with forged results, a deleted requirement, a lowered threshold or a wider sandbox.
  - Seven cases add a defect to a desk profile or to the engine, e.g., a message sent to the wrong desk, or a late reply that reactivates a cancelled RFQ.
  - Two cases make changes that need a person's approval.
  - Three cases are correct changes that the gate must pass, so that a gate that rejects everything fails the test.
- The full release process has been run from start to finish, including shadow mode, rollback and turning a failing sequence of events into a permanent test.
- On every push and pull request, CI compiles, checks and gates both desks. CI also runs the sandbox check, `qualify-gate` and a punctuation check for the writing style.

## Known limitations

- The example engine
  - The engine keeps its data in SQLite and writes outgoing messages to files. A production engine would use its own database and messaging systems.
  - The parser uses fixed rules instead of a language model. The factory can't yet evaluate a parser that uses a language model, because the answers of a language model can vary between runs.
  - Each category of example messages has 6 to 10 examples, which gives only weak statistical evidence. Add more examples before you rely on the accuracy minimums.
- Isolation of the checks
  - The worker runs as a separate process, without a full sandbox. Secrets are removed from its environment, but another process that runs as the same user could still read them. In production, run the worker inside a sandbox.
  - Any change to the code in `factory/` counts as a change to the checks. An approver must run `trust-init` again before the gate accepts new results.
- Connections to other systems
  - The Jira and Confluence connectors haven't been tested against live systems. The Jira update plan has only been checked against a saved snapshot.

## Writing style

All prose in the repository follows the plain-writing skill in [`.claude/skills/plain-writing/SKILL.md`](.claude/skills/plain-writing/SKILL.md). The prose includes the documentation, the code comments and docstrings, the command help and the messages that the tools print. Claude Code loads the skill automatically, and CI rejects dashes, middle dots and curly quotes, which rules 15 and 17 of the skill forbid.

## Licence

The project is released under the [MIT License](LICENSE). Every source file has a short licence tag, called an SPDX header, so that licence scanners can identify the licence.

Contributions are accepted under the same licence. You don't need to sign a separate agreement, but you do need to sign off your commits, as [CONTRIBUTING.md](CONTRIBUTING.md) explains.

The plain-writing skill is copied without changes from [docwriter-org/plain-writing-skill](https://github.com/docwriter-org/plain-writing-skill) at commit `f0d3630`. The skill is also under the MIT License, and its copyright notice is in [`.claude/skills/plain-writing/LICENSE`](.claude/skills/plain-writing/LICENSE).

The project installs the following packages from PyPI, and none of them are copied into the repository.

| Package | Licence |
|---|---|
| pydantic, pydantic-core, annotated-types, typing-inspection, PyYAML | MIT |
| typing-extensions | PSF-2.0 |
| sortedcontainers | Apache-2.0 |
| hypothesis | MPL-2.0 |

The MPL-2.0 licence only sets conditions on changes to the files of Hypothesis itself, so using Hypothesis as a dependency sets no conditions on your code.

The optional `openshell-prover` tool is under the Apache-2.0 licence. CI downloads the tool when it runs, and the project doesn't distribute it.

## Contributing and security

- [CONTRIBUTING.md](CONTRIBUTING.md) explains how to set up the project, sign off your commits, test your changes and follow the writing style.
- [SECURITY.md](SECURITY.md) explains how to report a vulnerability privately.
- [CHANGELOG.md](CHANGELOG.md) lists the changes in each release.
