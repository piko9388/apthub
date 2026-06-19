#!/usr/bin/env python3
"""정적 대시보드 사이트 생성기 — data/seed/*.json 을 읽어 site/index.html 을 만든다.

자체완결 단일 HTML(인라인 CSS/JS). 외부 의존성·웹폰트 없음.
디자인: 톤다운 네이비, 시스템 폰트(맥/윈도/iOS/안드로이드 한영 모두 지원), 반응형.
실행: python3 scripts/build_site.py
"""
from __future__ import annotations

import html
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DATA = ROOT / ".build_data"
SITE = ROOT / "site"

# 빌드 전용 데이터 디렉터리로 격리 후 시드 적재
shutil.rmtree(BUILD_DATA, ignore_errors=True)
os.environ["APTHUB_DATA_DIR"] = str(BUILD_DATA)
sys.path.insert(0, str(ROOT / "src"))

from apthub import config, manual, store  # noqa: E402

CATEGORY = {
    "policy": "정책·세제",
    "price": "강서 시세",
    "macro": "금리·거시",
    "semicon": "반도체·소득",
}
TRIGGER = {"red": "🔴 즉시", "yellow": "🟡 주목", "none": ""}


def load_all():
    for f in sorted((ROOT / "data" / "seed").glob("*.json")):
        manual.ingest_json(f.read_text(encoding="utf-8"), by_date=True)
    sigs = []
    for day in store.all_days():
        sigs += store.load_day(day)
    # 발행일 desc, 트리거 우선
    rank = {"red": 0, "yellow": 1, "none": 2}
    sigs.sort(key=lambda s: (s.date or "", rank.get(s.trigger, 2)), reverse=True)
    return sigs


def esc(s: str) -> str:
    return html.escape(s or "")


def card(sig) -> str:
    trig = sig.trigger
    badge = f'<span class="badge {trig}">{TRIGGER[trig]}</span>' if trig != "none" else ""
    src = (f'<a class="src" href="{esc(sig.url)}" target="_blank" rel="noopener">{esc(sig.source)} ↗</a>'
           if sig.url else f'<span class="src">{esc(sig.source)}</span>')
    areas = "".join(f'<span class="tag">{esc(a)}</span>' for a in sig.areas[:4])
    impl = (f'<p class="impl"><b>함의</b> {esc(sig.implication)}</p>'
            if sig.implication else "")
    return f"""<article class="card" data-cat="{sig.category or ''}" data-trig="{trig}">
  <div class="meta"><span class="date">{esc(sig.date or '')}</span>
    <span class="cat {sig.category or ''}">{CATEGORY.get(sig.category, '기타')}</span>{badge}</div>
  <h3>{esc(sig.title)}</h3>
  <p class="sum">{esc(sig.summary)}</p>
  {impl}
  <div class="foot">{src}<span class="tags">{areas}</span></div>
</article>"""


def dashboard(sigs) -> str:
    """상단 요약 대시보드 — 매수 타이밍·자기자본·후보단지·최근 트리거."""
    recent_reds = [s for s in sigs if s.trigger == "red"][:3]
    red_li = "".join(
        f'<li><span class="dd">{esc(s.date or "")}</span>{esc(s.title)}</li>'
        for s in recent_reds) or "<li>최근 🔴 없음</li>"

    blocks = [
        ("매수 타이밍 2안", [
            "<b>8월(희망#1)</b> 천장 ~8.5억 · 희주 단독 생애최초 LTV70%",
            "<b>27.2(희망#2)</b> 천장 ~10.5억 · 성과급(PS) 보강 후",
            "5월 매파 전환·서울 +11% → <b>가격상승 vs 자기자본증가</b> 트레이드오프",
        ]),
        ("자기자본 조달", [
            "대출은 <b>6억 상한</b> 고정 → 8.5억 매수 시 <b>갭 2.5억</b>",
            "PS: 26.2 수령 세전 ~1.48억(2025 실적)",
            "증여: 혼인·출산 공제로 <b>양가 최대 3억</b> 무세",
        ]),
        ("후보 단지", [
            "<b>천장 내</b> 가양·발산·염창·우장산 구축 59㎡ (≈7~9억)",
            "<b>관찰</b> 등촌주공3·5·마곡 (천장 초과)",
            "토허 실거주 의무=정훈 계획과 일치(페널티 아님)",
        ]),
        ("27.2 업사이드", [
            "하이닉스 2026 영업이익 <b>250조+</b> 전망",
            "→ 27.2 PS 1인 수억 거론 → 천장 10.5억은 <b>보수적</b>일 수",
            "검단 매각 없이도 강서 상급 진입 여력 가능",
        ]),
    ]
    cards = ""
    for title, items in blocks:
        lis = "".join(f"<li>{x}</li>" for x in items)
        cards += f'<div class="dcard"><h4>{title}</h4><ul>{lis}</ul></div>'
    return (f'<section class="dash"><div class="dgrid">{cards}</div>'
            f'<div class="dcard wide"><h4>🔴 최근 핵심 트리거</h4>'
            f'<ul class="reds">{red_li}</ul></div></section>')


def build():
    sigs = load_all()
    reds = sum(1 for s in sigs if s.trigger == "red")
    yellows = sum(1 for s in sigs if s.trigger == "yellow")
    counts = {c: sum(1 for s in sigs if s.category == c) for c in CATEGORY}
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    ceil = config.ceilings_text()

    chips = "".join(
        f'<button class="chip" data-f="cat:{c}">{CATEGORY[c]} <em>{counts[c]}</em></button>'
        for c in CATEGORY)
    cards = "\n".join(card(s) for s in sigs)

    doc = TEMPLATE.format(
        ceil=esc(ceil), updated=updated, total=len(sigs), reds=reds, yellows=yellows,
        chips=chips, cards=cards, dashboard=dashboard(sigs),
    )
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(doc, encoding="utf-8")
    # .nojekyll : Pages 가 _ 파일 등을 그대로 서빙하도록
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site/index.html 생성: 시그널 {len(sigs)}건 (🔴{reds} 🟡{yellows})")


TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>정훈 부동산 시그널 · m-SIGNAL</title>
<style>
  :root {{
    --bg:#eef0f4; --surface:#ffffff; --navy:#1e2d44; --navy2:#33445f;
    --accent:#2f5d8a; --muted:#6b7480; --border:#e2e5ea;
    --red:#c0504d; --redbg:#f7ebeb; --amber:#b08628; --amberbg:#f7f1e0;
    --radius:14px; --shadow:0 1px 3px rgba(20,30,50,.06),0 4px 16px rgba(20,30,50,.04);
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; }}
  body {{
    background:var(--bg); color:var(--navy);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo",
      "Malgun Gothic","Noto Sans KR",Roboto,"Helvetica Neue",Arial,sans-serif;
    line-height:1.6; -webkit-font-smoothing:antialiased; font-size:15px;
  }}
  .wrap {{ max-width:760px; margin:0 auto; padding:0 16px 64px; }}
  header {{
    background:var(--navy); color:#fff; padding:28px 16px 22px;
    margin-bottom:18px; border-radius:0 0 20px 20px;
  }}
  header .inner {{ max-width:760px; margin:0 auto; }}
  header h1 {{ margin:0 0 4px; font-size:20px; letter-spacing:-.3px; }}
  header p {{ margin:0; color:#b9c4d6; font-size:13px; }}
  .stats {{ display:flex; gap:8px; margin-top:16px; flex-wrap:wrap; }}
  .stat {{ background:rgba(255,255,255,.08); border-radius:10px; padding:8px 12px; font-size:13px; }}
  .stat b {{ font-size:16px; display:block; }}
  .dash {{ margin-top:18px; }}
  .dgrid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
  @media (max-width:560px) {{ .dgrid {{ grid-template-columns:1fr; }} }}
  .dcard {{
    background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
    padding:14px 16px; box-shadow:var(--shadow);
  }}
  .dcard.wide {{ margin-top:12px; }}
  .dcard h4 {{ margin:0 0 8px; font-size:13px; color:var(--accent); letter-spacing:-.2px; }}
  .dcard ul {{ margin:0; padding:0; list-style:none; }}
  .dcard li {{ font-size:13px; color:var(--navy2); padding:3px 0; }}
  .dcard li + li {{ border-top:1px solid #f0f2f5; }}
  .dcard b {{ color:var(--navy); }}
  .reds li {{ display:flex; gap:8px; align-items:baseline; }}
  .reds .dd {{ color:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; flex:0 0 auto; }}
  .bar {{
    position:sticky; top:0; z-index:5; background:var(--bg);
    padding:12px 0 8px; margin-top:18px; display:flex; gap:8px; flex-wrap:wrap; align-items:center;
  }}
  .chip, .tog {{
    border:1px solid var(--border); background:var(--surface); color:var(--navy2);
    border-radius:999px; padding:6px 12px; font-size:13px; cursor:pointer;
    font-family:inherit; transition:all .12s;
  }}
  .chip em {{ font-style:normal; color:var(--muted); margin-left:2px; }}
  .chip.on, .tog.on {{ background:var(--navy); color:#fff; border-color:var(--navy); }}
  .chip.on em {{ color:#b9c4d6; }}
  #q {{
    flex:1; min-width:120px; border:1px solid var(--border); border-radius:999px;
    padding:7px 14px; font-size:13px; font-family:inherit; outline:none;
  }}
  #q:focus {{ border-color:var(--accent); }}
  .card {{
    background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
    padding:16px 16px 14px; margin-bottom:12px; box-shadow:var(--shadow);
  }}
  .card.hide {{ display:none; }}
  .meta {{ display:flex; align-items:center; gap:8px; margin-bottom:6px; flex-wrap:wrap; }}
  .date {{ color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }}
  .cat {{ font-size:12px; padding:2px 8px; border-radius:6px; background:#eef2f7; color:var(--accent); }}
  .cat.price {{ background:#eaf3ee; color:#2e7d52; }}
  .cat.macro {{ background:#f0eef7; color:#5b4b9a; }}
  .cat.semicon {{ background:#f3eee9; color:#9a6b3a; }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:6px; font-weight:600; }}
  .badge.red {{ background:var(--redbg); color:var(--red); }}
  .badge.yellow {{ background:var(--amberbg); color:var(--amber); }}
  .card h3 {{ margin:2px 0 6px; font-size:16px; line-height:1.4; letter-spacing:-.2px; }}
  .sum {{ margin:0 0 8px; color:var(--navy2); font-size:14px; }}
  .impl {{
    margin:0 0 10px; padding:9px 12px; background:#f6f8fb; border-left:3px solid var(--accent);
    border-radius:0 8px 8px 0; font-size:13.5px; color:var(--navy);
  }}
  .impl b {{ color:var(--accent); margin-right:6px; font-size:12px; }}
  .foot {{ display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; }}
  .src {{ color:var(--muted); font-size:12px; text-decoration:none; }}
  .src:hover {{ color:var(--accent); }}
  .tags {{ display:flex; gap:4px; flex-wrap:wrap; }}
  .tag {{ font-size:11px; color:var(--muted); background:#f2f4f7; border-radius:5px; padding:1px 7px; }}
  .empty {{ text-align:center; color:var(--muted); padding:40px 0; display:none; }}
  footer {{ text-align:center; color:var(--muted); font-size:12px; margin-top:24px; }}
</style>
</head>
<body>
<header><div class="inner">
  <h1>정훈 부동산 시그널 · m-SIGNAL</h1>
  <p>천장 {ceil} · 희주 단독 생애최초 · 업데이트 {updated}</p>
  <div class="stats">
    <div class="stat"><b>{total}</b>시그널</div>
    <div class="stat"><b>{reds}</b>🔴 즉시</div>
    <div class="stat"><b>{yellows}</b>🟡 주목</div>
  </div>
</div></header>

<div class="wrap">
  {dashboard}
  <div class="bar">
    <button class="chip on" data-f="all">전체</button>
    {chips}
    <button class="tog" data-t="red">🔴</button>
    <button class="tog" data-t="yellow">🟡</button>
    <input id="q" type="search" placeholder="검색 (단지·키워드)">
  </div>
  <div id="list">
{cards}
  </div>
  <div class="empty" id="empty">조건에 맞는 시그널이 없습니다.</div>
  <footer>apthub · 채팅 수동파싱 백데이터 · robots/약관 준수, 시장 데이터만</footer>
</div>

<script>
  var cat=null, trig=null, q="";
  var cards=[].slice.call(document.querySelectorAll('.card'));
  function apply(){{
    var shown=0;
    cards.forEach(function(c){{
      var ok=true;
      if(cat && c.dataset.cat!==cat) ok=false;
      if(trig && c.dataset.trig!==trig) ok=false;
      if(q && c.textContent.toLowerCase().indexOf(q)<0) ok=false;
      c.classList.toggle('hide',!ok); if(ok) shown++;
    }});
    document.getElementById('empty').style.display = shown? 'none':'block';
  }}
  document.querySelectorAll('.chip').forEach(function(b){{
    b.onclick=function(){{
      document.querySelectorAll('.chip').forEach(function(x){{x.classList.remove('on');}});
      b.classList.add('on');
      var f=b.dataset.f; cat = f==='all'? null : f.split(':')[1]; apply();
    }};
  }});
  document.querySelectorAll('.tog').forEach(function(b){{
    b.onclick=function(){{
      var t=b.dataset.t;
      if(trig===t){{ trig=null; b.classList.remove('on'); }}
      else {{ trig=t; document.querySelectorAll('.tog').forEach(function(x){{x.classList.remove('on');}}); b.classList.add('on'); }}
      apply();
    }};
  }});
  document.getElementById('q').oninput=function(e){{ q=e.target.value.toLowerCase().trim(); apply(); }};
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
