"""Domain mutation testing: does the behaviour's suite reject plausible wrong implementations?

Mutants are business faults (lost idempotency, reactivated cancellations, inverted sides,
wrong instrument mapping), not arithmetic noise. A mutant applies only when its file is in
the behaviour's runtime closure. A mutant whose target text no longer exists is *stale*:
the obligation reports an error (fail-closed) instead of silently shrinking the suite.
"""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from factory import worker


@dataclass(frozen=True)
class Mutant:
    id: str
    path: str
    find: str
    replace: str
    fault: str


MUTANTS = (
    Mutant("late-ack-reactivates", "runtime/engine.py", 'elif row[0] != "PENDING_ACK":', 'elif row[0] == "ACTIVE":', "a late trader ack reactivates a cancelled RFQ"),
    Mutant("recovery-republishes", "runtime/engine.py", "SET state='UNKNOWN' WHERE state='IN_FLIGHT'", "SET state='PENDING' WHERE state='IN_FLIGHT'", "recovery blindly re-publishes effects of unknown outcome"),
    Mutant("raw-text-overwritten", "runtime/engine.py", "UPDATE inbox SET derived_text=?, behaviour_id=?", "UPDATE inbox SET raw_text=?, behaviour_id=?", "enrichment overwrites the preserved raw text"),
    Mutant(
        "transport-ack-before-commit", "runtime/engine.py", "        with self.db:\n            seen =",
        "        transport_ack(msg.msg_id)\n        with self.db:\n            seen =", "transport acked before durable processing (loss on crash)",
    ),
    Mutant("follow-up-targets-oldest", "runtime/engine.py", "ORDER BY seq DESC LIMIT 1", "ORDER BY seq ASC LIMIT 1", "amend/cancel applied to the oldest open RFQ"),
    Mutant("pin-dropped", "runtime/engine.py", "if self._latest_open(conversation_id, rel.behaviour_id):", "if False:", "in-flight conversations not pinned to their release"),
    Mutant("size-cap-bypassed", "runtime/decide.py", 'cfg["min_size"] <= size <= cfg["max_size"]', 'cfg["min_size"] <= size', "maximum size limit not enforced"),
    Mutant("side-inverted", "runtime/components/convert.py", '"side": d.side,', '"side": {"BID": "OFFER", "OFFER": "BID"}.get(d.side, d.side),', "outbound RFQ side inverted"),
    Mutant("quoted-history-kept", "runtime/components/common.py", 'return _QUOTED.sub("", text)', "return text", "quoted history re-read as a new request"),
    Mutant("gilt-32s-mismapped", "runtime/components/gilt.py", '("ukt-4.25-2032", "4.25", "32")', '("ukt-3.75-2038", "4.25", "32")', "2032 gilt slang mapped to the 2038 bond"),
    Mutant("ust-tens-mismapped", "runtime/components/ust.py", '("ust10y", r"10s|10y|10yr|tens")', '("ust30y", r"10s|10y|10yr|tens")', "10-year slang mapped to the 30-year"),
)


def run(pkg: dict, policy: dict, runtime_root: Path) -> dict:
    closure = pkg["manifest"]["runtime"]["files"]
    probe_policy = {**policy, "exploration": {"max_examples": policy["mutation"]["explore_examples"]}}
    probes = [f"scenario:{sid}" for sid in sorted(pkg["scenarios"])] + ["eval", "explore"]
    results = []
    for m in (m for m in MUTANTS if m.path in closure):
        source = (runtime_root / m.path).read_text()
        if source.count(m.find) != 1:
            results.append({"mutant": m.id, "fault": m.fault, "result": "stale"})
            continue
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(runtime_root / "runtime", Path(tmp) / "runtime")
            (Path(tmp) / m.path).write_text(source.replace(m.find, m.replace))
            records = worker.call(Path(tmp), {"mode": "obligations", "package": pkg, "policy": probe_policy, "others": [], "baseline": None, "obligations": probes})
        killed_by = [r["obligation"] for r in records if r["status"] != "passed"]
        results.append({"mutant": m.id, "fault": m.fault, "result": "killed" if killed_by else "survived", "killed_by": killed_by})
    status = "error" if any(r["result"] == "stale" for r in results) else "failed" if any(r["result"] == "survived" for r in results) else "passed"
    return {"status": status, "mutants": results}
