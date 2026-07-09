#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""정적 사이트 생성기 — data/seed/*.json → site/index.html(+ 레포 루트 index.html).

UI: 좌측 지역 드릴다운 메뉴 · 상단 검색/정렬/필터 · 중앙 카드 리스트 · 지도(Leaflet).
데이터(시그널/지역집계)를 인라인 JSON으로 임베드하고 클라이언트에서 동적 렌더링.
APTHUB_PUBLIC=1 이면 개인(정훈) 보조 탭 제외.

실행: python3 scripts/build_site.py
"""
from __future__ import annotations

import html
import json
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
PUBLIC_ONLY = os.environ.get("APTHUB_PUBLIC") == "1"

shutil.rmtree(BUILD_DATA, ignore_errors=True)
os.environ["APTHUB_DATA_DIR"] = str(BUILD_DATA)
sys.path.insert(0, str(ROOT / "src"))

from apthub import config, manual, store  # noqa: E402

SIDO_ORDER = ["서울", "경기", "인천", "전국"]
CAT_LABEL = {"policy": "정책·세제", "price": "시세·실거래", "macro": "금리·거시", "semicon": "반도체"}

TRUST = {
    "공식": ["data.go.kr", "ecos.bok.or.kr", "opendart.fss.or.kr", "dart.fss.or.kr",
             "fss.or.kr", "reb.or.kr", "rt.molit.go.kr", "molit.go.kr", "korea.kr",
             "fsc.go.kr", "moef.go.kr", "nts.go.kr", "bok.or.kr", "myhome.go.kr",
             "applyhome.co.kr", "seoul.go.kr", "assembly.go.kr", "news.skhynix.co.kr",
             "kbland.kr", "kbstar.com", "nanet.go.kr"],
    "언론": ["hankyung.com", "mk.co.kr", "edaily.co.kr", "heraldcorp.com", "thelec.kr",
             "esgeconomy.com", "fnnews.com", "newsis.com", "asiatime.co.kr", "mt.co.kr",
             "housingherald.co.kr", "kukinews.com", "etoday.co.kr", "viva100.com",
             "dataeconomy.co.kr", "rcast.co.kr", "conslove.co.kr", "karnews.or.kr",
             "youthassembly.kr", "mygoyang.com", "news1.kr", "newdaily.co.kr",
             "choicestock.co.kr", "incheonin.com", "news-wa.com", "mstoday.co.kr",
             "seouleconews.com", "tradingeconomics.com", "kfenews.co.kr",
             # 주요 종합·경제지/통신사 보강(정상 언론이 '추정'으로 잘못 분류되던 문제 수정)
             "yna.co.kr", "yonhapnews.co.kr", "chosun.com", "joongang.co.kr", "donga.com",
             "sedaily.com", "hani.co.kr", "khan.co.kr", "newspim.com", "asiae.co.kr",
             "dailian.co.kr", "thebell.co.kr", "bizhankook.com", "imaeil.com",
             "joongboo.com", "elderlypress.co.kr", "ytn.co.kr", "sbs.co.kr",
             "kbs.co.kr", "imbc.com", "businesspost.co.kr", "moneys.co.kr",
             "joseilbo.com", "sentv.co.kr", "tf.co.kr", "ohmynews.com", "pressian.com",
             "segye.com", "kmib.co.kr", "munhwa.com", "hankookilbo.com", "wowtv.co.kr",
             "mbn.co.kr", "sisajournal.com", "ajunews.com", "g-enews.com", "ebn.co.kr",
             "inews24.com", "zdnet.co.kr", "biz.chosun.com"],
}


def confidence_of(url: str, given: str = "") -> str:
    """신뢰도 등급. '공식'은 정부·기관 1차 출처 도메인일 때만 인정 —
    언론이 인용한 공식 통계는 2차 인용이므로 '언론'으로 강등(배지 신뢰도 정직화)."""
    host = ""
    if url:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    is_official = any(d in host for d in TRUST["공식"])
    is_press = any(d in host for d in TRUST["언론"])
    if given:
        g = next((k for k in ("공식", "언론", "추정") if k in given), "")
        if g == "공식":
            # 공식 주장은 1차 출처(정부·기관) 도메인일 때만 인정. 아니면 언론 인용으로 강등.
            return "공식" if is_official else "언론"
        if g:
            return g
    if is_official:
        return "공식"
    if is_press:
        return "언론"
    return "추정"


# 수도권 시군구 중심 좌표 (지도 마커용, 근사치)
COORDS = {
    "서울": {
        "강남구": [37.495, 127.063], "서초구": [37.484, 127.033], "송파구": [37.505, 127.115],
        "강동구": [37.530, 127.124], "용산구": [37.532, 126.990], "마포구": [37.566, 126.901],
        "성동구": [37.563, 127.037], "광진구": [37.538, 127.082], "영등포구": [37.526, 126.896],
        "동작구": [37.512, 126.939], "양천구": [37.517, 126.866], "강서구": [37.551, 126.850],
        "구로구": [37.495, 126.887], "금천구": [37.457, 126.895], "관악구": [37.478, 126.951],
        "동대문구": [37.574, 127.040], "중랑구": [37.606, 127.092], "성북구": [37.589, 127.016],
        "강북구": [37.640, 127.011], "도봉구": [37.668, 127.047], "노원구": [37.654, 127.056],
        "은평구": [37.603, 126.929], "서대문구": [37.579, 126.937], "종로구": [37.573, 126.979],
        "중구": [37.564, 126.997],
    },
    "경기": {
        "성남시": [37.420, 127.127], "과천시": [37.429, 126.988], "하남시": [37.539, 127.215],
        "광명시": [37.479, 126.865], "수원시": [37.263, 127.029], "용인시": [37.241, 127.178],
        "안양시": [37.394, 126.957], "고양시": [37.658, 126.832], "남양주시": [37.636, 127.216],
        "화성시": [37.199, 126.831], "부천시": [37.504, 126.766], "의왕시": [37.345, 126.968],
        "군포시": [37.361, 126.935], "김포시": [37.615, 126.715], "구리시": [37.594, 127.130],
        "시흥시": [37.380, 126.803], "평택시": [36.992, 127.113], "안산시": [37.322, 126.831],
    },
    "인천": {
        "서구": [37.545, 126.676], "연수구": [37.410, 126.678], "남동구": [37.447, 126.731],
        "부평구": [37.507, 126.722], "계양구": [37.537, 126.738], "미추홀구": [37.464, 126.650],
        "중구": [37.474, 126.622], "동구": [37.474, 126.643],
    },
}

PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*억")
AREA_PRICE_RE = re.compile(r"㎡[^0-9]{0,7}(\d+(?:\.\d+)?)\s*억")
DELTA_KW = ("대비", "상승", "하락", "올라", "내려", "오른", "내린", "뛰", "급등", "급락", "연속")
PRICE_MIN, PRICE_MAX = 3.0, 200.0   # 수도권 아파트 현실 범위(억) — 초고가 한강변 포함


def parse_sale_prices(sig) -> list[float]:
    if getattr(sig, "kind", "news") == "data":
        return []        # 지표(지수·거래량 등)는 실거래 중위 표본에서 제외
    if sig.category != "price":
        return []
    if ("전세" in sig.title or "월세" in sig.title) and "매매" not in sig.title:
        return []
    text = sig.title + " " + sig.summary
    anchored = [float(m) for m in AREA_PRICE_RE.findall(text)]      # ㎡ 뒤 가격(신뢰)
    anchored = [v for v in anchored if PRICE_MIN <= v <= PRICE_MAX]
    if anchored:
        return anchored
    for m in PRICE_RE.finditer(text):                              # 폴백: 첫 비-델타 토큰
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if not (PRICE_MIN <= v <= PRICE_MAX):
            continue
        pre = text[max(0, m.start() - 6):m.start()]
        if any(k in pre for k in DELTA_KW):                        # '대비 13억 상승' 델타 배제
            continue
        return [v]
    return []


TOPIC_KEYS = ("zone", "tax", "loan", "supply", "rate", "market")


def topic_of(sig) -> str | None:
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


def load_all():
    for f in sorted((ROOT / "data" / "seed").glob("*.json")):
        manual.ingest_json(f.read_text(encoding="utf-8"), by_date=True)
    seen, sigs = set(), []
    for day in store.all_days():
        for s in store.load_day(day):
            if s.id in seen:        # 교차일 중복 제거(같은 id가 여러 날짜 파일에)
                continue
            seen.add(s.id)
            sigs.append(s)
    rank = {"red": 0, "yellow": 1, "none": 2}
    sigs.sort(key=lambda s: (s.date or "", rank.get(s.trigger, 2)), reverse=True)
    return sigs


def client_signal(s) -> dict:
    prices = parse_sale_prices(s)
    return {
        "date": s.date or "",
        "title": s.title, "summary": s.summary, "source": s.source, "url": s.url,
        "cat": s.category or "", "sido": (s.sido or "전국"),
        "gu": (s.region[0] if s.region else ""),
        "trig": s.trigger, "conf": confidence_of(s.url, s.confidence),
        "comment": s.comment, "topic": (topic_of(s) or ""),
        "price": (round(median(prices), 1) if prices else None),
        "kind": getattr(s, "kind", "news"),
        "metric": getattr(s, "metric", ""), "value": getattr(s, "value", None),
        "unit": getattr(s, "unit", ""),
        "aband": getattr(s, "area_band", ""), "pband": getattr(s, "price_band", ""),
        "pyeong": getattr(s, "pyeong_price", None), "hh": getattr(s, "households", None),
    }


def region_agg(sigs) -> list[dict]:
    by: dict[tuple, dict] = {}
    for s in sigs:
        if not s.region:
            continue
        sido = s.sido or "전국"
        if sido == "전국":
            continue
        key = (sido, s.region[0])
        d = by.setdefault(key, {"n": 0, "prices": [], "red": 0})
        d["n"] += 1
        d["prices"] += parse_sale_prices(s)
        if s.trigger == "red":
            d["red"] += 1
    out = []
    for (sido, gu), v in by.items():
        c = COORDS.get(sido, {}).get(gu)
        med = round(median(v["prices"]), 1) if len(v["prices"]) >= 3 else None
        out.append({"sido": sido, "gu": gu, "n": v["n"], "red": v["red"], "med": med,
                    "lat": (c[0] if c else None), "lng": (c[1] if c else None)})
    return out


def personal_html(sigs) -> str:
    if PUBLIC_ONLY:
        return ""
    ceil = config.ceilings_text()
    blocks = [
        ("매수 타이밍 2안", ["<b>8월(희망#1)</b> 천장 ~8.5억 · 희주 단독 생애최초 LTV70%",
                         "<b>27.2(희망#2)</b> 천장 ~10.5억 · 성과급(PS) 보강 후",
                         "가격상승 vs 자기자본증가 트레이드오프"]),
        ("자기자본 조달", ["대출 <b>6억 상한</b> 고정 → 8.5억 매수 시 갭 2.5억",
                       "PS 26.2 세전 ~1.48억 + 증여 양가 최대 3억 무세",
                       "검단 보유분 가치상승이 점프 자기자본에 기여"]),
        ("후보 단지", ["<b>천장 내</b> 가양·발산·염창·우장산 구축 59㎡",
                    "<b>관찰</b> 등촌주공3·5·마곡(천장 초과)",
                    "토허 실거주 의무=실거주 계획과 일치"]),
        ("27.2 업사이드", ["하이닉스 2026 영업이익 <b>250조+</b> 전망",
                        "27.2 PS 1인 수억 → 천장 10.5억은 보수적일 수",
                        "8월 vs 27.2 = 금리·PS·천장 3박자 비교"]),
    ]
    cards = ""
    for t, items in blocks:
        lis = "".join(f"<li>{x}</li>" for x in items)
        cards += f'<div class="dcard"><h4>{t}</h4><ul>{lis}</ul></div>'
    impls = ""
    for s in sigs:
        if s.implication:
            impls += (f'<li><span class="d">{html.escape(s.date or "")}</span>'
                      f'<b>{html.escape(s.title)}</b> — {html.escape(s.implication)}</li>')
    return (f'<div class="lead">천장 {html.escape(ceil)} · 희주 단독 생애최초</div>'
            f'<div class="dgrid">{cards}</div>'
            f'<h3 class="sub">전체 함의</h3><ul class="impls">{impls}</ul>')


def frames_html() -> str:
    path = ROOT / "config" / "budreadnam-frames.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = f'<div class="lead">{html.escape(data["source"])}</div>'
    for th in data["themes"]:
        prins = "".join(f"<li>{html.escape(p)}</li>" for p in th["principles"])
        out += (f'<article class="frame"><div class="lec">{html.escape(th["lectures"])}</div>'
                f'<h3>{html.escape(th["title"])}</h3><ul>{prins}</ul>'
                f'<p class="cmt"><b>2026</b> {html.escape(th["note2026"])}</p></article>')
    return out


def _sido_median(sigs, sido) -> str:
    ps = []
    for s in sigs:
        if (s.sido or "전국") == sido:
            ps += parse_sale_prices(s)
    return f"{round(median(ps), 1)}" if ps else "—"


def category_board_html(sigs, reviews) -> str:
    """종합 동향 상단 — 분야별 분석 보드(건수+연도분할+한줄 리뷰+대표 트리거)."""
    order = [("policy", "정책·세제"), ("price", "시세·실거래"),
             ("macro", "금리·거시"), ("semicon", "반도체")]
    rank = {"red": 0, "yellow": 1, "none": 2}
    cards = []
    for key, lbl in order:
        cs = [s for s in sigs if s.category == key]
        if not cs:
            continue
        y25 = sum(1 for s in cs if (s.date or "").startswith("2025"))
        y26 = sum(1 for s in cs if (s.date or "").startswith("2026"))
        reds = sum(1 for s in cs if s.trigger == "red")
        review = reviews.get(key, "")
        # 모멘텀: 2026 월평균(6개월) vs 2025 월평균(12개월) → 가속/둔화
        r25, r26 = y25 / 12.0, y26 / 6.0
        if r26 > r25 * 1.15:
            mom = '<span class="cbdir up" title="2026 발생 빈도 가속">▲ 가속</span>'
        elif r26 < r25 * 0.85:
            mom = '<span class="cbdir down" title="2026 발생 빈도 둔화">▼ 둔화</span>'
        else:
            mom = ''
        # 대표 시그널 2건 — 🔴 우선, 그다음 최신
        top = sorted(cs, key=lambda s: (rank.get(s.trigger, 2), _neg_date(s.date)))[:2]
        lis = "".join(
            f'<li><span class="yb">{"🔴" if s.trigger=="red" else ("🟡" if s.trigger=="yellow" else "·")}</span>'
            + (f'<a href="{html.escape(s.url)}" target="_blank" rel="noopener">{html.escape(s.title)}</a>'
               if s.url else html.escape(s.title)) + '</li>'
            for s in top)
        cards.append(
            f'<div class="cbcard"><div class="cbh"><b>{lbl}</b>'
            f'<span class="cbn">{len(cs)}건'
            + (f' · <span class="lr">🔴 {reds}</span>' if reds else '') + mom + '</span></div>'
            + (f'<div class="cbrev">{html.escape(review)}</div>' if review else '')
            + (f'<ul class="ylist">{lis}</ul>' if lis else '')
            + '</div>')
    if not cards:
        return ""
    return ('<section class="rsec"><h3>분야별 분석</h3>'
            '<div class="cbgrid">' + "".join(cards) + '</div></section>')


def _neg_date(d):
    """최신 우선 정렬용 키(문자열 날짜를 역순)."""
    return tuple(-int(x) for x in (d or "0000-00-00").replace("-", " ").split())


def _latest_metric(dat, metric, sido, official_only=False):
    """metric+sido 시계열의 최신값과 직전값을 (cur, prev)로 반환.
    official_only=True 면 신뢰도 '공식'(1차 출처) 값만 대상."""
    xs = [s for s in dat if getattr(s, "metric", None) == metric
          and (s.sido or "전국") == sido and getattr(s, "value", None) is not None]
    if official_only:
        xs = [s for s in xs if confidence_of(s.url, s.confidence) == "공식"]
    xs.sort(key=lambda s: s.date or "")
    if not xs:
        return None, None
    return xs[-1], (xs[-2] if len(xs) > 1 else None)


# 비율 기준 세대수 — 수집기 KAPT_MIN_HH와 동일 env로 동기화(기본 300, 분자·분모 정합)
RATIO_MIN_HH = int(os.environ.get("KAPT_MIN_HH", "300"))


def synth_lease_ratio(dat, cat=None):
    """공공임대 비율(%) — 분자·분모를 같은 기준(300세대 이상 단지)으로 맞춰 시도별 산출.
    분모: K-apt '아파트 세대수' 지표(300세대+ 단지 합계 — 의무관리대상이라 사실상 전수).
    분자: LH 임대 카탈로그에서 같은 기준(세대수≥300)으로 합산.
    기준이 맞는 분자(카탈로그)가 없으면 비율을 산출하지 않는다 — 기준 불일치 비율은
    수치가 그럴듯해도 오도라 발행 금지. 자체 산출값 → ○추정."""
    from apthub.schema import Signal
    out = []
    for sido in ("서울", "인천", "경기"):
        den, _ = _latest_metric(dat, "아파트 세대수", sido)
        if not den or not den.value:
            continue
        ls = [c for c in (cat or []) if c.get("tenure") == "임대" and c.get("sido") == sido
              and (c.get("households") or 0) >= RATIO_MIN_HH]
        if not ls:
            continue  # 정합 분자 없음 → 미산출
        num_val = sum(c["households"] for c in ls)
        num_n = len(ls)
        lh_m, _ = _latest_metric(dat, "공공임대 세대수", sido)
        date = max(den.date or "", (lh_m.date or "") if lh_m else "") or None
        pct = round(num_val / den.value * 100, 2)
        out.append(Signal(
            title=f"{sido} 공공임대 비율 {pct}% ({RATIO_MIN_HH}세대+ 기준: 임대 {int(num_val):,} ÷ 아파트 {int(den.value):,}세대)",
            source="APT-SIGNAL 산출(LH 임대 ÷ K-apt 아파트 세대수)",
            summary=f"{sido} LH 노출 공공임대 {int(num_val):,}세대({num_n}개 {RATIO_MIN_HH}세대+ 단지)를 "
                    f"같은 기준의 전체 아파트 {int(den.value):,}세대로 나눈 비율(분자·분모 모두 "
                    f"{RATIO_MIN_HH}세대 이상 단지, 정합). 분자가 '현재 공고·모집 노출분'이라 "
                    f"실제 재고 기준 비율의 하한값이다.",
            url="https://www.data.go.kr/data/15058453/openapi.do",
            date=date,
            category="policy", sido=sido, confidence="추정",
            kind="data", metric="공공임대 비율", value=pct, unit="%"))
    return out


_CONFMARK = {"공식": "●", "언론": "◐", "추정": "○"}


def _kpi(dat, metric, sido, label, suffix):
    """KPI 카드 1개 — 최신값 + 방향 화살표·색. 공식(1차 출처) 값 우선."""
    cur, prev = _latest_metric(dat, metric, sido, official_only=True)
    if not cur:  # 공식 값이 없으면 최신값 사용하되 신뢰도 배지로 명시
        cur, prev = _latest_metric(dat, metric, sido)
    if not cur:
        return ""
    v = cur.value
    if prev and prev.value is not None:
        d = v - prev.value
        cls, arr = ("up", "▲") if d > 0.005 else ("down", "▼") if d < -0.005 else ("flat", "→")
    else:
        cls, arr = ("up", "▲") if v > 0.02 else ("down", "▼") if v < -0.02 else ("flat", "→")
    sign = "+" if (v > 0 and "/주" in suffix) else ""  # 변동률만 부호 표기(금리 등 수준값 제외)
    cf = confidence_of(cur.url, cur.confidence)
    cfmark = f'<span class="kpi-cf {cf}" title="출처 신뢰도: {cf} · {html.escape(cur.date or "")}">{_CONFMARK[cf]}</span>'
    return (f'<div class="kpi"><div class="kpi-k">{html.escape(label)} {cfmark}</div>'
            f'<div class="kpi-v {cls}">{arr} {sign}{round(v,2)}{suffix}</div></div>')


def trend_headline(dat, verdict="") -> str:
    """동향 헤드라인 — '오늘의 결론' 1문장 + 핵심 KPI 4개(30초 판단용)."""
    kpis = [
        _kpi(dat, "주간 매매변동률", "서울", "서울 매매", "%/주"),
        _kpi(dat, "주간 전세변동률", "서울", "서울 전세", "%/주"),
        _kpi(dat, "기준금리", "전국", "기준금리", "%"),
        '<div class="kpi"><div class="kpi-k">대출규제</div>'
        '<div class="kpi-v flat" title="6·28 가계부채 관리방안">주담대 6억 상한</div></div>',
    ]
    kpis = [k for k in kpis if k]
    if not kpis and not verdict:
        return ""
    vd = (f'<div class="thl-vd"><span class="thl-vd-b">오늘의 결론</span> {html.escape(verdict)}</div>'
          if verdict else "")
    return ('<div class="thl"><div class="thl-t">📈 지금 시장은</div>'
            f'{vd}<div class="kpigrid">{"".join(kpis)}</div></div>')


def report_html(sigs, stats, dat=None) -> str:
    path = ROOT / "config" / "report.json"
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8")
    for k, v in stats.items():
        raw = raw.replace("{" + k + "}", str(v))
    rep = json.loads(raw)
    out = (f'<div class="rep-head"><h2>{html.escape(rep["title"])}</h2>'
           f'<div class="asof">{rep["asof"]}</div></div>')
    # 1) 동향 헤드라인(최신 지표) → 2) 분야별 보드 → 3) '한눈에' → 4) 상세는 접기
    if dat is not None:
        out += trend_headline(dat, rep.get("verdict", ""))
    out += category_board_html(sigs, rep.get("category_review", {}))

    def sec_html(sec):
        when = f'<span class="when">{html.escape(sec["when"])}</span>' if sec.get("when") else ""
        s = f'<section class="rsec"><h3>{html.escape(sec["h"])}{when}</h3>'
        t = sec.get("type", "para")
        if t == "table":
            cols = "".join(f"<th>{html.escape(c)}</th>" for c in sec["columns"])
            body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                           for row in sec["rows"])
            s += (f'<div class="tw"><table class="rt"><thead><tr>{cols}</tr></thead>'
                  f'<tbody>{body}</tbody></table></div>')
        elif t == "bullets":
            s += "<ul>" + "".join(f"<li>{it}</li>" for it in sec["items"]) + "</ul>"
        else:
            s += "".join(f'<p class="rp">{it}</p>' for it in sec["items"])
        return s + "</section>"

    secs = rep["sections"]
    if secs:
        out += sec_html(secs[0])  # '한눈에'는 기본 노출
    if len(secs) > 1:
        rest = "".join(sec_html(s) for s in secs[1:])
        out += (f'<details class="rmore"><summary>상세 분석 펼치기 — 규제·시장·지역·금리·반도체 ({len(secs)-1})</summary>'
                f'{rest}</details>')
    out += f'<p class="rdisc">{html.escape(rep.get("disclaimer", ""))}</p>'
    return out


def load_complex():
    """data/complex/*.json — 단지 카탈로그(아파트 정보 탭). 제원·실거래 명시 등록 단지."""
    out = []
    cdir = ROOT / "data" / "complex"
    if not cdir.exists():
        return out
    for f in sorted(cdir.glob("*.json")):
        try:
            arr = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(arr, list):
                out += arr
        except Exception:
            continue
    return out


SIDO_ALIAS = {"인천광역시": "인천", "인천시": "인천", "서울특별시": "서울", "서울시": "서울",
              "경기도": "경기", "수도권 전체": "수도권"}
_INDEX_RATE = {"매매가격지수 변동률", "전세가격지수 변동률"}


def _demote_to_news(s, note=""):
    """지표 트랙에서 뉴스 트랙으로 강등(시계열 오염 방지). 정보는 뉴스로 보존."""
    s.kind = "news"
    for attr in ("metric", "value", "unit", "area_band", "price_band"):
        if hasattr(s, attr):
            setattr(s, attr, None)


def normalize_signals(sigs):
    """지표 정합성 정규화(리뷰 P0/P1 반영):
    - sido 별칭 통일(인천광역시→인천 등) — 지역 카운트·필터·지도 정상화
    - 매매/전세 가격지수 변동률: 부동산원 아파트 단일 기준만 지표로 — 주택종합·KB는 뉴스 강등
    - 입주물량: 연간(연말) 스냅샷만 지표로 — 상반기/하반기/누적/월간은 뉴스 강등
    - 분양가 단위 이상치(평당 7,000만원 초과=천원/㎡ 혼입) 뉴스 강등
    - 미분양·준공후 미분양 단위 '가구'→'호' 통일
    - 매수우위지수: 0~200 범위 밖 오기재 제거
    """
    for s in sigs:
        if s.sido in SIDO_ALIAS:
            s.sido = SIDO_ALIAS[s.sido]
        if getattr(s, "kind", "news") != "data":
            continue
        m = getattr(s, "metric", None)
        txt = (s.title or "") + (s.summary or "") + (s.source or "")
        # 지수 변동률 기준 통일: 주택종합·KB는 아파트 단일축에서 분리(뉴스로)
        if m in _INDEX_RATE:
            if "주택종합" in txt or "종합주택" in txt or "KB" in txt.upper():
                _demote_to_news(s)
                continue
        # 입주물량: 연간 스냅샷만 유지
        if m == "입주물량":
            if any(k in txt for k in ("상반기", "하반기", "1~4월", "누적", "H1", "H2", "월 ")):
                _demote_to_news(s)
                continue
        # 분양가 평당(만원) 단위 이상치 제거
        if m == "분양가" and isinstance(getattr(s, "value", None), (int, float)) and s.value > 7000:
            _demote_to_news(s)
            continue
        # 미분양 단위 통일
        if m in ("미분양", "준공후 미분양") and getattr(s, "unit", None) in ("가구", "세대"):
            s.unit = "호"
        # 매수우위지수 범위 검증(0~200)
        if m == "매수우위지수" and isinstance(getattr(s, "value", None), (int, float)) \
                and not (0 <= s.value <= 200):
            _demote_to_news(s)
            continue
    return sigs


def build():
    sigs = normalize_signals(load_all())
    # 두 트랙 분리: news(기사·정성) vs data(공식 지표·정량)
    news = [s for s in sigs if getattr(s, "kind", "news") != "data"]
    dat = [s for s in sigs if getattr(s, "kind", "news") == "data"]
    cat = load_complex()
    dat += synth_lease_ratio(dat, cat)  # 공공임대 비율(300세대+ 기준, 임대÷아파트) 파생 지표
    reds = sum(1 for s in news if s.trigger == "red")
    yellows = sum(1 for s in news if s.trigger == "yellow")
    _dates = sorted(s.date for s in sigs if s.date and s.date <= datetime.now().strftime("%Y-%m-%d"))
    data = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "today": datetime.now().strftime("%Y-%m-%d"),
        "latest": (_dates[-1] if _dates else ""),
        "total": len(news), "reds": reds, "yellows": yellows,
        "data_count": len(dat), "public": PUBLIC_ONLY,
        "sig": [client_signal(s) for s in news],
        "met": [client_signal(s) for s in dat],
        "regions": region_agg(news),
        "cat": cat,
    }
    dates = sorted(s.date for s in news if s.date)
    def _ym(d):
        return f"{d[:4]}.{int(d[5:7])}" if d else ""
    # 기준 기간: 초기 희소 표본(아웃라이어)을 제외하고 최근 시그널 95%가 들어오는
    # 핵심 구간만 표기 — 2024~2026 같은 과대 기간으로 추세가 묻히는 것 방지
    period = ""
    if dates:
        cut = int(len(dates) * 0.05)              # 앞쪽 5% 절단
        core = dates[cut:] or dates
        period = f"{_ym(core[0])}~{_ym(dates[-1])}"
    stats = {
        "total": len(news), "reds": reds, "yellows": yellows,
        "updated": data["updated"], "period": period,
        "data_count": len(dat),
        "seoul_med": _sido_median(news, "서울"),
        "gg_med": _sido_median(news, "경기"),
        "ic_med": _sido_median(news, "인천"),
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    doc = (TEMPLATE
           .replace("__DATA__", blob)
           .replace("__REPORT__", report_html(news, stats, dat))
           .replace("__PERSONAL__", personal_html(news))
           .replace("__FRAMES__", frames_html())
           .replace("__PUBLIC__", "1" if PUBLIC_ONLY else "0"))
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(doc, encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    (ROOT / "index.html").write_text(doc, encoding="utf-8")
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"index.html 생성(site/ + 루트): 뉴스 {len(news)}건 (🔴{reds} 🟡{yellows}) "
          f"· 지표 {len(dat)}건 · {'공개판매' if PUBLIC_ONLY else '개인 포함'}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>APT-SIGNAL · 수도권 부동산 동향</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<style>
  :root{
    color-scheme:light dark;
    /* 팔레트(단순화): 화이트 배경 + 검정/그레이 텍스트가 기본, 네이비·레드는 강조 한정.
       --navy=근검정(1차 텍스트/제목), --navy2=진회색(2차 텍스트), --muted=중회색(메타).
       네이비 '강조 배경'은 --brand(헤더·선택상태), 파랑 '링크/인터랙션'은 --accent 로 한정. */
    --bg:#f4f5f6;--surface:#fff;--navy:#18191b;--navy2:#3d4247;--accent:#2b5aa0;
    --muted:#71767c;--border:#e4e6e9;--red:#c0392b;--redbg:#fbe9e7;--amber:#8a6a17;
    --amberbg:#f6f0de;--radius:12px;--shadow:0 1px 2px rgba(0,0,0,.05),0 3px 12px rgba(20,24,30,.05);
    --side:240px;--up:#c0392b;--down:#2e7d52;--brand:#1e2d44;--tint:#f8f9fa;--tint2:#eceef1;
  }
  /* 다크 테마 — 토큰만 재정의. --navy=근백색 텍스트, --brand=네이비 강조(다크용 소폭 밝게) */
  :root[data-theme="dark"]{
    --bg:#14161a;--surface:#1d2026;--navy:#ecedf0;--navy2:#c4c8ce;--accent:#7aa2db;
    --muted:#969ba3;--border:#2c313a;--red:#e0736c;--redbg:#2c1a18;--amber:#cfa24a;
    --amberbg:#241d10;--shadow:0 1px 3px rgba(0,0,0,.45),0 8px 22px rgba(0,0,0,.35);
    --up:#e0736c;--down:#5cb98a;--brand:#26384f;--tint:#242832;--tint2:#2b313b;
  }
  @media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
    --bg:#14161a;--surface:#1d2026;--navy:#ecedf0;--navy2:#c4c8ce;--accent:#7aa2db;
    --muted:#969ba3;--border:#2c313a;--red:#e0736c;--redbg:#2c1a18;--amber:#cfa24a;
    --amberbg:#241d10;--shadow:0 1px 3px rgba(0,0,0,.45),0 8px 22px rgba(0,0,0,.35);
    --up:#e0736c;--down:#5cb98a;--brand:#26384f;--tint:#242832;--tint2:#2b313b;
  }}
  *{box-sizing:border-box}html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--navy);font-size:14px;line-height:1.55;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}
  a{color:inherit}
  /* 접근성: 키보드 포커스 가시화 + 모션 최소화 */
  :focus-visible{outline:2.5px solid var(--accent);outline-offset:2px;border-radius:4px}
  [role="button"],.navitem,.rchip,.chip,.gu,.cp.loc,.wkhead{cursor:pointer}
  .skip{position:absolute;left:8px;top:-48px;z-index:100;background:var(--surface);color:var(--navy);
    border:1px solid var(--border);border-radius:8px;padding:8px 14px;font-weight:600;transition:top .12s}
  .skip:focus{top:8px}
  @media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
  /* 헤더 */
  header{position:fixed;top:0;left:0;right:0;height:56px;background:var(--brand);color:#fff;
    display:flex;align-items:center;gap:12px;padding:0 16px;z-index:1000}
  header h1{font-size:16px;margin:0;letter-spacing:.2px;font-weight:700;white-space:nowrap}
  header .tag{font-size:12px;color:#c2cee0;white-space:nowrap}
  header .stat{font-size:12px;color:#cdd6e4;margin-left:6px}
  #q{flex:1;max-width:520px;margin-left:auto;border:none;border-radius:999px;padding:9px 14px;font-size:13px;font-family:inherit;outline:none}
  #q:focus-visible{outline:2.5px solid #fff;outline-offset:1px}
  #burger{display:none;background:none;border:none;color:#fff;font-size:20px;cursor:pointer;padding:4px}
  #theme{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#fff;font-size:15px;
    cursor:pointer;width:34px;height:34px;min-width:34px;border-radius:9px;margin-left:8px;flex:0 0 auto}
  #theme:hover{background:rgba(255,255,255,.2)}
  /* 좌측 메뉴 */
  aside{position:fixed;top:56px;bottom:0;left:0;width:var(--side);background:var(--surface);
    border-right:1px solid var(--border);overflow-y:auto;padding:10px 0;z-index:900;display:flex;flex-direction:column}
  /* 메뉴 상단 요약 */
  .sidesum{margin:4px 12px 6px;padding:11px 12px;border-radius:10px;
    background:var(--brand);color:#fff}
  .sidesum .ss-t{font-size:12px;font-weight:600;opacity:.92}
  .sidesum .ss-b{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-top:4px}
  .sidesum .ss-n{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
  .sidesum .ss-n i{font-size:12px;font-weight:400;font-style:normal;opacity:.85;margin-left:1px}
  .sidesum .ss-r{font-size:11px;background:rgba(255,255,255,.18);border-radius:6px;padding:2px 7px}
  .sidesum .ss-d{font-size:11px;background:rgba(255,255,255,.14);border-radius:6px;padding:2px 7px}
  .sidesum .ss-u{font-size:10.5px;opacity:.8;margin-top:5px;font-variant-numeric:tabular-nums}
  /* 메뉴 하단 */
  .sidefoot{margin-top:auto;padding:8px 12px 4px;border-top:1px solid var(--border)}
  .sidefoot .guide{background:none;border:none;box-shadow:none;padding:0;margin:0}
  .sidefoot .guide summary{padding:6px 0;font-size:12.5px}
  .sidefoot .guide[open] summary{border-bottom:1px solid var(--border)}
  .sidefoot .guide ul{margin:8px 0 6px;padding-left:16px}
  .sidefoot .guide li{font-size:11px;line-height:1.5;padding:2px 0;color:var(--navy2)}
  .madeby{font-size:11px;color:var(--muted);padding:8px 2px 2px;line-height:1.6}
  .madeby b{color:var(--navy2)}.madeby a{color:var(--accent);text-decoration:none}
  .navsec{padding:6px 12px}
  .navttl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin:8px 6px 4px}
  .navitem{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:13.5px;color:var(--navy2)}
  .navitem:hover{background:var(--tint2)}
  .navitem.on{background:var(--brand);color:#fff}
  .navitem .c{font-size:11px;color:var(--muted)}
  .navitem.on .c{color:#b9c4d6}
  .gu{padding-left:22px;font-size:13px}
  .gu.hidden{display:none}
  .caret{display:inline-block;width:14px;color:var(--muted);transition:transform .15s}
  .caret.open{transform:rotate(90deg)}
  /* 본문 */
  main{margin-left:var(--side);margin-top:56px;padding:14px 16px 60px;max-width:1100px}
  .regbar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:0 0 10px}
  .regbar .rchip{border:1px solid var(--border);background:var(--surface);color:var(--navy2);border-radius:8px;
    padding:6px 13px;font-size:12.5px;cursor:pointer;font-family:inherit;font-weight:600}
  .regbar .rchip.on{background:var(--brand);color:#fff;border-color:var(--brand)}
  .regbar .rchip em{font-style:normal;font-weight:400;opacity:.7;margin-left:4px;font-size:11px}
  .tbl{font-size:11px;color:var(--muted);font-weight:600;margin-right:2px}
  .toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
  .chip{border:1px solid var(--border);background:var(--surface);color:var(--navy2);border-radius:999px;
    padding:6px 12px;font-size:12.5px;cursor:pointer;font-family:inherit}
  .chip.on{background:var(--brand);color:#fff;border-color:var(--navy)}
  .chip em{font-style:normal;color:var(--muted);margin-left:3px}.chip.on em{color:#b9c4d6}
  select{border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12.5px;font-family:inherit;background:var(--surface)}
  .crumb{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:2px 2px 12px}
  .crumb .cp{display:inline-flex;align-items:center;gap:5px;font-size:12px;border-radius:999px;
    padding:4px 11px;background:var(--surface);border:1px solid var(--border);color:var(--navy2)}
  .crumb .cp.loc{background:var(--brand);color:#fff;border-color:var(--navy);font-weight:600}
  .crumb .cp.loc i{color:#b9c4d6;font-style:normal;font-weight:400}
  .crumb .cp.n{font-variant-numeric:tabular-nums}.crumb .cp.n b{color:var(--navy)}
  .crumb .cp.red{background:var(--redbg);color:var(--red);border-color:#f3d4d4}
  .crumb .cp.yellow{background:var(--amberbg);color:var(--amber);border-color:#f0e4c4}
  .crumb .creset{display:inline-flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;
    border-radius:999px;padding:4px 11px;background:#fff;border:1px solid var(--border);color:var(--muted);font-family:inherit}
  .crumb .creset:hover{border-color:var(--accent);color:var(--accent)}
  #map{height:340px;border-radius:var(--radius);border:1px solid var(--border);margin-bottom:14px;background:var(--tint2)}
  .maphint{font-size:11px;color:var(--muted);margin:-10px 2px 12px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:13px 15px 11px;margin-bottom:9px;box-shadow:var(--shadow)}
  .meta{display:flex;align-items:center;gap:7px;margin-bottom:3px;flex-wrap:wrap}
  .date{color:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}
  .loc{font-size:11px;color:var(--navy2);background:var(--tint2);border-radius:5px;padding:1px 7px;cursor:pointer}
  .conf{font-size:11px;padding:0 1px;color:var(--muted)}
  .conf.공식{color:#2e7d52}.conf.언론{color:#9a6b3a}.conf.추정{color:var(--muted)}
  .fut{font-size:10px;font-weight:700;color:var(--amber);background:var(--amberbg);
    border-radius:4px;padding:1px 5px;margin-right:5px;vertical-align:1px}
  .bd{font-size:11px;padding:1px 7px;border-radius:5px;font-weight:600}
  .bd.red{background:var(--redbg);color:var(--red)}.bd.yellow{background:var(--amberbg);color:var(--amber)}
  .pr{font-size:11px;color:#2e7d52;font-weight:600;font-variant-numeric:tabular-nums}
  .card h3{margin:2px 0 5px;font-size:15px;line-height:1.4;letter-spacing:-.2px}
  .sum{margin:0 0 7px;color:var(--navy2);font-size:13.5px}
  .cmt{margin:0 0 7px;padding:7px 11px;background:var(--tint);border-left:3px solid #4e8a6a;border-radius:0 7px 7px 0;font-size:12.5px;color:var(--navy2)}
  .cmt b{color:#3a6b51;margin-right:5px;font-size:11px}
  .impl{margin:0 0 7px;padding:7px 11px;background:var(--tint);border-left:3px solid var(--accent);border-radius:0 7px 7px 0;font-size:12.5px}
  .impl b{color:var(--accent);margin-right:5px;font-size:11px}
  .foot{display:flex;justify-content:flex-end}.src{color:var(--muted);font-size:11.5px;text-decoration:none}.src:hover{color:var(--accent)}
  .empty{text-align:center;color:var(--muted);padding:40px 0}
  /* 패널(부읽남/개인) */
  .panel{display:none}.panel.on{display:block}
  /* 동향 리포트 */
  .rep-head{margin:2px 2px 14px}
  .rep-head h2{margin:0 0 4px;font-size:20px;letter-spacing:-.4px}
  .rep-head .asof{font-size:12px;color:var(--muted)}
  .guide{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:2px 16px;margin-bottom:11px;box-shadow:var(--shadow)}
  .guide summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--navy2);padding:11px 0;list-style:none}
  .guide summary::-webkit-details-marker{display:none}
  .guide summary::after{content:"▸";float:right;color:var(--muted);transition:transform .15s;display:inline-block}
  .guide[open] summary::after{transform:rotate(90deg)}
  .guide[open] summary{border-bottom:1px solid var(--border)}
  .guide ul{margin:10px 0 12px;padding-left:18px}
  .guide li{font-size:12.5px;color:var(--navy2);padding:3px 0;line-height:1.55}
  .guide b{color:var(--navy)}
  /* 분야별 분석 보드 */
  .cbgrid{display:grid;grid-template-columns:1fr 1fr;gap:11px}
  @media(max-width:620px){.cbgrid{grid-template-columns:1fr}}
  .cbcard{border:1px solid var(--border);border-radius:10px;padding:11px 13px;background:var(--tint)}
  .cbh{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:5px}
  .cbh b{font-size:14px;color:var(--navy)}
  .cbn{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}.cbn i{font-style:normal;opacity:.8}
  .cbrev{font-size:12px;color:var(--navy2);line-height:1.5;margin:2px 0 7px;padding-left:9px;border-left:3px solid var(--accent)}
  .ylist{list-style:none;margin:0;padding:0}
  .ylist li{font-size:12px;color:var(--navy2);padding:3px 0;border-top:1px solid var(--border);line-height:1.45}
  .ylist li:first-child{border-top:none}
  .ylist .yb{font-size:10px;margin-right:3px}
  .ylist .yd{color:var(--muted);font-size:10.5px;font-variant-numeric:tabular-nums;margin-right:3px}
  .ylist a{color:var(--navy2);text-decoration:none}.ylist a:hover{color:var(--accent);text-decoration:underline}
  .rsec{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:14px 17px;margin-bottom:11px;box-shadow:var(--shadow)}
  .rsec h3{margin:0 0 9px;font-size:15.5px;color:var(--navy);letter-spacing:-.2px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
  .rsec h3 .when{font-size:11px;font-weight:400;color:var(--muted)}
  .tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
  table.rt{border-collapse:collapse;width:100%;font-size:12.5px;min-width:0}
  table.rt th{background:var(--tint2);color:var(--navy2);text-align:left;padding:7px 10px;border-bottom:1px solid var(--border);white-space:nowrap;font-size:11.5px}
  table.rt td{padding:7px 10px;border-bottom:1px solid var(--border);color:var(--navy2);vertical-align:top}
  table.rt td:first-child{white-space:nowrap;font-weight:600;color:var(--navy)}
  table.rt tr:last-child td{border-bottom:none}
  table.rt b{color:var(--navy)}
  .rsec ul{margin:0;padding-left:18px}
  .rsec li{font-size:13.5px;color:var(--navy2);padding:3px 0;line-height:1.6}
  .rsec .rp{margin:0 0 8px;font-size:13.5px;color:var(--navy2);line-height:1.65}
  .rsec .rp:last-child{margin-bottom:0}
  .rsec b{color:var(--navy)}
  .rmore{margin:0 0 4px}
  .rmore>summary{cursor:pointer;list-style:none;font-size:13px;font-weight:600;color:var(--navy2);
    padding:11px 16px;background:var(--surface);border:1px solid var(--border);border-radius:10px;
    box-shadow:var(--shadow);user-select:none}
  .rmore>summary::-webkit-details-marker{display:none}
  .rmore>summary::before{content:"▸ ";color:var(--muted)}
  .rmore[open]>summary{margin-bottom:12px}.rmore[open]>summary::before{content:"▾ "}
  .rmore>summary:hover{border-color:var(--accent)}
  .rdisc{font-size:11px;color:var(--muted);margin:6px 2px 0;line-height:1.5}
  /* 동향 모니터링 */
  .msec{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:14px 17px;margin-bottom:11px;box-shadow:var(--shadow)}
  .msec h3{margin:0 0 11px;font-size:14.5px;color:var(--navy);letter-spacing:-.2px}
  .mgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:9px}
  .mtile{border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--tint)}
  .mt-h{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
  .mt-n{font-size:12px;color:var(--navy2);font-weight:600}
  .mt-v{font-size:18px;font-weight:700;color:var(--navy);text-decoration:none;font-variant-numeric:tabular-nums;white-space:nowrap}
  .mt-v:hover{color:var(--accent)}
  .mt-d{font-size:10.5px;color:var(--muted);margin-top:4px}
  .mt-rg{color:var(--muted);font-variant-numeric:tabular-nums;margin-left:2px}
  .spark{display:block;width:100%;height:40px;margin:7px 0 1px}
  .sp-line{fill:none;stroke:var(--muted);stroke-width:1.6;vector-effect:non-scaling-stroke}
  .sp-dot{fill:var(--muted);opacity:.4}
  .sp-last{fill:var(--navy)}
  .sp-zero{stroke:var(--border);stroke-width:1;stroke-dasharray:3 3;vector-effect:non-scaling-stroke}
  .sp-line.up{stroke:var(--up)}.sp-line.down{stroke:var(--down)}.sp-line.flat{stroke:var(--muted)}
  .sp-end{stroke-width:2.4;vector-effect:non-scaling-stroke;stroke:var(--navy)}
  .sp-end.up{stroke:var(--up)}.sp-end.down{stroke:var(--down)}.sp-end.flat{stroke:var(--muted)}
  .mt-cf{font-size:10px;font-weight:700;margin-right:3px;white-space:nowrap}
  .mt-cf.공식{color:#2e7d52}.mt-cf.언론{color:#9a6b3a}.mt-cf.추정{color:var(--muted)}
  .clegend{font-size:11px;color:var(--muted);line-height:1.6;margin:2px 2px 12px}
  .clegend .mt-cf{font-size:10.5px}
  .kpi-cf{font-size:10px;vertical-align:1px}
  .kpi-cf.공식{color:#2e7d52}.kpi-cf.언론{color:#9a6b3a}.kpi-cf.추정{color:var(--muted)}
  .dlt{font-size:11px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
  .dlt.up{color:var(--up)}.dlt.down{color:var(--down)}.dlt.flat{color:var(--muted)}
  /* 동향 헤드라인 배너 */
  .thl{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:13px 18px;margin:0 0 12px}
  .thl .thl-t{font-size:11.5px;color:var(--muted);font-weight:600;letter-spacing:.3px;margin-bottom:8px}
  .thl .thl-vd{font-size:14.5px;line-height:1.6;color:var(--navy);font-weight:600;margin-bottom:12px}
  .thl .thl-vd-b{display:inline-block;font-size:11px;font-weight:700;color:#fff;background:var(--accent);
    border-radius:5px;padding:1px 7px;margin-right:6px;vertical-align:1px}
  .thl .kpigrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
  @media(min-width:560px){.thl .kpigrid{grid-template-columns:repeat(4,1fr)}}
  .thl .kpi{background:var(--tint);border:1px solid var(--border);border-radius:9px;padding:8px 11px}
  .thl .kpi-k{font-size:11px;color:var(--muted);font-weight:600;margin-bottom:3px}
  .thl .kpi-v{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.25}
  .thl .kpi-v.up{color:var(--up)}.thl .kpi-v.down{color:var(--down)}.thl .kpi-v.flat{color:var(--navy)}
  .rec-dir{font-size:11px;font-weight:700;border-radius:5px;padding:1px 7px;margin-left:6px}
  .rec-dir.up{color:var(--up);background:var(--redbg)}.rec-dir.down{color:var(--down);background:#eaf3ee}
  .rec-dir.flat{color:var(--muted);background:var(--tint2)}
  .cbdir{font-style:normal;font-weight:700;margin-left:5px}.cbdir.up{color:var(--up)}.cbdir.down{color:var(--down)}
  .recgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
  .rec{border:1px solid var(--border);border-radius:10px;padding:11px 13px;background:var(--tint)}
  .rec-h{font-size:13.5px;font-weight:700;color:var(--navy);margin-bottom:6px;display:flex;justify-content:space-between;align-items:baseline;gap:8px}
  .rec-vol{font-size:11px;font-weight:400;color:var(--muted);font-variant-numeric:tabular-nums}
  .rec-b{font-size:12px;color:var(--navy2);margin:3px 0}
  .rec-i{display:inline-block;font-size:10px;font-weight:700;color:#fff;background:var(--accent);border-radius:5px;padding:1px 6px;margin-right:5px}
  .rec-i.news{background:#7a6a3a}
  .rec-b b{color:var(--navy)}
  .rec-v{font-size:11.5px;color:var(--navy2);margin-top:7px;padding-top:7px;border-top:1px dashed var(--border);line-height:1.5}
  .rec-v b{color:var(--red)}
  /* 밴드 분석 */
  .bsec{font-size:14px;color:var(--navy);margin:14px 2px 8px;font-weight:700}
  .bsec .btag{font-size:10.5px;font-weight:600;color:var(--muted);background:var(--amberbg);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:2px}
  .rt td .bn{font-size:9.5px;color:var(--muted);margin-left:3px;vertical-align:1px}
  /* 아파트 정보 */
  .aptgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
  .aptcard{border:1px solid var(--border);border-radius:10px;padding:11px 13px;background:var(--tint)}
  .apth{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
  .apth b{font-size:14px;color:var(--navy)}
  .aptloc{font-size:10.5px;color:var(--navy2);background:var(--tint2);border-radius:5px;padding:1px 6px}
  .apt-m{font-size:11px;color:var(--muted);margin:4px 0 6px;font-variant-numeric:tabular-nums}
  .apt-l{list-style:none;margin:0;padding:0}
  .apt-l li{font-size:12px;color:var(--navy2);padding:3px 0;border-top:1px solid var(--border)}
  .apt-l li:first-child{border-top:none}
  .apt-l a{color:var(--navy2);text-decoration:none}.apt-l a:hover{color:var(--accent)}
  .apt-l .ad{color:var(--muted);font-size:10.5px;font-variant-numeric:tabular-nums;margin-right:4px}
  .apt-l b{color:var(--navy)}
  .apt-j{font-size:11px;color:#2e7d52;margin-top:5px}
  .aptcard.reg{border-color:var(--accent);background:var(--tint)}
  .apt-spec{font-size:11.5px;color:var(--navy);font-weight:600;margin:4px 0 2px}
  .ten{display:inline-block;font-size:10.5px;font-weight:700;color:#2c6e8f;background:#e6f0f5;border-radius:5px;padding:1px 7px;margin:3px 0}
  .ten.old{color:var(--amber);background:var(--amberbg)}
  .apt-dev{font-size:11px;color:var(--accent);margin-top:6px}
  /* 월별 정리 */
  .lgd{font-size:11px;color:var(--muted)}
  .lr{color:var(--red);font-weight:600}.ly{color:var(--amber);font-weight:600}
  .wk{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 15px;margin-bottom:9px;box-shadow:var(--shadow)}
  .wkh{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
  .wwk{display:inline-flex;align-items:center;font-size:12px;font-weight:700;letter-spacing:.2px;
    color:#fff;background:var(--brand);border-radius:7px;padding:3px 10px;font-variant-numeric:tabular-nums}
  .wkh .up{font-size:11px;font-weight:700;color:var(--accent)}
  .wkh .dn{font-size:11px;font-weight:700;color:var(--muted)}
  .wkh .eq{font-size:11px;color:var(--muted)}
  .wkh b{font-size:13.5px;font-variant-numeric:tabular-nums;font-weight:600}
  .wkn{font-size:11.5px;color:var(--muted);margin-left:auto}
  .bar{height:6px;border-radius:4px;background:var(--tint2);margin:8px 0 2px;overflow:hidden}
  .bar span{display:block;height:100%;background:var(--brand);border-radius:4px}
  .wkc{margin:7px 0 2px;display:flex;flex-wrap:wrap;gap:5px}
  .wcat{font-size:11px;color:var(--navy2);background:var(--tint2);border-radius:6px;padding:2px 8px}
  .wkl{list-style:none;margin:7px 0 0;padding:0}
  .wkl li{font-size:12.5px;color:var(--navy2);padding:4px 0;border-top:1px solid var(--border);line-height:1.5}
  .wkl li:first-child{border-top:none}
  .wkl .d{color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums;margin-right:3px}
  .wkl .wb{font-size:10px;margin-right:3px}
  .wkl .loc2{font-size:10.5px;color:var(--navy2);background:var(--tint2);border-radius:4px;padding:0 5px}
  .wkl .more{color:var(--muted);font-style:italic}
  .wkl .tl{color:var(--navy2);text-decoration:none}.wkl .tl:hover{color:var(--accent);text-decoration:underline}
  .wkempty{font-size:12px;color:var(--muted);margin-top:6px}
  .dd{margin-top:9px;border-top:1px dashed var(--border);padding-top:6px}
  .dd>summary{cursor:pointer;font-size:11.5px;font-weight:600;color:var(--navy2);list-style:none;padding:3px 0}
  .dd>summary::-webkit-details-marker{display:none}
  .dd>summary::after{content:"▸";margin-left:5px;color:var(--muted);display:inline-block}
  .dd[open]>summary::after{transform:rotate(90deg)}
  .ddd{margin:6px 0 0;padding:7px 10px;background:var(--tint);border:1px solid var(--border);border-radius:8px}
  .ddh{font-size:11.5px;font-weight:600;color:var(--navy);font-variant-numeric:tabular-nums}
  .ddn{font-weight:400;color:var(--muted);margin-left:4px}
  .wfbar{display:flex;flex-wrap:wrap;gap:6px;margin:0 2px 12px}
  .wsum{font-size:12px;color:var(--navy2);margin:8px 0 2px;padding:8px 11px;background:var(--tint2);border-radius:8px;line-height:1.7}
  .wsb{display:inline-block;font-size:10px;font-weight:700;color:var(--accent);min-width:62px}
  .wtag{display:inline-block;font-size:9.5px;font-weight:600;border-radius:4px;padding:1px 5px;margin-right:5px;vertical-align:1px;
    background:var(--tint2);color:var(--navy2)}
  .wtag.policy{background:#eaf1f8;color:#2f5d8a}.wtag.price{background:#eaf3ee;color:#2e7d52}
  .wtag.macro{background:#f3eee9;color:#9a6b3a}.wtag.semicon{background:#efeaf5;color:#6b4e9a}
  .ftr{margin-top:24px;padding-top:14px;border-top:1px solid var(--border);text-align:center;font-size:11.5px;color:var(--muted);line-height:1.7}
  .ftr a{color:var(--accent);text-decoration:none}.ftr b{color:var(--navy2)}
  @media(min-width:721px){.rsec{padding:16px 20px}}
  .lead{font-size:12.5px;color:var(--muted);margin:4px 2px 12px}
  .dgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:11px}
  @media(max-width:620px){.dgrid{grid-template-columns:1fr}}
  .dcard{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:13px 15px;box-shadow:var(--shadow)}
  .dcard h4{margin:0 0 7px;font-size:12.5px;color:var(--navy)}.dcard ul{margin:0;padding:0;list-style:none}
  .dcard li{font-size:12.5px;color:var(--navy2);padding:3px 0}.dcard li+li{border-top:1px solid var(--border)}.dcard b{color:var(--navy)}
  .impls{list-style:none;padding:0;margin:8px 0 0}.impls li{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:9px 11px;margin-bottom:7px;font-size:12.5px;color:var(--navy2)}
  .impls .d{color:var(--muted);margin-right:6px;font-size:11px}.impls b{color:var(--navy)}
  .sub{font-size:14px;margin:16px 2px 8px}
  .frame{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:13px 15px;margin-bottom:9px;box-shadow:var(--shadow)}
  .frame .lec{font-size:11px;color:var(--accent)}.frame h3{margin:3px 0 7px;font-size:15px}.frame ul{margin:0 0 7px;padding-left:17px}.frame li{font-size:12.5px;color:var(--navy2)}
  .frame .cmt b{font-size:11px}
  .backdrop{display:none}
  @media(max-width:820px){
    aside{transform:translateX(-100%);transition:transform .2s;box-shadow:0 0 40px rgba(0,0,0,.2)}
    aside.open{transform:none}
    main{margin-left:0;padding:12px 12px 60px}
    #burger{display:block}
    .backdrop.on{display:block;position:fixed;inset:56px 0 0 0;background:rgba(0,0,0,.3);z-index:850}
  }
  @media(max-width:560px){
    header{gap:8px;padding:0 10px}
    header h1{font-size:15px}
    .stat,.tag{display:none}
    #q{margin-left:0;min-width:0}
    .rep-head h2{font-size:17px}
    #map{height:260px}
    .toolbar{gap:6px}
  }
</style>
</head>
<body>
<a class="skip" href="#main">본문 바로가기</a>
<header>
  <button id="burger" aria-label="메뉴 열기" aria-expanded="false" aria-controls="side">☰</button>
  <h1 id="brand" title="처음으로" role="button" tabindex="0">APT-SIGNAL</h1>
  <span class="tag">수도권 부동산 동향</span>
  <input id="q" type="search" aria-label="단지·지역·키워드 검색" placeholder="🔍 검색 — 단지·지역·키워드">
  <button id="theme" aria-label="라이트/다크 테마 전환" title="테마 전환">◐</button>
</header>
<div class="backdrop" id="backdrop"></div>
<aside id="side"></aside>
<main id="main" tabindex="-1">
  <div class="crumb" id="crumb"></div>
  <div class="panel" id="view-report">__REPORT__</div>
  <div class="panel" id="view-monitor"></div>
  <div class="panel" id="view-bands"></div>
  <div class="panel" id="view-apt"></div>
  <div class="panel" id="view-weekly"></div>
  <div id="view-list" style="display:none">
    <div id="map"></div>
    <div class="maphint" id="maphint">지도 마커: 시군구별 시그널(크기=건수, 색=매매중위). 클릭 시 해당 지역만.</div>
    <div class="regbar" id="regbar" aria-label="지역 토글"></div>
    <div class="toolbar">
      <span class="tbl">분야</span>
      <button class="chip on" data-cat="">전체</button>
      <button class="chip" data-cat="policy">정책·세제</button>
      <button class="chip" data-cat="price">시세·실거래</button>
      <button class="chip" data-cat="macro">금리·거시</button>
      <button class="chip" data-cat="semicon">반도체</button>
      <button class="chip tg" data-trig="red">🔴</button>
      <button class="chip tg" data-trig="yellow">🟡</button>
      <select id="sort">
        <option value="date_desc">최신순</option>
        <option value="date_asc">오래된순</option>
        <option value="price_desc">매매가 높은순</option>
        <option value="price_asc">매매가 낮은순</option>
        <option value="region">지역순</option>
      </select>
    </div>
    <div id="list"></div>
    <div class="empty" id="empty" style="display:none">조건에 맞는 시그널이 없습니다.</div>
  </div>
  <div class="panel" id="view-frames">__FRAMES__</div>
  <div class="panel" id="view-personal">__PERSONAL__</div>
  <footer class="ftr">APT-SIGNAL · 수도권 부동산 정책·시장 동향 — 공개 기사·실거래 시그널 요약·분석(참고용)<br>
    제작·문의 <b>이정훈</b> · <a href="mailto:piko9388@gmail.com">piko9388@gmail.com</a></footer>
</main>

<script>
var DATA = __DATA__;
var PUBLIC = "__PUBLIC__" === "1";
var SIG = DATA.sig, REG = DATA.regions, MET = DATA.met||[], CATALOG = DATA.cat||[];
var TODAY = DATA.today || "";
function futBadge(d){return (d&&TODAY&&d>TODAY)?'<span class="fut" title="발표·시행 예정(현재 미래 일자)">예정</span>':'';}
var S = {view:"report", sido:null, gu:null, cat:"", trig:null, q:"", sort:"date_desc", wcat:""};
var CAT={policy:"정책·세제",price:"시세·실거래",macro:"금리·거시",semicon:"반도체"};
var CONF={"공식":"● 공식","언론":"◐ 언론","추정":"○ 추정"};
function esc(s){return (s||"").replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
function safeUrl(u){u=(u||"").trim();return /^https?:\/\//i.test(u)?esc(u):"#";}  // http(s)만 허용(javascript: 등 차단)
function priceBand(m){return m==null?"#9aa3ad":m<8?"#2e8b57":m<12?"#2f5d8a":m<20?"#c8860b":"#c0504d";}


/* ---------- 좌측 메뉴(드릴다운) ---------- */
function counts(){
  var bySido={서울:0,경기:0,인천:0,전국:0}, byGu={};
  SIG.forEach(function(s){ bySido[s.sido]=(bySido[s.sido]||0)+1;
    if(s.gu){var k=s.sido+"|"+s.gu; byGu[k]=(byGu[k]||0)+1;} });
  return {bySido:bySido, byGu:byGu};
}
function buildSidebar(){
  var c=counts(), gus={};
  REG.forEach(function(r){ (gus[r.sido]=gus[r.sido]||[]).push(r.gu); });
  Object.keys(gus).forEach(function(k){gus[k].sort();});
  var latest=DATA.latest||((DATA.updated||"").slice(0,10)), built=(DATA.updated||"").slice(0,10);
  var h='<div class="sidesum"><div class="ss-t">수도권 부동산 동향</div>'
    +'<div class="ss-b"><span class="ss-n">'+DATA.total+'<i>건</i></span>'
    +'<span class="ss-r">🔴 긴급 '+DATA.reds+'</span>'
    +(DATA.data_count?'<span class="ss-d">📊 지표 '+DATA.data_count+'</span>':'')+'</div>'
    +'<div class="ss-u" title="빌드 '+built+'">데이터 기준일 '+latest+'</div></div>';
  h+='<div class="navsec"><div class="navttl">보기</div>';
  h+=navrow("📋 종합 동향","__view_report",S.view==="report");
  h+=navrow("📊 동향 모니터링","__view_monitor",S.view==="monitor");
  h+=navrow("📐 밴드 분석","__view_bands",S.view==="bands");
  h+=navrow("🗓 주차별 정리","__view_weekly",S.view==="weekly");
  h+=navrow("🗂 지역별 보기","__view_list",S.view==="list");
  h+=navrow("🏢 아파트 정보","__view_apt",S.view==="apt");
  h+=navrow("📚 부읽남 참고","__view_frames",S.view==="frames");
  if(!PUBLIC) h+=navrow("개인 맞춤(정훈)","__view_personal",S.view==="personal");
  h+='</div><div class="navsec"><div class="navttl">지역 드릴다운</div>';
  h+=navrow('<b>전체 수도권</b>','all',!S.sido,c.bySido["서울"]+c.bySido["경기"]+c.bySido["인천"]+c.bySido["전국"]);
  ["서울","경기","인천"].forEach(function(sido){
    var open=S.sido===sido;
    h+='<div class="navitem '+(S.sido===sido&&!S.gu?"on":"")+'" data-sido="'+sido+'">'
      +'<span><span class="caret '+(open?"open":"")+'">▸</span>'+sido+'</span>'
      +'<span class="c">'+(c.bySido[sido]||0)+'</span></div>';
    (gus[sido]||[]).forEach(function(gu){
      var n=c.byGu[sido+"|"+gu]||0;
      h+='<div class="navitem gu '+(open?"":"hidden")+' '+(S.sido===sido&&S.gu===gu?"on":"")+'" '
        +'data-sido="'+sido+'" data-gu="'+gu+'"><span>'+gu+'</span><span class="c">'+n+'</span></div>';
    });
  });
  h+='</div>';
  // 하단: 사용설명서 + 제작 문의
  h+='<div class="sidefoot">'
    +'<details class="guide"><summary>📖 사용설명서</summary><ul>'
    +'<li><b>종합 동향</b> — 기사·실거래를 연도별로 요약·분석한 흐름 브리핑</li>'
    +'<li><b>동향 모니터링</b> — 공식 지표(부동산원·KB·한은·국토부)를 추이 그래프로 보고 뉴스와 정합, 과장 여부 판별</li>'
    +'<li><b>주차별 정리</b> — 주 단위 흐름 요약 + 분야별 분류, 펼치면 일자별 전체</li>'
    +'<li><b>지역별 보기</b> — 좌측·지도에서 시·도·구 선택, 칩으로 분류 필터, 검색</li>'
    +'<li><b>🔴 즉시 영향</b> — 대출·세제·규제지역 등 <b>제도 변경</b>·<b>기준금리 변경</b>·주요 단지 <b>신고가</b>. 영향 기간 <b>즉시~6개월</b>, 발견 즉시 확인.</li>'
    +'<li><b>🟡 추세 관찰</b> — 코픽스·주담대 금리, 공급·입주·분양, 정비사업 진전. 영향 기간 <b>6~24개월</b>, 주간 단위 점검.</li>'
    +'<li><b>⚪ 참고</b> — 그 외 배경·심리 신호.</li>'
    +'<li><b>출처 신뢰도</b> — ● 공식(정부·기관 1차 출처) · ◐ 언론(보도 인용) · ○ 추정(환산·해석). 지표 타일·KPI에 등급 표기, 헤드라인 KPI는 공식값 우선. 산출·정규화 기준은 <b>docs/METHODOLOGY.md</b> 공개.</li>'
    +'<li><b>예정</b> 배지 — 발표·시행 예정(현재 미래 일자) 신호.</li>'
    +'<li><b>참고용</b> — 매수·매도 판단 보조 자료, 투자 권유 아님.</li>'
    +'</ul></details>'
    +'<div class="madeby">제작·문의 <b>이정훈</b><br><a href="mailto:piko9388@gmail.com">piko9388@gmail.com</a></div>'
    +'</div>';
  var side=document.getElementById("side"); side.innerHTML=h;
  side.querySelectorAll(".navitem[data-sido]").forEach(function(el){
    el.onclick=function(){
      var sido=el.getAttribute("data-sido"), gu=el.getAttribute("data-gu");
      if(gu){ S.sido=sido;S.gu=gu;S.view="list"; }
      else{ S.sido=(S.sido===sido?null:sido); S.gu=null; S.view="list"; }
      render(); closeSide();
    };
  });
  // 뷰 전환 / 전체
  side.querySelectorAll('[data-key]').forEach(function(el){
    el.onclick=function(){ var k=el.getAttribute("data-key");
      if(k==="all"){S.sido=null;S.gu=null;S.view="list";}
      else if(k==="__view_report"){S.view="report";}
      else if(k==="__view_monitor"){S.view="monitor";}
      else if(k==="__view_bands"){S.view="bands";}
      else if(k==="__view_apt"){S.view="apt";}
      else if(k==="__view_weekly"){S.view="weekly";}
      else if(k==="__view_list"){S.view="list";}
      else if(k==="__view_frames"){S.view="frames";}
      else if(k==="__view_personal"){S.view="personal";}
      render(); closeSide(); };
  });
}
function navrow(label,key,on,c){
  return '<div class="navitem '+(on?"on":"")+'" data-key="'+key+'"><span>'+label+'</span>'
    +(c!=null?'<span class="c">'+c+'</span>':'')+'</div>';
}

/* ---------- 필터/정렬 ---------- */
function filtered(){
  return SIG.filter(function(s){
    if(S.sido && s.sido!==S.sido) return false;
    if(S.gu && s.gu!==S.gu) return false;
    if(S.cat && s.cat!==S.cat) return false;
    if(S.trig && s.trig!==S.trig) return false;
    if(S.q){ var h=((s.title||"")+" "+(s.summary||"")+" "+(s.gu||"")+" "+(s.source||"")+" "+(s.comment||"")).toLowerCase();
      if(h.indexOf(S.q)<0) return false; }
    return true;
  });
}
function sortSig(arr){
  var a=arr.slice();
  if(S.sort==="date_desc") a.sort(function(x,y){return (y.date||"").localeCompare(x.date||"");});
  else if(S.sort==="date_asc") a.sort(function(x,y){return (x.date||"").localeCompare(y.date||"");});
  else if(S.sort==="price_desc") a.sort(function(x,y){return (y.price==null?-1:y.price)-(x.price==null?-1:x.price);});
  else if(S.sort==="price_asc") a.sort(function(x,y){return (x.price==null?1e9:x.price)-(y.price==null?1e9:y.price);});
  else if(S.sort==="region") a.sort(function(x,y){return (x.sido+x.gu).localeCompare(y.sido+y.gu);});
  return a;
}
function cardHTML(s){
  var loc=s.sido+(s.gu?" · "+s.gu:"");
  var bd=s.trig==="red"?'<span class="bd red">🔴</span>':s.trig==="yellow"?'<span class="bd yellow">🟡</span>':"";
  var pr=s.price!=null?'<span class="pr">매매 '+s.price+'억</span>':"";
  var cmt=s.comment?'<p class="cmt"><b>해석</b> '+esc(s.comment)+'</p>':"";
  var src=s.url?'<a class="src" href="'+safeUrl(s.url)+'" target="_blank" rel="noopener">'+esc(s.source)+' ↗</a>':'<span class="src">'+esc(s.source)+'</span>';
  return '<article class="card"><div class="meta"><span class="date">'+esc(s.date)+'</span>'+futBadge(s.date)
    +'<span class="loc" data-sido="'+esc(s.sido)+'" data-gu="'+esc(s.gu)+'">'+esc(loc)+'</span>'
    +'<span class="conf '+s.conf+'">'+CONF[s.conf]+'</span>'+pr+bd+'</div>'
    +'<h3>'+esc(s.title)+'</h3><p class="sum">'+esc(s.summary)+'</p>'+cmt
    +'<div class="foot">'+src+'</div></article>';
}
function renderList(){
  var arr=sortSig(filtered());
  var list=document.getElementById("list");
  list.innerHTML=arr.map(cardHTML).join("");
  document.getElementById("empty").style.display=arr.length?"none":"block";
  list.querySelectorAll(".loc").forEach(function(el){
    el.onclick=function(){ S.sido=el.getAttribute("data-sido")||null;
      var g=el.getAttribute("data-gu"); S.gu=g||null; buildSidebar(); render(); };
  });
}
function renderRegbar(){
  var rb=document.getElementById("regbar"); if(!rb) return;
  var c=counts();
  var regs=[["","전체 수도권",c.bySido["서울"]+c.bySido["경기"]+c.bySido["인천"]+(c.bySido["전국"]||0)],
            ["서울","서울",c.bySido["서울"]||0],["경기","경기",c.bySido["경기"]||0],["인천","인천",c.bySido["인천"]||0]];
  rb.innerHTML='<span class="tbl">지역</span>'+regs.map(function(r){
    return '<button class="rchip'+((S.sido||"")===r[0]?" on":"")+'" data-sido="'+r[0]+'">'+r[1]+'<em>'+r[2]+'</em></button>';
  }).join("");
  rb.querySelectorAll(".rchip").forEach(function(b){
    b.onclick=function(){ S.sido=b.getAttribute("data-sido")||null; S.gu=null; buildSidebar(); render(); };
  });
}
function renderCrumb(){
  var loc=S.sido?(esc(S.sido)+(S.gu?' <i>›</i> '+esc(S.gu):"")):"전체 수도권";
  var n=filtered().length;
  var h='<span class="cp loc">📍 '+loc+'</span>'
    +'<span class="cp n"><b>'+n+'</b>건</span>';
  if(S.cat) h+='<span class="cp">'+esc(CAT[S.cat])+'</span>';
  if(S.trig==="red") h+='<span class="cp red">🔴 즉시</span>';
  if(S.trig==="yellow") h+='<span class="cp yellow">🟡 주목</span>';
  if(S.q) h+='<span class="cp">🔍 '+esc(S.q)+'</span>';
  if(S.sido||S.gu||S.cat||S.trig||S.q) h+='<button class="creset" id="reset">✕ 초기화</button>';
  document.getElementById("crumb").innerHTML=h;
  var r=document.getElementById("reset");
  if(r) r.onclick=function(e){e.preventDefault();S.sido=S.gu=S.trig=null;S.cat="";S.q="";S.sort="date_desc";
    document.getElementById("q").value="";var so=document.getElementById("sort");if(so)so.value="date_desc";
    document.querySelectorAll(".chip").forEach(function(c){c.classList.remove("on");});
    document.querySelector('.chip[data-cat=""]').classList.add("on");buildSidebar();render();};
}

/* ---------- 지도 ---------- */
var map=null, layer=null;
var SUDO=[[36.92,126.55],[37.74,127.35]];  // 서울·경기·인천 커버 범위(기본 범례)
function initMap(){
  if(typeof L==="undefined"){ document.getElementById("map").style.display="none";
    document.getElementById("maphint").style.display="none"; return; }
  map=L.map("map",{scrollWheelZoom:false,minZoom:8}).fitBounds(SUDO);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {maxZoom:18,attribution:"© OpenStreetMap"}).addTo(map);
  layer=L.layerGroup().addTo(map);
  renderMap();
  if(S.view==="list") setTimeout(function(){ map.invalidateSize(); renderMap(); },60);
}
function renderMap(){
  if(!map) return; layer.clearLayers();
  var rs=REG.filter(function(r){ return r.lat!=null && (!S.sido||r.sido===S.sido); });
  rs.forEach(function(r){
    var m=L.circleMarker([r.lat,r.lng],{radius:Math.min(6+r.n*0.7,26),
      color:"#fff",weight:1,fillColor:priceBand(r.med),fillOpacity:.82});
    m.bindPopup("<b>"+r.sido+" "+r.gu+"</b><br>시그널 "+r.n+"건"
      +(r.med!=null?"<br>매매중위 "+r.med+"억":"<br>매매 표본 부족")
      +(r.red?"<br>🔴 즉시 "+r.red:""));
    m.on("click",function(){ S.sido=r.sido;S.gu=r.gu; buildSidebar(); render(); });
    m.addTo(layer);
  });
  // 컨테이너가 보일 때만 마커 범위로 맞춤, 아니면 수도권 기본 범위
  var visible=document.getElementById("map").offsetParent!==null;
  if(visible && rs.length){ try{ map.fitBounds(L.featureGroup(layer.getLayers()).getBounds().pad(0.12)); }catch(e){ map.fitBounds(SUDO); } }
  else { map.fitBounds(SUDO); }
}

/* ---------- 동향 모니터링 (지표 ↔ 뉴스 정합) ---------- */
var HOT=["급등","폭등","신고가","불장","과열","영끌","패닉","최고가","고점","치솟","뛴","급반등","불붙","폭주"];
var COLD=["하락","약세","급매","역전세","미분양","공포","조정","내림","침체","꺾","미끄","빙하기","거래절벽","하락세"];
function ymLabel(d){if(!d)return "";var p=d.split("-");return p[0].slice(2)+"."+parseInt(p[1],10);}
function fmtV(m){if(!m||m.value==null)return "—";var v=Math.round(m.value*100)/100;return (v>0&&m.unit==="%"?"+":"")+v+(m.unit||"");}
function series(metric,sido){return MET.filter(function(m){return m.metric===metric&&(!sido||m.sido===sido);})
  .sort(function(x,y){return (x.date||"").localeCompare(y.date||"");});}
function dnum(d){var p=(d||"").split("-");return (+p[0]||0)*372+((+p[1]||1)-1)*31+((+p[2]||1)-1);}
function sparkline(a){
  // 정량 지표 시계열 → 인라인 SVG. X축을 '날짜'로 배치(등간격 아님) → 결측·간격이 실제로 보임.
  var A=a.filter(function(m){return m.value!=null;});
  if(A.length<2) return "";
  var vals=A.map(function(m){return m.value;}), n=A.length;
  var w=190,h=40,pad=5;
  var mn=Math.min.apply(null,vals), mx=Math.max.apply(null,vals), rng=(mx-mn)||1;
  var t=A.map(function(m){return dnum(m.date);});
  var t0=t[0], tr=(t[n-1]-t0)||1;
  var X=function(i){return pad+(t[i]-t0)/tr*(w-2*pad);};
  var Y=function(v){return h-pad-(v-mn)/rng*(h-2*pad);};
  var pts=vals.map(function(v,i){return X(i).toFixed(1)+","+Y(v).toFixed(1);}).join(" ");
  var zero="";
  if(mn<0&&mx>0){ var zy=Y(0).toFixed(1); zero='<line x1="'+pad+'" y1="'+zy+'" x2="'+(w-pad)+'" y2="'+zy+'" class="sp-zero"/>'; }
  var d=vals[n-1]-vals[0]; var dir=d>0?"up":d<0?"down":"flat";
  // 끝점 마커는 세로 틱(preserveAspectRatio=none 하에서 원은 타원으로 왜곡되므로)
  var lx=X(n-1).toFixed(1), lyv=Y(vals[n-1]);
  var end='<line x1="'+lx+'" y1="'+(lyv-3).toFixed(1)+'" x2="'+lx+'" y2="'+(lyv+3).toFixed(1)+'" class="sp-end '+dir+'"/>';
  var lab=ymLabel(A[0].date)+"→"+ymLabel(A[n-1].date)+" ("+n+"점)";
  return '<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" role="img" aria-label="'+esc(lab)+'">'
    +'<title>'+esc(lab)+'</title>'+zero+'<polyline class="sp-line '+dir+'" points="'+pts+'"/>'+end+'</svg>';
}
// 두 지표값의 변화량 칩(▲/▼ + 절대 증감) — 방향을 한눈에
function deltaChip(cur,prev){
  if(!cur||!prev||cur.value==null||prev.value==null) return "";
  var d=Math.round((cur.value-prev.value)*100)/100;
  var cls=d>0?"up":d<0?"down":"flat", arr=d>0?"▲":d<0?"▼":"→";
  var u=(cur.unit==="%"||cur.unit==="배"||cur.unit==="배수")?cur.unit:"";
  var n=Math.abs(d).toLocaleString();
  return '<span class="dlt '+cls+'" title="직전값 대비">'+arr+(d!==0?n+u:"")+'</span>';
}
var CONFMARK={"공식":"●","언론":"◐","추정":"○"};
function confBadge(cf){cf=cf||"추정";return '<span class="mt-cf '+cf+'" title="출처 신뢰도: '+cf+'">'+CONFMARK[cf]+cf+'</span>';}
function metricTile(metric,sido){
  var a=series(metric,sido); if(!a.length)return "";
  var cur=a[a.length-1], prev=a.length>1?a[a.length-2]:null;
  var spk=sparkline(a);
  var rangeLbl=a.length>1?('<span class="mt-rg">'+ymLabel(a[0].date)+'→'+ymLabel(cur.date)+'</span>'):'';
  return '<div class="mtile"><div class="mt-h"><span class="mt-n">'+esc(metric)+'</span>'
    +'<span style="display:inline-flex;align-items:baseline;gap:6px">'+deltaChip(cur,prev)
    +'<a class="mt-v" href="'+safeUrl(cur.url)+'" target="_blank" rel="noopener" title="'+esc(cur.source||"")+'">'+fmtV(cur)+'</a></span></div>'
    +(spk||'')
    +'<div class="mt-d">'+confBadge(cur.conf)+' '+(futBadge(cur.date)||'최신')+' '+esc(cur.date||"")+' · '+esc(cur.source||"")+' '+rangeLbl+'</div></div>';
}
function newsLean(sido){
  var ns=SIG.filter(function(s){return s.sido===sido;});
  var hot=0,cold=0;
  ns.forEach(function(s){var t=(s.title||"")+(s.summary||"");
    if(HOT.some(function(k){return t.indexOf(k)>=0;}))hot++;
    if(COLD.some(function(k){return t.indexOf(k)>=0;}))cold++;});
  return {n:ns.length,hot:hot,cold:cold};
}
function reconcile(sido){
  var idx=series("매매가격지수 변동률",sido); idx=idx.length?idx[idx.length-1]:null;
  var vol=series("아파트 매매 거래량",sido); vol=vol.length?vol[vol.length-1]:null;
  var ln=newsLean(sido);
  var dir=idx&&idx.value!=null?(idx.value>0.1?"상승":idx.value<-0.1?"하락":"보합"):"지표 미수집";
  var lean=ln.hot>ln.cold+1?"과열 강조":ln.cold>ln.hot+1?"약세 강조":"중립";
  // 지표와 뉴스를 한 문장으로 연결(따로 노는 느낌 제거)
  var idxTxt=idx?('부동산원 매매지수 <b>'+fmtV(idx)+'</b>('+dir+')'):'지표 미수집';
  var newsTxt='뉴스 '+ln.n+'건 중 과열어 '+ln.hot+'·약세어 '+ln.cold;
  var verdict;
  if(dir==="지표 미수집") verdict=idxTxt+' → '+newsTxt+'. <b>공식 지표 보강 필요</b>(별도 크롤).';
  else if(dir==="상승"&&lean==="과열 강조") verdict=idxTxt+'가 '+newsTxt+'의 과열 정서를 <b>뒷받침</b> — 방향 일치.';
  else if((dir==="보합"||dir==="하락")&&lean==="과열 강조") verdict=idxTxt+'인데 '+newsTxt+' → <b>뉴스 과장 주의</b>(지표 우선).';
  else if(dir==="상승"&&lean==="약세 강조") verdict=idxTxt+'인데 '+newsTxt+' → 뉴스가 <b>과도하게 신중</b>.';
  else verdict=idxTxt+' · '+newsTxt+' — 큰 괴리 없음.';
  var dcls=dir==="상승"?"up":dir==="하락"?"down":"flat";
  var darr=dir==="상승"?"▲":dir==="하락"?"▼":dir==="보합"?"→":"";
  var dirBadge=dir!=="지표 미수집"?'<span class="rec-dir '+dcls+'">'+darr+' '+dir+'</span>':'';
  return '<div class="rec"><div class="rec-h">'+esc(sido)+dirBadge
    +(vol?' <span class="rec-vol">거래량 '+Math.round(vol.value).toLocaleString()+'건</span>':'')+'</div>'
    +'<div class="rec-v">'+verdict+'</div></div>';
}
function renderMonitor(){
  var host=document.getElementById("view-monitor");
  if(!MET.length){ host.innerHTML='<div class="lead">동향 모니터링 — 공식 지표 ↔ 뉴스 정합</div>'
    +'<div class="empty">공식 지표(부동산원·KB·한은·국토부) 수집 중입니다. 채워지면 뉴스와 정합해 실제 추세를 보여줍니다.</div>'; return; }
  var macro=["기준금리","COFIX","주택담보대출 금리","가계대출 증감","스트레스DSR 가산금리"];
  var price=["매매가격지수 변동률","전세가격지수 변동률","주간 매매변동률","주간 전세변동률","KB 매매변동률","5분위 평균매매가","5분위 배율","평당가","평형별 실거래가","전세가율","분양가","청약경쟁률","경매 낙찰가율","PIR","아파트 매매 거래량","주택 매매 거래량","미분양","준공후 미분양","입주물량","매수우위지수","매매전망지수","공공임대 세대수","공공임대 단지수","아파트 세대수","공공임대 비율"];
  var geos=["전국","수도권","서울","경기","인천"];
  var gc={공식:0,언론:0,추정:0}; MET.forEach(function(m){gc[m.conf||"추정"]=(gc[m.conf||"추정"]||0)+1;});
  var h='<div class="lead">동향 모니터링 — 정량 <b>지표</b>와 정성 <b>뉴스</b>를 정합해 추세 점검 · 지표 '+MET.length+'건</div>'
    +'<p class="clegend">각 타일은 값 출처 신뢰도를 표기 — <span class="mt-cf 공식">●공식</span> 정부·기관 1차('+gc.공식+') · <span class="mt-cf 언론">◐언론</span> 보도 인용('+gc.언론+') · <span class="mt-cf 추정">○추정</span> 환산·해석('+gc.추정+'). 스파크라인 X축은 실제 날짜(간격=결측).</p>';
  // 거시
  var mt=macro.map(function(m){return metricTile(m,"전국");}).filter(Boolean).join("");
  if(mt) h+='<section class="msec"><h3>금리·거시</h3><div class="mgrid">'+mt+'</div></section>';
  // 가격·거래(지역별)
  geos.forEach(function(g){
    var tiles=price.map(function(m){return metricTile(m,g);}).filter(Boolean).join("");
    if(tiles) h+='<section class="msec"><h3>'+esc(g)+' 가격·거래</h3><div class="mgrid">'+tiles+'</div></section>';
  });
  // 정합
  var recs=["서울","경기","인천"].map(reconcile).join("");
  h+='<section class="msec"><h3>정합 — 뉴스 vs 지표</h3><div class="recgrid">'+recs+'</div>'
    +'<p class="rdisc">과열어/약세어=뉴스 제목·요약의 표현 빈도(자극적 헤드라인 가늠용). 지표는 공식 통계 최신값. 둘의 방향이 어긋나면 뉴스 톤을 의심하고 지표를 따른다.</p></section>';
  host.innerHTML=h;
}

/* ---------- 밴드 분석 (가격대·면적대 분리) ---------- */
var ABANDS=["40이하","40-60","60-85","85-130","130초과"];
function bandLatest(metric,sido,bandkey,band){
  var a=MET.filter(function(m){return m.metric===metric&&m.sido===sido&&(m[bandkey]||"")===band;})
    .sort(function(x,y){return (x.date||"").localeCompare(y.date||"");});
  return a.length?a[a.length-1]:null;
}
function bandTable(metric,bandkey,bands){
  // 해당 metric에서 band가 채워진 데이터가 있는 sido만 행으로
  var rows=MET.filter(function(m){return m.metric===metric&&(m[bandkey]||"");});
  if(!rows.length) return "";
  var sidos=[]; rows.forEach(function(m){ if(sidos.indexOf(m.sido)<0)sidos.push(m.sido); });
  var order=["전국","수도권","서울","경기","인천"];
  sidos.sort(function(a,b){return order.indexOf(a)-order.indexOf(b);});
  var th=bands.map(function(b){return '<th>'+b+'</th>';}).join("");
  var body=sidos.map(function(sd){
    var tds=bands.map(function(b){var m=bandLatest(metric,sd,bandkey,b);
      return '<td>'+(m?fmtV(m):'·')+'</td>';}).join("");
    return '<tr><td>'+esc(sd)+'</td>'+tds+'</tr>';
  }).join("");
  return '<section class="msec"><h3>'+esc(metric)+'</h3><div class="tw"><table class="rt">'
    +'<thead><tr><th>지역</th>'+th+'</tr></thead><tbody>'+body+'</tbody></table></div></section>';
}
function renderBands(){
  var host=document.getElementById("view-bands");
  var aMetrics=[], pMetrics=[];
  MET.forEach(function(m){
    if(m.aband && aMetrics.indexOf(m.metric)<0) aMetrics.push(m.metric);
    if(m.pband && pMetrics.indexOf(m.metric)<0) pMetrics.push(m.metric);
  });
  var h='<div class="lead">밴드 분석 — 대출·세제 경계(<b>가격대</b> 6/9/15/25억) · R-ONE 표준(<b>면적대</b> 40/60/85/130㎡)로 분리. 최신값.</div>';
  if(!aMetrics.length && !pMetrics.length){
    h+='<div class="empty">밴드 데이터 수집 중. <code>scripts/m_signal_fetch.py</code>(RTMS 면적대 집계)·KB 5분위 적재 후 채워집니다.<br>실행: <code>RTMS_KEY=… python3 scripts/m_signal_fetch.py --regions gaps --out out.json</code></div>';
    host.innerHTML=h; return;
  }
  if(aMetrics.length){
    h+='<h2 class="bsec">면적대별 (전용㎡)</h2>';
    aMetrics.forEach(function(mt){ h+=bandTable(mt,"aband",ABANDS); });
  }
  if(pMetrics.length){
    // 가격대 밴드는 데이터에 나타난 순서대로
    var pbands=[]; MET.forEach(function(m){ if(m.pband&&pbands.indexOf(m.pband)<0)pbands.push(m.pband); });
    h+='<h2 class="bsec">가격대별</h2>';
    pMetrics.forEach(function(mt){ h+=bandTable(mt,"pband",pbands); });
  }
  h+=derivedBandsHTML();
  host.innerHTML=h;
}
// 뉴스 실거래(제목 파싱)에서 면적대별 시세 분포를 도출 — 공식 밴드지표 부족분 보완(참고용)
function derivedBandsHTML(){
  var bucket={};  // sido -> band -> [prices]
  SIG.forEach(function(s){
    if(s.cat!=="price"||/(전세|월세)/.test(s.title||"")) return;
    var m=APT_RE.exec(s.title||""); if(!m) return;
    var area=parseFloat(m[2]), price=parseFloat(m[3]);
    if(!(area>10&&area<400)||!(price>=1&&price<=250)) return;
    var b=areaBand(area), sd=s.sido||"전국";
    (bucket[sd]=bucket[sd]||{})[b]=(bucket[sd][b]||[]); bucket[sd][b].push(price);
  });
  var order=["서울","경기","인천","전국","수도권"];
  var sidos=Object.keys(bucket).sort(function(a,b){return order.indexOf(a)-order.indexOf(b);});
  if(!sidos.length) return "";
  function med(a){a=a.slice().sort(function(x,y){return x-y;});var n=a.length;return n?(n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2):null;}
  var body=sidos.map(function(sd){
    var tds=ABANDS.map(function(b){var a=(bucket[sd]||{})[b]||[];
      if(!a.length) return '<td>·</td>';
      return '<td><b>'+ (Math.round(med(a)*10)/10) +'</b>억<span class="bn">'+a.length+'</span></td>';}).join("");
    return '<tr><td>'+esc(sd)+'</td>'+tds+'</tr>';
  }).join("");
  var th=ABANDS.map(function(b){return '<th>'+b+'㎡</th>';}).join("");
  return '<h2 class="bsec">실거래 기반 면적대별 시세 <span class="btag">뉴스 추출·참고</span></h2>'
    +'<div class="tw"><table class="rt"><thead><tr><th>지역</th>'+th+'</tr></thead><tbody>'+body+'</tbody></table></div>'
    +'<p class="rdisc">뉴스 실거래 제목에서 전용면적·거래가를 추출해 면적대별 <b>중위 매매가(억)</b>·건수. 개별 신고가 편향이 있어 공식 지표(부동산원 규모별)와 차이가 있으며 <b>참고용</b>. 공식 밴드는 RTMS 자동수집 시 채워집니다.</p>';
}

/* ---------- 아파트 정보 (실거래 기반 단지 카탈로그) ---------- */
// 단지명 + (선택)전용 + NN㎡ + (층 등) + NN억. '전용' 앞의 실제 단지명을 잡는다.
var APT_RE=/([가-힣A-Za-z][가-힣A-Za-z0-9·()]{1,})\s+(?:전용\s*)?(\d+(?:\.\d+)?)\s*㎡[^0-9]{0,7}(\d+(?:\.\d+)?)\s*억/;
// 단지명으로 오추출되기 쉬운 일반명사(쓰레기 단지명 방지)
var APT_STOP={"전용":1,"국평":1,"전용면적":1,"면적":1,"매매":1,"아파트":1,"신고가":1,"실거래":1,
  "평균":1,"거래":1,"전세":1,"월세":1,"분양":1,"청약":1,"주택":1,"평형":1,"최고가":1,"직전":1};
function areaBand(a){return a<=40?"40이하":a<=60?"40-60":a<=85?"60-85":a<=130?"85-130":"130초과";}
function buildCatalog(){
  var by={};
  SIG.forEach(function(s){
    if(s.cat!=="price"||!s.gu) return;
    var m=APT_RE.exec(s.title||""); if(!m) return;
    var apt=m[1].replace(/^\[.*?\]/,"").trim();
    if(apt.length<2 || APT_STOP[apt] || !/[가-힣]/.test(apt)) return;
    var isJ=/(전세|월세)/.test(s.title);
    var key=s.sido+"|"+s.gu+"|"+apt;
    var o=by[key]||(by[key]={sido:s.sido,gu:s.gu,apt:apt,trades:[]});
    o.trades.push({area:parseFloat(m[2]),price:parseFloat(m[3]),date:s.date,jeonse:isJ,url:s.url});
  });
  return Object.keys(by).map(function(k){return by[k];});
}
function derivedCard(o){
  var sales=o.trades.filter(function(t){return !t.jeonse;}).sort(function(x,y){return (y.date||"").localeCompare(x.date||"");});
  var jeon=o.trades.filter(function(t){return t.jeonse;});
  var areas=[]; o.trades.forEach(function(t){ if(t.area&&areas.indexOf(Math.round(t.area))<0)areas.push(Math.round(t.area)); });
  areas.sort(function(a,b){return a-b;});
  var prices=sales.map(function(t){return t.price;});
  var rng=prices.length?(prices.length>1?Math.min.apply(null,prices)+"~"+Math.max.apply(null,prices)+"억":prices[0]+"억"):"—";
  var rows=sales.slice(0,4).map(function(t){
    return '<li>'+(t.url?'<a href="'+safeUrl(t.url)+'" target="_blank" rel="noopener">':'')
      +'<span class="ad">'+esc(t.date||"")+'</span> 전용 '+t.area+'㎡ <b>'+t.price+'억</b>'
      +(t.url?'</a>':'')+'</li>';
  }).join("");
  var jl=jeon.length?'<div class="apt-j">전세 '+jeon.length+'건 (최근 '+jeon[0].price+'억)</div>':'';
  return '<div class="aptcard"><div class="apth"><b>'+esc(o.apt)+'</b>'
    +'<span class="aptloc">'+esc(o.sido+" "+o.gu)+'</span></div>'
    +'<div class="apt-m">전용 '+(areas.join("·")||"-")+'㎡ · 매매 '+sales.length+'건 · 시세 '+rng+'</div>'
    +(rows?'<ul class="apt-l">'+rows+'</ul>':'')+jl+'</div>';
}
function regCard(c){
  var spec=[];
  if(c.households) spec.push(c.households.toLocaleString()+'세대');
  if(c.built_year) spec.push(c.built_year+'년');
  if(c.far) spec.push('용적률 '+c.far+'%');
  if(c.pyeong_price) spec.push('평당 '+Number(c.pyeong_price).toLocaleString()+'만');
  if(c.jeonse_ratio) spec.push('전세가율 '+c.jeonse_ratio+'%');
  var sizes=(c.sizes_m2||[]).join("·");
  var deals=(c.deal||[]).slice().sort(function(x,y){return (y.date||"").localeCompare(x.date||"");});
  var url=(c.source_urls||[])[0]||"";
  var rows=deals.slice(0,5).map(function(d){
    return '<li>'+(url?'<a href="'+safeUrl(url)+'" target="_blank" rel="noopener">':'')
      +'<span class="ad">'+esc(d.date||"")+'</span> 전용 '+d.size_m2+'㎡ <b>'+d.price_eok+'억</b> '+esc(d.type||"")
      +(url?'</a>':'')+'</li>';
  }).join("");
  var ten=c.tenure==="임대"?'<span class="ten'+((c.built_year&&c.built_year<=2000)?" old":"")+'">🏢 '+esc(c.rental_type||"공공임대")+((c.built_year&&c.built_year<=2000)?" · 노후주공":"")+'</span>':'';
  return '<div class="aptcard reg"><div class="apth"><b>'+esc(c.complex)+'</b>'
    +'<span class="aptloc">'+esc((c.sido||"")+" "+(c.gu||"")+(c.dong?" "+c.dong:""))+'</span></div>'
    +ten
    +(spec.length?'<div class="apt-spec">'+spec.join(" · ")+'</div>':'')
    +(sizes?'<div class="apt-m">평형 전용 '+esc(sizes)+'㎡</div>':'')
    +(rows?'<ul class="apt-l">'+rows+'</ul>':'')
    +(c.dev?'<div class="apt-dev">🏗 '+esc(c.dev)+'</div>':'')+'</div>';
}
function renderApt(){
  var host=document.getElementById("view-apt");
  var norm=function(s){return (s||"").replace(/\s/g,"").toLowerCase();};
  var reg=CATALOG.slice();
  var regKey={}; reg.forEach(function(c){ regKey[c.sido+"|"+c.gu+"|"+norm(c.complex)]=1; });
  var der=buildCatalog().filter(function(o){return !regKey[o.sido+"|"+o.gu+"|"+norm(o.apt)];});
  if(S.q){ reg=reg.filter(function(c){return (c.complex+c.sido+c.gu).toLowerCase().indexOf(S.q)>=0;});
    der=der.filter(function(o){return (o.apt+o.sido+o.gu).toLowerCase().indexOf(S.q)>=0;}); }
  der.sort(function(a,b){return b.trades.length-a.trades.length;});
  var CAP=80, shown=der.slice(0,CAP);
  // 등록 단지를 일반(제원·실거래)과 LH 공공임대(대량)로 분리 — 임대는 세대수 순 상한 표시.
  var seed=reg.filter(function(c){return c.tenure!=="임대";});
  var lease=reg.filter(function(c){return c.tenure==="임대";});
  lease.sort(function(a,b){
    var ao=(a.built_year&&a.built_year<=2000)?1:0, bo=(b.built_year&&b.built_year<=2000)?1:0;
    if(ao!==bo) return bo-ao;                       // 노후 주공 우선 노출
    return (b.households||0)-(a.households||0); });  // 그다음 세대수 큰 순
  var LCAP=60, leaseShown=lease.slice(0,LCAP);
  var leaseOld=lease.filter(function(c){return c.built_year&&c.built_year<=2000;}).length;
  var h='<div class="lead">아파트 정보 — 등록 '+seed.length+'개(제원 포함)'
    +(lease.length?' · LH 공공임대 '+lease.length+'개(노출 기준·노후주공 '+leaseOld+')':'')
    +' · 실거래 추출 '+der.length+'단지 · 단지 클릭 시 원문.</div>';
  if(seed.length){
    h+='<h2 class="bsec">등록 단지 (제원 포함)</h2><div class="aptgrid">'
      +seed.map(regCard).join("")+'</div>';
  }
  if(leaseShown.length){
    h+='<h2 class="bsec">공공임대 단지 (LH · 현재 공고·모집 노출)</h2><div class="aptgrid">'
      +leaseShown.map(regCard).join("")+'</div>'
      +(lease.length>LCAP?'<p class="rdisc">세대수 상위 '+LCAP+'개 표시(전체 '+lease.length+'개는 상단 <b>공공임대 세대수·단지수</b> 지표로 집계) · 검색으로 좁히기. LH 임대주택단지 조회 API는 전체 재고가 아닌 현재 노출분 기준.</p>':'');
  }
  if(shown.length){
    h+='<h2 class="bsec">실거래 추출 단지</h2><div class="aptgrid">'
      +shown.map(derivedCard).join("")+'</div>'
      +(der.length>CAP?'<p class="rdisc">상위 '+CAP+'단지 표시 · 검색으로 좁히기 · 더 많은 제원은 <code>scripts/apthub_official_apis.py --complex</code>로 생성.</p>':'');
  }
  if(!seed.length && !leaseShown.length && !shown.length) h+='<div class="empty">단지가 없습니다. 검색어를 바꿔보세요.</div>';
  host.innerHTML=h;
}

/* ---------- 주차별 정리 (일자별 드릴다운) ---------- */
function mondayOf(ds){var d=new Date(ds+"T00:00:00");if(isNaN(d))return ds;var w=(d.getDay()+6)%7;d.setDate(d.getDate()-w);return d.toISOString().slice(0,10);}
function addDays(ds,n){var d=new Date(ds+"T00:00:00");d.setDate(d.getDate()+n);return d.toISOString().slice(0,10);}
function isoWeek(ds){var d=new Date(ds+"T00:00:00");var t=new Date(d);t.setDate(d.getDate()+3-((d.getDay()+6)%7));var w1=new Date(t.getFullYear(),0,4);var n=1+Math.round(((t-w1)/864e5-3+((w1.getDay()+6)%7))/7);return (n<10?"0":"")+n;}
function sigLine(s){
  return '<li><span class="wb">'+(s.trig==="red"?"🔴":s.trig==="yellow"?"🟡":"·")+'</span>'
    +'<span class="d">'+esc(s.date)+'</span> '+futBadge(s.date)
    +(s.url?'<a class="tl" href="'+safeUrl(s.url)+'" target="_blank" rel="noopener">'+esc(s.title)+'</a>':esc(s.title))
    +(s.gu?' <span class="loc2">'+esc(s.sido+" "+s.gu)+'</span>':'')+'</li>';
}
var WD=["일","월","화","수","목","금","토"];
function weekdayKo(ds){var d=new Date(ds+"T00:00:00");return isNaN(d)?"":WD[d.getDay()];}
function clip(t,n){t=t||"";return t.length>n?t.slice(0,n)+"…":t;}
function weekSummary(arr){
  // 그 주 기사들의 한두 줄 리뷰(명사 종결) — 분야별 대표 헤드라인을 엮음
  var order=["policy","price","macro","semicon"];
  var rank={red:0,yellow:1,none:2};
  var parts=[];
  order.forEach(function(c){
    var cs=arr.filter(function(s){return s.cat===c;});
    if(!cs.length) return;
    cs.sort(function(a,b){return (rank[a.trig]||2)-(rank[b.trig]||2)||(b.date||"").localeCompare(a.date||"");});
    var lead=cs[0];
    parts.push('<span class="wsb">'+(CAT[c]||c)+'</span> '
      +(lead.trig==="red"?"🔴 ":lead.trig==="yellow"?"🟡 ":"")+esc(clip(lead.title,34)));
  });
  return parts.length?parts.join("<br>"):"주요 시그널 없음.";
}
function sigLineND(s){   // 날짜 생략(일자 헤더에 표시) · 카테고리 태그 부착
  return '<li><span class="wtag '+esc(s.cat||"")+'">'+esc(CAT[s.cat]||s.cat||"-")+'</span>'
    +'<span class="wb">'+(s.trig==="red"?"🔴":s.trig==="yellow"?"🟡":"·")+'</span>'+futBadge(s.date)
    +(s.url?'<a class="tl" href="'+safeUrl(s.url)+'" target="_blank" rel="noopener">'+esc(s.title)+'</a>':esc(s.title))
    +(s.gu?' <span class="loc2">'+esc(s.sido+" "+s.gu)+'</span>':'')+'</li>';
}
function renderWeekly(){
  var g={};
  SIG.forEach(function(s){ if(!s.date)return; var k=mondayOf(s.date); (g[k]=g[k]||[]).push(s); });
  var weeks=Object.keys(g).sort().reverse();
  var CAP=20, shown=weeks.slice(0,CAP);
  var peak=0; weeks.forEach(function(w){ if(g[w].length>peak)peak=g[w].length; });
  var cats=[["","전체"],["policy","정책·세제"],["price","시세·실거래"],["macro","금리·거시"],["semicon","반도체"]];
  var chips=cats.map(function(c){return '<button class="chip wf'+(S.wcat===c[0]?" on":"")+'" data-wcat="'+c[0]+'">'+c[1]+'</button>';}).join("");
  var h='<div class="lead">주(월~일)별 동향 — 최신순'+(weeks.length>CAP?(" · 최근 "+CAP+"주"):"")
    +' · 카드를 펼치면 일자별 전체'
    +' &nbsp;<span class="lgd"><span class="lr">🔴 즉시</span>=제도·금리 변경 등 즉시 영향 · <span class="ly">🟡 주목</span>=추세 점검</span></div>'
    +'<div class="wfbar">'+chips+'</div>';
  function pass(s){ return !S.wcat || s.cat===S.wcat; }
  shown.forEach(function(mon){
    var arr=g[mon].slice().sort(function(a,b){return (b.date||"").localeCompare(a.date||"");});
    var fa=arr.filter(pass);
    if(!fa.length) return;            // 필터 적용 후 빈 주는 숨김
    var reds=arr.filter(function(s){return s.trig==="red";});
    var yel=arr.filter(function(s){return s.trig==="yellow";});
    var pct=peak?Math.round(arr.length/peak*100):0;
    // 일자별 — 전부 표시, 날짜는 헤더에 한 번만
    var byd={}; fa.forEach(function(s){ (byd[s.date]=byd[s.date]||[]).push(s); });
    var days=Object.keys(byd).sort().reverse();
    var dd=days.map(function(d){
      var da=byd[d].slice().sort(function(a,b){return (a.trig==="red"?0:a.trig==="yellow"?1:2)-(b.trig==="red"?0:b.trig==="yellow"?1:2);});
      var dr=da.filter(function(s){return s.trig==="red";}).length;
      var dy=da.filter(function(s){return s.trig==="yellow";}).length;
      return '<div class="ddd"><div class="ddh">'+esc(d.slice(5))+' ('+weekdayKo(d)+') <span class="ddn">'+da.length+'건'
        +(dr?' · <span class="lr">🔴'+dr+'</span>':'')+(dy?' · <span class="ly">🟡'+dy+'</span>':'')+'</span></div>'
        +'<ul class="wkl">'+da.map(sigLineND).join("")+'</ul></div>';
    }).join("");
    h+='<section class="wk"><div class="wkh"><span class="wwk">W'+isoWeek(mon)+'</span>'
      +'<b>'+mon+' ~ '+addDays(mon,6)+'</b>'
      +'<span class="wkn">총 '+arr.length+' · <span class="lr">🔴 즉시 '+reds.length+'</span> · <span class="ly">🟡 주목 '+yel.length+'</span></span></div>'
      +'<div class="bar"><span style="width:'+pct+'%"></span></div>'
      +'<div class="wsum">'+weekSummary(arr)+'</div>'
      +'<details class="dd"'+(mon===shown[0]?" open":"")+'><summary>일자별 전체 ('+fa.length+'건'+(S.wcat?" · "+(CAT[S.wcat]||S.wcat):"")+')</summary>'+dd+'</details>'
      +'</section>';
  });
  document.getElementById("view-weekly").innerHTML=h;
  document.querySelectorAll(".chip.wf").forEach(function(b){
    b.onclick=function(){ S.wcat=b.getAttribute("data-wcat"); renderWeekly(); };
  });
}

/* ---------- 렌더 ---------- */
function render(){
  buildSidebar();
  document.getElementById("view-list").style.display=S.view==="list"?"block":"none";
  document.getElementById("view-report").classList.toggle("on",S.view==="report");
  document.getElementById("view-monitor").classList.toggle("on",S.view==="monitor");
  document.getElementById("view-bands").classList.toggle("on",S.view==="bands");
  document.getElementById("view-apt").classList.toggle("on",S.view==="apt");
  document.getElementById("view-weekly").classList.toggle("on",S.view==="weekly");
  document.getElementById("view-frames").classList.toggle("on",S.view==="frames");
  document.getElementById("view-personal").classList.toggle("on",S.view==="personal");
  var crumb=document.getElementById("crumb");
  if(S.view==="list"){ crumb.style.display=""; renderRegbar(); renderCrumb(); renderList();
    setTimeout(function(){ if(map){ map.invalidateSize(); renderMap(); } },60); }
  else {
    if(S.view==="weekly") renderWeekly();
    if(S.view==="monitor") renderMonitor();
    if(S.view==="bands") renderBands();
    if(S.view==="apt") renderApt();
    if(S.view==="report"){ crumb.style.display="none"; crumb.innerHTML=""; }
    else { crumb.style.display=""; crumb.innerHTML='<span class="cp">'
      +(S.view==="monitor"?"📊 동향 모니터링 — 공식 지표 ↔ 뉴스 정합"
       :S.view==="bands"?"📐 밴드 분석 — 가격대·면적대 분리"
       :S.view==="apt"?"🏢 아파트 정보 — 단지 카탈로그"
       :S.view==="weekly"?"🗓 주차별 정리 — 주별 동향(일자 드릴다운)"
       :S.view==="frames"?"📚 부읽남 38강 판단 프레임":"👤 개인 맞춤(정훈) — 보조")+'</span>'; }
  }
  a11yPass();
}
// 접근성 보강: click-only 요소를 키보드로 조작 가능하게(tabindex/role 부여)
var A11Y_SEL=".navitem,.rchip,.chip,.gu,.cp.loc,.wkhead,.dcard,.regbar .rchip";
function a11yPass(){
  document.querySelectorAll(A11Y_SEL).forEach(function(el){
    if(el.tagName==="BUTTON"||el.tagName==="A") return;
    if(!el.hasAttribute("tabindex")) el.setAttribute("tabindex","0");
    if(!el.hasAttribute("role")) el.setAttribute("role","button");
  });
}
document.addEventListener("keydown",function(e){
  if(e.key!=="Enter"&&e.key!==" ") return;
  var t=e.target;
  if(t&&t.matches&&t.matches(A11Y_SEL+',[role="button"]')&&t.tagName!=="BUTTON"&&t.tagName!=="A"&&t.id!=="q"){
    e.preventDefault(); t.click();
  }
});

/* ---------- 이벤트 ---------- */
document.querySelectorAll(".chip[data-cat]").forEach(function(b){
  b.onclick=function(){ document.querySelectorAll(".chip[data-cat]").forEach(function(x){x.classList.remove("on");});
    b.classList.add("on"); S.cat=b.getAttribute("data-cat"); S.view="list"; render(); };
});
document.querySelectorAll(".chip.tg").forEach(function(b){
  b.onclick=function(){ var t=b.getAttribute("data-trig");
    if(S.trig===t){S.trig=null;b.classList.remove("on");}
    else{S.trig=t;document.querySelectorAll(".chip.tg").forEach(function(x){x.classList.remove("on");});b.classList.add("on");}
    S.view="list"; render(); };
});
document.getElementById("sort").onchange=function(e){S.sort=e.target.value;renderList();};
document.getElementById("q").oninput=function(e){S.q=e.target.value.toLowerCase().trim();
  if(S.view!=="apt") S.view="list"; render();};
function closeSide(){document.getElementById("side").classList.remove("open");document.getElementById("backdrop").classList.remove("on");
  document.getElementById("burger").setAttribute("aria-expanded","false");}
document.getElementById("burger").onclick=function(){var o=document.getElementById("side").classList.toggle("open");
  document.getElementById("backdrop").classList.toggle("on",o);this.setAttribute("aria-expanded",o?"true":"false");};
document.getElementById("backdrop").onclick=closeSide;
// 테마 전환(라이트/다크) — OS 선호 존중 + 수동 오버라이드 저장
(function(){
  var root=document.documentElement, btn=document.getElementById("theme");
  function apply(t){ if(t){root.setAttribute("data-theme",t);} btn.textContent=(cur()==="dark"?"☀":"◐"); }
  function cur(){ var t=root.getAttribute("data-theme"); return t||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light"); }
  try{ var sv=localStorage.getItem("apt-theme"); if(sv)apply(sv); else apply(); }catch(e){ apply(); }
  btn.onclick=function(){ var n=cur()==="dark"?"light":"dark"; apply(n); try{localStorage.setItem("apt-theme",n);}catch(e){} };
})();
function goHome(){ S={view:"report",sido:null,gu:null,cat:"",trig:null,q:"",sort:"date_desc"};
  document.getElementById("q").value=""; var so=document.getElementById("sort"); if(so)so.value="date_desc";
  document.querySelectorAll(".chip").forEach(function(x){x.classList.remove("on");});
  var a=document.querySelector('.chip[data-cat=""]'); if(a)a.classList.add("on"); render(); closeSide(); }
document.getElementById("brand").onclick=goHome;
document.getElementById("brand").onkeydown=function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();goHome();}};

render();
window.addEventListener("load",initMap);
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
