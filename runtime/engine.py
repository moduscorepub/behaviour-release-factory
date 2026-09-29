"""Chat -> RFQ engine with durable inbox/outbox and an explicit external-effect protocol.

Protocol (the properties the factory's lab challenges):
- input identity: inbox keyed by transport msg_id; duplicates are recorded, never reprocessed;
- the transport is acked only after the processing transaction commits;
- effect identity derives from the input (msg / trader ack), never from the release;
- effects go PENDING -> IN_FLIGHT -> SENT; after a crash IN_FLIGHT becomes UNKNOWN
  (published-but-unrecorded is indistinguishable from lost) and is never blindly retried;
- a conversation with open RFQs stays pinned to the release that opened them;
- a trader ack only activates a PENDING_ACK RFQ: late acks never reactivate a cancellation.
"""

import hashlib
import json
import re
import sqlite3
from typing import Callable, Protocol

from runtime.components import REGISTRY
from runtime.decide import Decision, decide
from runtime.model import ChatMessage, Crash, Effect, Release

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox(msg_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, room TEXT, sender_firm TEXT,
  raw_text TEXT NOT NULL, derived_text TEXT, behaviour_id TEXT, release_digest TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS attempts(seq INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, instance_id TEXT NOT NULL,
  release_digest TEXT, outcome TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rfqs(rfq_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, behaviour_id TEXT NOT NULL,
  state TEXT NOT NULL, side TEXT, instrument TEXT, size INTEGER, ccy TEXT, seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(effect_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, rfq_id TEXT NOT NULL, kind TEXT NOT NULL,
  destination TEXT NOT NULL, payload TEXT NOT NULL, release_digest TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pins(conversation_id TEXT NOT NULL, behaviour_id TEXT NOT NULL, release_digest TEXT NOT NULL,
  PRIMARY KEY(conversation_id, behaviour_id));
"""


class Releases(Protocol):
    def active(self) -> list[Release]: ...

    def get(self, digest: str) -> Release | None:  # None when unknown or revoked
        ...


def triggers(trigger: dict, msg: ChatMessage) -> bool:
    text = msg.raw_text.lower()
    return (
        msg.room in trigger["rooms"]
        and ("*" in trigger["sender_firms"] or msg.sender_firm in trigger["sender_firms"])
        and (not trigger["keywords_any"] or any(re.search(rf"\b{re.escape(k.lower())}\b", text) for k in trigger["keywords_any"]))
        and (trigger.get("pattern") is None or re.search(trigger["pattern"], text) is not None)
    )


class Engine:
    def __init__(self, db: sqlite3.Connection, releases: Releases, publish: Callable[[Effect], None], instance_id: str = "i0"):
        self.db, self.releases, self.publish, self.instance_id = db, releases, publish, instance_id
        self.crash_points: set[str] = set()  # fault injection hooks, empty in production
        db.executescript(SCHEMA)

    # ---- inbound -------------------------------------------------------------------------
    def on_chat(self, msg: ChatMessage, transport_ack: Callable[[str], None]) -> None:
        with self.db:
            seen = self.db.execute("SELECT 1 FROM inbox WHERE msg_id=?", (msg.msg_id,)).fetchone()
            if seen:
                self._attempt(msg.msg_id, None, "duplicate")
            else:
                self._process(msg)
        self._crash("before_transport_ack")
        transport_ack(msg.msg_id)
        self.dispatch()

    def on_trader_ack(self, rfq_id: str) -> None:
        source = f"ack:{rfq_id}"
        with self.db:
            row = self.db.execute(
                "SELECT state, conversation_id, behaviour_id, side, instrument, size, ccy FROM rfqs WHERE rfq_id=?", (rfq_id,)
            ).fetchone()
            if row is None:
                self._attempt(source, None, "ack_unknown_rfq")
            elif row[0] != "PENDING_ACK":
                self._attempt(source, None, f"ack_ignored:{row[0]}")
            else:
                rel = self._release_for(row[1], row[2])
                self.db.execute("UPDATE rfqs SET state='ACTIVE' WHERE rfq_id=?", (rfq_id,))
                if rel is not None:
                    self._emit(rel, source, Decision("rfq_live", rfq_id, *row[3:]))
                self._attempt(source, rel.digest if rel else None, "rfq_live" if rel else "ack_no_release")
        self.dispatch()

    # ---- processing ----------------------------------------------------------------------
    def _process(self, msg: ChatMessage) -> None:
        self.db.execute(
            "INSERT INTO inbox(msg_id, conversation_id, room, sender_firm, raw_text) VALUES (?,?,?,?,?)",
            (msg.msg_id, msg.conversation_id, msg.room, msg.sender_firm, msg.raw_text),
        )
        self._crash("mid_process")
        rel = self._route(msg)
        if isinstance(rel, str):
            self.db.execute("UPDATE inbox SET outcome=? WHERE msg_id=?", (rel, msg.msg_id))
            self._attempt(msg.msg_id, None, rel)
            return
        cfg = rel.profile
        try:  # recovery boundary: a faulty component quarantines this message instead of wedging redelivery
            derived = msg.raw_text
            for name in cfg["enrichment"]:
                derived = REGISTRY[name].fn(derived)
            self.db.execute("UPDATE inbox SET derived_text=?, behaviour_id=? WHERE msg_id=?", (derived, rel.behaviour_id, msg.msg_id))
            parsed = REGISTRY[cfg["parser"]["component"]].fn(derived, cfg["parser"]["universe"])
            result = decide(parsed, cfg["parser"], msg.msg_id, self._latest_open(msg.conversation_id, rel.behaviour_id))
        except Exception as e:  # message recorded with a classified outcome; details stay out of outputs
            result = f"error:{type(e).__name__}"
        if isinstance(result, Decision):
            self._apply(rel, msg.conversation_id, result)
            self._emit(rel, msg.msg_id, result)
            outcome = result.kind
        else:
            outcome = result
        self.db.execute("UPDATE inbox SET release_digest=?, outcome=? WHERE msg_id=?", (rel.digest, outcome, msg.msg_id))
        self._attempt(msg.msg_id, rel.digest, outcome)
        self._repin(msg.conversation_id, rel)

    def _route(self, msg: ChatMessage) -> Release | str:
        candidates = [self._release_for(msg.conversation_id, r.behaviour_id) or r for r in self.releases.active()]
        affine = [r for r in candidates if self._latest_open(msg.conversation_id, r.behaviour_id)]
        matched = affine or [r for r in candidates if triggers(r.profile["trigger"], msg)]
        if not matched:
            return "unrouted"
        if len(matched) > 1:
            return "quarantined:" + ",".join(sorted(r.behaviour_id for r in matched))
        return matched[0]

    def _release_for(self, conversation_id: str, behaviour_id: str) -> Release | None:
        pin = self.db.execute(
            "SELECT release_digest FROM pins WHERE conversation_id=? AND behaviour_id=?", (conversation_id, behaviour_id)
        ).fetchone()
        pinned = self.releases.get(pin[0]) if pin else None
        return pinned or next((r for r in self.releases.active() if r.behaviour_id == behaviour_id), None)

    def _repin(self, conversation_id: str, rel: Release) -> None:
        """Pin while RFQs are open; adopt newer releases only at the no-open-RFQ boundary."""
        if self._latest_open(conversation_id, rel.behaviour_id):
            self.db.execute("INSERT OR IGNORE INTO pins VALUES (?,?,?)", (conversation_id, rel.behaviour_id, rel.digest))
        else:
            self.db.execute("DELETE FROM pins WHERE conversation_id=? AND behaviour_id=?", (conversation_id, rel.behaviour_id))

    def _latest_open(self, conversation_id: str, behaviour_id: str) -> Decision | None:
        row = self.db.execute(
            "SELECT rfq_id, side, instrument, size, ccy FROM rfqs WHERE conversation_id=? AND behaviour_id=? "
            "AND state IN ('PENDING_ACK','ACTIVE') ORDER BY seq DESC LIMIT 1",
            (conversation_id, behaviour_id),
        ).fetchone()
        return Decision("open", *row) if row else None

    def _apply(self, rel: Release, conversation_id: str, d: Decision) -> None:
        if d.kind == "rfq_new":
            self.db.execute(
                "INSERT INTO rfqs VALUES (?,?,?,'PENDING_ACK',?,?,?,?,(SELECT COALESCE(MAX(seq),0)+1 FROM rfqs))",
                (d.rfq_id, conversation_id, rel.behaviour_id, d.side, d.instrument, d.size, d.ccy),
            )
        elif d.kind == "rfq_amend":
            self.db.execute("UPDATE rfqs SET size=? WHERE rfq_id=?", (d.size, d.rfq_id))
        elif d.kind == "rfq_cancel":
            self.db.execute("UPDATE rfqs SET state='CANCELLED' WHERE rfq_id=?", (d.rfq_id,))

    def _emit(self, rel: Release, source_id: str, d: Decision) -> None:
        for out in rel.profile["outputs"]:
            component = REGISTRY[out["component"]]
            if d.kind not in component.handles:
                continue
            effect_id = hashlib.sha256(f"{source_id}|{d.kind}|{out['destination']}".encode()).hexdigest()[:24]
            self.db.execute(
                "INSERT OR IGNORE INTO outbox VALUES (?,(SELECT COALESCE(MAX(seq),0)+1 FROM outbox),?,?,?,?,?,'PENDING')",
                (effect_id, d.rfq_id, d.kind, out["destination"], json.dumps(component.fn(d, rel.desk)), rel.digest),
            )

    def _attempt(self, source_id: str, release_digest: str | None, outcome: str) -> None:
        self.db.execute(
            "INSERT INTO attempts(source_id, instance_id, release_digest, outcome) VALUES (?,?,?,?)",
            (source_id, self.instance_id, release_digest, outcome),
        )

    # ---- outbound ------------------------------------------------------------------------
    def dispatch(self) -> None:
        """Publish PENDING effects through the capability check (release-permitted destinations only)."""
        while row := self.db.execute(
            "SELECT effect_id, rfq_id, kind, destination, payload, release_digest FROM outbox WHERE state='PENDING' ORDER BY seq LIMIT 1"
        ).fetchone():
            effect = Effect(row[0], row[1], row[2], row[3], json.loads(row[4]), row[5])
            rel = self.releases.get(effect.release_digest)
            if rel is None or effect.destination not in rel.permitted_destinations:
                with self.db:
                    self.db.execute("UPDATE outbox SET state='REJECTED' WHERE effect_id=?", (effect.effect_id,))
                continue
            with self.db:
                self.db.execute("UPDATE outbox SET state='IN_FLIGHT' WHERE effect_id=?", (effect.effect_id,))
            self.publish(effect)
            self._crash("after_publish")
            with self.db:
                self.db.execute("UPDATE outbox SET state='SENT' WHERE effect_id=?", (effect.effect_id,))

    def recover(self) -> None:
        """Startup after a crash: never blindly re-publish an effect whose outcome is unknown."""
        with self.db:
            self.db.execute("UPDATE outbox SET state='UNKNOWN' WHERE state='IN_FLIGHT'")
        self.dispatch()

    def _crash(self, point: str) -> None:
        if point in self.crash_points:
            self.crash_points.discard(point)
            raise Crash(point)
