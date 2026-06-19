"""리포트 생성 — 데일리/위클리 Markdown (05-report-format.md 준수).

원칙: 모든 시그널에 '내 매수계획 함의' 한 줄. 🔴 즉시 트리거 우선 노출.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from . import config
from .schema import Signal, KST

CATEGORY_LABEL = {
    "policy": "정책/세제",
    "price": "강서 시세",
    "macro": "금리/거시",
    "semicon": "반도체/소득",
}
CATEGORY_PRIORITY = {"policy": 1, "price": 2, "macro": 3, "semicon": 4}
TRIGGER_RANK = {"red": 0, "yellow": 1, "none": 2}


def _src(sig: Signal) -> str:
    if sig.url:
        return f"[{sig.source}]({sig.url})"
    return sig.source


def _implication_line(sig: Signal) -> str:
    return sig.implication or "_(함의 미작성 — 채워 주세요)_"


def _primary_unit(sig: Signal, units: list[dict]) -> str | None:
    """시그널 제목에서 가장 먼저 등장하는 단지명을 '주제 단지'로 본다.
    인접 단지를 함께 언급한 시그널이 여러 행에 중복 귀속되는 것을 막는다.
    """
    best_pos: int | None = None
    best: str | None = None
    for unit in units:
        for name in [unit["name"]] + unit.get("aliases", []):
            i = sig.title.find(name)
            if i != -1 and (best_pos is None or i < best_pos):
                best_pos, best = i, unit["name"]
    return best


def _sort_key(sig: Signal):
    return (
        TRIGGER_RANK.get(sig.trigger, 2),
        CATEGORY_PRIORITY.get(sig.category or "", 9),
        sig.date or "",
    )


# ----------------------------------------------------------------------------
# Daily
# ----------------------------------------------------------------------------
def render_daily(signals: Iterable[Signal], day: str | None = None) -> str:
    signals = sorted(signals, key=_sort_key)
    day = day or datetime.now(KST).date().isoformat()
    lines: list[str] = []
    lines.append(f"📅 [{day}] 정훈 부동산 시그널 — Daily")
    lines.append(f"_천장: {config.ceilings_text()} · 희주 단독 생애최초_")
    lines.append("")

    # 🔴 핵심 트리거
    reds = [s for s in signals if s.trigger == "red"]
    lines.append("## 🔴 핵심 트리거")
    if reds:
        for s in reds:
            lines.append(f"- **{s.title}** ({_src(s)})")
            lines.append(f"  → 함의: {_implication_line(s)}")
    else:
        lines.append("- 특이사항 없음")
    lines.append("")

    # 📊 강서 시세 스냅
    snap = [s for s in signals if s.category == "price"]
    rates = [s for s in signals if s.category == "macro"]
    lines.append("## 📊 강서 시세 스냅")
    if snap:
        for s in snap:
            area = " · ".join(s.areas[:3]) if s.areas else "강서"
            lines.append(f"- {area}: {s.summary or s.title} ({_src(s)})")
            if s.implication:
                lines.append(f"  → {s.implication}")
    else:
        lines.append("- 신규 실거래·호가 변동 없음")
    if rates:
        for s in rates:
            lines.append(f"- 금리: {s.summary or s.title} ({_src(s)})")
    lines.append("")

    # 📰 정책/뉴스 Top 3 (🔴 핵심 트리거·시세/금리 스냅에 이미 나온 건 제외 → 중복 방지·반도체 등 노출)
    shown_ids = {s.id for s in reds}
    pool = [s for s in signals
            if s.category not in ("price", "macro") and s.id not in shown_ids]
    top = pool[:3]
    lines.append("## 📰 정책/뉴스 Top 3")
    if top:
        for i, s in enumerate(top, 1):
            tag = "🔴 " if s.trigger == "red" else ("🟡 " if s.trigger == "yellow" else "")
            lines.append(f"{i}. {tag}{s.title} ({_src(s)})")
            lines.append(f"   - {s.summary or '요약 미작성'}")
            lines.append(f"   - → 함의: {_implication_line(s)}")
    else:
        lines.append("- 해당 없음")
    lines.append("")

    # 💡 오늘의 액션
    actions = _derive_actions(signals)
    if actions:
        lines.append("## 💡 오늘의 액션")
        for a in actions:
            lines.append(f"- {a}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _derive_actions(signals: Iterable[Signal]) -> list[str]:
    acts: list[str] = []
    for s in signals:
        if s.trigger == "red" and s.category == "policy":
            acts.append("은행 대출 가심사(사전한도조회) 재확인 — 정책 변경분 반영")
            break
    for s in signals:
        if s.trigger == "red" and s.category == "price":
            acts.append("관심단지 매물·호가 확인 (네이버부동산/호갱노노 알림)")
            break
    return acts


# ----------------------------------------------------------------------------
# Weekly
# ----------------------------------------------------------------------------
def iso_week_label(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y} W{w:02d}"


def render_weekly(signals: Iterable[Signal], start: str, end: str,
                  budreadnam_note: str = "") -> str:
    signals = sorted(signals, key=_sort_key)
    end_d = date.fromisoformat(end)
    lines: list[str] = []
    lines.append(f"🗓️ [{iso_week_label(end_d)} · {start}~{end}] 정훈 부동산 시그널 — Weekly")
    lines.append(f"_천장: {config.ceilings_text()} · 희주 단독 생애최초_")
    lines.append("")

    # 1) 정책 변화 & 내 천장 영향
    lines.append("## 1) 정책 변화 & 내 천장 영향")
    pol = [s for s in signals if s.category == "policy"]
    if pol:
        for s in pol:
            tag = "🔴 " if s.trigger == "red" else ("🟡 " if s.trigger == "yellow" else "")
            lines.append(f"- {tag}**{s.title}** ({_src(s)})")
            lines.append(f"  → {_implication_line(s)}")
    else:
        lines.append("- 이번 주 대출·세제·규제 변화 없음")
    lines.append("")

    # 2) 강서 관심단지 주간 시세 표
    lines.append("## 2) 강서 관심단지 주간 시세")
    lines.append("| 단지 | 전용59(추정) | 주간 변동 | 메모 |")
    lines.append("|---|---|---|---|")
    price_sigs = [s for s in signals if s.category == "price"]
    units = config.target_areas()["units"]
    for unit in units:
        if unit["tier"] > 2:
            continue
        # 시그널은 '제목에서 가장 먼저 등장하는 단지'(주제 단지)에만 귀속 → 인접 언급 오염 방지
        related = [s for s in price_sigs if _primary_unit(s, units) == unit["name"]]
        memo = "; ".join(s.summary or s.title for s in related)[:60] if related else "-"
        change = "신규 시그널" if related else "-"
        lines.append(f"| {unit['name']} | ~{unit['est_price_59_eok']}억 | {change} | {memo} |")
    lines.append("")

    # 3) 금리·거시·반도체
    lines.append("## 3) 금리·거시·반도체")
    macro = [s for s in signals if s.category in ("macro", "semicon")]
    if macro:
        for s in macro:
            lines.append(f"- {CATEGORY_LABEL.get(s.category, '')}: {s.title} ({_src(s)})")
            if s.implication:
                lines.append(f"  → {s.implication}")
    else:
        lines.append("- 특이사항 없음")
    lines.append("")

    # 4) 부읽남 관점 코멘트
    lines.append("## 4) 부읽남 관점 코멘트")
    lines.append(budreadnam_note or
                 "_(이번 주 시장을 부읽남 38강 원칙으로 1문단 해석 — 대안의 부재 / "
                 "계획-과정-현실화 / 능력의 객관화 / 시간 레버리지 / 안전판)_")
    lines.append("")

    # 5) 다음 주 체크포인트 / 액션
    lines.append("## 5) 다음 주 체크포인트 / 액션")
    actions = _derive_actions(signals)
    if actions:
        for a in actions:
            lines.append(f"- {a}")
    else:
        lines.append("- 발표 예정 정책·지표 모니터링")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def week_bounds(any_day: str) -> tuple[str, str]:
    """해당 날짜가 포함된 주(월~일)의 시작/끝."""
    d = date.fromisoformat(any_day)
    start = d - timedelta(days=d.weekday())
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()
