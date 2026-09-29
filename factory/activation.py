# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Store releases and activate them in a controlled way.

The example uses SQLite as the configuration store of the engine, and nobody can change a
release after it's stored. A single row for each desk and mode points at the active release.
The row only changes if its generation number still has the value that the caller read, so
two people can't overwrite each other's switch. Each engine instance also records the
releases that it loaded.

A rollback revokes a release and stops its future use. The rollback can't take back the
messages that the release already sent, so it lists them for the team to correct.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from factory.canon import Workspace, load_json, sha

SCHEMA = """
CREATE TABLE IF NOT EXISTS releases(digest TEXT PRIMARY KEY, behaviour_id TEXT NOT NULL, package TEXT NOT NULL,
  evidence TEXT NOT NULL, gate TEXT NOT NULL, stored_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pointers(behaviour_id TEXT NOT NULL, mode TEXT NOT NULL, digest TEXT NOT NULL,
  generation INTEGER NOT NULL, PRIMARY KEY(behaviour_id, mode));
CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY AUTOINCREMENT, behaviour_id TEXT NOT NULL, mode TEXT NOT NULL,
  generation INTEGER NOT NULL, digest TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS adoption(instance_id TEXT NOT NULL, behaviour_id TEXT NOT NULL, mode TEXT NOT NULL, digest TEXT NOT NULL,
  generation INTEGER NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(instance_id, behaviour_id, mode));
CREATE TABLE IF NOT EXISTS gate_log(seq INTEGER PRIMARY KEY AUTOINCREMENT, behaviour_id TEXT NOT NULL, candidate_digest TEXT NOT NULL,
  outcome TEXT NOT NULL, decision TEXT NOT NULL, at TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Conflict(Exception):
    """Someone else switched the active release after the caller read the generation number."""


class Refused(Exception):
    def __init__(self, decision: dict):
        super().__init__(f"the gate answered {decision['outcome']}")
        self.decision = decision


class Store:
    def __init__(self, ws: Workspace):
        ws.state.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(ws.state / "factory.db")
        self.db.executescript(SCHEMA)

    def pointer(self, behaviour: str, mode: str) -> tuple[str, int] | None:
        """Return the digest and the generation number. An empty digest means that the desk was switched off on purpose."""
        row = self.db.execute("SELECT digest, generation FROM pointers WHERE behaviour_id=? AND mode=?", (behaviour, mode)).fetchone()
        return (row[0], row[1]) if row else None

    def pointers(self, mode: str) -> list[tuple[str, str, int]]:
        return list(self.db.execute("SELECT behaviour_id, digest, generation FROM pointers WHERE mode=? AND digest != '' ORDER BY behaviour_id", (mode,)))

    def release(self, digest: str) -> tuple[dict, bool] | None:
        row = self.db.execute("SELECT package, revoked FROM releases WHERE digest=?", (digest,)).fetchone()
        return (json.loads(row[0]), bool(row[1])) if row else None

    def live_package(self, behaviour: str) -> dict | None:
        ptr = self.pointer(behaviour, "live")
        return self.release(ptr[0])[0] if ptr and ptr[0] else None

    def active_packages(self) -> list[dict]:
        digests = {d for mode in ("live", "shadow") for _, d, _ in self.pointers(mode)}
        return [self.release(d)[0] for d in sorted(digests)]

    def put_release(self, digest: str, pkg: dict, evidence: dict, gate: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO releases(digest, behaviour_id, package, evidence, gate, stored_at) VALUES (?,?,?,?,?,?)",
                (digest, pkg["behaviour_id"], json.dumps(pkg), json.dumps(evidence), json.dumps(gate), now()),
            )

    def cas(self, behaviour: str, mode: str, digest: str, expected_generation: int, action: str, actor: str) -> int:
        with self.db:
            if expected_generation == 0:
                try:
                    self.db.execute("INSERT INTO pointers VALUES (?,?,?,1)", (behaviour, mode, digest))
                except sqlite3.IntegrityError:
                    raise Conflict(f"someone else activated {behaviour}/{mode} at the same time") from None
            elif self.db.execute(
                "UPDATE pointers SET digest=?, generation=generation+1 WHERE behaviour_id=? AND mode=? AND generation=?",
                (digest, behaviour, mode, expected_generation),
            ).rowcount != 1:
                raise Conflict(f"{behaviour}/{mode} has moved past generation {expected_generation}, because someone else switched it")
            generation = expected_generation + 1
            self.db.execute("INSERT INTO history(behaviour_id, mode, generation, digest, action, actor, at) VALUES (?,?,?,?,?,?,?)",
                            (behaviour, mode, generation, digest, action, actor, now()))
        return generation

    def record_adoption(self, instance: str, behaviour: str, mode: str, digest: str, generation: int, status: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO adoption VALUES (?,?,?,?,?,?,?)", (instance, behaviour, mode, digest, generation, status, now()))

    def log_gate(self, behaviour: str, decision: dict) -> None:
        with self.db:
            self.db.execute("INSERT INTO gate_log(behaviour_id, candidate_digest, outcome, decision, at) VALUES (?,?,?,?,?)",
                            (behaviour, decision["candidate_digest"], decision["outcome"], json.dumps(decision), now()))

    def last_gate(self, behaviour: str) -> dict | None:
        row = self.db.execute("SELECT decision FROM gate_log WHERE behaviour_id=? ORDER BY seq DESC LIMIT 1", (behaviour,)).fetchone()
        return json.loads(row[0]) if row else None


# Activation and rollback of releases.
def activate(ws: Workspace, behaviour: str, mode: str, actor: str, expect_generation: int | None = None) -> dict:
    from factory import gate  # Activation runs the gate again, because it doesn't trust a stored decision.

    store = Store(ws)
    decision = gate.evaluate(ws, behaviour, store)
    if decision["outcome"] != "PASS":
        raise Refused(decision)
    pkg, evidence = load_json(ws.package_path(behaviour)), load_json(ws.evidence_path(behaviour))
    digest = decision["candidate_digest"]
    store.put_release(digest, pkg, evidence, decision)
    current = store.pointer(behaviour, mode)
    expected = expect_generation if expect_generation is not None else (current[1] if current else 0)
    generation = store.cas(behaviour, mode, digest, expected, "activate", actor)
    shadow = store.pointer(behaviour, "shadow")
    if mode == "live" and shadow and shadow[0] == digest:
        store.cas(behaviour, "shadow", "", shadow[1], "promoted", actor)
    return {"behaviour": behaviour, "mode": mode, "digest": digest, "generation": generation, "change_class": decision["change_class"]}


def rollback(ws: Workspace, behaviour: str, actor: str) -> dict:
    store = Store(ws)
    current = store.pointer(behaviour, "live")
    if not current or not current[0]:
        raise ValueError(f"{behaviour} has no live release")
    bad, generation = current
    previous = store.db.execute(
        "SELECT h.digest FROM history h JOIN releases r ON r.digest = h.digest WHERE h.behaviour_id=? AND h.mode='live' "
        "AND h.action='activate' AND h.digest != ? AND r.revoked = 0 ORDER BY h.seq DESC LIMIT 1",
        (behaviour, bad),
    ).fetchone()
    target = previous[0] if previous else ""
    new_generation = store.cas(behaviour, "live", target, generation, "rollback", actor)
    with store.db:
        store.db.execute("UPDATE releases SET revoked=1 WHERE digest=?", (bad,))
    published, pinned = [], []
    for path in sorted(ws.state.glob("runtime-*.db")):
        if path.name.endswith("-shadow.db"):
            continue
        rt = sqlite3.connect(path)
        published += [dict(zip(("instance", "effect_id", "kind", "rfq_id", "destination", "state"), (path.stem.removeprefix("runtime-"), *r)))
                      for r in rt.execute("SELECT effect_id, kind, rfq_id, destination, state FROM outbox WHERE release_digest=? AND state IN ('SENT','UNKNOWN')", (bad,))]
        pinned += [c for (c,) in rt.execute("SELECT conversation_id FROM pins WHERE release_digest=?", (bad,))]
    return {
        "behaviour": behaviour, "revoked": bad, "now_live": target or None, "generation": new_generation,
        "published_not_retracted": published,
        "pinned_conversations_moved_to_active": pinned,
        "note": "The rollback only stops future use of the release. It didn't take back the messages listed above, so correct them in the receiving systems where you can.",
    }


# Loading releases into engine instances.
def compatible(pkg: dict, runtime_root: Path) -> list[str]:
    """Return the files whose deployed code differs from the code that the release was checked against."""
    return [f for f, d in pkg["manifest"]["runtime"]["files"].items() if not (runtime_root / f).exists() or sha((runtime_root / f).read_bytes()) != d]


class StoreReleases:
    """Give the engine its releases from the store.

    The class only loads a release if the deployed engine code matches the code that the release was checked against.
    """

    def __init__(self, store: Store, mode: str, runtime_root: Path, instance: str):
        from factory.lab import release_of

        self._release_of, self.store, self.runtime_root = release_of, store, runtime_root
        wanted = {b: (d, g, "live") for b, d, g in store.pointers("live")}
        if mode == "shadow":
            wanted |= {b: (d, g, "shadow") for b, d, g in store.pointers("shadow")}
        self._active, self._by_digest, self.packages = [], {}, []
        for behaviour, (digest, generation, source) in sorted(wanted.items()):
            pkg = store.release(digest)[0]
            drift = compatible(pkg, runtime_root)
            store.record_adoption(instance, behaviour, source, digest, generation, f"rejected, because the engine code differs in {drift}" if drift else "adopted")
            if not drift:
                rel = release_of(pkg, digest)
                self._active.append(rel)
                self._by_digest[digest] = rel
                self.packages.append(pkg)

    def active(self):
        return self._active

    def get(self, digest: str):
        if digest not in self._by_digest:
            found = self.store.release(digest)
            if found is None or found[1] or compatible(found[0], self.runtime_root):
                return None  # The engine never uses an unknown, revoked or incompatible release, so a conversation on the release moves to the active release.
            self._by_digest[digest] = self._release_of(found[0], digest)
        return self._by_digest[digest]


def feed(ws: Workspace, instance: str, events: list[dict]) -> dict:
    """Run the deployed engine over incoming chat events.

    Live releases write their messages to the outbound file. Shadow releases run in a separate engine, which can only write to the shadow file.
    """
    from factory.lab import Harness, contracts_of

    store = Store(ws)

    def sink(path: Path):
        def publish(effect):
            with path.open("a") as f:
                f.write(json.dumps({"effect_id": effect.effect_id, "kind": effect.kind, "destination": effect.destination,
                                    "rfq_id": effect.rfq_id, "payload": effect.payload, "release": effect.release_digest}) + "\n")
        return publish

    with store.db:  # The instance loads all of its releases again, so its old record of loaded releases is replaced.
        store.db.execute("DELETE FROM adoption WHERE instance_id=?", (instance,))
    runs = {}
    modes = ["live"] + (["shadow"] if store.pointers("shadow") else [])
    for mode in modes:
        suffix = "" if mode == "live" else "-shadow"
        src = StoreReleases(store, mode, ws.root, instance)
        h = Harness(src, contracts_of(src.packages), db=str(ws.state / f"runtime-{instance}{suffix}.db"),
                    publish=sink(ws.state / (f"outbound-{instance}.jsonl" if mode == "live" else f"shadow-{instance}.jsonl")), instance_id=instance)
        for ev in events:
            h.step(ev)
        runs[mode] = {"published": len(h.sink), "invariant_violations": h.final_checks()}
    adoption = [dict(zip(("behaviour", "mode", "digest", "generation", "status"), r))
                for r in store.db.execute("SELECT behaviour_id, mode, digest, generation, status FROM adoption WHERE instance_id=? ORDER BY behaviour_id, mode", (instance,))]
    return {"instance": instance, "adoption": adoption, **runs}


def shadow_report(ws: Workspace, instance: str) -> dict:
    live_db, shadow_db = ws.state / f"runtime-{instance}.db", ws.state / f"runtime-{instance}-shadow.db"
    if not shadow_db.exists():
        return {"instance": instance, "divergences": [], "note": "No shadow run has been recorded."}
    q = "SELECT msg_id, COALESCE(behaviour_id,'-') || ' ' || COALESCE(outcome,'-') FROM inbox"
    live, shadow = dict(sqlite3.connect(live_db).execute(q)), dict(sqlite3.connect(shadow_db).execute(q))
    divergences = [{"msg_id": m, "live": live.get(m), "shadow": shadow.get(m)} for m in sorted(live.keys() | shadow.keys()) if live.get(m) != shadow.get(m)]
    return {"instance": instance, "messages": len(live.keys() | shadow.keys()), "divergences": divergences}


def status(ws: Workspace) -> dict:
    store = Store(ws)
    pointers = {mode: [{"behaviour": b, "digest": d, "generation": g} for b, d, g in store.pointers(mode)] for mode in ("live", "shadow")}
    desired = {(p["behaviour"], mode): p for mode, ps in pointers.items() for p in ps}
    drift = []
    for inst, b, mode, d, g, st in store.db.execute("SELECT instance_id, behaviour_id, mode, digest, generation, status FROM adoption"):
        want = desired.get((b, mode))
        if want is None or want["digest"] != d or not st.startswith("adopted"):
            drift.append({"instance": inst, "behaviour": b, "mode": mode, "desired": want and want["digest"], "observed": d, "status": st})
    return {"pointers": pointers, "drift": drift}
