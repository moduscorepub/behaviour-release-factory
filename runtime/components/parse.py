"""Rules-based RFQ parser over derived text (expects canonical sz= and instrument tokens)."""

import re
from dataclasses import dataclass

from runtime.refdata import UNIVERSES


@dataclass(frozen=True)
class Parsed:
    intent: str  # new | amend | cancel | none
    side: str | None = None
    instrument: str | None = None
    size: int | None = None
    ambiguity: str | None = None


_CANCEL = re.compile(r"\b(cxl|cancel|canx|nvm|never mind)\b")
_AMEND = re.compile(r"\b(make it|amend to|change to|actually)\b")
_SIZE = re.compile(r"\bsz=(\d+)\b")
_BID = re.compile(r"\b(bid|i sell|we sell)\b")
_OFFER = re.compile(r"\b(offer|offered|ask|i buy|we buy)\b")
_TWO_WAY = re.compile(r"\b(2 way|two way|2-way|two-way|px|price|level|lvl|market)\b")


def rfq_parser_v1(text: str, universe: str) -> Parsed:
    sizes = _SIZE.findall(text)
    size = int(sizes[0]) if len(sizes) == 1 else None
    ambiguity = "multiple_sizes" if len(sizes) > 1 else None
    if _CANCEL.search(text):
        return Parsed("cancel")
    instruments = sorted(i for i in UNIVERSES[universe] if i.lower() in text)
    if not instruments:
        return Parsed("amend", size=size, ambiguity=ambiguity) if _AMEND.search(text) else Parsed("none")
    if len(instruments) > 1:
        return Parsed("new", ambiguity="multiple_instruments")
    bid, offer = bool(_BID.search(text)), bool(_OFFER.search(text))
    if bid and offer:
        side = "TWO_WAY"
    elif bid or offer:
        side = "BID" if bid else "OFFER"
    else:
        side = "TWO_WAY" if _TWO_WAY.search(text) else None
    return Parsed("new", side=side, instrument=instruments[0], size=size, ambiguity=ambiguity)
