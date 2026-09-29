# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    msg_id: str  # The fixed ID that the chat platform gives the message.
    conversation_id: str
    room: str
    sender_firm: str
    raw_text: str


@dataclass(frozen=True)
class Release:
    """A compiled desk release, as the engine sees it."""

    digest: str
    behaviour_id: str
    desk: str
    profile: dict
    permitted_destinations: frozenset[str]


@dataclass(frozen=True)
class Effect:
    effect_id: str  # The ID comes from the incoming message, and never from the release.
    rfq_id: str
    kind: str
    destination: str
    payload: dict
    release_digest: str


class Crash(BaseException):
    """A crash that the lab causes during fault exploration.

    The class isn't a subclass of Exception, so ordinary error handling doesn't catch it.
    """
