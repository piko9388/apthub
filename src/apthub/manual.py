"""채팅 수동파싱 진입점.

Phase 1 흐름:
  1) 채팅에 뉴스/실거래/공시 원문을 붙여넣는다.
  2) Claude(또는 사람)가 아래 dict 형태로 파싱한다 (함의 한 줄 포함).
  3) ingest() 가 enrich(자동 태깅) 후 저장한다.
  4) report 로 데일리/위클리를 뽑는다.

파싱 dict 최소 형태:
  {"title": "...", "source": "...", "summary": "...", "url": "...",
   "date": "2026-06-19", "category": "policy", "implication": "..."}
category/areas/keywords/trigger 는 비워도 enrich 가 보강한다.
"""
from __future__ import annotations

import json
from typing import Iterable

from . import filters, store
from .schema import Signal


def to_signal(item: dict) -> Signal:
    return filters.enrich(Signal.from_dict(item))


def ingest(items: Iterable[dict], day: str | None = None,
           replace: bool = False, by_date: bool = False) -> list[Signal]:
    """파싱 dict 목록 → enrich → 저장. 저장된 Signal 목록 반환.

    by_date=True 면 각 시그널을 자신의 발행일 파일에 저장(백데이터 적재).
    """
    signals = [to_signal(it) for it in items]
    if by_date:
        store.add_by_date(signals)
    else:
        store.add(signals, day=day, replace=replace)
    return signals


def ingest_json(text: str, day: str | None = None,
                replace: bool = False, by_date: bool = False) -> list[Signal]:
    """JSON 문자열(배열 또는 단건) 수용."""
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    return ingest(data, day=day, replace=replace, by_date=by_date)
