# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Score the labelled example messages for each category separately, and never as a single overall score.

Each example is a whole conversation, so similar messages can't carry context from one example into another. For
each category, the check compares the lower bound of the Wilson confidence interval for accuracy with a minimum in
the protected policy. In the riskiest categories, any wrong or extra RFQ fails the check. The check also compares
the new version with the live version on the same examples, using an exact sign test (McNemar's test), so gains in
easy categories can't hide a drop in a risky one.
"""

import math

from factory.lab import RFQ_KINDS, Harness, StaticReleases


def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def paired_regression_p(worse: int, better: int) -> float:
    """Return the one-sided p-value of McNemar's exact test, i.e., P(X >= worse) for n = worse + better and p = 1/2."""
    n = worse + better
    return 1.0 if n == 0 else sum(math.comb(n, i) for i in range(worse, n + 1)) / 2**n


def score_item(release, contracts: dict, item: dict) -> dict:
    h = Harness(StaticReleases([release]), contracts)
    events = [{"chat": f"{item['id']}-{i}", "conv": item["id"], "text": text} for i, text in enumerate(item["messages"])]
    h.run(events, item["room"], item["firm"])
    seen, actual = set(), []
    for e in h.sink:
        if e.kind in RFQ_KINDS and (e.kind, e.rfq_id) not in seen:
            seen.add((e.kind, e.rfq_id))
            actual.append({"kind": e.kind, **{k: e.payload.get(k) for k in ("side", "instrument", "size")}})
    expected = item["expect"]
    matches = [not (exp.items() - act.items()) for exp, act in zip(expected, actual)]
    correct = len(actual) == len(expected) and all(matches)
    harmful = len(actual) > len(expected) or not all(matches)  # A wrong or extra RFQ is harmful, but a missing RFQ isn't.
    return {"id": item["id"], "correct": correct, "harmful": harmful, "actual": actual}


def evaluate(candidate, baseline, contracts: dict, corpus: list[dict], policy: dict) -> dict:
    cand = {item["id"]: score_item(candidate, contracts, item) for item in corpus}
    base = {item["id"]: score_item(baseline, contracts, item) for item in corpus} if baseline else {}
    slices, failures = {}, []
    for name in sorted({item["slice"] for item in corpus}):
        items = [item for item in corpus if item["slice"] == name]
        n = len(items)
        k = sum(cand[i["id"]]["correct"] for i in items)
        harmful = [i["id"] for i in items if cand[i["id"]]["harmful"]]
        floor = policy["slice_floors"].get(name, policy["min_wilson_lower"])
        s = {"n": n, "correct": k, "wilson_lower": round(wilson_lower(k, n), 4), "floor": floor, "harmful": harmful}
        if s["wilson_lower"] < floor:
            failures.append(f"slice {name}: the Wilson lower bound {s['wilson_lower']} is below the minimum {floor} ({k} of {n} correct)")
        if harmful and name in policy["zero_harm_slices"]:
            failures.append(f"slice {name}: wrong or extra RFQs for {harmful}")
        if base:
            worse = sum(base[i["id"]]["correct"] and not cand[i["id"]]["correct"] for i in items)
            better = sum(cand[i["id"]]["correct"] and not base[i["id"]]["correct"] for i in items)
            s |= {"vs_baseline": {"worse": worse, "better": better, "p": round(paired_regression_p(worse, better), 4)}}
            if worse and s["vs_baseline"]["p"] < policy["paired_alpha"]:
                failures.append(f"slice {name}: significantly worse than the live release ({worse} worse, {better} better, p={s['vs_baseline']['p']})")
        slices[name] = s
    emitting = [i for i in corpus if i["expect"]]
    automation = sum(cand[i["id"]]["correct"] for i in emitting) / len(emitting) if emitting else 0.0
    wrong = {i: r["actual"] for i, r in cand.items() if not r["correct"]}
    return {"status": "failed" if failures else "passed", "failures": failures, "slices": slices, "automation_rate": round(automation, 4), "incorrect_items": wrong}
