# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Enrichment steps that every desk can use.

Every enrichment step takes text and returns text, so it can only produce the derived_text of the current message.
The steps can't reach raw_text.
"""

import re

_QUOTED = re.compile(r"^\s*>.*$", re.MULTILINE)
_SPACE = re.compile(r"\s+")
_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(mm|mio|mln|m|k|bn|yards?)\b")
_MULT = {"mm": 10**6, "mio": 10**6, "mln": 10**6, "m": 10**6, "k": 10**3, "bn": 10**9, "yard": 10**9, "yards": 10**9}


def strip_quoted_history(text: str) -> str:
    """Remove quoted lines, which start with ">", so the parser never reads the amounts in the history again."""
    return _QUOTED.sub("", text)


def normalise_whitespace(text: str) -> str:
    return _SPACE.sub(" ", text).strip().lower()


def expand_size_shorthand(text: str) -> str:
    """Turn amounts such as 25mm, 2.5m, 500k and 1bn into the sz= form, e.g., 25mm becomes sz=25000000."""
    return _SIZE.sub(lambda m: f"sz={round(float(m[1]) * _MULT[m[2]])}", text)
