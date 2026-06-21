#!/usr/bin/env python3
"""지역 커버리지 갭 리포트 — 크롤 프롬프트(§A·§B) 타깃 갱신용.

매매 표본 3건 미만(중위 미산출) 구, 시그널 0건 구, 출처 신뢰도 분포를 출력.
실행: PYTHONPATH=src python3 scripts/region_gaps.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_site as B  # noqa: E402

sigs = B.load_all()
agg = {(r["sido"], r["gu"]): r for r in B.region_agg(sigs)}
reg = json.loads((ROOT / "config" / "regions.json").read_text(encoding="utf-8"))

# 구별 매매 표본 수(중위 산출은 3건 이상)
samples = defaultdict(int)
for s in sigs:
    if s.region and (s.sido or "전국") != "전국":
        samples[(s.sido, s.region[0])] += len(B.parse_sale_prices(s))

for sido in ("서울", "경기", "인천"):
    miss = [d for d in reg[sido]["districts"] if (sido, d) not in agg]
    thin = sorted(f"{d}(표본{samples.get((sido, d), 0)})"
                  for (s, d) in agg if s == sido and samples.get((sido, d), 0) < 3)
    print(f"\n[{sido}]")
    print("  시그널 0건  :", ", ".join(miss) or "없음")
    print("  매매표본<3 :", ", ".join(thin) or "없음")

conf = defaultdict(int)
cat = defaultdict(int)
for s in sigs:
    conf[B.confidence_of(s.url, s.confidence)] += 1
    cat[s.category] += 1
print(f"\n총 {len(sigs)}건 · 출처 {dict(conf)} · 카테고리 {dict(cat)}")
