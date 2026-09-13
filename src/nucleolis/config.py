"""Configuration loading: YAML config files plus .env, with no extra dependencies."""
from __future__ import annotations

import os
import pathlib
from functools import lru_cache

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

_ENV_PREFIXES = ("NOD_", "COGEX_", "AMASS_", "NCBI_", "LLM_", "NEBIUS_", "ANTHROPIC_")


def _parse_env_file(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        out[key] = value
    return out


@lru_cache(maxsize=1)
def env() -> dict[str, str]:
    """.env file values, overridden by the real process environment."""
    values = _parse_env_file(REPO_ROOT / ".env")
    for key, value in os.environ.items():
        if key.startswith(_ENV_PREFIXES):
            values[key] = value
    return values


def data_dir() -> pathlib.Path:
    raw = env().get("NOD_DATA_DIR") or "./data"
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


@lru_cache(maxsize=8)
def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def seeds() -> dict:
    return load_yaml("seeds.yaml")


def predicates() -> dict:
    return load_yaml("predicates.yaml")


def sources() -> dict:
    return load_yaml("sources.yaml")
