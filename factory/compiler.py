# SPDX-FileCopyrightText: 2026 The behaviour-release-factory contributors
# SPDX-License-Identifier: MIT

"""Compile a desk into a release package.

The compiler combines the approved requirements, the profile, the scenarios and the example
messages of a desk into one package, and it always gives the same result for the same input.
It checks that the components fit together and only have allowed effects. It also checks that
the desk can't pick up the messages of another desk, and it ties the package to the exact
engine code that it was compiled against.

The worker passes in the objects from the engine, e.g., the component list, the reference data
and the trigger matcher, so the trusted parent process never imports the code under test.
"""

import ast
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from factory.canon import digest, load_yaml, sha

FORMAT = "behaviour-release/1"
CORE_MODULES = ("runtime/engine.py",)
REGISTRY_MODULE = "runtime/components/__init__.py"
DYNAMIC = re.compile(rb"\bimportlib\b|__import__\(|\bexec\(|\beval\(")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Trigger(_Strict):
    rooms: list[str] = Field(min_length=1)
    sender_firms: list[str] = Field(min_length=1)  # ["*"] means any firm.
    keywords_any: list[str] = []
    pattern: str | None = None

    @model_validator(mode="after")
    def _pattern_compiles(self):
        if self.pattern is not None:
            re.compile(self.pattern)
        return self


class ParserConfig(_Strict):
    component: str
    universe: str
    min_size: int = Field(gt=0)
    max_size: int = Field(gt=0)

    @model_validator(mode="after")
    def _bounds(self):
        if self.min_size > self.max_size:
            raise ValueError("min_size is larger than max_size")
        return self


class Output(_Strict):
    component: str
    destination: str


class Profile(_Strict):
    behaviour_id: str
    desk: str
    trigger: Trigger
    enrichment: list[str]
    parser: ParserConfig
    outputs: list[Output] = Field(min_length=1)


class Source(_Strict):
    confluence_page_id: str
    page_version: int
    content_digest: str


class Requirement(_Strict):
    id: str
    statement: str
    criticality: Literal["critical", "standard"]
    verified_by: list[str] = Field(min_length=1)  # Each entry is scenario:<id>, eval:<slice>, explore or mutation.


class WorkItem(_Strict):
    id: str
    summary: str
    satisfies: list[str] = Field(min_length=1)
    jira_key: str | None = None


class Spec(_Strict):
    spec_id: str
    revision: int
    source: Source
    requirements: list[Requirement] = Field(min_length=1)
    work_items: list[WorkItem] = Field(min_length=1)


# Reading the files of a desk. The code only reads files, and it runs in the trusted parent process.
def read_behaviour(directory: Path) -> dict:
    scenario_dir = directory / "scenarios"
    return {
        "format": FORMAT,
        "behaviour_id": directory.name,
        "intent": (directory / "intent.md").read_text(),
        "spec": load_yaml(directory / "spec.yaml"),
        "profile": json.loads((directory / "profile.json").read_text()),
        "contracts": {p.stem: json.loads(p.read_text()) for p in sorted((directory / "contracts").glob("*.json"))},
        "scenarios": {s["id"]: s for s in (json.loads(p.read_text()) for p in sorted(scenario_dir.glob("*.json")) if p.name != "pools.json")},
        "pools": json.loads((scenario_dir / "pools.json").read_text()),
        "corpus": [json.loads(line) for line in (directory / "corpus.jsonl").read_text().splitlines() if line.strip()],
    }


def module_path(module: str, root: Path) -> str:
    rel = module.replace(".", "/")
    return f"{rel}/__init__.py" if (root / rel).is_dir() else f"{rel}.py"


def runtime_closure(root: Path, component_modules: list[str]) -> dict:
    """Hash every engine file that the desk can run, i.e., the files that the core engine imports and the selected components.

    The compiler doesn't follow the imports in the component list, because the imports there only declare components.
    If a file uses dynamic imports or exec, nobody can know which files it runs, so the impact check treats any engine
    change as a change that affects the desk.
    """
    todo = list(CORE_MODULES) + [module_path(m, root) for m in component_modules]
    files: dict[str, str] = {}
    dynamic = False
    while todo:
        rel = todo.pop()
        if rel in files:
            continue
        src = (root / rel).read_bytes()
        files[rel] = sha(src)
        dynamic |= bool(DYNAMIC.search(src))
        if rel == REGISTRY_MODULE:
            continue
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                continue
            todo += [module_path(n, root) for n in names if n == "runtime" or n.startswith("runtime.")]
    return {"files": dict(sorted(files.items())), "tree_digest": runtime_tree_digest(root), "dynamic_edges": dynamic}


def runtime_tree_digest(root: Path) -> str:
    return digest({str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted((root / "runtime").rglob("*.py"))})


def manifest(pkg: dict, root: Path, registry: dict, policy: dict) -> dict:
    profile = pkg["profile"]
    names = [*profile.get("enrichment", []), profile.get("parser", {}).get("component"), *(o.get("component") for o in profile.get("outputs", []))]
    modules = sorted({registry[n].fn.__module__ for n in names if n in registry})
    desk = policy["desks"].get(profile.get("desk"), {})
    return {
        "runtime": runtime_closure(root, modules),
        "components": {n: registry[n].fn.__module__ for n in names if n in registry},
        "permitted_destinations": sorted(desk.get("destinations", [])),
        "spec_digest": digest(pkg["spec"]),
    }


def package_digest(pkg: dict) -> str:
    return digest(pkg)


# Static checks. The worker runs them against the engine code under test.
def _errors(model, data) -> list[str]:
    try:
        model.model_validate(data)
        return []
    except ValidationError as e:
        return [f"{model.__name__}: {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
    except (re.error, ValueError) as e:  # A trigger pattern that doesn't compile raises one of the errors.
        return [f"{model.__name__}: {e}"]


def check_schema(pkg: dict) -> list[str]:
    errors = _errors(Spec, pkg["spec"]) + _errors(Profile, pkg["profile"])
    for sid, s in pkg["scenarios"].items():
        if not isinstance(s.get("events"), list) or not s["events"]:
            errors.append(f"scenario {sid} has no events")
    for i, item in enumerate(pkg["corpus"]):
        if not {"id", "slice", "room", "firm", "messages", "expect"} <= item.keys():
            errors.append(f"corpus[{i}] needs the fields id, slice, room, firm, messages and expect")
    return errors


def check_traceability(pkg: dict) -> list[str]:
    spec, errors = pkg["spec"], []
    if sha(pkg["intent"].encode()) != spec["source"]["content_digest"]:
        errors.append("intent.md doesn't match the hash of the approved Confluence page")
    if not (pkg["behaviour_id"] == spec["spec_id"] == pkg["profile"].get("behaviour_id")):
        errors.append("the folder name, spec_id and profile.behaviour_id aren't the same")
    req_ids = {r["id"] for r in spec["requirements"]}
    slices = {item["slice"] for item in pkg["corpus"]}
    for r in spec["requirements"]:
        for v in r["verified_by"]:
            kind, _, ref = v.partition(":")
            if (kind == "scenario" and ref not in pkg["scenarios"]) or (kind == "eval" and ref not in slices) or kind not in ("scenario", "eval", "explore", "mutation"):
                errors.append(f"{r['id']}: the check '{v}' doesn't exist")
        if r["criticality"] == "critical" and not any(v.startswith(("scenario:", "explore")) for v in r["verified_by"]):
            errors.append(f"{r['id']} is critical, so it needs a scenario or fault exploration among its checks")
    covered = {rid for w in spec["work_items"] for rid in w["satisfies"]}
    errors += [f"a work item refers to the unknown requirement {rid}" for rid in sorted(covered - req_ids)]
    errors += [f"{rid} isn't delivered by any work item" for rid in sorted(req_ids - covered)]
    for sid, s in pkg["scenarios"].items():
        errors += [f"scenario {sid} refers to the unknown requirement {rid}" for rid in s.get("requirements", []) if rid not in req_ids]
    return errors


def check_composition(pkg: dict, registry: dict, universes: dict) -> list[str]:
    p, errors = pkg["profile"], []
    have: set[str] = set()
    for name in p["enrichment"]:
        c = registry.get(name)
        if c is None or c.stage != "enrichment":
            errors.append(f"'{name}' isn't a registered enrichment component")
            continue
        errors += [f"'{name}' needs '{t}', but no earlier enrichment provides it" for t in sorted(c.requires - have)]
        have |= c.provides
    universe = p["parser"]["universe"]
    if universe not in universes:
        errors.append(f"the parser universe '{universe}' has no reference data")
    parser = registry.get(p["parser"]["component"])
    if parser is None or parser.stage != "parser":
        errors.append(f"'{p['parser']['component']}' isn't a registered parser")
    else:
        needed = {t.replace("{universe}", universe) for t in parser.requires}
        errors += [f"the parser needs '{t}', but no enrichment provides it" for t in sorted(needed - have)]
    for out in p["outputs"]:
        c = registry.get(out["component"])
        if c is None or c.stage != "converter":
            errors.append(f"'{out['component']}' isn't a registered converter")
            continue
        if not out["destination"].startswith(f"{c.scheme}:"):
            errors.append(f"'{out['component']}' produces {c.scheme} messages, but the output goes to '{out['destination']}'")
        contract = pkg["contracts"].get(c.contract)
        if contract is None:
            errors.append(f"'{out['component']}' produces the format '{c.contract}', but the package has no contract for the format")
        else:
            errors += [f"'{out['component']}' doesn't produce the field '{f}', which {c.contract} requires" for f in sorted(set(contract["required"]) - c.fields)]
    return errors


def check_effects(pkg: dict, registry: dict, policy: dict) -> list[str]:
    p, errors = pkg["profile"], []
    desk = policy["desks"].get(p["desk"])
    if desk is None:
        return [f"the policy doesn't list the desk '{p['desk']}'"]
    for out in p["outputs"]:
        if out["destination"] not in desk["destinations"]:
            errors.append(f"the desk {p['desk']} isn't allowed to send to '{out['destination']}'")
    for name in [*p["enrichment"], p["parser"]["component"], *(o["component"] for o in p["outputs"])]:
        c = registry.get(name)
        if c is not None:
            extra = c.effects - set(policy["stage_effects"][c.stage])
            errors += [f"'{name}' declares the effect '{e}', which isn't allowed at the {c.stage} stage" for e in sorted(extra)]
    return errors


def check_interference(pkg: dict, others: list[dict], triggers, ChatMessage) -> dict:
    """Check whether another desk could pick up the same message as the desk.

    For triggers that only use rooms, firms and keywords, the check is exact. For triggers with a regular expression,
    the check tries every known example message instead, and it reports any overlap that it can't rule out as uncertain.
    """
    mine = pkg["profile"]["trigger"]
    collisions, uncertain = [], []
    for other in others:
        if other["behaviour_id"] == pkg["behaviour_id"]:
            continue
        theirs = other["profile"]["trigger"]
        rooms = sorted(set(mine["rooms"]) & set(theirs["rooms"]))
        a, b = set(mine["sender_firms"]), set(theirs["sender_firms"])
        firms = sorted(a & b) if "*" not in a and "*" not in b else sorted(b - {"*"} if "*" in a else a - {"*"}) or ["ANY-FIRM"]
        if not rooms or not firms:
            continue  # The desks share no room or firm, so no message can reach both desks.
        words = [t["keywords_any"][0] for t in (mine, theirs) if t["keywords_any"]]
        witness = ChatMessage("witness", "witness", rooms[0], firms[0], " ".join(words))
        if triggers(mine, witness) and triggers(theirs, witness):
            collisions.append({"with": other["behaviour_id"], "message": {"room": witness.room, "firm": witness.sender_firm, "text": witness.raw_text}})
            continue
        known = [ChatMessage("k", "k", item.get("room", rooms[0]), item.get("firm", firms[0]), text) for src in (pkg, other) for item in src["corpus"] for text in item["messages"]]
        hit = next((m for m in known if m.room in rooms and triggers(mine, m) and triggers(theirs, m)), None)
        if hit:
            collisions.append({"with": other["behaviour_id"], "message": {"room": hit.room, "firm": hit.sender_firm, "text": hit.raw_text}})
        else:
            uncertain.append(f"{other['behaviour_id']}: both desks listen in the rooms {rooms}. The regular expressions in the triggers prevent an exact check, "
                             "and no known message reaches both desks.")
    status = "failed" if collisions else "inconclusive" if uncertain else "passed"
    return {"status": status, "collisions": collisions, "uncertain": uncertain}


def required_obligations(pkg: dict, policy: dict) -> list[str]:
    """Return the checks that the release must pass.

    The list comes from the protected policy and the package, and never from a list that the builder supplies.
    """
    out = []
    for ob in policy["obligations"]:
        out += [f"scenario:{sid}" for sid in sorted(pkg["scenarios"])] if ob == "scenarios" else [ob]
    return out
