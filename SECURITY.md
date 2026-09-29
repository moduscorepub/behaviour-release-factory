# Security policy

## How to report a vulnerability

Please report vulnerabilities privately with the [Report a vulnerability](https://github.com/moduscorepub/behaviour-release-factory/security/advisories/new) form on GitHub. Don't report a suspected vulnerability in a public issue, pull request or discussion.

Please include the following details in your report:

- The version or commit that you tested.
- The part of the project that is involved, e.g., the compiler, the worker, the gate or the release tools.
- The steps that reproduce the problem.
- What happened, and what you expected to happen.

We aim to reply within 5 working days, and we'll agree with you on a timetable for the fix and for its public disclosure. If you'd like to be credited, we'll name you in the published advisory.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## What counts as a vulnerability

The factory exists to stop unsafe changes from being released, so any way around its checks is a security problem. Apart from the usual problems, e.g., running unintended code or exposing secrets, please report any of the following problems privately:

- A way to get a PASS from the gate without the evidence that the policy requires, e.g., by forging or reusing results.
- A way for code under test to read the signing key or any other secret.
- Sandbox settings that `sandbox-check` accepts even though the settings allow more access than the approved limits.
- A way for a release that is rolled back, unapproved or incompatible to send messages.

The README lists some known limitations, e.g., the worker runs as a separate process without a full sandbox. If a limitation turns out to be weaker than the README describes, please report it privately.
