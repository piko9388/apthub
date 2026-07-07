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
import argparse, calendar, json, os, ssl, sys, time
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

def _http(url):
    last = None
    for i in range(HTTP_RETRY):
        try:
            return urlopen(Request(url, headers=HEADERS), timeout=25, context=_SSL).read()
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

# ──────────────────────────── main ────────────────────────────
# ──────────────────────────── LH 임대주택단지 ────────────────────────────
LH_URL = "https://apis.data.go.kr/B552555/lhLeaseInfo1/lhLeaseInfo1"
# 응답 필드는 LH 봉투 구조라 후보키 다중매칭(태그무관). 첫 레코드 스키마는 자동 출력해 확정.
LHF = {
    "region": ("CNP_CD_NM", "지역명", "지역", "LCTN_ARA_NM", "RGN_NM", "brmpNm", "지역본부"),
    "rtype":  ("AIS_TP_CD_NM", "공급유형", "임대유형", "SPL_TP_CD_NM", "RNTL_KND_NM", "주택유형"),
    "name":   ("SBD_LGO_NM", "단지명", "BSNS_NM", "LGO_NM", "complexNm", "단지"),
    "hh":     ("SUM_HSHLDCO", "총세대수", "세대수", "HSHLDCO", "totHshldCo", "HSHLD_CNT", "TOT_HSHLD_CO"),
    "moved":  ("MVIN_XPC_YM", "최초입주년월", "입주년월", "준공일", "MVIN_YM", "완공일"),
    "addr":   ("LEG_ADRES", "주소", "단지주소", "도로명주소", "ADRES", "LEGADDR"),
}
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
    import calendar as _cal
    if "여기에" in key:
        print("✗ LH_KEY 미설정: data.go.kr #15059475 활용신청 후 인증키를 LH_KEY 환경변수로", file=sys.stderr)
        return [], []
    if not asof:
        from datetime import date
        asof = date.today().replace(day=1).isoformat()  # 스냅샷 기준(월초); 아래서 월말로
    y, m = int(asof[:4]), int(asof[5:7])
    asof = f"{y:04d}-{m:02d}-{_cal.monthrange(y, m)[1]:02d}"

    complexes, page, seen_schema = [], 1, False
    while page <= 60:
        q = urlencode({"serviceKey": key, "PG_": page, "PG_SIZE": 100})
        try:
            raw = _http(f"{LH_URL}?{q}").decode("utf-8", "replace")
        except Exception as e:
            print(f"  ! LH p{page} 요청실패: {e}", file=sys.stderr); break
        try:
            obj = json.loads(raw)
        except Exception:
            try:  # XML 폴백
                obj = _xml_to_obj(ET.fromstring(raw))
            except Exception as e:
                print(f"  ! LH p{page} 파싱실패: {e} (앞부분 {raw[:140]!r})", file=sys.stderr); break
        recs = _find_records(obj)
        if not recs:
            if page == 1:
                print(f"  ! LH 레코드 없음 — 응답 앞부분: {raw[:200]!r}", file=sys.stderr)
            break
        if not seen_schema:
            print(f"  · LH 첫 레코드 키: {sorted(recs[0].keys())}", file=sys.stderr); seen_schema = True
        for r in recs:
            region = _pick(r, LHF["region"]); addr = _pick(r, LHF["addr"])
            sido = next((v for k, v in _SIDO_KEY.items() if k in region or k in addr), "")
            if not sido:
                continue  # 수도권만
            hh_s = _pick(r, LHF["hh"]).replace(",", "")
            try: hh = int(float(hh_s))
            except ValueError: hh = None
            moved = _pick(r, LHF["moved"])
            byear = None
            mm = re.search(r"(19|20)\d{2}", moved or "")
            if mm: byear = int(mm.group(0))
            complexes.append({
                "complex": _pick(r, LHF["name"]) or "(단지명미상)",
                "sido": sido, "gu": _gu_of(addr, sido),
                "households": hh, "built_year": byear,
                "tenure": "임대", "rental_type": _pick(r, LHF["rtype"]),
                "dev": ("LH 공공임대" + (" · 노후 주공" if byear and byear <= 2000 else "")),
                "source_urls": [LH_URL],
            })
        if len(recs) < 100: break
        page += 1; time.sleep(0.12)

    # 집계 지표(시군구/시도별 공공임대 세대수·단지수)
    rows, by = [], {}
    for c in complexes:
        b = by.setdefault(c["sido"], {"hh": 0, "n": 0, "old": 0})
        b["n"] += 1; b["hh"] += (c["households"] or 0)
        if c["built_year"] and c["built_year"] <= 2000: b["old"] += 1
    for sido, b in by.items():
        rows.append(_row("공공임대 세대수", b["hh"], "세대", sido, asof,
            f"{sido} LH 공공임대 {b['n']}개 단지·{b['hh']:,}세대(노후주공 {b['old']}단지). LH 임대주택단지 조회 집계",
            title=f"{sido} 공공임대 {b['hh']:,}세대·{b['n']}단지 ({asof[:7]}·LH)",
            source="한국토지주택공사 임대주택단지 조회", url=LH_URL, confidence="공식", category="policy"))
        rows.append(_row("공공임대 단지수", b["n"], "단지", sido, asof,
            f"{sido} LH 공공임대 단지 {b['n']}개(노후주공 {b['old']}). 임대유형·준공 포함 카탈로그 동시 생성",
            title=f"{sido} 공공임대 {b['n']}단지 ({asof[:7]}·LH)",
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtms", action="store_true", help="RTMS 실거래 수집(주력)")
    ap.add_argument("--ecos", action="store_true", help="ECOS 거시(기준금리 등) 수집")
    ap.add_argument("--kosis", action="store_true", help="KOSIS 규모별/분양가 수집(CONFIG 필요)")
    ap.add_argument("--lh", action="store_true", help="LH 임대주택단지 조회(수도권 공공임대 현황·카탈로그)")
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
    if not (a.rtms or a.ecos or a.kosis or a.lh):
        sys.exit("✗ 수집 소스 미지정: --rtms / --ecos / --kosis / --lh 중 하나 이상")

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
