"""Component registry: each component declares its data contract and permitted effects.

Declarations are checked by the compiler; they are enforced structurally at runtime
(enrichment is str -> str, converters are pure, only the engine broker publishes).
Imports here are declaration edges: a component module executes only when a profile selects it.
"""

from dataclasses import dataclass
from typing import Callable

from runtime.components.common import expand_size_shorthand, normalise_whitespace, strip_quoted_history
from runtime.components.convert import chat_suggestion_v1, bus_rfq_v1
from runtime.components.gilt import gilt_aliases
from runtime.components.parse import rfq_parser_v1
from runtime.components.ust import ust_aliases


@dataclass(frozen=True)
class Component:
    name: str
    stage: str  # enrichment | parser | converter
    fn: Callable
    requires: frozenset[str] = frozenset()  # text properties needed ("{universe}" is substituted)
    provides: frozenset[str] = frozenset()
    effects: frozenset[str] = frozenset()
    handles: frozenset[str] = frozenset()  # converter: decision kinds
    contract: str | None = None  # converter: produced downstream contract
    fields: frozenset[str] = frozenset()  # converter: produced payload fields
    scheme: str | None = None  # converter: destination scheme


def _c(name, stage, fn, **kw) -> Component:
    return Component(name, stage, fn, **{k: frozenset(v) if isinstance(v, (set, list, tuple)) else v for k, v in kw.items()})


REGISTRY: dict[str, Component] = {
    c.name: c
    for c in (
        _c("strip_quoted_history", "enrichment", strip_quoted_history, provides={"unquoted"}, effects={"write:derived_text"}),
        _c("normalise_whitespace", "enrichment", normalise_whitespace, provides={"normalised"}, effects={"write:derived_text"}),
        _c("expand_size_shorthand", "enrichment", expand_size_shorthand, requires={"normalised"}, provides={"sizes"}, effects={"write:derived_text"}),
        _c("ust_aliases", "enrichment", ust_aliases, requires={"normalised"}, provides={"instruments:ust"}, effects={"write:derived_text"}),
        _c("gilt_aliases", "enrichment", gilt_aliases, requires={"normalised"}, provides={"instruments:gilts"}, effects={"write:derived_text"}),
        _c("rfq_parser_v1", "parser", rfq_parser_v1, requires={"unquoted", "normalised", "sizes", "instruments:{universe}"}, effects={"read:refdata"}),
        _c(
            "bus_rfq_v1", "converter", bus_rfq_v1, effects={"emit:payload"}, handles={"rfq_new", "rfq_amend", "rfq_cancel"},
            contract="rfq_event.v1", fields={"type", "rfq_id", "desk", "side", "instrument", "size", "ccy"}, scheme="bus",
        ),
        _c(
            "chat_suggestion_v1", "converter", chat_suggestion_v1, effects={"emit:payload"}, handles={"rfq_live"},
            contract="chat_suggestion.v1", fields={"rfq_id", "text"}, scheme="chat",
        ),
    )
}
