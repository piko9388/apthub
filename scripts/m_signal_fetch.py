#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
m_signal_fetch.py  —  정훈 맞춤 부동산 시그널(m-SIGNAL) 백데이터 인제스트 하네스
=================================================================================
공식 Open API(국토부 RTMS / 한국은행 ECOS / 금감원 DART)에서 직접 끌어와
apthub 적재용 Signal JSON 배열로 변환한다. 집계사이트/블로그 스크래핑 없음.

[출력 스키마] (apthub add --file 호환)
  { "title","source","url","date":"YYYY-MM-DD",
    "summary","category":"policy|price|macro|semicon","implication" }
  - areas/keywords/trigger 는 비운다(적재 시 자동 태깅).
  - --with-confidence 시 "confidence":"●공식|◐통설|○추정" 1필드 추가(3번 모듈).

[수집 축]
  RTMS  : 아파트 매매·전월세 실거래(단지·전용㎡·억·층) + 지역×월 집계
          + 면적대(40/60/85/130㎡) 중위가 → kind:"data"·metric "평형별 실거래가"·area_band (밴드 분석 뷰)
  ECOS  : 기준금리(검증). COFIX·M2 등은 통계코드 확정 후 활성.
  DART  : SK하이닉스 실적 공시.
  R-ONE : 규모별 가격지수(STATBL_ID 확정 후 활성, REB_KEY) — area_band 시계열.

[실행]
  # 키 없이 동작 검증(번들 샘플로 변환만)
  python3 scripts/m_signal_fetch.py --selftest --out sample.json

  # 빈 구 11곳을 한 번에(웹 스니펫이 막힌 영역) — 면적대 밴드까지 자동 산출
  RTMS_KEY=... python3 scripts/m_signal_fetch.py --regions gaps --months 12 --out out.json
  # 전체(강서·검단·빈구) / 특정 구
  RTMS_KEY=... ECOS_KEY=... python3 scripts/m_signal_fetch.py --regions all --out out.json
  RTMS_KEY=... python3 scripts/m_signal_fetch.py --regions gunpo,gimpo,bupyeong --out out.json

  # 이후 적재 + 빌드 + 리포트
  PYTHONPATH=src python3 -m apthub add --file out.json --by-date
  python3 scripts/build_site.py && python3 scripts/gen_reports.py

키 발급: RTMS/청약 → data.go.kr · 거시 → ecos.bok.or.kr · 공시 → opendart.fss.or.kr · R-ONE → data.go.kr(#15134761).
빈 구(--regions gaps): 군포·김포·시흥·안산(상록/단원)·의왕·하남 / 인천 계양·동구·부평·중구.
stdlib만 사용(urllib, xml.etree, json) — pip 설치 불필요.
"""

import os, sys, json, argparse, time, datetime as dt
from urllib import request, parse, error
import xml.etree.ElementTree as ET

# =============================================================================
# CONFIG  —  정훈 매수계획 파라미터 (여기만 고치면 implication 전체가 갱신됨)
# =============================================================================
P = {
    "CEIL_AUG":     8.50e8,   # 8월 천장 (희주 단독 생애최초)
    "CEIL_FEB27":  10.50e8,   # 27.2 천장 (하이닉스 PS 수령 후)
    "LOAN_CAP":     6.00e8,   # 수도권/규제지역 주담대 6억 상한
    "LTV_FIRST":    0.70,     # 생애최초 LTV 70% (10·15에도 유지)
    "AREA_MIN":     59.0,     # 전용 59㎡ 이상
    "GIFT_MAX":     3.00e8,   # 양가 혼인+출산 증여공제 최대(무세)
}

# 법정동코드 앞5자리 (RTMS LAWD_CD)
REGIONS = {
    "gangseo": {"code": "11500", "label": "서울 강서구", "regulated": True},   # 투기과열+토허
    "geomdan": {"code": "28260", "label": "인천 서구(검단)", "regulated": False}, # 비규제(풍선효과)
    # 표본 부족 잔여 구 — 웹 스니펫이 막혀 RTMS API로 정합 수집
    "gunpo":   {"code": "41410", "label": "경기 군포시", "regulated": False},
    "gimpo":   {"code": "41570", "label": "경기 김포시", "regulated": False},
    "siheung": {"code": "41390", "label": "경기 시흥시", "regulated": False},
    "ansan_sr":{"code": "41271", "label": "경기 안산시 상록구", "regulated": False},
    "ansan_dw":{"code": "41273", "label": "경기 안산시 단원구", "regulated": False},
    "uiwang":  {"code": "41430", "label": "경기 의왕시", "regulated": False},
    "hanam":   {"code": "41450", "label": "경기 하남시", "regulated": False},
    "gyeyang": {"code": "28245", "label": "인천 계양구", "regulated": False},
    "ic_donggu":{"code": "28140", "label": "인천 동구", "regulated": False},
    "bupyeong":{"code": "28237", "label": "인천 부평구", "regulated": False},
    "ic_junggu":{"code": "28110", "label": "인천 중구", "regulated": False},
}
# 빈 구 일괄 수집용 그룹(--regions gaps)
REGION_GROUPS = {
    "gaps": ["gunpo", "gimpo", "siheung", "ansan_sr", "ansan_dw", "uiwang",
             "hanam", "gyeyang", "ic_donggu", "bupyeong", "ic_junggu"],
    "all": None,   # 전체
}

# 관심단지 — 매칭 시 강조(부분일치). 미매칭 거래도 천장밴드/신고가면 신호화.
WATCH_CANDIDATE = ["가양2", "가양3", "가양4", "가양5", "가양6", "가양9",
                   "강변", "한강타운", "염창"]              # 천장 내 후보군
WATCH_WATCHONLY = ["등촌주공", "마곡엠밸리", "우장산힐스테이트", "우장산롯데캐슬",
                   "강서한강자이", "힐스테이트등촌역", "가양역두산",
                   "우장산숲아이파크", "e편한세상염창"]       # 천장 초과 관찰군

# ECOS 통계코드 — 기준금리는 검증 완료. 나머지는 코드목록에서 확정 후 주석 해제.
ECOS_SERIES = [
    {"code": "722Y001", "item": "0101000", "period": "M",
     "name": "한국은행 기준금리", "verified": True},
    # {"code": "722Y001", "item": "0101000", "period": "D", "name": "기준금리(일별)"},
    # {"code": "121Y002", "item": "...", "period": "M", "name": "신규취급액 COFIX"},   # TODO 코드 확정
    # {"code": "101Y004", "item": "...", "period": "M", "name": "M2(평잔)"},           # TODO 코드 확정
    # {"code": "151Y005", "item": "...", "period": "M", "name": "가계신용"},           # TODO 코드 확정
]

DART_CORP = {"skhynix": "00164779"}   # SK하이닉스 DART corp_code(8자리) — corpCode.xml로 검증 가능

# 3번 모듈: 도메인 → 신뢰도 (m-SIGNAL Option B 색상)
TRUST = {
    "●공식": ["data.go.kr", "ecos.bok.or.kr", "opendart.fss.or.kr", "dart.fss.or.kr",
              "fss.or.kr", "reb.or.kr", "rt.molit.go.kr", "korea.kr", "molit.go.kr",
              "fsc.go.kr", "moef.go.kr", "nts.go.kr", "bok.or.kr", "news.skhynix.co.kr"],
    "◐통설": ["hankyung.com", "mk.co.kr", "edaily.co.kr", "heraldcorp.com",
              "thelec.kr", "esgeconomy.com"],
    # 그 외 전부 ○추정 (블로그/카페/SNS/SEO)
}
TRUST_BLACKLIST = ["yna.co.kr", "yonhapnews"]   # AI 학습·활용 금지 → 적재 제외


def confidence_of(url: str) -> str:
    """URL 도메인 → 신뢰도 등급. apthub 적재부에서 재사용 가능(3번 모듈 핵심)."""
    host = (parse.urlparse(url).hostname or "").lower()
    for tier, domains in TRUST.items():
        if any(d in host for d in domains):
            return tier
    return "○추정"


# =============================================================================
# HTTP / 파싱 유틸
# =============================================================================
def http_get(url, params=None, timeout=20, retries=2, parse_json=False):
    if params:
        url = url + "?" + parse.urlencode(params)
    last = None
    for _ in range(retries + 1):
        try:
            req = request.Request(url, headers={"User-Agent": "m-signal/1.0"})
            with request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if parse_json else raw
        except (error.URLError, error.HTTPError, TimeoutError) as e:
            last = e
            time.sleep(1.0)
    raise last


def won(amount_str):
    """RTMS 거래금액('120,000' 만원, 공백/콤마 포함) → 원(int)."""
    s = (amount_str or "").replace(",", "").replace(" ", "").strip()
    return int(s) * 10_000 if s.isdigit() else 0


def eok(w):
    return round(w / 1e8, 2)


def area_bucket(area):
    """전용면적 → 평형대 버킷(신고가/전세가율 비교 단위)."""
    try:
        a = float(area)
    except (TypeError, ValueError):
        return "기타"
    for b in (49, 59, 74, 84, 114):
        if a <= b + 5:
            return str(b)
    return "115+"


def area_band_of(area):
    """전용면적 → 표준 면적대 밴드(R-ONE 규모별 기준: 40/60/85/130㎡)."""
    try:
        a = float(area)
    except (TypeError, ValueError):
        return ""
    if a <= 40:
        return "40이하"
    if a <= 60:
        return "40-60"
    if a <= 85:
        return "60-85"
    if a <= 130:
        return "85-130"
    return "130초과"


def split_label(label):
    """'서울 강서구' / '인천 서구(검단)' / '경기 안산시 상록구' → (sido, gu)."""
    parts = label.replace("(", " ").split()
    sido = parts[0]
    gu = parts[1] if len(parts) > 1 else ""
    return sido, gu


def bands_to_signals(trades):
    """RTMS 매매 → 면적대(area_band)×지역×월 중위가 data 신호(밴드 분리 뷰용).
       웹으로 못 뽑는 면적대 시계열을 실거래 원본에서 직접 산출."""
    grp = {}
    for r in trades:
        band = area_band_of(r.get("area"))
        if not band:
            continue
        sido, gu = split_label(r["region"])
        ym = r["date"][:7]
        grp.setdefault((sido, gu, band, ym), []).append(r["price_won"])
    out = []
    for (sido, gu, band, ym), prices in grp.items():
        if len(prices) < 1:
            continue
        prices.sort()
        med = prices[len(prices) // 2]
        out.append({
            "kind": "data",
            "title": f"{sido} {gu} {band}㎡ 매매 중위 {eok(med)}억 ({ym}·RTMS {len(prices)}건)",
            "source": "국토교통부 RTMS 실거래가",
            "url": "https://rt.molit.go.kr/",
            "date": f"{ym}-01",
            "summary": (f"{sido} {gu} 전용 {band}㎡ {ym} 신고 매매 {len(prices)}건, "
                        f"중위 {eok(med)}억(최고 {eok(prices[-1])}·최저 {eok(prices[0])})."),
            "category": "price",
            "metric": "평형별 실거래가",
            "value": eok(med),
            "unit": "억",
            "sido": sido,
            "area_band": band,
            "_conf": confidence_of("https://rt.molit.go.kr/"),
        })
    return out


def recent_months(n):
    """직전 n개월 'YYYYMM' 리스트(최신→과거)."""
    today = dt.date.today().replace(day=1)
    out = []
    for i in range(n):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12; y -= 1
        out.append(f"{y}{m:02d}")
    return out


# =============================================================================
# 매수계획 함의(implication) 엔진 — API 수치 → 정훈 맞춤 한 줄
# =============================================================================
def classify(price_won):
    if price_won <= P["CEIL_AUG"]:
        return "천장내_8월"
    if price_won <= P["CEIL_FEB27"]:
        return "천장내_27.2"
    return "천장초과"


def self_capital_gap(price_won):
    loan = min(price_won * P["LTV_FIRST"], P["LOAN_CAP"])
    return price_won - loan


def impl_trade(rec, is_high):
    p = rec["price_won"]; cls = classify(p); gap = self_capital_gap(p)
    head = "신고가(수집구간) " if is_high else ""
    try:
        small = float(rec["area"] or 0) < P["AREA_MIN"]
    except ValueError:
        small = False
    sz = f" 단 전용 {rec['area']}㎡로 59㎡·방3 요건 미달, 후보 제외." if small else ""
    if cls == "천장내_8월":
        cov = "증여 3억 내 충당 가능" if gap <= P["GIFT_MAX"] else f"자기자본 {eok(gap)}억 필요"
        return (f"{head}천장 내(8월 8.5억)·전용 {rec['area']}㎡ → LTV70%·6억상한 적용 "
                f"자기자본 갭 {eok(gap)}억, {cov}. 8월 진입 후보.{sz}")
    if cls == "천장내_27.2":
        return (f"{head}8월 천장 초과·27.2 천장(10.5억) 내 → 6억상한 적용 자기자본 갭 {eok(gap)}억, "
                f"하이닉스 PS 수령(27.2) 후 진입 사정권.{sz}")
    return (f"{head}27.2 천장(10.5억)도 초과({eok(p)}억) → 6억상한 시 자기자본 {eok(gap)}억 필요, "
            f"관찰 전용·매수 대상 아님.")


def impl_rent(rec, sale_med_won):
    dep = rec["deposit_won"]
    if rec["monthly_won"] == 0 and sale_med_won:           # 순수 전세 + 매매 comp 존재
        jr = round(dep / sale_med_won * 100)
        return (f"전세가율 {jr}%(전세 {eok(dep)}억/매매중위 {eok(sale_med_won)}억), 갭 "
                f"{eok(sale_med_won - dep)}억 → 토허 2년 실거주의무로 갭투자 불가, 실거주 매수만 유효.")
    kind = "전세" if rec["monthly_won"] == 0 else f"월세(보증 {eok(dep)}억)"
    return (f"{kind} 체결·전용 {rec['area']}㎡ → 매매 comp 부재로 전세가율 산출 보류, "
            f"동단지 매매 수집 후 갭 재계산 권장.")


def impl_macro(name, series):
    if not series:
        return f"{name} 시계열 비어있음 — 통계코드 확정 필요."
    cur = series[-1]["value"]; prev = series[0]["value"]
    if name.startswith("한국은행 기준금리"):
        trend = "동결" if cur == prev else ("인하" if cur < prev else "인상")
        return (f"기준금리 {cur}%({trend}) → 코픽스·변동 주담대 안정, 8월 금리급등 리스크 낮음. "
                f"인하 재개는 27.2 전후 전망이라 27.2 매수가 금리·PS 동시 유리.")
    arrow = "상승" if cur > prev else ("하락" if cur < prev else "보합")
    return f"{name} {cur}({arrow}) → 매수 타이밍(8월 vs 27.2) 거시 변수로 모니터링."


def impl_semicon(report_nm):
    return ("하이닉스 실적/공시 → PS 재원(전년 영업이익 10%) 직접 연동, "
            "2026 실적분 PS는 27.2 지급 → 정훈 자기자본 천장(8.5→10.5억) 점프 근거.")


# =============================================================================
# RTMS — 아파트 매매 실거래 상세
# =============================================================================
RTMS_TRADE = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
RTMS_RENT  = "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"


def _parse_rtms_items(xml_text):
    root = ET.fromstring(xml_text)
    return root.iter("item")


def fetch_trade(region, ymd, key):
    rows = []
    xml_text = http_get(RTMS_TRADE, {
        "serviceKey": key, "LAWD_CD": region["code"], "DEAL_YMD": ymd,
        "numOfRows": 1000, "pageNo": 1})
    for it in _parse_rtms_items(xml_text):
        g = lambda t: (it.findtext(t) or "").strip()
        y, m, d = g("dealYear"), g("dealMonth"), g("dealDay")
        if not y:
            continue
        rows.append({
            "apt": g("aptNm"), "umd": g("umdNm"), "area": g("excluUseAr"),
            "bucket": area_bucket(g("excluUseAr")), "floor": g("floor"),
            "build": g("buildYear"), "jibun": g("jibun"),
            "price_won": won(g("dealAmount")),
            "date": f"{y}-{int(m):02d}-{int(d):02d}",
            "region": region["label"],
        })
    return rows


def fetch_rent(region, ymd, key):
    rows = []
    xml_text = http_get(RTMS_RENT, {
        "serviceKey": key, "LAWD_CD": region["code"], "DEAL_YMD": ymd,
        "numOfRows": 1000, "pageNo": 1})
    for it in _parse_rtms_items(xml_text):
        g = lambda t: (it.findtext(t) or "").strip()
        y, m, d = g("dealYear"), g("dealMonth"), g("dealDay")
        if not y:
            continue
        rows.append({
            "apt": g("aptNm"), "umd": g("umdNm"), "area": g("excluUseAr"),
            "bucket": area_bucket(g("excluUseAr")),
            "deposit_won": won(g("deposit")), "monthly_won": won(g("monthlyRent")),
            "date": f"{y}-{int(m):02d}-{int(d):02d}", "region": region["label"],
        })
    return rows


def watch_tag(apt):
    if any(w in apt for w in WATCH_CANDIDATE):
        return "후보"
    if any(w in apt for w in WATCH_WATCHONLY):
        return "관찰"
    return None


def trades_to_signals(trades):
    """매매 거래 → 신호. 신호화 기준: 관심단지 OR 천장밴드(7~11억,59㎡↑) OR 구간내 신고가.
       + 지역×월 집계 신호 1건."""
    sigs = []
    # 구간 내 (단지,버킷) 최고가 식별
    highs = {}
    for r in trades:
        k = (r["region"], r["apt"], r["bucket"])
        if r["price_won"] > highs.get(k, {"price_won": -1})["price_won"]:
            highs[k] = r

    seen = set()
    for r in trades:
        try:
            a = float(r["area"] or 0)
        except ValueError:
            a = 0
        tag = watch_tag(r["apt"])
        in_band = (a >= P["AREA_MIN"] and 7.0e8 <= r["price_won"] <= 11.0e8)
        k = (r["region"], r["apt"], r["bucket"])
        is_high = highs.get(k) is r
        if not (tag or in_band or is_high):
            continue
        sid = (r["region"], r["apt"], r["area"], r["date"], r["price_won"])
        if sid in seen:
            continue
        seen.add(sid)
        flag = f"[{tag}] " if tag else ""
        sigs.append({
            "title": f"{flag}{r['region']} {r['apt']} {r['area']}㎡ {eok(r['price_won'])}억 실거래",
            "source": "국토교통부 RTMS 실거래가",
            "url": "https://rt.molit.go.kr/",
            "date": r["date"],
            "summary": (f"{r['umd']} {r['apt']}({r['build']}년) 전용 {r['area']}㎡ "
                        f"{r['floor']}층 {eok(r['price_won'])}억 매매 신고."),
            "category": "price",
            "implication": impl_trade(r, is_high),
            "_conf": confidence_of("https://rt.molit.go.kr/"),
        })

    # 지역×월 집계
    bym = {}
    for r in trades:
        ym = r["date"][:7]
        bym.setdefault((r["region"], ym), []).append(r["price_won"])
    for (region, ym), prices in bym.items():
        prices.sort()
        med = prices[len(prices) // 2]
        sigs.append({
            "title": f"{region} {ym} 아파트 매매 {len(prices)}건·중위 {eok(med)}억",
            "source": "국토교통부 RTMS 실거래가",
            "url": "https://rt.molit.go.kr/",
            "date": f"{ym}-01",
            "summary": (f"{region} {ym} 신고 매매 {len(prices)}건, 중위 {eok(med)}억, "
                        f"최고 {eok(prices[-1])}억·최저 {eok(prices[0])}억."),
            "category": "macro",
            "implication": (f"중위 {eok(med)}억 기준 천장 8.5억 대비 "
                            + ("여유, 후보 다수" if med <= P["CEIL_AUG"] else "초과, 후보 협소")
                            + " → 거래량은 매도자 협상력 가늠 지표."),
            "_conf": confidence_of("https://rt.molit.go.kr/"),
        })
    return sigs


def rents_to_signals(rents, trades):
    """전월세 → 전세가율 신호(관심/천장밴드 단지 한정). 매매 comp는 동단지×버킷 중위."""
    sale_med = {}
    grp = {}
    for r in trades:
        grp.setdefault((r["apt"], r["bucket"]), []).append(r["price_won"])
    for k, v in grp.items():
        v.sort(); sale_med[k] = v[len(v) // 2]

    sigs, seen = [], set()
    for r in rents:
        tag = watch_tag(r["apt"])
        try:
            a = float(r["area"] or 0)
        except ValueError:
            a = 0
        if not (tag or a >= P["AREA_MIN"]):
            continue
        if r["monthly_won"] != 0:      # 전세가율 신호는 순수 전세만
            continue
        sid = (r["apt"], r["area"], r["date"], r["deposit_won"])
        if sid in seen:
            continue
        seen.add(sid)
        comp = sale_med.get((r["apt"], r["bucket"]))
        flag = f"[{tag}] " if tag else ""
        sigs.append({
            "title": f"{flag}{r['region']} {r['apt']} {r['area']}㎡ 전세 {eok(r['deposit_won'])}억",
            "source": "국토교통부 RTMS 실거래가",
            "url": "https://rt.molit.go.kr/",
            "date": r["date"],
            "summary": (f"{r['umd']} {r['apt']} 전용 {r['area']}㎡ 전세 보증금 "
                        f"{eok(r['deposit_won'])}억 신고."
                        + (f" 동단지 매매중위 {eok(comp)}억." if comp else "")),
            "category": "price",
            "implication": impl_rent(r, comp),
            "_conf": confidence_of("https://rt.molit.go.kr/"),
        })
    return sigs


# =============================================================================
# ECOS — 시계열
# =============================================================================
ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"


def fetch_ecos(series, key, start, end):
    sub = f"/{series['item']}" if series.get("item") else ""
    url = (f"{ECOS_BASE}/{key}/json/kr/1/100/"
           f"{series['code']}/{series['period']}/{start}/{end}{sub}")
    data = http_get(url, parse_json=True)
    if "StatisticSearch" not in data:
        return []   # RESULT 에러(데이터 없음/코드 오류)
    out = []
    for row in data["StatisticSearch"].get("row", []):
        try:
            out.append({"time": row["TIME"], "value": float(row["DATA_VALUE"]),
                        "unit": row.get("UNIT_NAME", "")})
        except (KeyError, ValueError):
            continue
    return out


def ecos_to_signals(series_meta, points):
    if not points:
        return []
    last = points[-1]
    t = last["time"]
    date = f"{t[:4]}-{t[4:6]}-01" if len(t) >= 6 else f"{t}-01-01"
    return [{
        "title": f"{series_meta['name']} {last['value']}{last['unit']} ({t})",
        "source": "한국은행 ECOS",
        "url": "https://ecos.bok.or.kr/",
        "date": date,
        "summary": (f"{series_meta['name']} 최신치 {last['value']}{last['unit']}"
                    f"(기준 {t}), 수집구간 {points[0]['time']}~{t}."),
        "category": "macro",
        "implication": impl_macro(series_meta["name"], points),
        "_conf": confidence_of("https://ecos.bok.or.kr/"),
    }]


# =============================================================================
# R-ONE (한국부동산원) — 면적대별/지역별 가격지수 (data.go.kr #15134761)
# =============================================================================
# OpenAPI: SttsApiTblData.do?KEY=...&STATBL_ID=...&DTACYCLE_CD=MM&...&Type=json
# STATBL_ID(통계표 ID)는 R-ONE 통계표 목록(SttsApiTbl.do)에서 확정해야 한다.
# 잘못된 ID를 박으면 엉뚱한 시계열이 들어오므로, 검증 전까지 verified=False로 비워둔다(ECOS와 동일 원칙).
REB_BASE = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
REB_SERIES = [
    # {"statbl_id": "TODO_규모별매매지수", "metric": "매매가격지수 변동률",
    #  "name": "아파트 매매가격지수(규모별)", "cycle": "MM", "verified": False},
    # {"statbl_id": "TODO_규모별전세지수", "metric": "전세가격지수 변동률",
    #  "name": "아파트 전세가격지수(규모별)", "cycle": "MM", "verified": False},
]


def fetch_reb(meta, key, start, end):
    """R-ONE 통계표 데이터 조회(검증된 STATBL_ID에 한해). 미검증이면 [] 반환."""
    if not meta.get("verified"):
        return []
    data = http_get(REB_BASE, {
        "KEY": key, "Type": "json", "STATBL_ID": meta["statbl_id"],
        "DTACYCLE_CD": meta.get("cycle", "MM"),
        "START_WRTTIME": start, "END_WRTTIME": end, "pIndex": 1, "pSize": 500,
    }, parse_json=True)
    # 응답 구조는 STATBL_ID별로 상이 → 확정 후 row 매핑 구현(area_band·sido 포함)
    return []


# =============================================================================
# DART — 공시목록(실적)
# =============================================================================
DART_LIST = "https://opendart.fss.or.kr/api/list.json"
KW = ("실적", "분기보고서", "반기보고서", "사업보고서", "영업(잠정)", "주요사항")


def fetch_dart(corp_code, key, start, end):
    data = http_get(DART_LIST, {
        "crtfc_key": key, "corp_code": corp_code,
        "bgn_de": start, "end_de": end, "page_count": 100}, parse_json=True)
    return data.get("list", []) if data.get("status") == "000" else []


def dart_to_signals(items):
    sigs = []
    for it in items:
        nm = it.get("report_nm", "")
        if not any(k in nm for k in KW):
            continue
        d = it.get("rcept_dt", "")
        date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
        rcp = it.get("rcept_no", "")
        url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}"
        sigs.append({
            "title": f"{it.get('corp_name','SK하이닉스')} 공시: {nm}",
            "source": "금융감독원 DART",
            "url": url,
            "date": date,
            "summary": f"{it.get('corp_name','')} '{nm}' 접수({d}). 원문 DART 공시.",
            "category": "semicon",
            "implication": impl_semicon(nm),
            "_conf": confidence_of(url),
        })
    return sigs


# =============================================================================
# 적재/출력
# =============================================================================
def finalize(signals, with_conf):
    out, seen = [], set()
    for s in signals:
        conf = s.pop("_conf", "○추정")
        host = (parse.urlparse(s["url"]).hostname or "")
        if any(b in host for b in TRUST_BLACKLIST):     # 약관상 제외
            continue
        key = (s["title"], s["date"])                   # 중복 1건, 후속은 날짜별 별건
        if key in seen:
            continue
        seen.add(key)
        if with_conf:
            s["confidence"] = conf
        out.append(s)
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


# =============================================================================
# SELFTEST  —  키 없이 변환 로직 검증(번들 샘플)
# =============================================================================
SAMPLE_TRADE_XML = """<response><body><items>
<item><aptNm>가양2단지성지</aptNm><umdNm>가양동</umdNm><excluUseAr>59.92</excluUseAr>
<floor>7</floor><buildYear>1992</buildYear><jibun>1481</jibun>
<dealAmount> 74,000</dealAmount><dealYear>2026</dealYear><dealMonth>5</dealMonth><dealDay>12</dealDay></item>
<item><aptNm>마곡엠밸리7단지</aptNm><umdNm>마곡동</umdNm><excluUseAr>84.96</excluUseAr>
<floor>10</floor><buildYear>2014</buildYear><jibun>770</jibun>
<dealAmount>198,500</dealAmount><dealYear>2026</dealYear><dealMonth>5</dealMonth><dealDay>20</dealDay></item>
<item><aptNm>등촌주공5단지</aptNm><umdNm>등촌동</umdNm><excluUseAr>84.60</excluUseAr>
<floor>3</floor><buildYear>1995</buildYear><jibun>691</jibun>
<dealAmount>120,000</dealAmount><dealYear>2026</dealYear><dealMonth>5</dealMonth><dealDay>9</dealDay></item>
<item><aptNm>강변</aptNm><umdNm>마곡동</umdNm><excluUseAr>49.50</excluUseAr>
<floor>8</floor><buildYear>1992</buildYear><jibun>744</jibun>
<dealAmount> 95,000</dealAmount><dealYear>2026</dealYear><dealMonth>5</dealMonth><dealDay>1</dealDay></item>
</items></body></response>"""

SAMPLE_RENT_XML = """<response><body><items>
<item><aptNm>가양2단지성지</aptNm><umdNm>가양동</umdNm><excluUseAr>59.92</excluUseAr>
<deposit> 42,000</deposit><monthlyRent>0</monthlyRent>
<dealYear>2026</dealYear><dealMonth>5</dealMonth><dealDay>15</dealDay></item>
</items></body></response>"""

SAMPLE_ECOS = {"StatisticSearch": {"row": [
    {"TIME": "202604", "DATA_VALUE": "2.5", "UNIT_NAME": "%"},
    {"TIME": "202605", "DATA_VALUE": "2.5", "UNIT_NAME": "%"},
]}}

SAMPLE_DART = [{"corp_name": "SK하이닉스", "report_nm": "분기보고서 (2026.03)",
                "rcept_dt": "20260515", "rcept_no": "20260515000123"}]


def run_selftest(with_conf):
    region = REGIONS["gangseo"]
    trades = []
    for it in _parse_rtms_items(SAMPLE_TRADE_XML):
        g = lambda t: (it.findtext(t) or "").strip()
        y, m, d = g("dealYear"), g("dealMonth"), g("dealDay")
        trades.append({"apt": g("aptNm"), "umd": g("umdNm"), "area": g("excluUseAr"),
                       "bucket": area_bucket(g("excluUseAr")), "floor": g("floor"),
                       "build": g("buildYear"), "jibun": g("jibun"),
                       "price_won": won(g("dealAmount")),
                       "date": f"{y}-{int(m):02d}-{int(d):02d}", "region": region["label"]})
    rents = []
    for it in _parse_rtms_items(SAMPLE_RENT_XML):
        g = lambda t: (it.findtext(t) or "").strip()
        y, m, d = g("dealYear"), g("dealMonth"), g("dealDay")
        rents.append({"apt": g("aptNm"), "umd": g("umdNm"), "area": g("excluUseAr"),
                      "bucket": area_bucket(g("excluUseAr")),
                      "deposit_won": won(g("deposit")), "monthly_won": won(g("monthlyRent")),
                      "date": f"{y}-{int(m):02d}-{int(d):02d}", "region": region["label"]})

    sigs = []
    sigs += trades_to_signals(trades)
    sigs += rents_to_signals(rents, trades)
    sigs += ecos_to_signals(ECOS_SERIES[0], [
        {"time": r["TIME"], "value": float(r["DATA_VALUE"]), "unit": r["UNIT_NAME"]}
        for r in SAMPLE_ECOS["StatisticSearch"]["row"]])
    sigs += dart_to_signals(SAMPLE_DART)
    return finalize(sigs, with_conf)


# =============================================================================
# MAIN
# =============================================================================
def resolve_regions(arg):
    """--regions 값 해석: 그룹(gaps/all) 또는 콤마구분 키."""
    if arg in REGION_GROUPS:
        keys = REGION_GROUPS[arg] or list(REGIONS)
    else:
        keys = [k for k in arg.split(",") if k in REGIONS]
    return [REGIONS[k] for k in keys]


def run_live(args):
    rtms = os.environ.get("RTMS_KEY"); ecos = os.environ.get("ECOS_KEY")
    dart = os.environ.get("DART_KEY"); reb = os.environ.get("REB_KEY")
    months = recent_months(args.months)
    regions = resolve_regions(args.regions)
    sigs = []

    if rtms:
        for region in regions:
            all_t, all_r = [], []
            for ym in months:
                try:
                    all_t += fetch_trade(region, ym, rtms)
                    all_r += fetch_rent(region, ym, rtms)
                    time.sleep(0.3)
                except Exception as e:
                    print(f"  ! RTMS {region['label']} {ym}: {e}", file=sys.stderr)
            sigs += trades_to_signals(all_t)
            sigs += rents_to_signals(all_r, all_t)
            sigs += bands_to_signals(all_t)        # 면적대 밴드 data 신호
    else:
        print("  - RTMS_KEY 없음 → 매매/전세 스킵", file=sys.stderr)

    if reb and REB_SERIES:
        for meta in REB_SERIES:
            try:
                sigs += fetch_reb(meta, reb, months[-1], months[0])
            except Exception as e:
                print(f"  ! R-ONE {meta.get('name')}: {e}", file=sys.stderr)
    elif not reb:
        print("  - REB_KEY 없음 → R-ONE 규모별 지수 스킵(STATBL_ID 확정 후 활성)", file=sys.stderr)

    if ecos:
        start, end = months[-1], months[0]
        for meta in ECOS_SERIES:
            try:
                pts = fetch_ecos(meta, ecos, start, end)
                sigs += ecos_to_signals(meta, pts)
            except Exception as e:
                print(f"  ! ECOS {meta['name']}: {e}", file=sys.stderr)
    else:
        print("  - ECOS_KEY 없음 → 거시 스킵", file=sys.stderr)

    if dart:
        end = dt.date.today().strftime("%Y%m%d")
        start = (dt.date.today() - dt.timedelta(days=args.months * 31)).strftime("%Y%m%d")
        for name, corp in DART_CORP.items():
            try:
                sigs += dart_to_signals(fetch_dart(corp, dart, start, end))
            except Exception as e:
                print(f"  ! DART {name}: {e}", file=sys.stderr)
    else:
        print("  - DART_KEY 없음 → 반도체 스킵", file=sys.stderr)

    return finalize(sigs, args.with_confidence)


def main():
    ap = argparse.ArgumentParser(description="m-SIGNAL 인제스트 하네스")
    ap.add_argument("--selftest", action="store_true", help="키 없이 샘플로 변환 검증")
    ap.add_argument("--months", type=int, default=6, help="수집 직전 개월수(기본 6)")
    ap.add_argument("--regions", default="gangseo,geomdan",
                    help="콤마구분 키 또는 그룹: gaps(빈 구 11곳)·all(전체)·gangseo,geomdan,gunpo,…")
    ap.add_argument("--with-confidence", action="store_true", help="신뢰도 필드 포함")
    ap.add_argument("--out", default="out.json", help="출력 파일")
    args = ap.parse_args()

    signals = run_selftest(args.with_confidence) if args.selftest else run_live(args)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)
    print(f"✓ {len(signals)}건 → {args.out}")
    print(f"  적재: PYTHONPATH=src python3 -m apthub add --file {args.out} --by-date")


if __name__ == "__main__":
    main()
