# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Turn the slang of the US Treasury desk, e.g., "10s" or "tens", into the instrument IDs in the reference data."""

import re

_ALIASES = (
    ("ust2y", r"2s|2y|2yr|twos"),
    ("ust5y", r"5s|5y|5yr|fives"),
    ("ust10y", r"10s|10y|10yr|tens"),
    ("ust30y", r"30s|30y|30yr|bonds|long bond"),
)


def ust_aliases(text: str) -> str:
    for token, alternatives in _ALIASES:
        text = re.sub(rf"\b(?:{alternatives})\b", token, text)
    return text
