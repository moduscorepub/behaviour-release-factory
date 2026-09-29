# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Mutation testing, which checks that the tests of a desk catch realistic wrong versions of the engine.

Each mutant is a business fault, e.g., a swapped side, a wrong bond or a cancelled RFQ that becomes active again. A
mutant only applies when the desk runs the file that the mutant changes. If the text that a mutant looks for no
longer exists, the mutant is stale, and the check reports an error, so the set of mutants can't shrink without
anyone noticing.
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
    Mutant("late-ack-reactivates", "runtime/engine.py", 'elif row[0] != "PENDING_ACK":', 'elif row[0] == "ACTIVE":',
           "A late reply from a trader reactivates a cancelled RFQ."),
    Mutant("recovery-republishes", "runtime/engine.py", "SET state='UNKNOWN' WHERE state='IN_FLIGHT'", "SET state='PENDING' WHERE state='IN_FLIGHT'",
           "After a crash, recovery resends messages that may already have been sent."),
    Mutant("raw-text-overwritten", "runtime/engine.py", "UPDATE inbox SET derived_text=?, behaviour_id=?", "UPDATE inbox SET raw_text=?, behaviour_id=?",
           "Enrichment overwrites the original text of the message."),
    Mutant(
        "transport-ack-before-commit", "runtime/engine.py", "        with self.db:\n            seen =",
        "        transport_ack(msg.msg_id)\n        with self.db:\n            seen =", "The engine confirms a message before it saves it, so a crash loses the message.",
    ),
    Mutant("follow-up-targets-oldest", "runtime/engine.py", "ORDER BY seq DESC LIMIT 1", "ORDER BY seq ASC LIMIT 1",
           "A change or a cancellation applies to the oldest open RFQ."),
    Mutant("pin-dropped", "runtime/engine.py", "if self._latest_open(conversation_id, rel.behaviour_id):", "if False:",
           "Open conversations don't stay on their release."),
    Mutant("size-cap-bypassed", "runtime/decide.py", 'cfg["min_size"] <= size <= cfg["max_size"]', 'cfg["min_size"] <= size',
           "The engine doesn't enforce the maximum size."),
    Mutant("side-inverted", "runtime/components/convert.py", '"side": d.side,', '"side": {"BID": "OFFER", "OFFER": "BID"}.get(d.side, d.side),',
           "The outgoing RFQ has the opposite side."),
    Mutant("quoted-history-kept", "runtime/components/common.py", 'return _QUOTED.sub("", text)', "return text",
           "The engine reads quoted history as a new request."),
    Mutant("gilt-32s-mismapped", "runtime/components/gilt.py", '("ukt-4.25-2032", "4.25", "32")', '("ukt-3.75-2038", "4.25", "32")',
           "The engine reads the slang for the 2032 gilt as the 2038 bond."),
    Mutant("ust-tens-mismapped", "runtime/components/ust.py", '("ust10y", r"10s|10y|10yr|tens")', '("ust30y", r"10s|10y|10yr|tens")',
           "The engine reads the slang for the 10-year note as the 30-year bond."),
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
