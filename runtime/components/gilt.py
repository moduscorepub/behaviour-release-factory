# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Turn the slang of the UK gilt desk, e.g., "4¼s of 32", "ukt 32" or "38s", into instrument IDs."""

import re

_FRACTIONS = (("½", ".5"), ("¼", ".25"), ("¾", ".75"), (" 1/2", ".5"), (" 1/4", ".25"), (" 3/4", ".75"))
_GILTS = (("ukt-4.5-2028", "4.5", "28"), ("ukt-4.25-2032", "4.25", "32"), ("ukt-3.75-2038", "3.75", "38"))


def gilt_aliases(text: str) -> str:
    for fraction, decimal in _FRACTIONS:
        text = text.replace(fraction, decimal)
    for token, coupon, yy in _GILTS:
        c = re.escape(coupon)
        text = re.sub(rf"\b(?:ukt\s)?{c}s?\s(?:of\s)?(?:20)?{yy}s?\b", token, text)
        text = re.sub(rf"\b(?:ukt\s|gilt\s)?(?:20)?{yy}s\b|\bukt\s(?:20)?{yy}\b", token, text)
    return text
