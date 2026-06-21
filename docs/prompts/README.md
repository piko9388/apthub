# 프롬프트 인덱스 (백데이터)

챗/에이전트에 넘겨 데이터를 수집·파싱하기 위해 사용한 프롬프트 모음. 각 프롬프트는 apthub `Signal` JSON을 산출하며, 적재는 공통:
```bash
PYTHONPATH=src python3 -m apthub add --file out.json --by-date
python3 scripts/build_site.py
python3 scripts/gen_reports.py        # 일/주간 리포트 재생성
```

| 프롬프트 | 용도 | 트랙 |
|---|---|---|
| `master-crawl-prompt.md` | **종합 크롤(RSS·Google News·공식)** — 수도권 부동산+직결 경제 전수 | news+data |
| `source-gap-prompt.md` | **1차 출처 매칭·세그먼트 보강**(면적대/가격대/심리/PIR/분양가…) | data |
| `../news-crawl-prompt.md` | 주차별 뉴스(탈자극 사실추출) | news |
| `../data-crawl-prompt.md` | 공식 지표(표준 metric: 지수·금리·거래량·미분양) | data |
| `../paste-prompt.md` | 사람이 기사 붙여넣기(MAX 버전) | news |
| `../agent-crawl-prompt.md` | 갭 타깃형(빈 구·표본<3 우선) | news |
| `../crawler-handoff-prompt.md` | 초기 핸드오프 | — |
| `../00-prompt.md` | 최초 시스템 프롬프트(원본) | — |

## 카테고리(2축)
- **유형(kind)**: `news`(기사·정성) / `data`(공식 지표·정량)
- **분야(category)**: `policy`(정책·규제) / `price`(시장·실거래) / `macro`(금리·거시) / `semicon`(반도체·보조)
- **지표 출처군(data 세분)**: 부동산원·국토부 동향 / KB·실거래가 / 한은·금융위 거시

## 표준 metric(data 트랙)
`매매가격지수 변동률`·`전세가격지수 변동률`·`주간 매매변동률`·`주간 전세변동률`·`KB 매매변동률`·`매매전망지수`·`매수우위지수`·`아파트 매매 거래량`·`주택 매매 거래량`·`미분양`·`준공후 미분양`·`입주물량`·`기준금리`·`COFIX`·`주택담보대출 금리`·`가계대출 증감`·`스트레스DSR 가산금리`
