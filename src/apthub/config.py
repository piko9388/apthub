"""config/ 와 data/ 경로 로딩."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SIGNALS_DIR = DATA_DIR / "signals"
RAW_DIR = DATA_DIR / "raw"
REPORTS_DIR = DATA_DIR / "reports"


def _load(name: str) -> dict[str, Any]:
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def profile() -> dict[str, Any]:
    return _load("profile.json")


@lru_cache(maxsize=None)
def target_areas() -> dict[str, Any]:
    return _load("target_areas.json")


@lru_cache(maxsize=None)
def monitoring() -> dict[str, Any]:
    return _load("monitoring.json")


def ceilings_text() -> str:
    """리포트 헤더용 천장 요약. 예: '8월 ~8.5억 / 27.2 ~10.5억'."""
    parts = []
    for c in profile()["ceilings"]:
        d = c["date"].split("-")
        label = f"{int(d[1])}월" if d[0] == "2026" else f"{d[0][2:]}.{int(d[1])}"
        parts.append(f"{label} ~{c['ceiling_eok']}억")
    return " / ".join(parts)


def ensure_dirs() -> None:
    for d in (SIGNALS_DIR, RAW_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
