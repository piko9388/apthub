#!/usr/bin/env python3
"""데이터 신선도 헬스체크 — 수집이 조용히 멈추는 것을 잡는다.

배경: 지표 트랙은 주간 자동수집으로 6일 지연을 유지했는데, 수동 큐레이션인
뉴스 트랙은 107일 동안 멈춰 있었다. 그런데도 CI는 아무 경고를 내지 않았다.
자동화된 트랙만 살아남고, 멈춘 트랙은 아무도 모르게 썩는다.

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
import sys
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-news", type=int, default=14)
    ap.add_argument("--max-age-data", type=int, default=14)
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

    if a.github:
        return 0
    return 1 if breached else 0


if __name__ == "__main__":
    sys.exit(main())
