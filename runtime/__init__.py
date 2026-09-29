# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""The example chat parsing engine, which the factory checks.

The engine has the following parts, which the factory needs:

- A list of components.
- Releases, which are compiled profiles.
- A single place where the engine sends every outgoing message.
- A database that keeps its data after a crash.

To check your own engine with the factory, give your engine the same parts.
"""
