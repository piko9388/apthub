#!/usr/bin/env python3
"""정적 사이트 생성기 — data/seed/*.json → site/index.html.

메인: 부동산 정책·시장 동향(비개인화, 공개·판매용) — 핵심 요약 + 정책별 뉴스 요약.
보조: 개인 맞춤(정훈·희주) 탭 — 천장·자기자본·함의. 환경변수 APTHUB_PUBLIC=1 이면
보조 탭을 빌드에서 제외(완전 공개판매용).

자체완결 단일 HTML(인라인 CSS/JS). 외부 의존성·웹폰트 없음.
디자인: 톤다운 네이비, 시스템 폰트(맥/윈도/iOS/안드로이드 한영), 반응형.
실행: python3 scripts/build_site.py
"""
from __future__ import annotations

import html
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
BUILD_DATA = ROOT / ".build_data"
SITE = ROOT / "site"
PUBLIC_ONLY = os.environ.get("APTHUB_PUBLIC") == "1"  # 보조(개인) 탭 제외

shutil.rmtree(BUILD_DATA, ignore_errors=True)
os.environ["APTHUB_DATA_DIR"] = str(BUILD_DATA)
sys.path.insert(0, str(ROOT / "src"))

from apthub import config, manual, store  # noqa: E402

# 정책 이슈(토픽) — 메인의 정책별 그룹
TOPICS = [
    ("loan", "대출 규제", "DSR·LTV·6억 상한·생애최초·정책대출"),
    ("tax", "세제", "취득·양도·종부·증여세"),
    ("zone", "규제지역·토허", "투기과열·조정대상·토지거래허가구역"),
    ("supply", "공급·정비", "공급대책·재건축·교통호재"),
    ("rate", "금리·거시", "기준금리·코픽스·전세시장"),
    ("market", "시장 동향", "실거래·시세·신고가"),
]
TOPIC_LABEL = {k: v for k, v, _ in TOPICS}
TOPIC_DESC = {k: d for k, _, d in TOPICS}
TRIGGER = {"red": "🔴 즉시", "yellow": "🟡 주목", "none": ""}
SIDO_ORDER = ["서울", "경기", "인천", "전국"]

# 정책 이슈별 해석 코멘트(중립·일반 독자용)
TOPIC_NOTE = {
    "loan": "6억 상한 + 스트레스 DSR 3단계로 '소득 대비 상환능력'이 한도를 결정. 고소득·생애최초·출산 가구가 아니면 레버리지 진입장벽이 구조적으로 높아진 국면.",
    "tax": "1주택 비과세·종부세 기준이 12억으로 상향돼 실수요 1주택 부담은 완화. 다만 조정지역은 2년 거주의무가 붙어 '실거주 가능자'에게 유리. 혼인·출산 증여로 자산이전 통로 확대.",
    "zone": "10.15로 서울 전역이 규제지역+토지거래허가. 갭투자(전세 끼고 매수)는 사실상 차단되고 실거주 의무가 핵심 변수 → 비규제 인천·외곽으로 풍선효과.",
    "supply": "공급 확대는 2027년 이후 물량이라 단기 수급 완화 효과는 제한적. 재건축·노후계획도시·교통(GTX·신설노선)은 중장기 '계획→과정' 호재로 작동.",
    "rate": "기준금리 2.5% 동결 장기화 속 5월 매파 전환으로 인상 리스크 부각, 인하는 26 하반기~27 전망. 입주절벽·전세난이 매매 수요를 떠받치는 구조.",
    "market": "2025 서울 +11% 급등 후 규제에도 상급지·재건축 기대지역·역세권 중심 차별적 강세. 신축·대형은 천장가, 구축 중소형이 실수요 진입 구간.",
}


# 출처 신뢰도(도메인 기반) — m_signal_fetch.py 와 동일 기준
TRUST = {
    "공식": ["data.go.kr", "ecos.bok.or.kr", "opendart.fss.or.kr", "dart.fss.or.kr",
             "fss.or.kr", "reb.or.kr", "rt.molit.go.kr", "molit.go.kr", "korea.kr",
             "fsc.go.kr", "moef.go.kr", "nts.go.kr", "bok.or.kr", "myhome.go.kr",
             "applyhome.co.kr", "seoul.go.kr", "assembly.go.kr", "news.skhynix.co.kr",
             "kbland.kr", "kbstar.com"],
    "언론": ["hankyung.com", "mk.co.kr", "edaily.co.kr", "heraldcorp.com", "thelec.kr",
             "esgeconomy.com", "fnnews.com", "newsis.com", "asiatime.co.kr", "mt.co.kr",
             "housingherald.co.kr", "kukinews.com", "etoday.co.kr", "viva100.com",
             "dataeconomy.co.kr", "rcast.co.kr", "conslove.co.kr", "karnews.or.kr",
             "youthassembly.kr", "mygoyang.com", "elderlypress.co.kr", "jjmagazin.com",
             "reportera.co.kr", "globalepic.co.kr", "infogoodman.com", "kfenews.co.kr"],
}
TRUST_LABEL = {"공식": "● 공식", "언론": "◐ 언론", "추정": "○ 추정"}


def confidence_of(url: str, given: str = "") -> str:
    if given:
        for k in ("공식", "언론", "추정"):
            if k in given:
                return k
    host = ""
    if url:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    for tier, domains in TRUST.items():
        if any(d in host for d in domains):
            return tier
    return "추정"


def esc(s: str) -> str:
    return html.escape(s or "")


# ---------------------------------------------------------------- 지역 지표 집계
PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*억")
# 전용면적(㎡) 바로 뒤의 가격 — 실거래가만 안정적으로 포착(델타·증감액 제외)
AREA_PRICE_RE = re.compile(r"㎡[^0-9]{0,7}(\d+(?:\.\d+)?)\s*억")


def parse_sale_prices(sig) -> list[float]:
    """price 시그널에서 매매가(억) 추출. 전세·월세·정책수치 제외.
    1순위: '㎡ 뒤 가격' 패턴을 모두 포착(한 시그널의 복수 거래 반영).
    없으면 본문 첫 억-토큰 1개(제목 우선). 모두 3~60억 범위로 필터."""
    if sig.category != "price":
        return []
    if ("전세" in sig.title or "월세" in sig.title) and "매매" not in sig.title:
        return []
    text = sig.title + " " + sig.summary
    anchored = [float(m) for m in AREA_PRICE_RE.findall(text)]
    anchored = [v for v in anchored if 3.0 <= v <= 60.0]
    if anchored:
        return anchored
    for m in PRICE_RE.findall(text):
        try:
            v = float(m)
        except ValueError:
            continue
        if 3.0 <= v <= 60.0:
            return [v]
    return []


def region_metrics(sigs):
    """(시도, 시군구) → {n, prices[], latest, red}. 대표 지역(첫 매칭)에 귀속."""
    by = {}
    for s in sigs:
        if not s.region:
            continue
        sido = s.sido or "전국"
        if sido == "전국":
            continue
        key = (sido, s.region[0])
        d = by.setdefault(key, {"n": 0, "prices": [], "latest": "", "red": 0})
        d["n"] += 1
        d["prices"] += parse_sale_prices(s)
        if (s.date or "") > d["latest"]:
            d["latest"] = s.date or ""
        if s.trigger == "red":
            d["red"] += 1
    return by


def _fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def render_region_dashboard(sigs) -> str:
    by = region_metrics(sigs)
    # 시/도 요약 카드
    sido_cards = ""
    for sido in SIDO_ORDER:
        if sido == "전국":
            continue
        rows = [(k[1], v) for k, v in by.items() if k[0] == sido]
        if not rows:
            continue
        n = sum(v["n"] for _, v in rows)
        prices = [p for _, v in rows for p in v["prices"]]
        med = f"중위 {_fmt(median(prices))}억" if prices else "가격 표본 부족"
        rng = f" · {_fmt(min(prices))}~{_fmt(max(prices))}억" if prices else ""
        sido_cards += (f'<div class="dcard"><h4>{sido} <em>{len(rows)}개 구·시</em></h4>'
                       f'<ul><li>매매 시그널 <b>{n}</b>건</li>'
                       f'<li>{med}{rng}</li></ul></div>')

    # 시군구 지표 테이블 (시도→매매중위 desc)
    order = {s: i for i, s in enumerate(SIDO_ORDER)}
    items = sorted(by.items(),
                   key=lambda kv: (order.get(kv[0][0], 9),
                                   -(median(kv[1]["prices"]) if kv[1]["prices"] else 0)))
    rows_html = ""
    for (sido, dist), v in items:
        pr = v["prices"]
        if len(pr) >= 3:                       # 표본 3건 이상만 중위·시세대 표시(신뢰도)
            med = _fmt(median(pr))
            rng = f"{_fmt(min(pr))}~{_fmt(max(pr))}"
        else:
            med = "-"
            rng = f"표본 {len(pr)}" if pr else "-"
        red = f'<span class="rdot">🔴{v["red"]}</span>' if v["red"] else ""
        rows_html += (f'<tr data-sido="{sido}"><td>{esc(sido)}</td><td>{esc(dist)}</td>'
                      f'<td class="num">{v["n"]}</td><td class="num">{med}</td>'
                      f'<td class="num rng">{rng}</td><td>{red}</td>'
                      f'<td class="dt">{esc(v["latest"])}</td></tr>')

    return (f'<section class="dash"><div class="lead">지역 지표 — 매매가(억)·시그널 집계 '
            f'(수집 데이터 기반, 신고가·정책 트리거 포함)</div>'
            f'<div class="dgrid3">{sido_cards}</div>'
            f'<div class="tablewrap"><table class="metrics">'
            f'<thead><tr><th>시/도</th><th>시군구</th><th class="num">시그널</th>'
            f'<th class="num">매매중위<br>(억)</th><th class="num">시세대<br>(억)</th>'
            f'<th>긴급</th><th>최근</th></tr></thead><tbody>{rows_html}</tbody></table></div>'
            f'<p class="foot-note">※ 매매중위·시세대는 수집된 실거래·시세 시그널 본문에서 추출한 '
            f'표본 통계로 참고용이며, 공식 시세(부동산원·KB)와 차이가 있을 수 있습니다.</p></section>')


def load_all():
    for f in sorted((ROOT / "data" / "seed").glob("*.json")):
        manual.ingest_json(f.read_text(encoding="utf-8"), by_date=True)
    sigs = []
    for day in store.all_days():
        sigs += store.load_day(day)
    rank = {"red": 0, "yellow": 1, "none": 2}
    sigs.sort(key=lambda s: (s.date or "", rank.get(s.trigger, 2)), reverse=True)
    return sigs


def topic_of(sig) -> str | None:
    """정책 이슈(토픽) 분류. semicon(반도체·소득)은 메인 제외(개인 보조용)."""
    if sig.category == "semicon":
        return None
    t = (sig.title + " " + sig.summary).lower()

    def has(*ws):
        return any(w.lower() in t for w in ws)

    if has("토지거래", "토허", "투기과열", "조정대상", "규제지역"):
        return "zone"
    if has("취득세", "양도세", "종부세", "증여", "비과세", "세제"):
        return "tax"
    if has("dsr", "ltv", "주담대", "생애최초", "디딤돌", "보금자리", "신생아", "대출"):
        return "loan"
    if has("공급", "입주", "분양", "택지", "재건축", "정비", "노후계획도시",
           "스타필드", "cj", "착공", "gtx", "급행", "홍대선", "예타", "청약", "개발"):
        return "supply"
    if has("기준금리", "금통위", "코픽스", "금리", "전세", "통화", "한국은행"):
        return "rate"
    if sig.category == "macro":
        return "rate"
    return "market"


# ---------------------------------------------------------------- 카드 렌더
def card(sig, public: bool = True) -> str:
    trig = sig.trigger
    badge = f'<span class="badge {trig}">{TRIGGER[trig]}</span>' if trig != "none" else ""
    src = (f'<a class="src" href="{esc(sig.url)}" target="_blank" rel="noopener">{esc(sig.source)} ↗</a>'
           if sig.url else f'<span class="src">{esc(sig.source)}</span>')
    cmt = f'<p class="cmt"><b>해석</b> {esc(sig.comment)}</p>' if sig.comment else ""
    impl = ""
    if not public and sig.implication:
        impl = f'<p class="impl"><b>내 함의</b> {esc(sig.implication)}</p>'
    topic = topic_of(sig) or "market"
    sido = sig.sido or "전국"
    loc = sido + ((" · " + sig.region[0]) if sig.region else "")
    conf = confidence_of(sig.url, sig.confidence)
    conf_b = f'<span class="conf {conf}">{TRUST_LABEL[conf]}</span>'
    return f"""<article class="card" data-topic="{topic}" data-trig="{trig}" data-sido="{sido}">
  <div class="meta"><span class="date">{esc(sig.date or '')}</span>
    <span class="loc">{esc(loc)}</span>{conf_b}{badge}</div>
  <h3>{esc(sig.title)}</h3>
  <p class="sum">{esc(sig.summary)}</p>
  {cmt}{impl}
  <div class="foot">{src}</div>
</article>"""


# ---------------------------------------------------------------- 핵심 요약(메인)
def core_summary(sigs) -> str:
    reds = [s for s in sigs if s.trigger == "red"]
    latest_red = reds[0].title if reds else "—"
    blocks = [
        ("규제·대출", [
            "서울 전역 <b>투기과열·조정대상·토지거래허가구역</b>(10.15) — 취득 후 2년 실거주 의무",
            "수도권 주담대 <b>6억 상한</b>(6.27) · 무주택 LTV 40% / 생애최초 70%",
            "<b>스트레스 DSR 3단계</b> 가산 3.0% — 한도 15~20% 축소",
        ]),
        ("세제", [
            "1주택 양도세 비과세 12억 · 종부세 12억 공제",
            "조정지역 비과세는 <b>2년 보유+2년 실거주</b> 필수",
            "혼인·출산 증여공제 1억(기본 5천 별도) — 양가 최대 3억 무세",
        ]),
        ("금리·시장", [
            "기준금리 <b>2.50% 동결</b> 장기화 · 5월 <b>매파 전환</b>(인상 신호), 인하는 26 하반기~27 전망",
            "2025 서울 아파트 <b>+11.26%</b> · 규제 후에도 상급지·재건축 기대지역 강세",
            "2026 입주절벽(전년比 -40%)·전세 반등 → 매매 수요 전이",
        ]),
        ("공급·정비", [
            "9.7 대책: 2030까지 수도권 135만호(2027↑ 물량)",
            "노후계획도시·재건축 규제완화 기조 — 단기 입주효과는 제한",
            "토허·증빙 의무 확대로 갭투자 수요 차단",
        ]),
    ]
    cards = ""
    for title, items in blocks:
        lis = "".join(f"<li>{x}</li>" for x in items)
        cards += f'<div class="dcard"><h4>{title}</h4><ul>{lis}</ul></div>'
    return (f'<section class="dash"><div class="lead">최근 핵심 트리거 · '
            f'<b>{esc(latest_red)}</b></div>'
            f'<div class="dgrid">{cards}</div></section>')


# ---------------------------------------------------------------- 정책별 섹션(메인)
def policy_sections(sigs) -> str:
    out = ""
    for key, label, desc in TOPICS:
        items = [s for s in sigs if topic_of(s) == key]
        if not items:
            continue
        cards = "\n".join(card(s, public=True) for s in items)
        note = f'<p class="tnote"><b>해석</b> {esc(TOPIC_NOTE.get(key, ""))}</p>' if TOPIC_NOTE.get(key) else ""
        out += (f'<section class="topic" data-topic="{key}">'
                f'<div class="thead"><h3>{label} <em>{len(items)}</em></h3>'
                f'<span class="tdesc">{esc(desc)}</span></div>{note}{cards}</section>')
    return out


# ---------------------------------------------------------------- 개인 보조 탭
def personal_view(sigs) -> str:
    if PUBLIC_ONLY:
        return ""
    ceil = config.ceilings_text()
    blocks = [
        ("매수 타이밍 2안", [
            "<b>8월(희망#1)</b> 천장 ~8.5억 · 희주 단독 생애최초 LTV70%",
            "<b>27.2(희망#2)</b> 천장 ~10.5억 · 성과급(PS) 보강 후",
            "가격상승 vs 자기자본증가 트레이드오프",
        ]),
        ("자기자본 조달", [
            "대출 <b>6억 상한</b> 고정 → 8.5억 매수 시 갭 2.5억",
            "PS: 26.2 수령 세전 ~1.48억(2025 실적)",
            "증여: 혼인·출산 공제 양가 최대 3억 무세",
        ]),
        ("후보 단지", [
            "<b>천장 내</b> 가양·발산·염창·우장산 구축 59㎡",
            "<b>관찰</b> 등촌주공3·5·마곡(천장 초과)",
            "토허 실거주 의무=실거주 계획과 일치",
        ]),
        ("27.2 업사이드", [
            "하이닉스 2026 영업이익 <b>250조+</b> 전망",
            "27.2 PS 1인 수억 → 천장 10.5억은 보수적일 수",
            "검단 매각 없이 강서 상급 진입 여력 가능",
        ]),
    ]
    dcards = ""
    for title, items in blocks:
        lis = "".join(f"<li>{x}</li>" for x in items)
        dcards += f'<div class="dcard"><h4>{title}</h4><ul>{lis}</ul></div>'

    impl_li = ""
    for s in sigs:
        if s.implication:
            impl_li += (f'<li><span class="date">{esc(s.date or "")}</span>'
                        f'<b>{esc(s.title)}</b> — {esc(s.implication)}</li>')
    return (f'<section class="dash"><div class="lead">천장 {esc(ceil)} · 희주 단독 생애최초</div>'
            f'<div class="dgrid">{dcards}</div></section>'
            f'<section class="impls"><h3>전체 함의 ({sum(1 for s in sigs if s.implication)})</h3>'
            f'<ul>{impl_li}</ul></section>')


def budreadnam_view() -> str:
    """부읽남 38강 체계적 재분류·해석 참고 섹션."""
    import json
    path = ROOT / "config" / "budreadnam-frames.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    cards = ""
    for th in data["themes"]:
        prins = "".join(f"<li>{esc(p)}</li>" for p in th["principles"])
        cards += (f'<article class="frame"><div class="meta">'
                  f'<span class="loc">{esc(th["lectures"])}</span></div>'
                  f'<h3>{esc(th["title"])}</h3><ul class="prin">{prins}</ul>'
                  f'<p class="cmt"><b>2026</b> {esc(th["note2026"])}</p></article>')
    return (f'<div class="lead">{esc(data["source"])}</div>{cards}')


def build():
    sigs = load_all()
    reds = sum(1 for s in sigs if s.trigger == "red")
    yellows = sum(1 for s in sigs if s.trigger == "yellow")
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    chips = '<button class="chip on" data-f="all">전체</button>'
    for key, label, _ in TOPICS:
        n = sum(1 for s in sigs if topic_of(s) == key)
        if n:
            chips += f'<button class="chip" data-f="{key}">{label} <em>{n}</em></button>'

    # 지역(시/도) 필터 칩
    region_chips = '<button class="rchip on" data-r="all">전국·전체</button>'
    main_sigs = [s for s in sigs if topic_of(s)]
    for sido in SIDO_ORDER:
        n = sum(1 for s in main_sigs if (s.sido or "전국") == sido)
        if n:
            region_chips += f'<button class="rchip" data-r="{sido}">{sido} <em>{n}</em></button>'

    personal = personal_view(sigs)
    personal_tab = "" if PUBLIC_ONLY else '<button class="tab" data-v="personal">개인 맞춤</button>'
    personal_block = "" if PUBLIC_ONLY else f'<div id="view-personal" class="view">{personal}</div>'

    doc = TEMPLATE.format(
        updated=updated, total=len(sigs), reds=reds, yellows=yellows,
        region_dash=render_region_dashboard(sigs),
        summary=core_summary(sigs), chips=chips, region_chips=region_chips,
        sections=policy_sections(sigs),
        personal_tab=personal_tab, personal_block=personal_block,
        budreadnam=budreadnam_view(),
    )
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(doc, encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    # 레포 루트에도 출력 — Pages Source가 'Deploy from a branch'(root)여도
    # README 대신 대시보드가 홈으로 서빙되도록 보장(이중화).
    (ROOT / "index.html").write_text(doc, encoding="utf-8")
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")
    mode = "공개판매(개인 제외)" if PUBLIC_ONLY else "개인 보조 포함"
    print(f"index.html 생성(site/ + 루트): 시그널 {len(sigs)}건 (🔴{reds} 🟡{yellows}) · {mode}")


TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>m-SIGNAL · 부동산 정책 동향</title>
<meta name="description" content="대출·세제·규제·공급·금리 등 부동산 정책을 정책별로 크롤링·요약하는 동향 리포트.">
<style>
  :root {{
    --bg:#eef0f4; --surface:#fff; --navy:#1e2d44; --navy2:#33445f;
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
  .wrap {{ max-width:780px; margin:0 auto; padding:0 16px 64px; }}
  header {{ background:var(--navy); color:#fff; padding:26px 16px 20px; border-radius:0 0 20px 20px; }}
  header .inner {{ max-width:780px; margin:0 auto; }}
  header h1 {{ margin:0 0 4px; font-size:20px; letter-spacing:-.3px; }}
  header p {{ margin:0; color:#b9c4d6; font-size:13px; }}
  .stats {{ display:flex; gap:8px; margin-top:14px; flex-wrap:wrap; }}
  .stat {{ background:rgba(255,255,255,.08); border-radius:10px; padding:7px 12px; font-size:13px; }}
  .stat b {{ font-size:16px; margin-right:4px; }}
  .tabs {{ display:flex; gap:6px; margin:16px 0 4px; }}
  .tab {{ flex:0 0 auto; border:1px solid var(--border); background:var(--surface); color:var(--navy2);
    border-radius:10px 10px 0 0; padding:9px 16px; font-size:14px; font-weight:600; cursor:pointer; font-family:inherit; }}
  .tab.on {{ background:var(--navy); color:#fff; border-color:var(--navy); }}
  .view {{ display:none; }} .view.on {{ display:block; }}
  .lead {{ font-size:13px; color:var(--muted); margin:14px 2px 10px; }}
  .lead b {{ color:var(--red); }}
  .dash {{ margin-top:8px; }}
  .dgrid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
  .dgrid3 {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:14px; }}
  @media (max-width:560px) {{ .dgrid, .dgrid3 {{ grid-template-columns:1fr; }} }}
  .tablewrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:var(--radius);
    background:var(--surface); box-shadow:var(--shadow); }}
  table.metrics {{ width:100%; border-collapse:collapse; font-size:13px; min-width:520px; }}
  table.metrics th {{ background:#f4f6f9; color:var(--navy2); font-weight:600; text-align:left;
    padding:9px 10px; border-bottom:1px solid var(--border); font-size:12px; white-space:nowrap; }}
  table.metrics td {{ padding:8px 10px; border-bottom:1px solid #f0f2f5; }}
  table.metrics tr:last-child td {{ border-bottom:none; }}
  table.metrics .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  table.metrics .rng {{ color:var(--muted); }}
  table.metrics .dt {{ color:var(--muted); font-size:11px; white-space:nowrap; }}
  .rdot {{ color:var(--red); font-size:11px; }}
  .foot-note {{ color:var(--muted); font-size:11px; margin:8px 2px 0; }}
  .dcard {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
    padding:14px 16px; box-shadow:var(--shadow); }}
  .dcard h4 {{ margin:0 0 8px; font-size:13px; color:var(--accent); }}
  .dcard ul {{ margin:0; padding:0; list-style:none; }}
  .dcard li {{ font-size:13px; color:var(--navy2); padding:3px 0; }}
  .dcard li + li {{ border-top:1px solid #f0f2f5; }}
  .dcard b {{ color:var(--navy); }}
  .rbar {{ display:flex; gap:8px; flex-wrap:wrap; margin:14px 0 2px; }}
  .rchip {{ border:1px solid var(--border); background:var(--surface); color:var(--navy2);
    border-radius:8px; padding:6px 12px; font-size:13px; font-weight:600; cursor:pointer; font-family:inherit; }}
  .rchip em {{ font-style:normal; color:var(--muted); margin-left:2px; font-weight:400; }}
  .rchip.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .rchip.on em {{ color:#dce7f2; }}
  .bar {{ position:sticky; top:0; z-index:5; background:var(--bg); padding:12px 0 8px;
    display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
  .chip {{ border:1px solid var(--border); background:var(--surface); color:var(--navy2);
    border-radius:999px; padding:6px 12px; font-size:13px; cursor:pointer; font-family:inherit; }}
  .chip em {{ font-style:normal; color:var(--muted); margin-left:2px; }}
  .chip.on {{ background:var(--navy); color:#fff; border-color:var(--navy); }}
  .chip.on em {{ color:#b9c4d6; }}
  .tog {{ border:1px solid var(--border); background:var(--surface); border-radius:999px;
    padding:6px 12px; font-size:13px; cursor:pointer; font-family:inherit; }}
  .tog.on {{ background:var(--navy); color:#fff; border-color:var(--navy); }}
  #q {{ flex:1; min-width:120px; border:1px solid var(--border); border-radius:999px;
    padding:7px 14px; font-size:13px; font-family:inherit; outline:none; }}
  #q:focus {{ border-color:var(--accent); }}
  .topic {{ margin-top:18px; }}
  .thead {{ display:flex; align-items:baseline; gap:10px; margin:0 2px 10px; flex-wrap:wrap; }}
  .thead h3 {{ margin:0; font-size:16px; }}
  .thead h3 em {{ font-style:normal; color:var(--muted); font-size:13px; }}
  .tdesc {{ color:var(--muted); font-size:12px; }}
  .tnote {{ background:#eef3f8; border:1px solid #dce6f0; border-radius:10px; padding:10px 13px;
    margin:0 0 12px; font-size:13px; color:var(--navy2); }}
  .tnote b {{ color:var(--accent); margin-right:6px; font-size:12px; }}
  .cmt {{ margin:0 0 8px; padding:8px 12px; background:#f3f6f4; border-left:3px solid #4e8a6a;
    border-radius:0 8px 8px 0; font-size:13px; color:var(--navy2); }}
  .cmt b {{ color:#3a6b51; margin-right:6px; font-size:12px; }}
  .frame {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
    padding:14px 16px; margin-bottom:10px; box-shadow:var(--shadow); }}
  .frame h3 {{ margin:4px 0 8px; font-size:16px; }}
  .frame .prin {{ margin:0 0 8px; padding-left:18px; }}
  .frame .prin li {{ font-size:13.5px; color:var(--navy2); padding:1px 0; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
    padding:14px 16px 12px; margin-bottom:10px; box-shadow:var(--shadow); }}
  .card.hide {{ display:none; }}
  .meta {{ display:flex; align-items:center; gap:8px; margin-bottom:4px; flex-wrap:wrap; }}
  .date {{ color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }}
  .loc {{ font-size:11px; color:var(--accent); background:#eef2f7; border-radius:5px; padding:1px 7px; }}
  .conf {{ font-size:11px; border-radius:5px; padding:1px 7px; }}
  .conf.공식 {{ color:#2e7d52; background:#eaf3ee; }}
  .conf.언론 {{ color:#9a6b3a; background:#f3eee9; }}
  .conf.추정 {{ color:var(--muted); background:#f0f1f3; }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:6px; font-weight:600; }}
  .badge.red {{ background:var(--redbg); color:var(--red); }}
  .badge.yellow {{ background:var(--amberbg); color:var(--amber); }}
  .card h3 {{ margin:2px 0 6px; font-size:15.5px; line-height:1.4; letter-spacing:-.2px; }}
  .sum {{ margin:0 0 8px; color:var(--navy2); font-size:14px; }}
  .impl {{ margin:0 0 8px; padding:8px 12px; background:#f6f8fb; border-left:3px solid var(--accent);
    border-radius:0 8px 8px 0; font-size:13px; }}
  .impl b {{ color:var(--accent); margin-right:6px; font-size:12px; }}
  .foot {{ display:flex; justify-content:flex-end; }}
  .src {{ color:var(--muted); font-size:12px; text-decoration:none; }}
  .src:hover {{ color:var(--accent); }}
  .impls {{ margin-top:18px; }}
  .impls h3 {{ font-size:15px; margin:0 2px 8px; }}
  .impls ul {{ margin:0; padding:0; list-style:none; }}
  .impls li {{ background:var(--surface); border:1px solid var(--border); border-radius:10px;
    padding:10px 12px; margin-bottom:8px; font-size:13px; color:var(--navy2); }}
  .impls .date {{ margin-right:6px; }}
  .impls b {{ color:var(--navy); }}
  .empty {{ text-align:center; color:var(--muted); padding:36px 0; display:none; }}
  footer {{ text-align:center; color:var(--muted); font-size:12px; margin-top:24px; }}
</style>
</head>
<body>
<header><div class="inner">
  <h1>m-SIGNAL · 부동산 정책 동향</h1>
  <p>대출·세제·규제·공급·금리 정책을 정책별로 크롤링·요약 · 업데이트 {updated}</p>
  <div class="stats">
    <div class="stat"><b>{total}</b>시그널</div>
    <div class="stat"><b>{reds}</b>🔴 즉시</div>
    <div class="stat"><b>{yellows}</b>🟡 주목</div>
  </div>
</div></header>

<div class="wrap">
  <div class="tabs">
    <button class="tab on" data-v="policy">대시보드</button>
    <button class="tab" data-v="frames">부읽남 참고</button>
    {personal_tab}
  </div>

  <div id="view-policy" class="view on">
    {region_dash}
    {summary}
    <div class="rbar">{region_chips}</div>
    <div class="bar">
      {chips}
      <button class="tog" data-t="red">🔴</button>
      <button class="tog" data-t="yellow">🟡</button>
      <input id="q" type="search" placeholder="검색 (정책·지역·단지·키워드)">
    </div>
    {sections}
    <div class="empty" id="empty">조건에 맞는 시그널이 없습니다.</div>
  </div>

  <div id="view-frames" class="view">{budreadnam}</div>

  {personal_block}

  <footer>m-SIGNAL · 부동산 정책 동향 리포트 · RSS/Open API·약관 준수, 시장·정책 데이터</footer>
</div>

<script>
  // 탭
  document.querySelectorAll('.tab').forEach(function(t){{
    t.onclick=function(){{
      document.querySelectorAll('.tab').forEach(function(x){{x.classList.remove('on');}});
      document.querySelectorAll('.view').forEach(function(x){{x.classList.remove('on');}});
      t.classList.add('on');
      document.getElementById('view-'+t.dataset.v).classList.add('on');
    }};
  }});
  // 정책 동향 필터
  var topic=null, trig=null, sido=null, q="";
  var cards=[].slice.call(document.querySelectorAll('#view-policy .card'));
  var sections=[].slice.call(document.querySelectorAll('#view-policy .topic'));
  function apply(){{
    var shown=0;
    cards.forEach(function(c){{
      var ok=true;
      if(topic && c.dataset.topic!==topic) ok=false;
      if(trig && c.dataset.trig!==trig) ok=false;
      if(sido && c.dataset.sido!==sido) ok=false;
      if(q && c.textContent.toLowerCase().indexOf(q)<0) ok=false;
      c.classList.toggle('hide',!ok); if(ok) shown++;
    }});
    sections.forEach(function(s){{
      var vis=s.querySelectorAll('.card:not(.hide)').length;
      s.style.display = vis? '':'none';
    }});
    document.getElementById('empty').style.display = shown? 'none':'block';
  }}
  document.querySelectorAll('.rchip').forEach(function(b){{
    b.onclick=function(){{
      document.querySelectorAll('.rchip').forEach(function(x){{x.classList.remove('on');}});
      b.classList.add('on');
      sido = b.dataset.r==='all'? null : b.dataset.r; apply();
    }};
  }});
  document.querySelectorAll('.chip').forEach(function(b){{
    b.onclick=function(){{
      document.querySelectorAll('.chip').forEach(function(x){{x.classList.remove('on');}});
      b.classList.add('on');
      topic = b.dataset.f==='all'? null : b.dataset.f; apply();
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
