"""Scenario and counterexample laboratory (imports the candidate runtime; runs inside the worker).

The harness is a small digital twin of the transport and downstream sinks:
- at-least-once delivery: unacked messages are redelivered after a crash;
- a crash kills the engine; uncommitted work rolls back; a fresh engine recovers on the same store;
- a release switch activates a successor release mid-conversation (challenges pinning);
- every run is monitored for business invariants, not only scenario expectations.
"""

import dataclasses
import sqlite3

from hypothesis import HealthCheck, find, settings
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample

from runtime.components import REGISTRY
from runtime.engine import Engine
from runtime.model import ChatMessage, Crash, Effect, Release

RFQ_KINDS = ("rfq_new", "rfq_amend", "rfq_cancel")
FORBIDDEN_AFTER_CANCEL = ("rfq_new", "rfq_amend", "rfq_live")
CRASHES = (None, None, None, "mid_process", "before_transport_ack", "after_publish")
STEP_KINDS = ("new", "amend", "cancel", "ack", "redeliver", "switch")


class StaticReleases:
    """Fixed release set; switch() activates a successor (same profile, new identity) to challenge pinning."""

    def __init__(self, releases: list[Release]):
        self._active = list(releases)
        self._successor = [dataclasses.replace(r, digest=f"{r.digest}#successor") for r in releases]
        self._by_digest = {r.digest: r for r in self._active + self._successor}

    def active(self) -> list[Release]:
        return self._active

    def get(self, digest: str) -> Release | None:
        return self._by_digest.get(digest)

    def switch(self) -> None:
        self._active, self._successor = self._successor, self._active


def release_of(pkg: dict, digest: str) -> Release:
    p = pkg["profile"]
    return Release(digest, p["behaviour_id"], p["desk"], p, frozenset(pkg["manifest"]["permitted_destinations"]))


def contracts_of(pkgs: list[dict]) -> dict[str, list[str]]:
    """destination -> fields the downstream consumer contract requires."""
    out = {}
    for pkg in pkgs:
        for o in pkg["profile"]["outputs"]:
            c = REGISTRY.get(o["component"])
            if c is not None and c.contract in pkg["contracts"]:
                out[o["destination"]] = pkg["contracts"][c.contract]["required"]
    return out


class Harness:
    def __init__(self, releases, contracts: dict[str, list[str]], db: str = ":memory:", publish=None, instance_id: str = "lab"):
        self.releases, self.contracts, self.instance_id = releases, contracts, instance_id
        self.db = sqlite3.connect(db)
        self.sink: list[Effect] = []
        self._publish = publish
        self.delivered: dict[str, ChatMessage] = {}
        self.unacked: dict[str, ChatMessage] = {}
        self.cancelled_at: dict[str, int] = {}  # rfq_id -> sink length when cancellation was first observed
        self.violations: list[str] = []
        self.engine = self._engine()

    def _engine(self) -> Engine:
        return Engine(self.db, self.releases, self._record, self.instance_id)

    def _record(self, effect: Effect) -> None:
        self.sink.append(effect)
        if self._publish:
            self._publish(effect)

    def _transport_ack(self, msg_id: str) -> None:
        self.unacked.pop(msg_id, None)

    def step(self, ev: dict, room: str = "", firm: str = "") -> None:
        if ev.get("crash"):
            self.engine.crash_points.add(ev["crash"])
        try:
            if "chat" in ev:
                msg = ChatMessage(ev["chat"], ev.get("conv", "c1"), ev.get("room", room), ev.get("firm", firm), ev["text"])
                self.delivered.setdefault(msg.msg_id, msg)
                self.unacked[msg.msg_id] = msg
                self.engine.on_chat(msg, self._transport_ack)
            elif "trader_ack" in ev:
                self.engine.on_trader_ack(ev["trader_ack"])
            elif "redeliver" in ev and ev["redeliver"] in self.delivered:
                self.engine.on_chat(self.delivered[ev["redeliver"]], self._transport_ack)
            elif "switch" in ev:
                self.releases.switch()
        except Crash:
            self._restart()
        self.engine.crash_points.clear()
        self._observe()

    def _restart(self) -> None:
        self.engine = self._engine()
        self.engine.recover()
        for msg in list(self.unacked.values()):
            self.engine.on_chat(msg, self._transport_ack)

    def _observe(self) -> None:
        for rfq_id, state in self.db.execute("SELECT rfq_id, state FROM rfqs"):
            if rfq_id in self.cancelled_at and state != "CANCELLED":
                self._violate(f"I2 cancelled RFQ {rfq_id} reactivated to {state}")
            elif state == "CANCELLED":
                self.cancelled_at.setdefault(rfq_id, len(self.sink))
        for rfq_id, mark in self.cancelled_at.items():
            for e in self.sink[mark:]:
                if e.rfq_id == rfq_id and e.kind in FORBIDDEN_AFTER_CANCEL:
                    self._violate(f"I2 {e.kind} published for {rfq_id} after its cancellation")

    def _violate(self, text: str) -> None:
        if text not in self.violations:
            self.violations.append(text)

    def final_checks(self) -> list[str]:
        ids = [e.effect_id for e in self.sink]
        for eid in sorted({i for i in ids if ids.count(i) > 1}):
            e = next(x for x in self.sink if x.effect_id == eid)
            self._violate(f"I1 duplicate external effect: {e.kind} for {e.rfq_id} to {e.destination} published {ids.count(eid)}x")
        for rfq_id in sorted({e.rfq_id for e in self.sink}):
            if len({e.release_digest for e in self.sink if e.rfq_id == rfq_id}) > 1:
                self._violate(f"I8 effects for {rfq_id} came from more than one release (in-flight conversation not pinned)")
        stored = dict(self.db.execute("SELECT msg_id, raw_text FROM inbox"))
        for msg_id, msg in self.delivered.items():
            if msg_id not in stored:
                self._violate(f"I6 message {msg_id} was delivered but never durably recorded (silent loss)")
            elif stored[msg_id] != msg.raw_text:
                self._violate(f"I3 raw text of {msg_id} was modified")
        for e in self.sink:
            rel = self.releases.get(e.release_digest)
            if rel is None or e.destination not in rel.permitted_destinations:
                self._violate(f"I4 {e.kind} published to unpermitted destination {e.destination}")
            missing = [f for f in self.contracts.get(e.destination, []) if e.payload.get(f) is None]
            if missing:
                self._violate(f"I7 {e.kind} to {e.destination} violates consumer contract, missing {missing}")
        return self.violations

    def run(self, events: list[dict], room: str = "", firm: str = "") -> list[str]:
        for ev in events:
            self.step(ev, room, firm)
        return self.final_checks()

    def projected(self) -> list[dict]:
        return [{"kind": e.kind, "rfq_id": e.rfq_id, "destination": e.destination, **e.payload} for e in self.sink]


def run_scenario(releases: list[Release], contracts: dict, scenario: dict) -> list[str]:
    h = Harness(StaticReleases(releases), contracts)
    failures = list(h.run(scenario["events"], scenario.get("room", ""), scenario.get("firm", "")))
    expect = scenario.get("expect") or {}
    if "effects" in expect:
        actual = h.projected()
        if len(actual) != len(expect["effects"]) or any(e.items() - a.items() for e, a in zip(expect["effects"], actual)):
            shown = [{k: a[k] for k in ("kind", "rfq_id", "destination", "side", "instrument", "size") if k in a} for a in actual]
            failures.append(f"effects: expected {expect['effects']} got {shown}")
    for rfq_id, state in expect.get("rfq_states", {}).items():
        row = h.db.execute("SELECT state FROM rfqs WHERE rfq_id=?", (rfq_id,)).fetchone()
        if (row[0] if row else None) != state:
            failures.append(f"rfq {rfq_id}: expected {state} got {row[0] if row else None}")
    for msg_id, outcome in expect.get("outcomes", {}).items():
        row = h.db.execute("SELECT outcome FROM inbox WHERE msg_id=?", (msg_id,)).fetchone()
        if (row[0] if row else None) != outcome:
            failures.append(f"message {msg_id}: expected outcome {outcome} got {row[0] if row else None}")
    return failures


# ---- fault exploration ----------------------------------------------------------------------
STEP = st.tuples(st.sampled_from(STEP_KINDS), st.integers(0, 63), st.integers(0, 1), st.sampled_from(CRASHES))


def to_events(steps, pools: dict[str, list[str]]) -> list[dict]:
    events, chats, news = [], [], []
    for kind, idx, conv, crash in steps:
        if kind in ("new", "amend", "cancel"):
            if not pools.get(kind):
                continue
            msg_id = f"g{len(chats)}"
            ev = {"chat": msg_id, "conv": f"x{conv}", "text": pools[kind][idx % len(pools[kind])]}
            chats.append(msg_id)
            if kind == "new":
                news.append(msg_id)
        elif kind == "ack" and news:
            ev = {"trader_ack": news[idx % len(news)]}
        elif kind == "redeliver" and chats:
            ev = {"redeliver": chats[idx % len(chats)]}
        elif kind == "switch":
            ev = {"switch": True}
        else:
            continue
        if crash:
            ev["crash"] = crash
        events.append(ev)
    return events


def explore(releases: list[Release], contracts: dict, pools: dict, room: str, firm: str, max_examples: int) -> dict:
    """Search delivery/crash/ack/release-switch schedules for an invariant violation; return the shrunk counterexample."""

    def violated(steps) -> bool:
        return bool(Harness(StaticReleases(releases), contracts).run(to_events(steps, pools), room, firm))

    try:
        cex = find(
            st.lists(STEP, max_size=10),
            violated,
            settings=settings(max_examples=max_examples, database=None, derandomize=True, suppress_health_check=list(HealthCheck)),
        )
    except NoSuchExample:
        return {"status": "passed", "examples": max_examples}
    events = to_events(cex, pools)
    violations = Harness(StaticReleases(releases), contracts).run(events, room, firm)
    return {"status": "failed", "counterexample": {"room": room, "firm": firm, "events": events, "violations": violations}}
