# 아키텍처 — apthub (m-SIGNAL)

> 수집 → 정규화(JSON) → 필터(키워드·지역·트리거) → 요약/함의 → 리포트(Markdown) → 발송.
> Phase 1은 **수집을 채팅 수동파싱**으로 대체하고 나머지 파이프라인은 실제 코드로 동작한다.

## 파이프라인

```
[원문]
  ├ Phase 1: 채팅에 붙여넣기 → Claude가 Signal dict로 수동파싱 (+함의 1줄)
  └ Phase 2: sources/*.py 커넥터(RSS/Open API)가 자동 수집
        │
        ▼
  manual.ingest() / sources
        │
        ▼
  filters.enrich()  ── config/monitoring.json, target_areas.json 규칙
        │            (areas/keywords/category 태깅 + 🔴/🟡 트리거 평가)
        ▼
  store  ── data/signals/YYYY-MM-DD.jsonl  (id=URL/제목 해시로 중복 제거)
        │
        ▼
  report.render_daily / render_weekly  ── 05-report-format.md 템플릿
        │
        ▼
  data/reports/*.md  →  (Phase 2) 메일/텔레그램 발송
```

## 모듈

| 모듈 | 책임 |
|---|---|
| `schema.py` | `Signal` 데이터클래스. 날짜 정규화, id 해시, 직렬화 |
| `config.py` | `config/*.json` 로딩, 천장 요약 텍스트, 경로 |
| `filters.py` | 키워드/지역/카테고리 매칭, 트리거 규칙 평가, `enrich()` |
| `store.py` | JSONL 저장/로드, 날짜 범위 조회, 중복 제거 |
| `manual.py` | **Phase 1** 수동파싱 진입점 (`ingest`, `ingest_json`) |
| `report.py` | 데일리/위클리 Markdown 생성, 주차 계산 |
| `cli.py` | `add / enrich / report / list` 커맨드 |
| `sources/` | **Phase 2** 자동 수집 커넥터 (RTMS/ECOS/DART/RSS) — 스텁 |

## 설정 = 데이터 (config/)

핵심 도메인 지식은 코드가 아니라 JSON에 있다. 관심단지·키워드·트리거를 바꾸려면
`config/`만 수정하면 된다 (01~05 문서를 기계가 읽는 형태로 옮긴 것).

- `profile.json` — 천장(8.5/10.5억), 명의전략, 제약 (민감 수치 제외)
- `target_areas.json` — 관심단지 + 별칭 + 추정시세 + tier
- `monitoring.json` — 카테고리별 키워드 + 🔴/🟡 트리거 규칙

## 트리거 규칙 평가

`monitoring.json` 의 각 규칙은 `all_of_*` / `any_of_*` 그룹을 가진다.
- `all_of_*` 그룹: 나열된 키워드가 **전부** 본문에 있어야 함
- `any_of_*` 그룹: 그룹 내 **하나 이상** 매칭되면 충족
- 규칙은 모든 그룹이 충족될 때 매칭. red 규칙이 하나라도 맞으면 🔴, 아니면 yellow 검사.

수동으로 더 높은 트리거 등급을 지정하면 `enrich()`가 강등하지 않는다(사람 판단 우선).

## 보안·프라이버시 원칙

- 크롤러는 **시장 데이터만** 다룬다. 급여·자산(finance-model.json)은 레포에 두지 않는다.
- 천장 숫자(8.5/10.5억)·관심단지는 비식별 수준으로만 `config/`에 둔다.
- 수집은 RSS·Open API 우선, robots.txt·이용약관 준수, 무단 대량 크롤 금지.
- 발송은 개인 메일/텔레그램(Phase 2). 토큰·API 키는 환경변수/`.env`로만 (커밋 금지).

## Phase 2 로드맵 (자동화)

1. `sources/rtms.py` — 국토부 실거래가 Open API (공공데이터포털 키). 관심단지 단지코드 매핑.
2. `sources/ecos.py` — 한국은행 ECOS (기준금리·코픽스·M2).
3. `sources/dart.py` — DART Open API (SK하이닉스 실적·공시).
4. `sources/rss.py` — 경제지/포털 부동산 RSS (feedparser), 본문 대신 제목·요약·링크.
5. `summarize.py` — 최신 Claude 모델로 요약·함의 자동 생성(수동파싱 대체/보조).
6. `notify.py` — 메일(HTML 변환)/텔레그램 발송.
7. 스케줄러 — GitHub Actions cron (평일 아침 데일리, 일요일 위클리).
