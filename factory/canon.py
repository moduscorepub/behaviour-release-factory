"""Canonical digests and workspace layout shared by every factory component."""

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

FACTORY_DIR = Path(__file__).resolve().parent
PROJECT = FACTORY_DIR.parent


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest(obj) -> str:
    return sha(canonical(obj))


def sign(key: bytes, obj) -> str:
    return hmac.new(key, canonical(obj), hashlib.sha256).hexdigest()


def verify(key: bytes, obj, signature: str) -> bool:
    return hmac.compare_digest(sign(key, obj), signature or "")


def evaluator_digest(factory_dir: Path = FACTORY_DIR) -> str:
    """Identity of the code that produces and judges evidence (every factory module)."""
    return digest({p.name: sha(p.read_bytes()) for p in sorted(factory_dir.glob("*.py"))})


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def load_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class Workspace:
    """behaviours/ + runtime/ are builder-owned; policy/ and trust/ are authority-owned."""

    root: Path

    @property
    def behaviours(self) -> Path:
        return self.root / "behaviours"

    @property
    def policy_file(self) -> Path:
        return self.root / "policy" / "policy.yaml"

    @property
    def trust(self) -> Path:
        return self.root / "trust"

    @property
    def state(self) -> Path:
        return self.root / "state"

    def package_path(self, behaviour: str) -> Path:
        return self.root / "build" / behaviour / "package.json"

    def evidence_path(self, behaviour: str) -> Path:
        return self.root / "build" / behaviour / "evidence.json"


def runner_key(trust: Path) -> bytes:
    """CI supplies the key as a secret env var; locally it lives in the authority-owned trust dir."""
    env = os.environ.get("FACTORY_RUNNER_KEY")
    return bytes.fromhex(env) if env else (trust / "runner.key").read_bytes()
