from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    msg_id: str  # stable transport identity (chat platform message id)
    conversation_id: str
    room: str
    sender_firm: str
    raw_text: str


@dataclass(frozen=True)
class Release:
    """A compiled behaviour as the engine sees it."""

    digest: str
    behaviour_id: str
    desk: str
    profile: dict
    permitted_destinations: frozenset[str]


@dataclass(frozen=True)
class Effect:
    effect_id: str  # derived from input identity, never from release version
    rfq_id: str
    kind: str
    destination: str
    payload: dict
    release_digest: str


class Crash(BaseException):
    """Injected process death (fault exploration only); deliberately not an Exception."""
