#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apthub_official_apis.py  (v2 — 검증·하드닝판)
수도권 부동산 정량 데이터 → apthub Signal JSON 적재 엔진 (약관 준수 공식 오픈API 전용)

채우는 영역
  C. 평당가 / 평형별 실거래가  ← RTMS (data.go.kr #1613000)  ★주력
  A. area_band (40↓/40-60/60-85/85-130/130↑)  ← RTMS 전용면적 버킷팅
  B. price_band (6↓/6-9/9-15/15-25/25↑)        ← RTMS 거래금액 버킷팅
  D. 서울 25구 → sido 집계 월별 시계열           ← RTMS LAWD_CD 루프(+ --per-gu 구 단위)
  (보조) HUG 면적별 분양가 / 부동산원 규모별 지수 ← KOSIS  (CONFIG에 tblId/항목코드 채우면 동작)
  (보조) 기준금리/주담대금리 등 거시              ← ECOS  (CONFIG에 statCode/itemCode 채우면 동작)

────────────────────────────────────────────────────────────────────────
v2 변경점 (모두 컨테이너 오프라인 테스트로 검증)
  [FIX1] RTMS 태그 무관 파서 — 신 엔드포인트(apis.data.go.kr) 영문 카멜케이스
         (dealAmount/excluUseAr/aptNm…)와 구 한글 태그를 모두 시도.
  [FIX2] 인증/쿼터 오류 명시 감지 — returnAuthMsg/returnReasonCode 읽어 즉시 사유 출력.
  [FIX3] 구별 행을 sido로 집계(기본) — apthub dedup(metric·sido·band·date) 충돌 제거.
         구 단위가 필요하면 --per-gu(region 필드). 카탈로그는 lawd_cd+단지+전용㎡로 항상 구 보존.
  [FIX4] 월 말일 calendar.monthrange — 윤년 2월 정확 처리.
  [FIX5] ECOS/KOSIS main 연결(--ecos/--kosis) + 데이터드리븐 변환.

사용법
  python3 apthub_official_apis.py --rtms --months 202604 202605 --out data-out.json --complex complex-out.json
  # 구 단위: --per-gu · 거시: --ecos · 규모별/분양가(KOSIS): --kosis(CONFIG 채울 것)
적재
  PYTHONPATH=src python3 -m apthub add --file data-out.json --by-date
  python3 scripts/build_site.py

키 발급(무료): RTMS=data.go.kr #1613000 일반 인증키(Decoding) / KOSIS=kosis.kr/openapi / ECOS=ecos.bok.or.kr/api.
키는 환경변수 우선(RTMS_KEY/KOSIS_KEY/ECOS_KEY).
주의: RTMS는 실거래(계약일 기준). 네이버 호가와 섞지 말 것. RTMS_KEY는 반드시 Decoding 키.
"""
import argparse, calendar, json, os, re, ssl, sys, time
import statistics as st
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

# ──────────────────────────── CONFIG ────────────────────────────
RTMS_KEY  = os.environ.get("RTMS_KEY",  "여기에_RTMS_DECODING_인증키")
KOSIS_KEY = os.environ.get("KOSIS_KEY", "여기에_KOSIS_API_KEY")
ECOS_KEY  = os.environ.get("ECOS_KEY",  "여기에_ECOS_인증키")
LH_KEY    = os.environ.get("LH_KEY",    "여기에_LH_인증키")   # data.go.kr #15059475 임대주택단지 조회
KAPT_KEY  = os.environ.get("KAPT_KEY",  "여기에_공동주택표준데이터_인증키")  # data.go.kr #15096285 전국공동주택표준데이터(분모)
KAPT_STD_UDDI = os.environ.get("KAPT_STD_UDDI", "")  # odcloud 표준데이터 리소스 uddi(포털 요청URL에서 확인)

PYEONG = 3.3058                  # 1평 = 3.3058㎡
_SSL = ssl.create_default_context()
HEADERS = {"User-Agent": "apthub/2.0"}
HTTP_RETRY = 3
HTTP_BACKOFF = 0.8

LAWD = {
    "서울 종로구":"11110","서울 중구":"11140","서울 용산구":"11170","서울 성동구":"11200",
    "서울 광진구":"11215","서울 동대문구":"11230","서울 중랑구":"11260","서울 성북구":"11290",
    "서울 강북구":"11305","서울 도봉구":"11320","서울 노원구":"11350","서울 은평구":"11380",
    "서울 서대문구":"11410","서울 마포구":"11440","서울 양천구":"11470","서울 강서구":"11500",
    "서울 구로구":"11530","서울 금천구":"11545","서울 영등포구":"11560","서울 동작구":"11590",
    "서울 관악구":"11620","서울 서초구":"11650","서울 강남구":"11680","서울 송파구":"11710",
    "서울 강동구":"11740",
    "경기 성남분당":"41135","경기 수원영통":"41117","경기 화성":"41590","인천 연수구":"28185",
}
def sido_of(nm):
    return ("서울" if nm.startswith("서울") else
            "경기" if nm.startswith("경기") else
            "인천" if nm.startswith("인천") else "전국")

ECOS_SPECS = [
    {"name":"기준금리", "stat":"722Y001", "item":"0101000", "cycle":"M",
     "metric":"기준금리", "unit":"%"},
]

KOSIS_SPECS = [
    # {"name":"부동산원 규모별 매매변동률(서울 60-85)","org":"408","tbl":"<TBL_ID>",
    #  "objL1":"<지역코드>","itm":"<규모코드>","prdSe":"M",
    #  "metric":"매매가격지수 변동률","unit":"%","sido":"서울","area_band":"60-85"},
]

# ──────────────────────────── 공통 ────────────────────────────
def last_day(ym):
    y, mo = int(ym[:4]), int(ym[4:6])
    return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"

def _http(url, timeout=25, retries=None):
    last = None
    n = HTTP_RETRY if retries is None else retries
    for i in range(n):
        try:
            return urlopen(Request(url, headers=HEADERS), timeout=timeout, context=_SSL).read()
        except (HTTPError, URLError, TimeoutError) as e:
            last = e; time.sleep(HTTP_BACKOFF * (i + 1))
    raise last

def _get(el, *names):
    for n in names:
        v = el.findtext(n)
        if v is not None and v.strip() != "":
            return v.strip()
    return ""

def area_band(m2):
    if m2 <= 40:  return "40이하"
    if m2 <= 60:  return "40-60"
    if m2 <= 85:  return "60-85"
    if m2 <= 130: return "85-130"
    return "130초과"

def price_band(eok):
    if eok <= 6:  return "6억이하"
    if eok <= 9:  return "6-9"
    if eok <= 15: return "9-15"
    if eok <= 25: return "15-25"
    return "25초과"

def _row(metric, value, unit, sido, date, summary, title, source, url,
         category="price", confidence="공식", **extra):
    r = {"kind":"data","title":title,"source":source,"url":url,"date":date,
         "summary":summary,"category":category,"metric":metric,"value":value,
         "unit":unit,"sido":sido,"confidence":confidence}
    r.update({k:v for k, v in extra.items() if v is not None})
    return r

# ──────────────────────────── RTMS ────────────────────────────
RTMS_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
TAG = {
    "amt":("거래금액","dealAmount"), "m2":("전용면적","excluUseAr"),
    "y":("년","dealYear"), "mo":("월","dealMonth"), "d":("일","dealDay"),
    "apt":("아파트","aptNm"), "dong":("법정동","umdNm"), "jibun":("지번","jibun"),
    "floor":("층","floor"), "built":("건축년도","buildYear"),
}

def _auth_error(root):
    msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg")
    code = root.findtext(".//returnReasonCode")
    if msg or (code and code not in ("00", "000")):
        return f"{code or ''} {msg or ''}".strip()
    return None

def rtms_fetch(lawd_cd, ymd, key):
    rows, page = [], 1
    while True:
        q = urlencode({"serviceKey": key, "LAWD_CD": lawd_cd, "DEAL_YMD": ymd,
                       "pageNo": page, "numOfRows": 1000})
        try:
            raw = _http(f"{RTMS_URL}?{q}").decode("utf-8")
        except Exception as e:
            print(f"  ! {lawd_cd}/{ymd} p{page} 요청실패: {e}", file=sys.stderr); break
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"  ! {lawd_cd}/{ymd} XML파싱 실패: {e} (앞부분: {raw[:120]!r})", file=sys.stderr); break
        ae = _auth_error(root)
        if ae:
            print(f"  ✗ API 인증/쿼터 오류: {ae}  → 인증키·활용신청·일일호출한도 확인", file=sys.stderr); break
        rc = root.findtext(".//resultCode")
        if rc not in (None, "00", "000"):
            print(f"  ! API오류 resultCode={rc} msg={root.findtext('.//resultMsg')}", file=sys.stderr); break
        items = root.findall(".//item")
        if not items: break
        for it in items:
            amt_s = _get(it, *TAG["amt"]).replace(",", "")
            m2_s  = _get(it, *TAG["m2"])
            try:
                amt = float(amt_s); m2 = float(m2_s)
            except ValueError:
                continue
            y  = _get(it, *TAG["y"]); mo = _get(it, *TAG["mo"]); d = _get(it, *TAG["d"])
            built = _get(it, *TAG["built"])
            rows.append({
                "amt_manwon": amt, "eok": round(amt/10000, 4), "m2": m2,
                "ppyeong": round(amt / (m2/PYEONG)),
                "apt": _get(it, *TAG["apt"]), "dong": _get(it, *TAG["dong"]),
                "jibun": _get(it, *TAG["jibun"]), "floor": _get(it, *TAG["floor"]),
                "built": int(built) if built.isdigit() else None,
                "date": f"{y}-{int(mo or 0):02d}-{int(d or 0):02d}",
            })
        if len(items) < 1000: break
        page += 1; time.sleep(0.12)
    return rows

def _emit_band_rows(rows, recs, label, sido, day, **idtag):
    pp = [r["ppyeong"] for r in recs]
    rows.append(_row("평당가", round(st.median(pp)), "만원", sido, day,
        f"{label} 아파트 평당가 중앙값 {round(st.median(pp)):,}만원/평 (RTMS 실거래 {len(recs)}건, 계약일 기준)",
        title=f"{label} 아파트 평당가 {round(st.median(pp)):,}만원/평 ({day[:7]}·RTMS)",
        source="국토교통부 RTMS 아파트 실거래가", url=RTMS_URL,
        pyeong_price=round(st.median(pp)), **idtag))
    for b in ["40이하","40-60","60-85","85-130","130초과"]:
        sub = [r["eok"] for r in recs if area_band(r["m2"]) == b]
        if len(sub) >= 3:
            rows.append(_row("평형별 실거래가", round(st.median(sub), 2), "억", sido, day,
                f"{label} 전용 {b} 실거래가 중앙값 {round(st.median(sub),2)}억 ({len(sub)}건, RTMS 계약일)",
                title=f"{label} {b} 실거래가 중앙값 {round(st.median(sub),2)}억 ({day[:7]})",
                source="국토교통부 RTMS 아파트 실거래가", url=RTMS_URL, area_band=b, **idtag))
    for b in ["6억이하","6-9","9-15","15-25","25초과"]:
        cnt = sum(1 for r in recs if price_band(r["eok"]) == b)
        if cnt:
            rows.append(_row("아파트 매매 거래량", cnt, "건", sido, day,
                f"{label} {b} 실거래 {cnt}건 (RTMS 계약일, 가격대 분포)",
                title=f"{label} {b} 실거래 {cnt}건 ({day[:7]})",
                source="국토교통부 RTMS 아파트 실거래가", url=RTMS_URL, price_band=b, **idtag))

def rtms_to_apthub(months, key, complex_path=None, per_gu=False):
    out, catalog = [], {}
    for m in months:
        day = last_day(m)
        sido_recs = {}
        for nm, cd in LAWD.items():
            sido = sido_of(nm)
            recs = rtms_fetch(cd, m, key)
            if not recs:
                continue
            print(f"  · {nm} {m}: {len(recs)}건", file=sys.stderr)
            sido_recs.setdefault(sido, []).extend(recs)
            if per_gu:
                _emit_band_rows(out, recs, nm, sido, day, region=nm)
            for r in recs:
                k = (cd, r["apt"], r["m2"])
                catalog.setdefault(k, {
                    "complex": r["apt"], "sido": sido, "gu": nm.split(" ", 1)[-1],
                    "dong": r["dong"], "lawd_cd": cd, "size_m2": r["m2"],
                    "built_year": r["built"], "households": None,
                    "deal": [], "source_urls": [RTMS_URL],
                })["deal"].append({"size_m2": r["m2"], "price_eok": r["eok"],
                                   "floor": r["floor"], "date": r["date"], "type": "매매"})
        for sido, recs in sido_recs.items():
            _emit_band_rows(out, recs, sido, sido, day)
    if complex_path:
        with open(complex_path, "w", encoding="utf-8") as f:
            json.dump(list(catalog.values()), f, ensure_ascii=False, indent=2)
        print(f"[complex] {len(catalog)}개 단지·전용㎡ → {complex_path}", file=sys.stderr)
    return out

# ──────────────────────── ECOS (거시) ────────────────────────
def ecos_collect(specs, key):
    rows = []
    if not specs:
        return rows
    if "여기에" in key:
        print("  ! ECOS_KEY 미설정 — ECOS 스킵", file=sys.stderr); return rows
    for s in specs:
        cyc = s.get("cycle", "M")
        start = s.get("start", "202401"); end = s.get("end", "203012")
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/2000/"
               f"{s['stat']}/{cyc}/{start}/{end}/{s.get('item','')}")
        try:
            js = json.loads(_http(url).decode("utf-8"))
        except Exception as e:
            print(f"  ! ECOS {s['name']} 요청실패: {e}", file=sys.stderr); continue
        if "RESULT" in js:
            print(f"  ✗ ECOS {s['name']} 오류: {js['RESULT']}", file=sys.stderr); continue
        for it in js.get("StatisticSearch", {}).get("row", []):
            t = it.get("TIME", ""); v = it.get("DATA_VALUE", "")
            try:
                val = float(v)
            except ValueError:
                continue
            date = last_day(t) if len(t) == 6 else (f"{t[:4]}-{t[4:6]}-{t[6:8]}" if len(t) == 8 else t)
            rows.append(_row(s["metric"], val, s["unit"], "전국", date,
                f"{s['name']} {val}{s['unit']} ({date}, 한국은행 ECOS)",
                title=f"{s['name']} {val}{s['unit']} ({date[:7]}·ECOS)",
                source="한국은행 ECOS", url="https://ecos.bok.or.kr/api/", category="macro"))
    return rows

# ──────────────────────── KOSIS (보조) ────────────────────────
def kosis_collect(specs, key):
    rows = []
    if not specs:
        return rows
    if "여기에" in key:
        print("  ! KOSIS_KEY 미설정 — KOSIS 스킵", file=sys.stderr); return rows
    base = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    for s in specs:
        q = urlencode({"method":"getList","apiKey":key,"orgId":s["org"],"tblId":s["tbl"],
                       "prdSe":s.get("prdSe","M"),"startPrdDe":s.get("start","202401"),
                       "endPrdDe":s.get("end","203012"),"objL1":s.get("objL1",""),
                       "itmId":s.get("itm",""),"format":"json","jsonVD":"Y"})
        try:
            js = json.loads(_http(f"{base}?{q}").decode("utf-8"))
        except Exception as e:
            print(f"  ! KOSIS {s['name']} 요청실패: {e}", file=sys.stderr); continue
        if isinstance(js, dict) and js.get("err"):
            print(f"  ✗ KOSIS {s['name']} 오류: {js.get('errMsg', js['err'])}", file=sys.stderr); continue
        for it in (js if isinstance(js, list) else []):
            t = it.get("PRD_DE", ""); v = it.get("DT", "")
            try:
                val = float(v)
            except (ValueError, TypeError):
                continue
            date = last_day(t) if len(t) == 6 else t
            extra = {k: s[k] for k in ("area_band", "price_band") if s.get(k)}
            rows.append(_row(s["metric"], val, s["unit"], s.get("sido","전국"), date,
                f"{s['name']} {val}{s['unit']} ({date}, KOSIS {s['org']}/{s['tbl']})",
                title=f"{s['name']} {val}{s['unit']} ({date[:7]}·KOSIS)",
                source=f"KOSIS {s['org']}/{s['tbl']}",
                url="https://kosis.kr/openapi/", category=s.get("category","price"), **extra))
    return rows


# ── KOSIS 아파트 재고(분모) — 시도별 아파트 호수/세대 집계 ──
# 통계표 코드는 표별로 달라 env로 조정 가능(첫 실행 로그의 원레코드로 확정).
# 기본값: 통계청 인구주택총조사 '주택의 종류별 주택'(연간). itm=호수, 지역=C1/C2.
KOSIS_APT = {
    "org": os.environ.get("KOSIS_APT_ORG", "101"),
    "tbl": os.environ.get("KOSIS_APT_TBL", "DT_1JU1501"),
    "itm": os.environ.get("KOSIS_APT_ITM", "T20"),      # 호수
    "objL1": os.environ.get("KOSIS_APT_OBJL1", ""),     # 지역(비우면 전체 후 필터)
    "objL2": os.environ.get("KOSIS_APT_OBJL2", ""),     # 주택종류(아파트) — 표에 따라
    "prdSe": os.environ.get("KOSIS_APT_PRDSE", "Y"),
}
_KOSIS_SIDO = {"서울": "서울", "인천": "인천", "경기": "경기"}


def apt_stock_kosis(key, asof=None):
    """KOSIS 통계표에서 수도권 시도별 아파트 호수(≈세대수, 분모) 집계.
    표 코드가 다르면 첫 실행 로그의 '원레코드'를 보고 KOSIS_APT_* env로 교정."""
    if "여기에" in key or not key:
        print("✗ KOSIS_KEY 미설정: kosis.kr/openapi 인증키를 KOSIS_KEY로", file=sys.stderr)
        return [], {}
    if not asof:
        from datetime import date
        asof = date.today().isoformat()
    base = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    params = {"method": "getList", "apiKey": key, "orgId": KOSIS_APT["org"],
              "tblId": KOSIS_APT["tbl"], "itmId": KOSIS_APT["itm"],
              "prdSe": KOSIS_APT["prdSe"], "startPrdDe": "2020", "endPrdDe": "2030",
              "format": "json", "jsonVD": "Y"}
    if KOSIS_APT["objL1"]:
        params["objL1"] = KOSIS_APT["objL1"]
    if KOSIS_APT["objL2"]:
        params["objL2"] = KOSIS_APT["objL2"]
    try:
        js = json.loads(_http(f"{base}?{urlencode(params)}").decode("utf-8", "replace"))
    except Exception as e:
        print(f"  ! KOSIS 아파트재고 요청/파싱 실패: {e}", file=sys.stderr); return [], {}
    if isinstance(js, dict) and js.get("err"):
        print(f"  ✗ KOSIS 오류: {js.get('errMsg', js.get('err'))} — KOSIS_APT_* 코드 확인", file=sys.stderr)
        return [], {}
    items = js if isinstance(js, list) else []
    if not items:
        print(f"  ! KOSIS 응답 0건 — 표/코드 확인. 응답: {str(js)[:200]!r}", file=sys.stderr)
        return [], {}
    print(f"  · KOSIS 첫 레코드: {json.dumps(items[0], ensure_ascii=False)[:300]}", file=sys.stderr)
    def _names(it):
        return " ".join(str(it.get(k, "")) for k in ("C1_NM", "C2_NM", "C3_NM", "ITM_NM"))
    # 주택종류 차원이 있으면(어느 레코드든 '아파트' 언급) 아파트 레코드만 채택.
    # 아파트-전용 표면 언급이 없어 전부 채택. → 단독/연립/다세대·합계 오채택 방지.
    has_type = any("아파트" in _names(it) for it in items)
    by_sido, latest = {}, {}
    for it in items:
        names = _names(it)
        if has_type and "아파트" not in names:
            continue
        sido = next((v for k, v in _KOSIS_SIDO.items() if k in names), "")
        if not sido:
            continue
        try:
            val = float(it.get("DT", ""))
        except (ValueError, TypeError):
            continue
        prd = it.get("PRD_DE", "")
        if prd >= latest.get(sido, ""):        # 최신 기간 값 채택
            latest[sido] = prd; by_sido[sido] = val
    rows = []
    for sido, val in by_sido.items():
        rows.append(_row("아파트 세대수", int(val), "세대", sido, asof,
            f"{sido} 아파트 {int(val):,}호(≈세대, KOSIS {KOSIS_APT['org']}/{KOSIS_APT['tbl']}). 공공임대 비율의 분모",
            title=f"{sido} 아파트 {int(val):,}호 ({latest.get(sido,'')[:4]}·KOSIS)",
            source=f"KOSIS {KOSIS_APT['org']}/{KOSIS_APT['tbl']}",
            url="https://kosis.kr/openapi/", confidence="공식", category="stock"))
    print(f"[kosis] 분모 {len(rows)}건(시도) — { {k:int(v) for k,v in by_sido.items()} }", file=sys.stderr)
    return rows, {}


# ──────────────────────────── main ────────────────────────────
# ──────────────────────────── LH 임대주택단지 ────────────────────────────
LH_URL = "https://apis.data.go.kr/B552555/lhLeaseInfo1/lhLeaseInfo1"
# 실검증된 응답 스키마(dsList 레코드): SUM_HSH_CNT 총세대수 / HSH_CNT 세대수 / ARA_NM 지역명 /
# AIS_TP_CD_NM 공급유형명 / SBD_LGO_NM 단지명 / MVIN_XPC_YM 최초입주년월 / DDO_AR 전용면적 /
# RFE 월임대료 / LS_GMY 임대보증금 / ALL_CNT 전체건수. 요청변수: PG_SZ, PAGE, CNP_CD(시도2자리).
# 봉투는 [{dsSch:[...]},{dsList:[...],resHeader:[{SS_CODE:"Y"}]}]. 후보키 다중매칭으로 스키마 변동에도 견고.
LHF = {
    "region": ("ARA_NM", "지역명", "CNP_CD_NM", "지역", "LCTN_ARA_NM"),
    "rtype":  ("AIS_TP_CD_NM", "공급유형명", "공급유형", "임대유형", "SPL_TP_CD_NM"),
    "name":   ("SBD_LGO_NM", "단지명", "BSNS_NM", "LGO_NM"),
    "hh":     ("SUM_HSH_CNT", "총세대수", "HSH_CNT", "세대수", "SUM_HSHLDCO"),
    "moved":  ("MVIN_XPC_YM", "최초입주년월", "입주년월", "MVIN_YM"),
    "area":   ("DDO_AR", "전용면적"),
}
# LH lhLeaseInfo1 은 CNP_CD(시도 2자리) 필터가 사실상 필수 — 미지정 시 dsList 빈 배열.
LH_CNP = (("11", "서울"), ("28", "인천"), ("41", "경기"))
_SIDO_KEY = {"서울": "서울", "경기": "경기", "인천": "인천"}


def _pick(d, keys):
    for k in keys:
        if k in d and str(d[k]).strip() not in ("", "None"):
            return str(d[k]).strip()
    # 대소문자·공백 무시 재시도
    low = {str(k).lower().replace(" ", ""): v for k, v in d.items()}
    for k in keys:
        kk = k.lower().replace(" ", "")
        if kk in low and str(low[kk]).strip() not in ("", "None"):
            return str(low[kk]).strip()
    return ""


def _find_records(obj):
    """LH 봉투(숫자키/head+row 등)에서 실제 레코드(dict) 리스트를 재귀로 찾는다."""
    best = []
    def walk(x):
        nonlocal best
        if isinstance(x, list):
            dicts = [e for e in x if isinstance(e, dict)]
            # 레코드다움: 단지명/세대수류 키가 있는 dict 리스트
            if dicts and any(_pick(e, LHF["name"]) or _pick(e, LHF["hh"]) for e in dicts[:3]):
                if len(dicts) > len(best):
                    best = dicts
            for e in x:
                walk(e)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
    walk(obj)
    return best


def _gu_of(addr, sido):
    if not addr:
        return ""
    import re as _re
    if sido == "경기":
        m = _re.search(r"([가-힣]{2,}시)", addr)
        return m.group(1) if m else ""
    m = _re.search(r"([가-힣]{1,}구)", addr)
    return m.group(1) if m else ""


def lh_lease_collect(key, asof=None, complex_out=None):
    """LH 임대주택단지 조회 → 수도권 시군구별 공공임대 세대수·단지수(집계 지표)
    + 단지 카탈로그(아파트 정보 탭, tenure=임대). 오래된 주공은 built_year<=2000."""
    if "여기에" in key:
        print("✗ LH_KEY 미설정: data.go.kr #15059475 활용신청 후 인증키를 LH_KEY 환경변수로", file=sys.stderr)
        return [], []
    if not asof:
        from datetime import date
        asof = date.today().isoformat()  # 라이브 스냅샷 = 수집일(미래 월말 금지 → '예정' 오배지 방지)

    complexes, seen_schema, seen_key = [], False, set()
    for cnp, sido in LH_CNP:
        page = 1
        while page <= 40:
            q = urlencode({"serviceKey": key, "PG_SZ": 100, "PAGE": page, "CNP_CD": cnp})
            try:
                raw = _http(f"{LH_URL}?{q}").decode("utf-8", "replace")
            except Exception as e:
                print(f"  ! LH {sido} p{page} 요청실패: {e}", file=sys.stderr); break
            try:
                obj = json.loads(raw)
            except Exception:
                try:  # XML 폴백
                    obj = _xml_to_obj(ET.fromstring(raw))
                except Exception as e:
                    print(f"  ! LH {sido} p{page} 파싱실패: {e} (앞부분 {raw[:140]!r})", file=sys.stderr); break
            recs = _find_records(obj)
            if not recs:
                if page == 1:
                    print(f"  ! LH {sido}(CNP_CD={cnp}) 레코드 없음 — 응답: {raw[:200]!r}", file=sys.stderr)
                break
            if not seen_schema:
                print(f"  · LH 첫 레코드 키: {sorted(recs[0].keys())}", file=sys.stderr); seen_schema = True
            for r in recs:
                # 한 단지가 전용면적(타입)별로 여러 행 → (시도·단지명·지역명)으로 유일화, 총세대수는 단지당 1회
                name = _pick(r, LHF["name"]) or "(단지명미상)"
                region = _pick(r, LHF["region"])
                dkey = (sido, name, region)
                if dkey in seen_key:
                    continue
                seen_key.add(dkey)
                hh_s = _pick(r, LHF["hh"]).replace(",", "")
                try: hh = int(float(hh_s))
                except ValueError: hh = None
                moved = _pick(r, LHF["moved"])
                byear = None
                mm = re.search(r"(19|20)\d{2}", moved or "")
                if mm: byear = int(mm.group(0))
                complexes.append({
                    "complex": name, "sido": sido, "gu": _gu_of(region, sido),
                    "households": hh, "built_year": byear,
                    "tenure": "임대", "rental_type": _pick(r, LHF["rtype"]) or "공공임대",
                    "dev": ("LH 공공임대" + (" · 노후 주공" if byear and byear <= 2000 else "")),
                    "source_urls": [LH_URL],
                })
            if len(recs) < 100:
                break
            page += 1; time.sleep(0.12)

    # 집계 지표(시군구/시도별 공공임대 세대수·단지수)
    rows, by = [], {}
    for c in complexes:
        b = by.setdefault(c["sido"], {"hh": 0, "n": 0, "old": 0})
        b["n"] += 1; b["hh"] += (c["households"] or 0)
        if c["built_year"] and c["built_year"] <= 2000: b["old"] += 1
    for sido, b in by.items():
        rows.append(_row("공공임대 세대수", b["hh"], "세대", sido, asof,
            f"{sido} LH 임대주택단지 조회 노출 {b['n']}개 단지·{b['hh']:,}세대(노후주공 {b['old']}단지). "
            f"본 API는 현재 공고·모집 노출 단지 기준(전체 재고 아님)",
            title=f"{sido} LH 노출임대 {b['hh']:,}세대·{b['n']}단지 ({asof[:7]})",
            source="한국토지주택공사 임대주택단지 조회", url=LH_URL, confidence="공식", category="policy"))
        rows.append(_row("공공임대 단지수", b["n"], "단지", sido, asof,
            f"{sido} LH 노출 임대단지 {b['n']}개(노후주공 {b['old']}). 임대유형·준공·전용면적 포함 카탈로그 동시 생성. "
            f"현재 공고·모집 기준이라 영구·국민임대 등 비노출분은 제외",
            title=f"{sido} LH 노출임대 {b['n']}단지 ({asof[:7]})",
            source="한국토지주택공사 임대주택단지 조회", url=LH_URL, confidence="공식", category="policy"))
    if complex_out and complexes:
        with open(complex_out, "w", encoding="utf-8") as f:
            json.dump(complexes, f, ensure_ascii=False, indent=2)
        print(f"[lh] 단지 카탈로그 {len(complexes)}건 → {complex_out}")
    print(f"[lh] 집계 {len(rows)}건 · 단지 {len(complexes)}건 (수도권)", file=sys.stderr)
    return rows, complexes


def _xml_to_obj(el):
    """ElementTree → dict/list (JSON 폴백용, 태그를 키로)."""
    children = list(el)
    if not children:
        return el.text or ""
    out = {}
    for c in children:
        v = _xml_to_obj(c)
        if c.tag in out:
            if not isinstance(out[c.tag], list): out[c.tag] = [out[c.tag]]
            out[c.tag].append(v)
        else:
            out[c.tag] = v
    return out


# ──────────────────────── K-apt 아파트 재고(분모) ────────────────────────
# 전국공동주택표준데이터(#15096285) odcloud API — 전 아파트 단지 세대수 전수.
# 시군구별 세대수를 합산해 '아파트 세대수' 지표(분모) 생성 → 공공임대 비율의 분모.
# 이 데이터가 호갱노노·네이버 아파트 세대수의 실제 원천(K-apt)이며 전수·무료·약관 문제 없음.
KAPT_STD_BASE = "https://api.odcloud.kr/api/15096285/v1"
KAPTF = {
    "sido":   ("시도", "시도명", "sidoNm", "CTPRVN_NM", "광역시도"),
    "sigungu":("시군구", "시군구명", "sigunguNm", "SIGNGU_NM"),
    "hh":     ("세대수", "세대수합계", "hshldCnt", "kaptdaCnt", "HSHLD_CO", "총세대수"),
    "name":   ("단지명", "kaptName", "공동주택명"),
    "approve":("사용승인일", "useAprDay", "사용검사일", "준공일자"),
}
# odcloud 표준데이터는 시도가 '서울특별시/경기도/인천광역시' 전체표기 → 별칭 정규화 재사용
_STD_SIDO = {"서울특별시": "서울", "서울시": "서울", "서울": "서울",
             "인천광역시": "인천", "인천시": "인천", "인천": "인천",
             "경기도": "경기", "경기": "경기"}


def apt_stock_collect(key, uddi="", asof=None):
    """전국공동주택표준데이터(#15096285)에서 수도권 시군구별 아파트 세대수(분모) 집계.
    odcloud: {base}/uddi:{uddi}?page&perPage&serviceKey&returnType=JSON.
    반환: 시도별 '아파트 세대수' 지표 rows + 시군구별 세대수 dict(비율 세분화용)."""
    if "여기에" in key:
        print("✗ KAPT_KEY 미설정: data.go.kr #15096285 활용신청 후 인증키를 KAPT_KEY로", file=sys.stderr)
        return [], {}
    if not uddi:
        print("✗ KAPT_STD_UDDI 미설정: 포털 #15096285 '요청 URL'의 uddi 값을 KAPT_STD_UDDI로", file=sys.stderr)
        return [], {}
    if not asof:
        from datetime import date
        asof = date.today().isoformat()
    url0 = f"{KAPT_STD_BASE}/uddi:{uddi}"
    by_gu, seen_schema, page, per = {}, False, 1, 1000
    total = None
    while page <= 60:
        q = urlencode({"serviceKey": key, "page": page, "perPage": per, "returnType": "JSON"})
        try:
            obj = json.loads(_http(f"{url0}?{q}").decode("utf-8", "replace"))
        except Exception as e:
            print(f"  ! KAPT p{page} 요청/파싱 실패: {e}", file=sys.stderr); break
        recs = obj.get("data") if isinstance(obj, dict) else None
        if not isinstance(recs, list) or not recs:
            if page == 1:
                print(f"  ! KAPT 레코드 없음 — 응답 앞부분: {str(obj)[:200]!r}", file=sys.stderr)
            break
        if not seen_schema:
            print(f"  · KAPT 첫 레코드 키: {sorted(recs[0].keys())}", file=sys.stderr); seen_schema = True
        if total is None:
            total = obj.get("totalCount") or obj.get("matchCount")
        for r in recs:
            sido = _STD_SIDO.get(_pick(r, KAPTF["sido"]), "")
            if not sido:
                continue  # 수도권만
            hh_s = _pick(r, KAPTF["hh"]).replace(",", "")
            try: hh = int(float(hh_s))
            except ValueError: continue
            gu = _pick(r, KAPTF["sigungu"])
            b = by_gu.setdefault((sido, gu), {"hh": 0, "n": 0})
            b["hh"] += hh; b["n"] += 1
        got = page * per
        if total and got >= total:
            break
        if len(recs) < per:
            break
        page += 1; time.sleep(0.1)

    # 시도별 합산 → 분모 지표
    rows, by_sido = [], {}
    for (sido, gu), b in by_gu.items():
        s = by_sido.setdefault(sido, {"hh": 0, "n": 0})
        s["hh"] += b["hh"]; s["n"] += b["n"]
    for sido, s in by_sido.items():
        rows.append(_row("아파트 세대수", s["hh"], "세대", sido, asof,
            f"{sido} 공동주택(아파트) {s['n']:,}개 단지·{s['hh']:,}세대(K-apt 전수). 공공임대 비율의 분모",
            title=f"{sido} 아파트 {s['hh']:,}세대·{s['n']:,}단지 ({asof[:7]}·K-apt)",
            source="국토교통부 전국공동주택표준데이터(K-apt)", url="https://www.data.go.kr/data/15096285/standard.do",
            confidence="공식", category="stock"))
    print(f"[kapt] 분모 {len(rows)}건(시도) · 시군구 {len(by_gu)}개 (수도권)", file=sys.stderr)
    return rows, {f"{k[0]}|{k[1]}": v["hh"] for k, v in by_gu.items()}


# ── 대안 분모 경로: 국토부 공동주택 목록(#15057332)+기본정보(#15058453) API ──
# 사용자가 등록한 AptBasisInfoServiceV4를 그대로 사용. 목록 API로 수도권 단지코드를
# 열거(getSidoAptList3)한 뒤 단지마다 세대수(kaptdaCnt)를 조회해 시군구별 합산.
# 세대수는 목록에 없고 기본정보에만 있어 단지당 1콜 필요(수도권 수천 콜, 일 쿼터 1만 내).
KAPT_LIST_URL = os.environ.get("KAPT_LIST_URL", "https://apis.data.go.kr/1613000/AptListService3/getSidoAptList3")
KAPT_BASIS_URL = os.environ.get("KAPT_BASIS_URL", "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusBassInfoV4")
KAPT_SIDO = (("11", "서울"), ("28", "인천"), ("41", "경기"))
KAPT_MAX_BASIS = int(os.environ.get("KAPT_MAX_BASIS", "12000"))  # 안전 상한(쿼터 보호)


def _kapt_items(obj):
    """공동주택 API 응답에서 item 리스트 추출. JSON은 response>body>items>item,
    XML 폴백(_xml_to_obj)은 response 래퍼가 없을 수 있어 body를 직접도 탐색."""
    if not isinstance(obj, dict):
        return []
    resp = obj.get("response")
    root = resp if isinstance(resp, dict) else obj      # JSON: response 래퍼 / XML폴백: 없음
    body = root.get("body") if isinstance(root, dict) else None
    items = (body.get("items") if isinstance(body, dict) else None)
    if items is None and isinstance(root, dict):
        items = root.get("items")
    if isinstance(items, dict):
        items = items.get("item")
    if isinstance(items, dict):
        return [items]
    return items if isinstance(items, list) else []


def _kapt_fetch(url, params, timeout=25, retries=None):
    q = urlencode(dict(params, serviceKey=params.get("serviceKey", ""), _type="json"))
    try:
        raw = _http(f"{url}?{q}", timeout=timeout, retries=retries).decode("utf-8", "replace")
    except Exception:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        try:
            return _xml_to_obj(ET.fromstring(raw))
        except Exception:
            return {}


def apt_stock_kapt_api(key, asof=None):
    """국토부 공동주택 목록+기본정보 API로 수도권 시군구별 아파트 세대수(분모) 집계.
    반환: 시도별 '아파트 세대수' rows + 시군구별 세대수 dict."""
    if "여기에" in key:
        print("✗ KAPT_KEY 미설정: data.go.kr #15058453/#15057332 활용신청 후 인증키를 KAPT_KEY로", file=sys.stderr)
        return [], {}
    if not asof:
        from datetime import date
        asof = date.today().isoformat()

    # 1) 수도권 단지코드 열거(목록 API)
    codes = []   # (kaptCode, sido, sigungu)
    for sido_cd, sido in KAPT_SIDO:
        page = 1
        while page <= 200:
            obj = _kapt_fetch(KAPT_LIST_URL, {"serviceKey": key, "sidoCode": sido_cd,
                                              "pageNo": page, "numOfRows": 1000})
            items = _kapt_items(obj)
            if not items:
                if page == 1:
                    print(f"  ! KAPT 목록 {sido}({sido_cd}) 0건 — 응답 {str(obj)[:160]!r}", file=sys.stderr)
                break
            for it in items:
                kc = _pick(it, ("kaptCode", "KAPT_CODE", "단지코드"))
                if kc:
                    codes.append((kc, sido, _pick(it, ("as2", "sigungu", "시군구", "as3"))))
            if len(items) < 1000:
                break
            page += 1; time.sleep(0.03)
    if not codes:
        print("  ! KAPT 단지코드 0건 — 목록 API(#15057332) 활용신청·엔드포인트 확인", file=sys.stderr)
        return [], {}
    print(f"  · KAPT 수도권 단지코드 {len(codes):,}개 열거", file=sys.stderr)
    if os.environ.get("KAPT_PROBE"):   # 진단: 기본정보 원응답 5건 덤프 후 종료
        for kc, sido, gu in codes[:5]:
            q = urlencode({"serviceKey": key, "kaptCode": kc, "_type": "json"})
            try:
                raw = _http(f"{KAPT_BASIS_URL}?{q}", timeout=15, retries=1).decode("utf-8", "replace")
            except Exception as e:
                raw = f"EXC {e}"
            print(f"  · PROBE {kc}: {raw[:400]!r}", file=sys.stderr)
        return [], {}
    if len(codes) > KAPT_MAX_BASIS:
        print(f"  · 상한 {KAPT_MAX_BASIS:,} 적용(쿼터 보호) — 초과분 {len(codes)-KAPT_MAX_BASIS:,}개 미조회", file=sys.stderr)
        codes = codes[:KAPT_MAX_BASIS]

    # 프리플라이트: 기본정보 3건을 순차 시험. 전부 실패(429/쿼터)면 전체 수집을 조기 중단
    #    — 수도권 아파트(약 1만 단지) > 기본정보 일 쿼터 1만이라 429가 상시 발생 가능.
    #    doomed한 수만 콜(35분+)을 낭비하지 않도록 방어. (해결: 벌크 #15096285 사용)
    ok = 0
    for kc, _, _ in codes[:3]:
        if _kapt_items(_kapt_fetch(KAPT_BASIS_URL, {"serviceKey": key, "kaptCode": kc}, timeout=12, retries=1)):
            ok += 1
        time.sleep(0.4)
    if ok == 0:
        print("  ! KAPT 기본정보 프리플라이트 전건 실패(429/쿼터 추정) — 수집 중단.\n"
              "    수도권 단지수(~1.0만) > 기본정보 일 쿼터(1만). 벌크 표준데이터(#15096285,"
              " KAPT_STD_UDDI)로 전환 권장.", file=sys.stderr)
        return [], {}

    # 2) 단지별 세대수(기본정보 API) → 시군구 합산. 수천 콜이라 순차는 과도하게 느려
    #    (재시도 폭주로 시간 폭증) → 제한 동시성(스레드풀)+짧은 타임아웃+1회 재시도로 견고·신속.
    from concurrent.futures import ThreadPoolExecutor
    def _one(item):
        kc, sido, gu = item
        obj = _kapt_fetch(KAPT_BASIS_URL, {"serviceKey": key, "kaptCode": kc}, timeout=8, retries=2)
        items = _kapt_items(obj)
        if not items:
            return None
        r = items[0]
        hh_s = _pick(r, ("kaptdaCnt", "세대수", "hshldCnt")).replace(",", "")
        try: hh = int(float(hh_s))
        except ValueError: return None
        gu2 = gu or _gu_of(_pick(r, ("kaptAddr", "법정동주소", "doroJuso")), sido)
        return (sido, gu2, hh, sorted(r.keys()))

    by_gu, done, fail, schema = {}, 0, 0, None
    with ThreadPoolExecutor(max_workers=10) as ex:
        for res in ex.map(_one, codes):
            if res is None:
                fail += 1; continue
            sido, gu2, hh, keys = res
            if schema is None:
                schema = keys
                print(f"  · KAPT 기본정보 첫 레코드 키: {keys}", file=sys.stderr)
            b = by_gu.setdefault((sido, gu2), {"hh": 0, "n": 0})
            b["hh"] += hh; b["n"] += 1
            done += 1
            if done % 1000 == 0:
                print(f"  · KAPT 기본정보 {done:,}/{len(codes):,}", file=sys.stderr)
    if fail:
        print(f"  · KAPT 기본정보 조회실패/결측 {fail:,}건(집계 제외)", file=sys.stderr)

    rows, by_sido = [], {}
    for (sido, gu), b in by_gu.items():
        s = by_sido.setdefault(sido, {"hh": 0, "n": 0})
        s["hh"] += b["hh"]; s["n"] += b["n"]
    for sido, s in by_sido.items():
        rows.append(_row("아파트 세대수", s["hh"], "세대", sido, asof,
            f"{sido} 공동주택(아파트) {s['n']:,}개 단지·{s['hh']:,}세대(K-apt 기본정보 집계). 공공임대 비율의 분모",
            title=f"{sido} 아파트 {s['hh']:,}세대·{s['n']:,}단지 ({asof[:7]}·K-apt)",
            source="국토교통부 공동주택 기본정보(K-apt)", url="https://www.data.go.kr/data/15058453/openapi.do",
            confidence="공식", category="stock"))
    print(f"[kapt-api] 분모 {len(rows)}건(시도) · 조회 {done:,}단지 · 시군구 {len(by_gu)}개", file=sys.stderr)
    return rows, {f"{k[0]}|{k[1]}": v["hh"] for k, v in by_gu.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtms", action="store_true", help="RTMS 실거래 수집(주력)")
    ap.add_argument("--ecos", action="store_true", help="ECOS 거시(기준금리 등) 수집")
    ap.add_argument("--kosis", action="store_true", help="KOSIS 규모별/분양가 수집(CONFIG 필요)")
    ap.add_argument("--lh", action="store_true", help="LH 임대주택단지 조회(수도권 공공임대 현황·카탈로그)")
    ap.add_argument("--kapt", action="store_true", help="K-apt 전국공동주택표준데이터 벌크(#15096285, uddi 필요)")
    ap.add_argument("--kapt-api", dest="kapt_api", action="store_true",
                    help="K-apt 공동주택 목록+기본정보 API(#15057332+#15058453)로 아파트 세대수(분모)")
    ap.add_argument("--kosis-stock", dest="kosis_stock", action="store_true",
                    help="KOSIS 시도별 아파트 호수(≈세대수·비율 분모, 쿼터벽 없음)")
    ap.add_argument("--per-gu", action="store_true",
                    help="sido 집계 외에 구 단위 행도 생성(region 필드)")
    ap.add_argument("--months", nargs="+", default=["202605"], help="YYYYMM 복수 가능(시계열)")
    ap.add_argument("--out", default="data-out.json")
    ap.add_argument("--complex", dest="complex_path", default=None)
    ap.add_argument("--complex-out", dest="complex_out", default=None,
                    help="LH 단지 카탈로그 저장 경로(아파트 정보 탭용)")
    a = ap.parse_args()

    rows = []
    if a.rtms:
        if "여기에" in RTMS_KEY:
            sys.exit("✗ RTMS_KEY 미설정: data.go.kr #1613000 활용신청 후 Decoding 인증키 입력")
        rows += rtms_to_apthub(a.months, RTMS_KEY, a.complex_path, per_gu=a.per_gu)
    if a.ecos:
        rows += ecos_collect(ECOS_SPECS, ECOS_KEY)
    if a.kosis:
        rows += kosis_collect(KOSIS_SPECS, KOSIS_KEY)
    if a.lh:
        lh_rows, _ = lh_lease_collect(LH_KEY, complex_out=a.complex_out)
        rows += lh_rows
    if a.kapt:
        kapt_rows, _ = apt_stock_collect(KAPT_KEY, KAPT_STD_UDDI)
        rows += kapt_rows
    if a.kapt_api:
        kapt_rows, _ = apt_stock_kapt_api(KAPT_KEY)
        rows += kapt_rows
    if a.kosis_stock:
        ks_rows, _ = apt_stock_kosis(KOSIS_KEY)
        rows += ks_rows
    if not (a.rtms or a.ecos or a.kosis or a.lh or a.kapt or a.kapt_api or a.kosis_stock):
        sys.exit("✗ 수집 소스 미지정: --rtms / --ecos / --kosis / --lh / --kapt / --kapt-api / --kosis-stock 중 하나 이상")

    seen, uniq = set(), []
    for r in rows:
        k = (r["metric"], r["sido"], r.get("region",""),
             r.get("area_band",""), r.get("price_band",""), r["date"])
        if k in seen:
            continue
        seen.add(k); uniq.append(r)

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(uniq)}건 → {a.out}")

if __name__ == "__main__":
    main()
