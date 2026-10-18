#!/usr/bin/env python3
"""데이터 신선도 헬스체크 — 수집이 조용히 멈추는 것을 잡는다.

배경: 지표 트랙은 주간 자동수집으로 6일 지연을 유지했는데, 수동 큐레이션인
뉴스 트랙은 107일 동안 멈춰 있었다. 그런데도 CI는 아무 경고를 내지 않았다.
자동화된 트랙만 살아남고, 멈춘 트랙은 아무도 모르게 썩는다.

트랙 단위 점검만으로는 부족하다. 지표 트랙은 자동수집 3종(공공임대 세대수·
단지수·아파트 세대수)이 매주 갱신돼 '최신 6일'로 보였지만, 수동 큐레이션인
나머지 22종은 110~200일 멈춰 있었다. 최신값 하나가 트랙 전체를 초록으로
칠해버린 것이다. 그래서 지표별로도 본다 — 각 지표가 과거에 실제로 갱신돼 온
주기(관측 간격의 중앙값)를 데이터에서 구하고, 그보다 한참 지났으면 지연으로
판정한다. 발표 일정을 하드코딩하지 않으므로 날조할 여지가 없다.

사용
    python3 scripts/healthcheck.py                 # 초과 시 exit 1(로컬·수동 점검용)
    python3 scripts/healthcheck.py --github        # ::warning:: 로 알리고 항상 exit 0(CI용)
    python3 scripts/healthcheck.py --max-age-news 21

임계 기본값은 주간 수집(7일) 기준으로 2주 연속 실패를 잡도록 14일로 둔다.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_signals():
    """build_site 의 로더를 그대로 쓴다 — 판정 기준을 사이트와 일치시키기 위함."""
    os.environ.setdefault("APTHUB_PUBLIC", "1")
    spec = importlib.util.spec_from_file_location("bs", ROOT / "scripts" / "build_site.py")
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    return bs.normalize_signals(bs.load_all())


def _age(latest: str | None, today: datetime.date) -> int | None:
    if not latest:
        return None
    return (today - datetime.date.fromisoformat(latest)).days


def metric_staleness(rows, today: datetime.date, factor: float, floor: int) -> list[dict]:
    """지표별 지연 판정 — 발표 일정을 하드코딩하지 않고 데이터에서 주기를 구한다.

    각 지표가 과거에 실제로 갱신돼 온 간격의 중앙값을 그 지표의 기대 주기로 보고,
    마지막 관측이 그 주기의 `factor` 배를 넘고 동시에 `floor` 일을 넘으면 지연으로
    본다. floor 는 주기가 짧은 지표(주간 지수 등)가 며칠 늦었다고 소음을 내지 않게 한다.
    관측이 3개 미만이면 주기를 추정할 근거가 없으므로 판정하지 않는다.
    """
    by = defaultdict(set)
    iso = today.isoformat()
    for s in rows:
        m, d = getattr(s, "metric", None), getattr(s, "date", None)
        if m and d and d <= iso:          # 미래 일자(예정 공시)는 '갱신'으로 치지 않는다
            by[m].add(d)
    out = []
    for m, dates in by.items():
        ds = sorted(dates)
        if len(ds) < 3:
            continue
        gaps = [(datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
                for a, b in zip(ds, ds[1:])]
        cadence = statistics.median(gaps)
        if cadence <= 0:
            continue
        age = (today - datetime.date.fromisoformat(ds[-1])).days
        if age > factor * cadence and age > floor:
            out.append({"metric": m, "cadence": cadence, "latest": ds[-1],
                        "age": age, "ratio": age / cadence})
    out.sort(key=lambda x: -x["ratio"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-news", type=int, default=14)
    ap.add_argument("--max-age-data", type=int, default=14)
    ap.add_argument("--metric-factor", type=float, default=2.0,
                    help="지표별 판정 배수 — 자체 관측주기 중앙값의 N배를 넘으면 지연")
    ap.add_argument("--metric-floor", type=int, default=21,
                    help="지표별 판정 최소 유예일 — 주기가 짧은 지표의 소음을 막는다")
    ap.add_argument("--no-metrics", action="store_true", help="지표별 점검 생략")
    ap.add_argument("--github", action="store_true",
                    help="GitHub Actions 주석(::warning::)으로 내보내고 항상 0으로 종료")
    a = ap.parse_args()

    today = datetime.date.today()
    sigs = _load_signals()
    tracks = {
        "뉴스(정성)": ([s for s in sigs if getattr(s, "kind", "news") != "data"], a.max_age_news),
        "지표(정량)": ([s for s in sigs if getattr(s, "kind", "news") == "data"], a.max_age_data),
    }

    breached = []
    print(f"데이터 신선도 점검 — 기준일 {today}")
    for name, (rows, limit) in tracks.items():
        # 미래 일자(예정 공시 등)는 '최신'으로 치지 않는다.
        dates = [s.date for s in rows if getattr(s, "date", None) and s.date <= today.isoformat()]
        latest = max(dates) if dates else None
        age = _age(latest, today)
        status = "OK"
        if age is None:
            status, age_txt = "비어있음", "-"
        else:
            age_txt = f"{age}일"
            if age > limit:
                status = "지연"
                breached.append((name, latest, age, limit))
        print(f"  {name:10s} {len(rows):>5d}건 · 최신 {latest or '-':10s} · {age_txt:>6s} "
              f"· 임계 {limit}일 · {status}")

    for name, latest, age, limit in breached:
        msg = (f"{name} 트랙이 {age}일째 갱신되지 않았습니다(최신 {latest}, 임계 {limit}일). "
               f"수집기 또는 수동 큐레이션이 멈췄는지 확인하세요.")
        print(f"::warning::{msg}" if a.github else f"  ⚠ {msg}")

    stale_metrics = []
    if not a.no_metrics:
        stale_metrics = metric_staleness(
            [s for s in sigs if getattr(s, "kind", "news") == "data"],
            today, a.metric_factor, a.metric_floor)
        print(f"\n지표별 점검 — 각 지표의 자체 관측주기(중앙값) 대비 "
              f"{a.metric_factor:g}배 초과 & {a.metric_floor}일 초과 시 지연")
        if stale_metrics:
            print(f"  {'metric':22s} {'주기':>6s} {'최신':>11s} {'경과':>6s}")
            for m in stale_metrics:
                print(f"  {m['metric']:22s} {m['cadence']:>5.0f}일 {m['latest']:>11s} "
                      f"{m['age']:>5d}일  (x{m['ratio']:.1f})")
            head = ", ".join(m["metric"] for m in stale_metrics[:5])
            more = f" 외 {len(stale_metrics) - 5}종" if len(stale_metrics) > 5 else ""
            msg = (f"지표 {len(stale_metrics)}종이 자체 갱신주기를 크게 넘겼습니다: {head}{more}. "
                   f"트랙 최신일만 보면 자동수집분 때문에 정상으로 보일 수 있습니다.")
            print(f"::warning::{msg}" if a.github else f"  ⚠ {msg}")
        else:
            print("  지연 지표 없음")

    if a.github:
        return 0
    return 1 if (breached or stale_metrics) else 0


if __name__ == "__main__":
    sys.exit(main())
