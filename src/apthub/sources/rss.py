"""RSS 수집 커넥터 (Phase 2 스텁).

feedparser 로 매체 RSS 를 읽어 Signal 로 변환한다. 본문 전체가 아니라
제목·요약·링크·발행일만 보존(약관 준수). enrich 는 호출부에서 적용.
"""
from __future__ import annotations

from ..schema import Signal

# 매체별 부동산 섹션 RSS (Phase 2 에서 실제 URL 검증·교체)
FEEDS: dict[str, str] = {
    # "한국경제 부동산": "https://...",
    # "매일경제 부동산": "https://...",
    # "이데일리 부동산": "https://...",
}


def collect(feeds: dict[str, str] | None = None) -> list[Signal]:
    """RSS 피드를 읽어 Signal 목록 반환. feedparser 미설치 시 빈 목록."""
    feeds = feeds or FEEDS
    try:
        import feedparser  # type: ignore
    except ImportError:
        return []
    out: list[Signal] = []
    for source, url in feeds.items():
        parsed = feedparser.parse(url)
        for e in parsed.entries:
            out.append(Signal(
                title=getattr(e, "title", "").strip(),
                source=source,
                url=getattr(e, "link", ""),
                summary=getattr(e, "summary", "")[:300],
                date=getattr(e, "published", None),
            ))
    return out
