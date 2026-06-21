"""Signal 스키마 — 수집→정규화의 표준 단위.

하나의 뉴스/실거래/공시/지표가 모두 Signal 한 건으로 정규화된다.
필수: title, source. 나머지는 파싱 시 채우고, filters.enrich() 가 보강한다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

KST = timezone(timedelta(hours=9))

# category: 03-monitoring.md 의 A/B/C/D 에 대응
CATEGORIES = ("policy", "price", "macro", "semicon")
TRIGGERS = ("red", "yellow", "none")


def _now_kst_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def normalize_date(value: str | None) -> Optional[str]:
    """다양한 날짜 표기를 YYYY-MM-DD 로 정규화. 실패하면 None."""
    if not value:
        return None
    s = value.strip()
    # 이미 ISO 형태면 앞 10자
    m = re.match(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # 2026년 6월 19일 형태
    m = re.match(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


@dataclass
class Signal:
    title: str
    source: str
    summary: str = ""
    url: str = ""
    date: Optional[str] = None            # 발행일 YYYY-MM-DD
    category: Optional[str] = None        # policy|price|macro|semicon
    sido: Optional[str] = None            # 서울|경기|인천|전국 (광역)
    region: list[str] = field(default_factory=list)    # 매칭된 시군구
    comment: str = ""                     # 해석 코멘트(중립·일반 독자용)
    confidence: str = ""                  # 출처 신뢰도(●공식|◐통설|○추정), 비면 URL서 추론
    areas: list[str] = field(default_factory=list)     # 매칭된 관심 지역/단지
    keywords: list[str] = field(default_factory=list)  # 매칭된 키워드
    trigger: str = "none"                 # red|yellow|none
    trigger_reasons: list[str] = field(default_factory=list)
    implication: str = ""                 # 내 매수계획 함의 한 줄 (필수 권장)
    raw_ref: str = ""                     # data/raw 원문 캐시 경로(선택)
    collected_at: str = field(default_factory=_now_kst_iso)
    id: str = ""

    def __post_init__(self) -> None:
        self.date = normalize_date(self.date) if self.date else None
        if self.category and self.category not in CATEGORIES:
            self.category = None      # 크롤 입력 오타(예: 'macre')에 견고 — 크래시 대신 무시
        if self.trigger not in TRIGGERS:
            self.trigger = "none"
        if not self.id:
            self.id = self.make_id()

    def make_id(self) -> str:
        """중복 제거용 id: URL+제목 해시.
        집계사이트가 같은 랜딩 URL을 여러 거래에 재사용하는 경우가 있어, URL만으로
        합치면 서로 다른 실거래가 사라진다. URL+제목 조합으로 구분한다."""
        basis = (self.url + "\n" + self.title).strip().lower()
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Signal":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})
