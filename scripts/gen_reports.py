#!/usr/bin/env python3
"""2026 일자별·주차별 동향 리포트 생성 (공개·비개인화).

주차별이 메인, 일자별은 그 주가 포함하는 드릴다운.
  reports/2026/weekly/2026-Www.md   ← 주간 요약(+ 포함 일자 링크)
  reports/2026/daily/YYYY-MM-DD.md  ← 일자별 상세
  reports/2026/INDEX.md             ← 목차

실행: PYTHONPATH=src python3 scripts/gen_reports.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_site as B  # noqa: E402

YEAR = "2026"
OUT = ROOT / "reports" / YEAR
CATL = {"policy": "정책·규제", "price": "시장·실거래", "macro": "금리·거시", "semicon": "반도체"}
TRIG = {"red": "🔴 즉시", "yellow": "🟡 주목"}


def _is_data(s):
    return getattr(s, "kind", "news") == "data"


def _loc(s):
    if s.sido and s.region:
        return f"{s.sido} {s.region[0]}"
    return s.sido or ""


def _cat_counts(sigs):
    c = defaultdict(int)
    for s in sigs:
        c[s.category or "기타"] += 1
    return " · ".join(f"{CATL.get(k, k)} {v}" for k, v in
                      sorted(c.items(), key=lambda kv: -kv[1]))


def _trigger_lines(sigs):
    out = []
    for s in sorted(sigs, key=lambda s: (s.trigger != "red", s.trigger != "yellow")):
        if s.trigger in ("red", "yellow"):
            loc = _loc(s)
            tag = f" `{loc}`" if loc else ""
            src = f" ([{s.source}]({s.url}))" if s.url else f" ({s.source})"
            out.append(f"- {TRIG[s.trigger]} **{s.title}**{tag}{src}")
    return out


def _fmt_val(v, unit):
    if v is None:
        return "—"
    if unit == "%":
        return f"{'+' if v > 0 else ''}{v:g}{unit}"
    if float(v).is_integer():
        return f"{int(v):,}{unit}"
    return f"{v:g}{unit}"


def _data_lines(sigs):
    out = []
    for s in sorted(sigs, key=lambda s: (s.metric or "", s.sido or "")):
        if _is_data(s) and s.value is not None:
            src = f" ([{s.source}]({s.url}))" if s.url else ""
            out.append(f"- {s.sido} · {s.metric} **{_fmt_val(s.value, s.unit)}**{src}")
    return out


def render_daily(day, sigs):
    news = [s for s in sigs if not _is_data(s)]
    dat = [s for s in sigs if _is_data(s)]
    reds = sum(1 for s in news if s.trigger == "red")
    yel = sum(1 for s in news if s.trigger == "yellow")
    L = [f"# {day} 일일 동향 — APT-SIGNAL", ""]
    L.append(f"> 뉴스 {len(news)}건 · 🔴 {reds} · 🟡 {yel}"
             + (f" · 지표 {len(dat)}건" if dat else ""))
    L.append("")
    if news:
        L.append(f"**분야** — {_cat_counts(news)}")
        L.append("")
    trig = _trigger_lines(news)
    if trig:
        L.append("## 트리거")
        L += trig
        L.append("")
    others = [s for s in news if s.trigger == "none"]
    if others:
        L.append("## 그 외 시그널")
        for s in others[:20]:
            loc = _loc(s)
            tag = f" `{loc}`" if loc else ""
            src = f" ([{s.source}]({s.url}))" if s.url else ""
            L.append(f"- {s.title}{tag}{src}")
        if len(others) > 20:
            L.append(f"- …외 {len(others) - 20}건")
        L.append("")
    if dat:
        L.append("## 공식 지표")
        L += _data_lines(dat)
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def render_weekly(label, start, end, sigs, day_files):
    news = [s for s in sigs if not _is_data(s)]
    dat = [s for s in sigs if _is_data(s)]
    reds = sum(1 for s in news if s.trigger == "red")
    yel = sum(1 for s in news if s.trigger == "yellow")
    L = [f"# {label} 주간 동향 — APT-SIGNAL", f"_{start} ~ {end}_", ""]
    L.append(f"> 뉴스 {len(news)}건 · 🔴 {reds} · 🟡 {yel}"
             + (f" · 지표 {len(dat)}건" if dat else ""))
    L.append("")
    if news:
        L.append(f"**분야** — {_cat_counts(news)}")
        L.append("")
    trig = _trigger_lines(news)
    if trig:
        L.append("## 이 주의 트리거")
        L += trig[:15]
        if len(trig) > 15:
            L.append(f"- …외 트리거 {len(trig) - 15}건")
        L.append("")
    if dat:
        L.append("## 이 주의 공식 지표")
        L += _data_lines(dat)
        L.append("")
    if day_files:
        L.append("## 일자별 드릴다운")
        for d, fn in day_files:
            L.append(f"- [{d}](../daily/{fn})")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def iso_week(d: date):
    y, w, _ = d.isocalendar()
    return y, w


def main():
    sigs = [s for s in B.load_all() if (s.date or "").startswith(YEAR)]
    by_day = defaultdict(list)
    for s in sigs:
        by_day[s.date].append(s)
    (OUT / "daily").mkdir(parents=True, exist_ok=True)
    (OUT / "weekly").mkdir(parents=True, exist_ok=True)

    # 일자별
    day_meta = {}
    for day in sorted(by_day):
        fn = f"{day}.md"
        (OUT / "daily" / fn).write_text(render_daily(day, by_day[day]), encoding="utf-8")
        d = date.fromisoformat(day)
        day_meta[day] = (iso_week(d), fn)

    # 주차별(ISO 주) — 포함 일자 묶기
    by_week = defaultdict(list)
    for day in sorted(by_day):
        (yw), _ = day_meta[day]
        by_week[yw].append(day)
    week_files = []
    for (y, w), days in sorted(by_week.items()):
        label = f"{y} W{w:02d}"
        mon = date.fromisoformat(days[0]) - timedelta(days=date.fromisoformat(days[0]).weekday())
        start, end = mon.isoformat(), (mon + timedelta(days=6)).isoformat()
        wk_sigs = [s for d in days for s in by_day[d]]
        day_files = [(d, day_meta[d][1]) for d in days]
        fn = f"{y}-W{w:02d}.md"
        (OUT / "weekly" / fn).write_text(
            render_weekly(label, start, end, wk_sigs, day_files), encoding="utf-8")
        week_files.append((label, fn, start, end, len(wk_sigs)))

    # INDEX
    idx = [f"# {YEAR} 동향 리포트 — 목차", "",
           "주차별이 메인, 각 주에서 일자별로 드릴다운.", ""]
    idx.append("## 주간")
    for label, fn, start, end, n in reversed(week_files):
        idx.append(f"- [{label}](weekly/{fn}) · {start}~{end} · {n}건")
    (OUT / "INDEX.md").write_text("\n".join(idx) + "\n", encoding="utf-8")

    print(f"리포트 생성: 일자 {len(by_day)}일 · 주 {len(week_files)}주 → {OUT}")


if __name__ == "__main__":
    main()
