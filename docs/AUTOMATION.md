# 자동 데이터 수집 파이프라인

APT-SIGNAL은 **무료 범위에서 공식 정량 지표를 주간 자동 수집**한다.
LLM 기반 뉴스(정성) 큐레이션은 유료이므로 자동화하지 않고 챗(수동)으로 유지한다.

## 비용 — $0
- **GitHub Actions**: 공개(public) 레포는 무제한 무료. (비공개면 월 2,000분 무료 한도)
- **정부 공식 API**: RTMS(국토부 실거래)·ECOS(한국은행)·KOSIS(통계청) 모두 **무료**.
- 따라서 주간 자동 수집은 추가 요금이 없다.
- ⚠️ 자동화하지 않는 것: 뉴스/정책/반도체 **정성 기사 수집은 LLM이 필요**(유료 API).
  → 이 부분만 챗으로 직접 수집해 붙인다(아래 프롬프트 문서 참조).

## 동작 방식
1. `.github/workflows/crawl.yml` 이 **매주 월요일 06:00(KST)** 실행(수동 실행도 가능).
2. `scripts/apthub_official_apis.py` 로 최근 4개월 RTMS 실거래 + ECOS 기준금리 수집
   → `data/seed/auto-official-latest.json` (롤링 갱신, 누적 아님).
3. 변경이 있으면 main에 커밋 → 데이터 경로 변경을 감지한 `pages.yml` 이 **자동 재배포**.
4. RTMS는 구별 실거래를 sido로 집계해 **평당가·평형별 실거래가(면적대별)·거래량**을 채운다
   — 현재 수동으로 채우기 어려운 바로 그 지표들이다.

## 1회 설정 — 무료 API 키 발급 후 레포 Secrets 등록
키가 없으면 워크플로는 **경고만 남기고 조용히 건너뛴다**(실패하지 않음). 아래를 등록하면 작동.

### 1) RTMS_KEY (국토부 아파트 매매 실거래가) — 핵심
1. <https://www.data.go.kr> 회원가입/로그인
2. "아파트 매매 실거래가" 검색 → **국토교통부_아파트 매매 실거래가 자료(#1613000)** 활용신청(자동승인)
3. 마이페이지 → 활용신청 → 일반 인증키에서 **Decoding 키** 복사
   (반드시 Encoding이 아닌 **Decoding** 키)

### 2) ECOS_KEY (한국은행 경제통계, 기준금리 등)
1. <https://ecos.bok.or.kr> → Open API → 인증키 신청(무료, 즉시 발급)

### 3) 레포 Secrets 등록
GitHub 레포 → **Settings → Secrets and variables → Actions → New repository secret**
- `RTMS_KEY` = (위 Decoding 키)
- `ECOS_KEY` = (ECOS 인증키)

등록 후 **Actions 탭 → Weekly official data crawl → Run workflow** 로 즉시 테스트 가능.

## 자동화 범위와 한계
| 항목 | 자동화 | 방식 |
|---|---|---|
| 평당가·평형별 실거래가·거래량(실거래) | ✅ | RTMS 주간 cron |
| 기준금리 | ✅ | ECOS 주간 cron |
| 매매/전세 지수·미분양·청약·경매·분양가·KB지표 | ❌(부분) | 공식 발표를 챗으로 큐레이션 |
| 정책·거시·반도체 뉴스(정성) | ❌ | 챗 프롬프트로 수집(유료 LLM) |

KOSIS(분양가·규모별)도 `--kosis` 로 확장 가능하나, 통계표 ID 설정(`KOSIS_SPECS`)이
필요해 기본 비활성 상태다. 필요 시 KOSIS_KEY 등록 후 specs를 채우면 된다.

수동 챗 수집에 쓰는 프롬프트는 `docs/prompts/current-crawl-prompts.md` 참조.
