# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub:
**[Report a vulnerability](https://github.com/moduscorepub/behaviour-release-factory/security/advisories/new)**.
Please do not open a public issue, pull request or discussion for a suspected vulnerability.

Include the affected version or commit, the component (compiler, worker, runner, gate, activation,
isolation), reproduction steps and the impact you observed.

We aim to acknowledge reports within 5 business days, agree a fix and disclosure timeline with you,
and credit you in the published advisory if you would like to be credited.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## What counts as a vulnerability here

This project is an assurance control, so in addition to conventional issues (code execution, secret
exposure, unsafe deserialisation) please report privately:

- any way to obtain a gate `PASS` without the evidence policy requires: gate bypass, evidence
  forgery, signature or digest confusion, stale evidence being accepted;
- candidate code in the worker reaching the runner key or any other `FACTORY_*` secret;
- a builder sandbox policy that `sandbox-check` accepts but that grants more access than the pinned
  boundary;
- activation, shadow or rollback paths that let a revoked, unapproved or incompatible release publish.

The limits listed in the README (for example, subprocess-level worker isolation) are known design
boundaries; reports showing that they are weaker than documented are welcome.
