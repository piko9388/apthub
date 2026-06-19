"""필터·태깅 엔진 — Signal 에 areas/keywords/category/trigger 를 보강.

수동파싱 단계에서 사람(또는 Claude)이 일부 필드를 채워도, enrich() 가
config 규칙으로 누락분을 자동 보강한다. 이미 채워진 값은 보존·병합.
"""
from __future__ import annotations

from typing import Iterable

from . import config
from .schema import Signal


def _text(sig: Signal) -> str:
    return f"{sig.title}\n{sig.summary}".lower()


def match_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    hits = []
    low = text.lower()
    for kw in keywords:
        if kw.lower() in low:
            hits.append(kw)
    return hits


def detect_areas(text: str) -> list[str]:
    """관심 지역/단지명(별칭 포함) 매칭. canonical name 으로 반환."""
    low = text.lower()
    found: list[str] = []
    for unit in config.target_areas()["units"]:
        names = [unit["name"]] + unit.get("aliases", [])
        if any(n.lower() in low for n in names):
            found.append(unit["name"])
    # 광역 키워드도 포착
    for region in ("강서구", "강서", "동작구", "마곡", "검단", "인천 서구"):
        if region.lower() in low and region not in found:
            found.append(region)
    return _dedup(found)


def detect_category(text: str) -> tuple[str | None, list[str]]:
    """카테고리 추론 + 매칭된 키워드. 매칭 수 우선, 동률이면 priority 높은 카테고리."""
    cats = config.monitoring()["categories"]
    best_score: tuple[int, int] | None = None
    best_key: str | None = None
    all_hits: list[str] = []
    for key, spec in cats.items():
        hits = match_keywords(text, spec["keywords"])
        if hits:
            all_hits.extend(hits)
            score = (len(hits), -spec["priority"])  # 매칭 수, 그다음 priority(작을수록 우선)
            if best_score is None or score > best_score:
                best_score = score
                best_key = key
    return best_key, _dedup(all_hits)


def _rule_matches(text: str, rule: dict) -> bool:
    """규칙 매칭.
      all_of_*  : 나열 키워드가 전부 있어야 함
      any_of_*  : 그룹 내 1개 이상
      none_of_* : 하나라도 있으면 탈락(오탐 방지 가드)
    """
    low = text.lower()
    for field_name, words in rule.items():
        if field_name == "name" or not isinstance(words, list):
            continue
        present = [w for w in words if w.lower() in low]
        if field_name.startswith("all_of"):
            if len(present) != len(words):
                return False
        elif field_name.startswith("any_of"):
            if not present:
                return False
        elif field_name.startswith("none_of"):
            if present:
                return False
    return True


def evaluate_triggers(text: str) -> tuple[str, list[str]]:
    """trigger 등급(red>yellow>none)과 사유 리스트."""
    trig = config.monitoring()["triggers"]
    red_reasons = [r["name"] for r in trig["red"]["rules"] if _rule_matches(text, r)]
    if red_reasons:
        return "red", red_reasons
    yellow_reasons = [r["name"] for r in trig["yellow"]["rules"] if _rule_matches(text, r)]
    if yellow_reasons:
        return "yellow", yellow_reasons
    return "none", []


def _dedup(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def enrich(sig: Signal) -> Signal:
    """config 규칙으로 누락 필드 보강. 기존 수동 입력값은 병합·보존."""
    text = _text(sig)

    areas = _dedup(list(sig.areas) + detect_areas(text))
    sig.areas = areas

    cat, kw_hits = detect_category(text)
    sig.keywords = _dedup(list(sig.keywords) + kw_hits)
    if not sig.category:
        sig.category = cat

    # trigger: 수동으로 더 높은 등급을 줬으면 보존
    auto_trig, reasons = evaluate_triggers(text)
    order = {"red": 2, "yellow": 1, "none": 0}
    if order[auto_trig] >= order.get(sig.trigger, 0):
        sig.trigger = auto_trig
    sig.trigger_reasons = _dedup(list(sig.trigger_reasons) + reasons)
    return sig


def enrich_all(signals: Iterable[Signal]) -> list[Signal]:
    return [enrich(s) for s in signals]
