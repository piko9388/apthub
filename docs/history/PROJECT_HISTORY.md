# APT-SIGNAL 개발 히스토리

> 수도권(서울·경기·인천) 부동산 정책·시장 동향 모니터링 대시보드.
> 개인 크롤러+리포트로 출발해 공개형 동향 모니터링 제품으로 진화.

## 전체 구성(아키텍처 한눈에)
```
config/        도메인 지식(JSON) — regions·monitoring·target_areas·report·profile
data/seed/     Signal 시드(발행일별). news 트랙 + data 트랙(공식 지표)
src/apthub/    파이프라인 — schema·config·filters·store·manual·report·cli·sources
scripts/       build_site.py(정적 사이트 생성)·gen_reports.py(일/주간 리포트)·region_gaps.py·m_signal_fetch.py
docs/          명세·프롬프트·히스토리(본 폴더)
reports/2026/  자동 생성 일자별·주차별 리포트(백데이터)
.github/workflows/pages.yml  main 푸시 시 Pages 배포
index.html     자체완결 대시보드(루트 + site/)
```

## 데이터 흐름
```
수집(채팅 수동파싱 / 에이전트 크롤 / 공식 API)
  → Signal JSON 배열
  → apthub add --by-date  (정규화 normalize_date·make_id, filters.enrich 자동 태깅)
  → data/seed/*.json (발행일별)
  → build_site.py        → index.html (뉴스/지표 2트랙 분리, 모니터링 정합)
  → gen_reports.py       → reports/2026/{daily,weekly}/*.md
  → 커밋·푸시 → Pages 자동 배포
```

## 핵심 모델
- **Signal**: title·source·url·date·summary·category(policy|price|macro|semicon)·sido·region[]·comment·confidence·trigger·trigger_reasons + **kind(news|data)·metric·value·unit**.
- **2트랙**: 뉴스(정성) ↔ 지표(정량). 모니터링 뷰에서 정합.
- **트리거**: 🔴 즉시(red) / 🟡 주목(yellow) — `config/monitoring.json` 규칙(all_of/any_of/none_of 가드).
- **신뢰도**: 공식/언론/추정(URL 도메인 기반 `TRUST`).

## 개발 단계 & PR 타임라인
| 단계 | 내용 | PR |
|---|---|---|
| Phase 1 | 파이프라인 구축(스키마·필터·트리거·리포트), 채팅 수동파싱 | — |
| 실전검증 | 전수 검증 4개 버그 수정(위클리 교차오염·반도체 증발·금리 오탐·데이터 위생) | #2 |
| 백데이터 | 2026 발행일별 적재 + 파싱 프롬프트 + 시드 | #2 |
| 배포 | 정적 대시보드 + GitHub Pages | — |
| 공개 피벗 | 메인=정책 동향, 개인=보조 탭(APTHUB_PUBLIC) | #3 |
| 지역 확장 | 수도권 분류체계 + 해석 코멘트 + 부읽남 참고 | #4 |
| 대용량 크롤 | 7권역 283건 + 공식 API 하네스 + 신뢰도 배지 | #5 |
| 지표 재구축 | 지역 지표 보드 + 태깅 정확도(가중치) | #6 |
| 표시 수정 | 루트 index.html 출력(README 서빙 문제) | #7 |
| 갭 보강 | 갭 타깃 크롤 55건 + dedup/파싱 견고화 | #8 |
| 라운드2 | 구로·금천·중랑·고양·용산 20건(412건) | #9 |
| UX 개편 | 좌측 드릴다운·검색·정렬/필터·지도(Leaflet) | #10 |
| 브리핑 | 편집형 '동향 리포트' 기본 화면 | #11 |
| 리브랜딩 | APT-SIGNAL + 리포트 표화 + 주간 정리 + 모바일 | #12 |
| UX/접근성 | 주차 도형·범례·브레드크럼 칩·사용설명서·WCAG | #13 |
| 시계열 | 주차→월별 묶음 + 한눈에 기준기간 핵심 구간 | #14 |
| 2트랙 | 뉴스+공식지표 모델 + 동향 모니터링(정합) 뷰 | (이후) |

## 진화 메모(주요 피벗)
1. 개인 크롤러 → 공개형 제품(D04).
2. 카드 나열 → 편집형 브리핑(D08) → 정량 지표 정합(D11·D12).
3. 시계열 단위: 주 → 월(D10-1) → 주/일 드릴다운(D10-2·D14).
4. 단일 트랙 → 2트랙(뉴스/지표).

자세한 결정 근거는 `DECISION_LOG.md`, 프롬프트는 `docs/prompts/`(인덱스) 참고.
