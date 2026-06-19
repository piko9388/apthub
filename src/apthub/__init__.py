"""apthub — 정훈 맞춤 부동산 시그널 크롤러 + 리포트 (m-SIGNAL).

Phase 1: 채팅 수동파싱. 원문을 Signal JSON으로 파싱 → 필터/트리거 태깅 → 데일리/위클리 리포트.
Phase 2: RSS/Open API 커넥터로 수집 자동화 (src/apthub/sources/).
"""

__version__ = "0.1.0"
