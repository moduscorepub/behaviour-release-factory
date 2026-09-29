# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""The list of components, where each component declares the data that it needs and the effects that it may have.

An enrichment step prepares the text of a message before the parser reads it, and a converter turns a decision into
an outgoing message. The compiler checks the declarations, and the structure of the engine enforces them at runtime.
For example, an enrichment step only takes text and returns text, and a converter has no side effects. Moreover,
only the engine sends messages.

The imports below only declare the components, and the code of a component only runs when a profile selects it.
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
    stage: str  # One of enrichment, parser or converter.
    fn: Callable
    requires: frozenset[str] = frozenset()  # The text properties that the component needs. "{universe}" stands for the universe of the desk.
    provides: frozenset[str] = frozenset()
    effects: frozenset[str] = frozenset()
    handles: frozenset[str] = frozenset()  # For a converter, the kinds of decision that it handles.
    contract: str | None = None  # For a converter, the message format that it produces.
    fields: frozenset[str] = frozenset()  # For a converter, the fields that it produces.
    scheme: str | None = None  # For a converter, the type of destination, e.g., bus or chat.


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
