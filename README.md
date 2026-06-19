# 📡 apthub — 정훈 부동산 시그널 (m-SIGNAL)

부동산 뉴스·정책·시장 시그널 **크롤러 + 데일리/위클리 리포트** 시스템.
개인 맞춤 부동산 브리핑("m-SIGNAL")을 목표로, 모든 시그널에
**"내 매수계획(8월 ~8.5억 / 27.2 ~10.5억, 희주 단독 생애최초)에의 함의" 한 줄**을 붙인다.

> **현재 단계 = Phase 1: 채팅 수동파싱.**
> 수집을 채팅(원문 붙여넣기 → 파싱)으로 대체하고, 정규화→필터→트리거→리포트는 실제 코드로 동작한다.
> API 키 없이 오늘부터 데일리/위클리 리포트를 뽑을 수 있다. 자동 수집(RSS/Open API)은 Phase 2.

## 빠른 시작

```bash
# 1) 예제 시그널 적재 (Claude가 채팅에서 파싱한 결과 형태)
PYTHONPATH=src python3 -m apthub add --file examples/sample-signals.json --day 2026-06-19

# 2) 데일리 리포트
PYTHONPATH=src python3 -m apthub report daily --day 2026-06-19

# 3) 위클리 리포트(해당 주 월~일 집계)
PYTHONPATH=src python3 -m apthub report weekly --day 2026-06-19 --save
```

생성 예시: [`examples/daily-2026-06-19.md`](examples/daily-2026-06-19.md) · [`examples/weekly-2026-06-21.md`](examples/weekly-2026-06-21.md)

## 백데이터 구축 (2026 전체)

채팅에 기사를 붙여넣어 발행일별 백데이터를 쌓는다.

1. **파싱 프롬프트** — [`docs/paste-prompt.md`](docs/paste-prompt.md)의 블록을 새 세션에 붙여넣고, 이어서 기사 원문(여러 건 가능)을 붙여넣으면 Signal JSON 배열로 변환된다.
2. **적재(발행일별)** — `apthub add --file out.json --by-date` → 각 시그널이 자기 발행일 파일(`data/signals/YYYY-MM-DD.jsonl`)로 분산 저장된다.
3. **과거 리포트** — `apthub report weekly --day 2026-05-28` 처럼 임의 과거 시점 조회 가능.

큐레이션 시드는 [`data/seed/2026-backdata.json`](data/seed/2026-backdata.json)에 커밋해 두어 컨테이너 리셋에도 보존·재적재된다(`apthub add --file data/seed/2026-backdata.json --by-date`). 현재 시드에는 2025.6 6.27 대책 ~ 2026.6 강서 신고가까지 20건의 핵심 시그널이 담겨 있다.

## 채팅 수동파싱 워크플로 (Phase 1)

1. **채팅에 원문을 붙여넣는다** — 부동산 뉴스, 국토부/금융위/기재부 보도자료, RTMS 실거래, DART 공시, 금통위 결정문 등.
2. **Claude가 Signal JSON으로 파싱한다** — 아래 형태. 카테고리·지역·키워드·트리거는 비워도 `enrich`가 자동 보강하고, **함의(implication) 한 줄은 사람/Claude가 작성**한다.
   ```json
   {
     "title": "금융위, 스트레스 DSR 추가 강화 검토",
     "source": "금융위원회 보도자료",
     "url": "https://...",
     "date": "2026-06-19",
     "summary": "한 줄 요약",
     "category": "policy",
     "implication": "DSR 강화 → 희주 단독 한도 축소 → 8월 천장 8.5억 하방 압력"
   }
   ```
3. **적재** — `apthub add --file parsed.json` (또는 stdin). 자동으로 지역·키워드·🔴/🟡 트리거를 태깅하고 중복(URL/제목 해시)을 제거한다.
4. **리포트** — `apthub report daily|weekly`.

## CLI

| 명령 | 설명 |
|---|---|
| `apthub add --file f.json [--day D] [--replace] [--by-date]` | 파싱 JSON(배열/단건) 적재 + 자동 태깅. `--replace`는 해당 날짜 덮어쓰기, `--by-date`는 각 시그널을 발행일 파일로 분산 저장(백데이터) |
| `apthub clear --day D` | 해당 날짜 시그널 삭제 |
| `apthub enrich [--day D \| --all]` | 저장된 시그널 재태깅 |
| `apthub report daily [--day D] [--save]` | 데일리 리포트 |
| `apthub report weekly [--day D] [--save]` | 위클리 리포트(주 월~일) |
| `apthub list [--day D]` | 저장된 시그널 목록 |

> 환경변수 `APTHUB_DATA_DIR`로 데이터 루트를 바꿀 수 있다(테스트/실전 격리). 미설정 시 `./data`.

## 카테고리 & 트리거

| 카테고리 | 대상 (03-monitoring.md) |
|---|---|
| `policy` | 대출/세제 — DSR·LTV·6억 상한·생애최초·증여공제·규제지역 (최우선) |
| `price` | 강서 시세/공급 — 등촌주공·가양·발산·염창·우장산·대방, 신고가·정비·분양 |
| `macro` | 금리/거시 — 기준금리·코픽스·M2·역전세 |
| `semicon` | 반도체/소득 — SK하이닉스 실적·HBM·성과급(27.2 재원) |

- 🔴 **즉시**: DSR·LTV·6억 상한·생애최초 요건 변경 / 강서·검단 규제지역 변동 / 기준금리 변경 / 관심단지 신고가·급매
- 🟡 **주목**: 등촌주공 정비 진전 / 강서 입주·분양 / 하이닉스 실적 / 코픽스·주담대 금리 변동

규칙은 모두 `config/monitoring.json`에 있다. 관심단지·키워드·트리거를 바꾸려면 `config/`만 수정.

## 구조

```
config/        profile.json · target_areas.json · monitoring.json  (도메인 지식 = 데이터)
src/apthub/    schema · config · filters · store · manual · report · cli  (+ sources/ Phase2)
docs/          01~05 원본 + architecture.md + data-sources-research.md + budreadnam-lectures.md
examples/      sample-signals.json + 생성된 데일리/위클리 예시
data/          raw · signals · reports  (런타임, .gitignore)
tests/         test_pipeline.py
```

자세한 설계: [`docs/architecture.md`](docs/architecture.md) · 소스 조사: [`docs/data-sources-research.md`](docs/data-sources-research.md)

## 테스트

```bash
python3 tests/test_pipeline.py     # 또는: PYTHONPATH=src python3 -m pytest -q
```

## 프라이버시 원칙

- 크롤러는 **시장 데이터만** 다룬다. 급여·자산(`finance-model.json`)은 레포에 두지 않는다.
- 천장 숫자(8.5/10.5억)·관심단지는 비식별 수준으로 `config/`에만.
- 수집은 RSS·Open API 우선, robots.txt·이용약관 준수. API 키는 `.env`(커밋 금지).

## 로드맵 (Phase 2 — 자동화)

`sources/`에 RTMS·ECOS·DART·RSS 커넥터 구현 → `summarize.py`(Claude 요약·함의 자동화) →
`notify.py`(메일/텔레그램) → GitHub Actions cron(평일 데일리·일요일 위클리). 상세는 architecture.md 참고.
