"""시그널 저장소 — data/signals/YYYY-MM-DD.jsonl (수집일 기준).

중복 제거는 Signal.id(URL 또는 제목 해시) 기준. 같은 날 같은 id 면 갱신.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from . import config
from .schema import Signal, KST


def _file_for(day: str) -> Path:
    return config.SIGNALS_DIR / f"{day}.jsonl"


def _today() -> str:
    return datetime.now(KST).date().isoformat()


def add(signals: Iterable[Signal], day: str | None = None) -> int:
    """시그널을 해당 날짜 파일에 저장(id 중복 시 덮어씀). 추가/갱신된 건수 반환."""
    config.ensure_dirs()
    day = day or _today()
    existing = {s.id: s for s in load_day(day)}
    n = 0
    for sig in signals:
        existing[sig.id] = sig
        n += 1
    path = _file_for(day)
    with path.open("w", encoding="utf-8") as f:
        for sig in existing.values():
            f.write(json.dumps(sig.to_dict(), ensure_ascii=False) + "\n")
    return n


def load_day(day: str) -> list[Signal]:
    path = _file_for(day)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(Signal.from_dict(json.loads(line)))
    return out


def load_range(start: str, end: str) -> list[Signal]:
    """start~end(포함) 사이 모든 시그널, id 중복 제거."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    seen: dict[str, Signal] = {}
    cur = s
    while cur <= e:
        for sig in load_day(cur.isoformat()):
            seen[sig.id] = sig
        cur += timedelta(days=1)
    return list(seen.values())


def all_days() -> list[str]:
    config.ensure_dirs()
    return sorted(p.stem for p in config.SIGNALS_DIR.glob("*.jsonl"))
