"""Phase 2 자동 수집 커넥터 (스텁).

각 커넥터는 `collect() -> list[Signal]` 을 구현하고, filters.enrich() 로 태깅한 뒤
store.add() 로 저장한다. Phase 1(채팅 수동파싱)에서는 사용하지 않는다.

구현 예정:
  rtms.py  — 국토부 실거래가 Open API (DATA_GO_KR_KEY)
  ecos.py  — 한국은행 ECOS (ECOS_KEY): 기준금리·코픽스·M2
  dart.py  — DART 전자공시 (DART_KEY): SK하이닉스 실적·공시
  rss.py   — 경제지/포털 부동산 RSS (feedparser)
"""
