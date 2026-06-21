#!/usr/bin/env python3
"""지역 커버리지 갭 리포트 — 크롤 프롬프트(§A·§B) 타깃 갱신용.

매매가 표본 3건 미만(중위 미산출) 구, 시그널 0건 구, 출처 신뢰도 분포를 출력.
실행: PYTHONPATH=src python3 scripts/region_gaps.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_site as B  # noqa: E402  (load_all/region_metrics/confidence_of 재사용)

sigs = B.load_all()
m = B.region_metrics(sigs)
reg = json.loads((ROOT / "config" / "regions.json").read_text(encoding="utf-8"))

for sido in ("서울", "경기", "인천"):
    thin = sorted(
        (f"{d}(표본{len(v['prices'])})" for (s, d), v in m.items()
         if s == sido and len(v["prices"]) < 3),
    )
    miss = [d for d in reg[sido]["districts"] if (sido, d) not in m]
    print(f"\n[{sido}]")
    print("  시그널 0건  :", ", ".join(miss) or "없음")
    print("  매매표본<3 :", ", ".join(thin) or "없음")

conf = defaultdict(int)
cat = defaultdict(int)
for s in sigs:
    conf[B.confidence_of(s.url, s.confidence)] += 1
    cat[s.category] += 1
print(f"\n총 {len(sigs)}건 · 출처 {dict(conf)} · 카테고리 {dict(cat)}")
