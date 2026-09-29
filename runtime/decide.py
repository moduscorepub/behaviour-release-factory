# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Decide what a parsed message may cause.

The parser only proposes a result, and the code below always gives the same decision for the same input.
"""

from dataclasses import dataclass

from runtime.components.parse import Parsed
from runtime.refdata import UNIVERSES


@dataclass(frozen=True)
class Decision:
    kind: str  # One of rfq_new, rfq_amend, rfq_cancel or rfq_live.
    rfq_id: str
    side: str | None = None
    instrument: str | None = None
    size: int | None = None
    ccy: str | None = None


def _size_ok(size: int | None, cfg: dict) -> bool:
    return size is not None and cfg["min_size"] <= size <= cfg["max_size"]


def decide(p: Parsed, cfg: dict, msg_id: str, latest_open: Decision | None) -> Decision | str:
    """Return a Decision, or an outcome string that explains why the engine sends nothing."""
    if p.intent == "none":
        return "ignored"
    if p.ambiguity:
        return f"abstain:{p.ambiguity}"
    if p.intent in ("cancel", "amend") and latest_open is None:
        return "abstain:no_open_rfq"
    if p.intent == "cancel":
        return Decision("rfq_cancel", latest_open.rfq_id, latest_open.side, latest_open.instrument, latest_open.size, latest_open.ccy)
    if p.intent == "amend":
        if not _size_ok(p.size, cfg):
            return "abstain:size"
        return Decision("rfq_amend", latest_open.rfq_id, latest_open.side, latest_open.instrument, p.size, latest_open.ccy)
    universe = UNIVERSES[cfg["universe"]]
    if p.instrument not in universe:
        return "abstain:unknown_instrument"
    if p.side is None:
        return "abstain:no_side"
    if not _size_ok(p.size, cfg):
        return "abstain:size"
    return Decision("rfq_new", msg_id, p.side, p.instrument, p.size, universe[p.instrument])
