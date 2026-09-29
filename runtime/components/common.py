# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Desk-agnostic enrichment. Every enrichment is str -> str: it can only produce
the current message's derived_text; raw_text is never reachable from here."""

import re

_QUOTED = re.compile(r"^\s*>.*$", re.MULTILINE)
_SPACE = re.compile(r"\s+")
_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(mm|mio|mln|m|k|bn|yards?)\b")
_MULT = {"mm": 10**6, "mio": 10**6, "mln": 10**6, "m": 10**6, "k": 10**3, "bn": 10**9, "yard": 10**9, "yards": 10**9}


def strip_quoted_history(text: str) -> str:
    """Drop quoted lines ("> ...") so amounts in history are never re-read."""
    return _QUOTED.sub("", text)


def normalise_whitespace(text: str) -> str:
    return _SPACE.sub(" ", text).strip().lower()


def expand_size_shorthand(text: str) -> str:
    """25mm / 2.5m / 500k / 1bn -> sz=<integer notional>."""
    return _SIZE.sub(lambda m: f"sz={round(float(m[1]) * _MULT[m[2]])}", text)
