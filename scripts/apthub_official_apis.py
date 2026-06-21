#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apthub_official_apis.py
수도권 부동산 정량 데이터 → apthub Signal JSON 적재 엔진 (약관 준수 공식 오픈API 전용)

채우는 영역
  C. 평당가 / 평형별 실거래가  ← RTMS (data.go.kr #1613000)  ★주력
  A. area_band (40↓/40-60/60-85/85-130/130↑)  ← RTMS 전용면적 버킷팅
  B. price_band (6↓/6-9/9-15/15-25/25↑)        ← RTMS 거래금액 버킷팅
  D. 서울 25구 월별 시계열                       ← RTMS LAWD_CD 25구 루프
  (보조) HUG 면적별 분양가 / 부동산원 규모별 지수 ← KOSIS  (statId만 채우면 동작)
  (보조) 기준금리/COFIX/가계대출 등 거시          ← ECOS

사용법
  1) 인증키 발급(무료, 즉시)
     - RTMS:  data.go.kr → '국토교통부_아파트 매매 실거래가 상세 자료'(#1613000) 활용신청 → 일반 인증키(Decoding)
     - KOSIS: kosis.kr/openapi → 사용자 등록 → API Key
     - ECOS:  ecos.bok.or.kr/api → 인증키
  2) 아래 CONFIG에 키 입력 → 실행
     python3 apthub_official_apis.py --rtms --months 202604 202605 --out data-out.json --complex complex-out.json
  3) 적재
     PYTHONPATH=src python3 -m apthub add --file data-out.json --by-date
     python3 scripts/build_site.py

주의: RTMS는 호가가 아닌 '실거래(계약일 기준)'다. 네이버 호가와 절대 섞지 말 것.
"""
import argparse, json, os, sys, time, statistics as st
from urllib.parse import urlencode
from urllib.request import urlopen, Request
import xml.etree.ElementTree as ET

# ──────────────────────────── CONFIG ────────────────────────────
RTMS_KEY  = os.environ.get("RTMS_KEY", "여기에_RTMS_DECODING_인증키")   # data.go.kr #1613000 (env 우선)
KOSIS_KEY = os.environ.get("KOSIS_KEY", "여기에_KOSIS_API_KEY")        # kosis.kr/openapi (env 우선)
ECOS_KEY  = os.environ.get("ECOS_KEY", "여기에_ECOS_인증키")           # ecos.bok.or.kr/api (env 우선)

PYEONG = 3.3058  # 1평 = 3.3058㎡

# 서울 25개 자치구 LAWD_CD(시군구 5자리) + 수도권 예시. 필요시 확장.
LAWD = {
    # 서울 25구
    "서울 종로구":"11110","서울 중구":"11140","서울 용산구":"11170","서울 성동구":"11200",
    "서울 광진구":"11215","서울 동대문구":"11230","서울 중랑구":"11260","서울 성북구":"11290",
    "서울 강북구":"11305","서울 도봉구":"11320","서울 노원구":"11350","서울 은평구":"11380",
    "서울 서대문구":"11410","서울 마포구":"11440","서울 양천구":"11470","서울 강서구":"11500",
    "서울 구로구":"11530","서울 금천구":"11545","서울 영등포구":"11560","서울 동작구":"11590",
    "서울 관악구":"11620","서울 서초구":"11650","서울 강남구":"11680","서울 송파구":"11710",
    "서울 강동구":"11740",
    # 수도권 예시(원하면 경기 31개 시군구·인천 군구 추가)
    "경기 성남분당":"41135","경기 수원영통":"41117","경기 화성":"41590","인천 연수구":"28185",
}
SIDO_OF = lambda nm: "서울" if nm.startswith("서울") else ("경기" if nm.startswith("경기") else ("인천" if nm.startswith("인천") else "전국"))

def area_band(m2: float) -> str:
    if m2 <= 40: return "40이하"
    if m2 <= 60: return "40-60"
    if m2 <= 85: return "60-85"
    if m2 <= 130: return "85-130"
    return "130초과"

def price_band(eok: float) -> str:
    if eok <= 6: return "6억이하"
    if eok <= 9: return "6-9"
    if eok <= 15: return "9-15"
    if eok <= 25: return "15-25"
    return "25초과"

# ──────────────────────────── RTMS ────────────────────────────
RTMS_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"

def rtms_fetch(lawd_cd: str, ymd: str, key: str):
    """한 시군구·한 달 실거래 전건(페이지네이션)."""
    rows, page = [], 1
    while True:
        q = urlencode({"serviceKey": key, "LAWD_CD": lawd_cd, "DEAL_YMD": ymd,
                       "pageNo": page, "numOfRows": 1000})
        req = Request(f"{RTMS_URL}?{q}", headers={"User-Agent": "apthub/1.0"})
        try:
            xml = urlopen(req, timeout=20).read().decode("utf-8")
        except Exception as e:
            print(f"  ! {lawd_cd}/{ymd} p{page} 요청실패: {e}", file=sys.stderr); break
        root = ET.fromstring(xml)
        head = root.findtext(".//resultCode")
        if head not in (None, "00", "000"):
            print(f"  ! API오류 resultCode={head} msg={root.findtext('.//resultMsg')}", file=sys.stderr); break
        items = root.findall(".//item")
        if not items: break
        for it in items:
            g = lambda t: (it.findtext(t) or "").strip()
            try:
                amt = float(g("거래금액").replace(",", ""))            # 만원
                m2  = float(g("전용면적"))
            except ValueError:
                continue
            rows.append({
                "amt_manwon": amt, "eok": round(amt/10000, 4), "m2": m2,
                "ppyeong": round(amt / (m2/PYEONG)),                  # 평당가(만원)
                "apt": g("아파트"), "dong": g("법정동"), "jibun": g("지번"),
                "floor": g("층"), "built": g("건축년도"),
                "date": f"{g('년')}-{int(g('월') or 0):02d}-{int(g('일') or 0):02d}",
            })
        if len(items) < 1000: break
        page += 1; time.sleep(0.12)
    return rows

def rtms_to_apthub(months, key, complex_path=None):
    out, catalog = [], {}
    last_day = {m: f"{m[:4]}-{m[4:6]}-{'30' if m[4:6] in ('04','06','09','11') else ('28' if m[4:6]=='02' else '31')}" for m in months}
    for nm, cd in LAWD.items():
        sido = SIDO_OF(nm)
        for m in months:
            recs = rtms_fetch(cd, m, key)
            if not recs:
                continue
            print(f"  · {nm} {m}: {len(recs)}건", file=sys.stderr)
            # (1) 구 단위 평당가 중앙값
            pp = [r["ppyeong"] for r in recs]
            out.append(_row("평당가", round(st.median(pp)), "만원", sido, last_day[m],
                f"{nm} 아파트 평당가 중앙값 {round(st.median(pp)):,}만원/평 (RTMS 실거래 {len(recs)}건, 계약일 기준)",
                title=f"{nm} 아파트 평당가 {round(st.median(pp)):,}만원/평 ({m[:4]}-{m[4:6]}·RTMS)",
                pyeong_price=round(st.median(pp))))
            # (2) area_band별 평형별 실거래가(억) 중앙값
            for b in ["40이하","40-60","60-85","85-130","130초과"]:
                sub = [r["eok"] for r in recs if area_band(r["m2"]) == b]
                if len(sub) >= 3:
                    out.append(_row("평형별 실거래가", round(st.median(sub),2), "억", sido, last_day[m],
                        f"{nm} 전용 {b} 실거래가 중앙값 {round(st.median(sub),2)}억 ({len(sub)}건, RTMS 계약일)",
                        title=f"{nm} {b} 실거래가 중앙값 {round(st.median(sub),2)}억 ({m[:4]}-{m[4:6]})",
                        area_band=b))
            # (3) price_band 분포(건수) — 가격대 쏠림 추적
            for b in ["6억이하","6-9","9-15","15-25","25초과"]:
                cnt = sum(1 for r in recs if price_band(r["eok"]) == b)
                if cnt:
                    out.append(_row("아파트 매매 거래량", cnt, "건", sido, last_day[m],
                        f"{nm} {b} 실거래 {cnt}건 (RTMS 계약일, 가격대 분포)",
                        title=f"{nm} {b} 실거래 {cnt}건 ({m[:4]}-{m[4:6]})",
                        price_band=b))
            # (4) 단지 카탈로그(complex-out.json)
            for r in recs:
                k = (cd, r["apt"], r["m2"])
                catalog.setdefault(k, {
                    "complex": r["apt"], "sido": sido, "gu": nm.split(" ",1)[-1],
                    "dong": r["dong"], "lawd_cd": cd, "size_m2": r["m2"],
                    "built_year": r["built"], "households": None,  # 세대수는 건축물대장(#15134735) 필요
                    "deal": [], "source_urls": [RTMS_URL],
                })["deal"].append({"size_m2": r["m2"], "price_eok": r["eok"],
                                    "floor": r["floor"], "date": r["date"], "type": "매매"})
    if complex_path:
        with open(complex_path, "w", encoding="utf-8") as f:
            json.dump(list(catalog.values()), f, ensure_ascii=False, indent=2)
        print(f"[complex] {len(catalog)}개 단지·전용㎡ → {complex_path}", file=sys.stderr)
    return out

def _row(metric, value, unit, sido, date, summary, title, **extra):
    r = {"kind":"data","title":title,"source":"국토교통부 RTMS 아파트 실거래가",
         "url":RTMS_URL,"date":date,"summary":summary,
         "category":"price","metric":metric,"value":value,"unit":unit,
         "sido":sido,"confidence":"공식"}
    r.update({k:v for k,v in extra.items() if v is not None})
    return r

# ──────────────────────── KOSIS (보조) ────────────────────────
# HUG 면적별 분양가 / 부동산원 규모별 지수는 KOSIS에 적재돼 있음.
# 통계표 orgId/tblId/항목코드는 kosis.kr에서 해당 표 '주소정보(URL)' 버튼으로 확인해 채운다.
def kosis_fetch(org_id, tbl_id, key, prd_se="M", start="202501", end="202612", obj_l1="", itm_id=""):
    base = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    q = urlencode({"method":"getList","apiKey":key,"orgId":org_id,"tblId":tbl_id,
                   "prdSe":prd_se,"startPrdDe":start,"endPrdDe":end,
                   "objL1":obj_l1,"itmId":itm_id,"format":"json","jsonVD":"Y"})
    req = Request(f"{base}?{q}", headers={"User-Agent":"apthub/1.0"})
    return json.loads(urlopen(req, timeout=20).read().decode("utf-8"))
# 예) HUG 분양가 통계표를 찾은 뒤:
#   js = kosis_fetch("390","DT_39003_...", KOSIS_KEY, obj_l1="<지역코드>", itm_id="<규모코드>")
#   → PRD_DE(YYYYMM)·DT(값)을 _row("분양가", float(DT), "만원", sido, ...,
#        area_band="60-85" 등)로 변환. HUG 규모(60/85/102)는 apthub 밴드와 60-85만 정합.

# ──────────────────────── ECOS (보조) ────────────────────────
def ecos_fetch(stat_code, key, cycle="M", start="202501", end="202612", item1=""):
    base = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/{stat_code}/{cycle}/{start}/{end}/{item1}"
    return json.loads(urlopen(Request(base, headers={"User-Agent":"apthub/1.0"}), timeout=20).read().decode("utf-8"))
# 예) 기준금리 722Y001, 예금은행 가중평균 주담대금리 121Y006 등. row[].TIME(YYYYMM)·DATA_VALUE 사용.

# ──────────────────────────── main ────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtms", action="store_true", help="RTMS 실거래 수집(주력)")
    ap.add_argument("--months", nargs="+", default=["202605"], help="YYYYMM 복수 가능(시계열)")
    ap.add_argument("--out", default="data-out.json")
    ap.add_argument("--complex", dest="complex_path", default=None)
    a = ap.parse_args()

    rows = []
    if a.rtms:
        if "여기에" in RTMS_KEY:
            sys.exit("✗ RTMS_KEY 미설정: data.go.kr #1613000 활용신청 후 CONFIG에 Decoding 인증키 입력")
        rows += rtms_to_apthub(a.months, RTMS_KEY, a.complex_path)

    # 동일 metric·sido·band·date 중복 제거(시계열 1건 규칙)
    seen, uniq = set(), []
    for r in rows:
        k = (r["metric"], r["sido"], r.get("area_band",""), r.get("price_band",""), r["date"], r["title"])
        if k in seen: continue
        seen.add(k); uniq.append(r)

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(uniq)}건 → {a.out}")
