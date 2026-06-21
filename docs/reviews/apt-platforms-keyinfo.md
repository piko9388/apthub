# APT-SIGNAL — 아파트 플랫폼 리서치 & 단지 핵심 데이터 정의

> 대상: 수도권 아파트 단지 중심 대시보드(APT-SIGNAL)의 "아파트 정보" 탭
> 목적: 단지별로 **어떤 고가치 필드를 어떤 소스에서 끌어오고 매칭할지** 확정
> 작성일: 2026-06-21
> 원칙: **1차 출처(공공 API) 우선 → 보조(플랫폼 스크랩) → 가공지표(계산)**. 추정·허위 금지.

리서치 방법: 각 플랫폼은 봇 차단(403)이 잦아 공식 가이드 + 검색 스니펫 + 공공데이터포털 명세로 교차검증함.

---

## 0. 단지 식별과 매칭의 핵심 문제

여러 소스를 한 단지로 합치려면 **공통 키**가 필요하다. 한국 부동산 데이터는 단일 표준 단지ID가 없으므로 다음을 조합한다.

- **법정동코드(10자리)** + **지번/도로명주소** : 모든 공공데이터의 기준키. RTMS·건축물대장 매칭 축.
- **단지명(정규화)** : 플랫폼(아실/호갱노노/네이버)은 단지명 기반. 띄어쓰기·차수(1차/2차)·브랜드 변형 때문에 fuzzy match 필요.
- **각 플랫폼 내부 단지ID** : 네이버 `complexId`, 호갱노노 단지 slug, 아실 단지 파라미터. 한 번 매칭해두면 이후 재조회가 안정적 → **크로스워크 테이블**로 보관 권장.
- 실거래(RTMS)는 단지ID가 없고 (법정동+지번+아파트명+전용면적+층)으로 들어옴 → 단지 단위 집계 시 이 키로 그룹핑.

---

## 1. 플랫폼별 강점 비교

| 플랫폼 | 한줄 요약 | 가장 잘하는 것 | API/접근성 | URL |
|---|---|---|---|---|
| **국토부 RTMS / data.go.kr** | 실거래 원천 | 매매·전월세 **실거래가 원본**(평형·층·계약일), 법정동코드 기반 | **공식 OpenAPI(무료, 키 발급)** | data.go.kr/data/15126469, /15126474 |
| **건축HUB 건축물대장** | 단지 제원 원천 | **세대수·준공일(사용승인일)·용적률·건폐율·연면적·구조** 등 표제부 | **공식 OpenAPI(무료)** | data.go.kr/data/15134735 |
| **아실 (asil.kr)** | 투자·수급 분석 | **입주물량, 매물증감, 갭투자, 외지인(투자자) 거래, 가격순/평당가 비교차트, 여러 단지 비교** | 스크랩 전용(공식 API 없음) | asil.kr |
| **호갱노노 (hogangnono.com)** | 단지 입체 분석 | **평형별 시세, 실거래, 학원가/경사/일조 3D, 분양, 거래량 랭킹, 거주민 후기** | 비공식 내부 API/스크랩 | hogangnono.com |
| **네이버 부동산 (land.naver.com)** | 매물·단지정보 허브 | **호가 매물(실시간), 단지정보(세대수·준공·용적률·평형 구성), 학군 매칭, 시세** | 비공식 내부 API(`new.land.naver.com/api/complexes/{id}`) | land.naver.com |
| **KB부동산 데이터허브** | 시세지수·심리 | **KB시세, 전세가율, 매수우위지수(매수심리), 가격지수** | 데이터허브 조회(상당수 스크랩/다운로드) | kbland.kr, data.kbland.kr |
| **청약홈(한국부동산원)** | 신축 분양 | **분양 공고·분양가·경쟁률·당첨가점** | **공식 OpenAPI** | data.go.kr/data/15098547 |
| **부동산플래닛** | 노후도/평당가 | **평당가, 건물 노후도 지도** | 스크랩 전용 | bdsplanet.com |
| **정비사업 정보몽땅(서울)** | 재건축/재개발 | 서울 정비사업 단계·조합 정보(개발호재) | 포털 조회/스크랩 | cleanup.seoul.go.kr |

**요지**
- "정확한 사실 수치(실거래·제원·분양)"는 **공공 API**가 원천 → 신뢰축.
- "분석·수급·심리·후기·호가" 같은 **부가가치 지표**는 아실/호갱노노/네이버/KB가 강함 → 스크랩 보조.

---

## 2. 매칭할 핵심 필드 — 우선순위 표

(우선순위: ★★★ 필수 / ★★ 권장 / ★ 부가)

| 우선 | 필드 | 베스트 소스 | 공식 API? | 갱신 주기 | 비고 |
|---|---|---|---|---|---|
| ★★★ | 단지명·주소·**법정동코드** | 건축물대장 / 행정표준코드 | ✅ (data.go.kr, code.go.kr) | 비정기(주소체계 변경 시) | 모든 매칭의 기준키 |
| ★★★ | **세대수** | 건축물대장 표제부 `hhldCnt` | ✅ | 비정기 | 네이버 단지정보로 교차검증 |
| ★★★ | **준공연도/연식**(사용승인일) | 건축물대장 `useAprDay` | ✅ | 비정기 | 연식 = 현재연도−준공연도(계산) |
| ★★★ | **용적률·건폐율** | 건축물대장 `vlRat`,`bcRat` | ✅ | 비정기 | 재건축 사업성 핵심 |
| ★★★ | **평형(전용㎡)·평형별 구성** | 네이버 단지정보 / 건축물대장 전유부 | 일부 ✅ | 비정기 | 네이버 `pyeong` 타입별 세대수 |
| ★★★ | **실거래가 매매**(평형·층·계약일) | RTMS `RTMSDataSvcAptTradeDev` | ✅ | **월 1회 신고분 + 수시(계약일 기준 30일 내 신고)** | 단지=법정동+지번+아파트명으로 집계 |
| ★★★ | **실거래가 전세/월세** | RTMS `RTMSDataSvcAptRent` | ✅ | 동일 | 전세가율 계산용 |
| ★★ | **호가(매물)** 매매/전세 | 네이버 부동산 매물 | ❌ 비공식 API | **실시간/수시** | 평형·층·향·동 단위, 변동 큼 |
| ★★ | **평당가**(3.3㎡당) | 계산(실거래/전용면적) or 아실/플래닛 | 계산 | 거래 갱신 시 | 전용 vs 공급 기준 통일 필요 |
| ★★ | **전세가율** | 계산(전세/매매) or KB | 계산/KB | 거래·주간 | =전세가÷매매가×100 |
| ★★ | **거래량** | RTMS 집계 / 호갱노노 랭킹 / 아실 | ✅(원본 집계) | 월/수시 | 월별 매매 건수 추이 |
| ★★ | **입주물량** | 아실 `household.jsp` | ❌ 스크랩 | 분기/연 갱신 | 지역(시군구) 단위 공급 |
| ★★ | **매물증감** | 아실 매물증감 | ❌ 스크랩 | 일/주 | 수급 시그널 |
| ★★ | **외지인/갭투자** | 아실 외지인·갭투자 | ❌ 스크랩(원천은 RTMS 매수자 거주지) | 월/수시 | 투자수요 시그널 |
| ★★ | **학군/학원가** | 네이버(학군) / 호갱노노(학원가 overlay) | ❌ 비공식 | 비정기 | 배정 초·중·고, 학원 밀집·평균비 |
| ★★ | **개발호재(재건축·교통·GTX)** | 정비사업 정보몽땅(서울) / 호갱노노 / 뉴스 | 일부 ✅(정비사업) | 비정기 | 단계(조합설립~준공), 노선 개통 시점 |
| ★ | **분양가(신축)** | 청약홈 분양정보 API | ✅ | 공고 시점 | 경쟁률·가점 동반 |
| ★ | **매수심리** | KB 매수우위지수 | ❌ 조회/스크랩 | 주간 | 지역 단위 심리지표 |
| ★ | **일조/경사/조망** | 호갱노노 3D | ❌ 스크랩 | 비정기 | 정성 보조지표 |
| ★ | **거주민 후기** | 호갱노노 커뮤니티 | ❌ 스크랩 | 수시 | 정성 텍스트 |
| ★ | **노후도** | 부동산플래닛 | ❌ 스크랩 | 비정기 | 준공연도로 자체계산 가능 |

> 핵심 정리: **사실 4종(세대수·준공·용적률·건폐율 = 건축물대장 / 실거래 = RTMS)**은 전부 공식 API로 확보 가능. **호가·수급·심리·후기**는 스크랩 보조.

### 주요 공공 API 엔드포인트(참고)
- 아파트 매매 실거래: `http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev`
  파라미터: `serviceKey`, `LAWD_CD`(법정동코드 앞5자리), `DEAL_YMD`(YYYYMM), `pageNo`, `numOfRows`
- 아파트 전월세 실거래: data.go.kr/data/15126474 (`RTMSDataSvcAptRent` 계열)
- 건축물대장(건축HUB): data.go.kr/data/15134735 (표제부 = 세대수·용적률·건폐율·사용승인일)
- 청약홈 분양정보: data.go.kr/data/15098547
- 법정동코드 조회: https://www.code.go.kr/stdcode/regCodeL.do

---

## 3. 권장 단지 데이터 스키마 ("아파트 정보" 탭)

```jsonc
{
  // --- 식별 (출처: 건축물대장 + 행정표준코드 + 플랫폼 크로스워크) ---
  "complex_id": "내부 단지 고유키(자체 발급)",
  "name": "단지명(원문)",
  "name_normalized": "정규화 단지명(매칭용)",
  "address_jibun": "지번주소",
  "address_road": "도로명주소",
  "bjd_code": "법정동코드(10자리)",
  "sigungu": "시군구",
  "dong": "읍면동",
  "lat": 0, "lng": 0,
  "source_ids": {
    "naver_complex_id": null,
    "hogangnono_id": null,
    "asil_id": null
  },

  // --- 단지 제원 (출처: 건축물대장 표제부) ---
  "households": 0,            // 세대수 hhldCnt
  "buildings": 0,            // 동수
  "approval_date": "YYYY-MM-DD", // 사용승인일 useAprDay
  "built_year": 0,
  "age_years": 0,            // 계산: 현재연도 - built_year
  "floor_area_ratio": 0.0,   // 용적률 vlRat (%)
  "building_coverage_ratio": 0.0, // 건폐율 bcRat (%)
  "structure": "철근콘크리트 등",
  "max_floors": 0,
  "parking_per_household": null,

  // --- 평형 구성 (출처: 네이버 단지정보 / 건축물대장 전유부) ---
  "unit_types": [
    {
      "exclusive_area_m2": 0.0,   // 전용면적
      "supply_area_m2": null,     // 공급면적
      "pyeong": 0,                // 평형(공급 기준)
      "household_count": 0        // 해당 평형 세대수
    }
  ],

  // --- 시세/거래 (출처: RTMS 실거래 + 네이버 호가 + 계산) ---
  "deals_sale": [   // 매매 실거래 (RTMS)
    { "deal_date": "YYYY-MM-DD", "exclusive_area_m2": 0.0, "floor": 0,
      "price_manwon": 0, "price_per_pyeong_manwon": 0 }
  ],
  "deals_jeonse": [ // 전세 실거래 (RTMS)
    { "deal_date": "YYYY-MM-DD", "exclusive_area_m2": 0.0, "deposit_manwon": 0 }
  ],
  "listings": [     // 호가 매물 (네이버, 비공식)
    { "trade_type": "매매|전세|월세", "exclusive_area_m2": 0.0, "floor": "중층",
      "price_manwon": 0, "captured_at": "YYYY-MM-DDTHH:MM" }
  ],
  "price_summary": {            // 계산/요약
    "recent_sale_per_pyeong_manwon": 0,
    "jeonse_ratio_pct": 0.0,    // 전세가율
    "monthly_deal_count": []    // 월별 거래량 추이
  },

  // --- 수급/투자 시그널 (출처: 아실, 스크랩) ---
  "supply_demand": {
    "supply_pipeline": [ { "year": 0, "households": 0 } ], // 입주물량(시군구)
    "listing_change_trend": null,   // 매물증감
    "outsider_buy_ratio_pct": null, // 외지인 비율
    "gap_invest_signal": null
  },

  // --- 입지/생활 (출처: 네이버 학군 + 호갱노노 overlay) ---
  "education": {
    "assigned_elementary": null,
    "assigned_middle": null,
    "academy_density": null,        // 학원가 밀집도
    "avg_academy_fee": null
  },
  "environment": {                  // 호갱노노 3D (정성)
    "sunlight": null, "slope": null, "view": null
  },

  // --- 개발호재 (출처: 정비사업 정보몽땅, 뉴스) ---
  "development": {
    "reconstruction_stage": null,   // 재건축/재개발 단계
    "transit_catalysts": [],        // GTX/지하철 호재 + 예상 시점
    "notes": null
  },

  // --- 분양 (출처: 청약홈 API, 신축만) ---
  "presale": {
    "is_presale": false,
    "announce_date": null, "supply_price_manwon": null,
    "competition_rate": null, "min_winning_score": null
  },

  // --- 심리지표 (출처: KB) ---
  "sentiment": {
    "kb_buy_superiority_index": null // 매수우위지수(지역)
  },

  // --- 메타 ---
  "sources": [ { "field_group": "households", "source": "건축물대장", "fetched_at": "..." } ],
  "last_updated": "YYYY-MM-DDTHH:MM"
}
```

**필드 정합성 규칙**
- 평당가: **공급면적 기준**으로 통일(또는 전용/공급 둘 다 표기), 단위 만원.
- 모든 가격은 만원 정수, 면적은 ㎡(전용·공급 구분).
- 실거래 vs 호가는 절대 합치지 않음(서로 다른 신뢰도). UI에서 분리 표기.

---

## 4. 재사용 크롤 프롬프트 (per-complex JSON 출력)

아래 프롬프트는 단일 단지에 대해 위 스키마대로 JSON을 만들도록 지시한다. **1차 출처 우선, 없으면 null, 절대 추정 금지.**

```text
역할: 너는 한국 수도권 아파트 단지 데이터 수집 에이전트다. 입력으로 받은 단지에 대해
아래 규칙으로 JSON 한 개를 생성한다.

[입력]
- 단지명: {{NAME}}
- 주소(지번 또는 도로명): {{ADDRESS}}
- (선택) 법정동코드: {{BJD_CODE}}

[수집 우선순위 — 반드시 이 순서]
1) 사실 데이터(원천 = 공공 API, 최우선 신뢰):
   - 단지 제원(세대수·사용승인일/준공·용적률·건폐율·구조·층수):
     건축HUB 건축물대장 표제부 (data.go.kr/data/15134735).
   - 매매 실거래: RTMS getRTMSDataSvcAptTradeDev
     (apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev) — LAWD_CD=법정동코드 앞5자리,
     DEAL_YMD=최근 12개월. (법정동+지번+아파트명+전용면적)으로 본 단지만 필터.
   - 전월세 실거래: RTMS 전월세 API (data.go.kr/data/15126474).
   - 분양(신축이면): 청약홈 분양정보 API (data.go.kr/data/15098547).
2) 단지정보/평형구성/호가(보조 = 네이버 부동산):
   new.land.naver.com/api/complexes/{complexId} 및 매물 목록. 단지명+주소로 complexId 먼저 확정.
3) 분석·수급·입지(보조 = 아실/호갱노노/KB):
   - 입주물량·매물증감·외지인·갭투자: 아실(asil.kr).
   - 학원가·일조·경사·후기·거래량 랭킹: 호갱노노(hogangnono.com).
   - 매수우위지수·전세가율 참고: KB부동산 데이터허브(kbland.kr).
   - 개발호재(재건축 단계/GTX): 정비사업 정보몽땅(서울) 및 신뢰 가능한 보도.

[규칙]
- 절대 수치를 지어내지 마라. 확인 불가 필드는 null.
- 각 필드(또는 필드 그룹)마다 출처와 수집시각을 sources[]에 기록.
- 실거래(deals_*)와 호가(listings)는 절대 합치지 말 것. 호가는 captured_at 필수.
- 평당가·연식·전세가율 등 계산값은 원천 수치로 직접 계산하고 계산식 근거가 되는 원 필드를 함께 남길 것.
- 단지명은 원문(name)과 정규화(name_normalized: 공백/차수/브랜드 정리) 둘 다 출력.
- 가격 단위 = 만원(정수), 면적 = ㎡(전용/공급 구분), 비율 = %.
- 봇 차단(403) 시 해당 소스는 건너뛰고 null 처리하되 sources[]에 "blocked"로 기록.

[출력]
- 위 "권장 단지 데이터 스키마"와 동일한 키 구조의 JSON 객체 하나만 출력(설명 텍스트 금지).
```

---

## 출처 (Sources)
- 국토부 아파트 매매 실거래가 OpenAPI: https://www.data.go.kr/data/15126469/openapi.do
- 국토부 아파트 매매 실거래가 상세: https://www.data.go.kr/data/15126468/openapi.do
- 국토부 아파트 전월세 실거래가: https://www.data.go.kr/data/15126474/openapi.do
- 국토부 실거래가공개시스템(RTMS): https://rt.molit.go.kr/
- 건축HUB 건축물대장정보 서비스: https://www.data.go.kr/data/15134735/openapi.do
- 행정표준 법정동코드: https://www.code.go.kr/stdcode/regCodeL.do
- 한국부동산원 청약홈 분양정보 API: https://www.data.go.kr/data/15098547/openapi.do
- 아실 입주물량: https://asil.kr/app/household.jsp / https://asil.kr/asil/sub/movein.jsp
- 아실 매매/전세 가격지수: https://asil.kr/asil/sub/price_index.jsp
- 호갱노노: https://hogangnono.com/ , 랭킹 https://hogangnono.com/ranking
- 네이버 부동산: https://land.naver.com/ (단지 API: new.land.naver.com/api/complexes/{id})
- KB부동산 데이터허브(매수심리): https://data.kbland.kr/kbstats/psychology-of-housing-market
- KB통계기상도(전세가율): https://data.kbland.kr/weathermap
- 정비사업 정보몽땅(서울 재건축/재개발): https://cleanup.seoul.go.kr/
