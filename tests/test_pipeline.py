"""파이프라인 단위 테스트. 실행: PYTHONPATH=src python3 -m pytest -q (또는 이 파일 직접 실행)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from apthub import filters, report  # noqa: E402
from apthub.schema import Signal, normalize_date  # noqa: E402


def test_normalize_date():
    assert normalize_date("2026-06-19") == "2026-06-19"
    assert normalize_date("2026.6.9") == "2026-06-09"
    assert normalize_date("2026년 6월 19일") == "2026-06-19"
    assert normalize_date("미정") is None
    assert normalize_date(None) is None


def test_id_dedup():
    a = Signal(title="제목", source="s", url="https://x/a")
    b = Signal(title="다른 제목", source="s", url="https://x/a")
    assert a.id == b.id  # 같은 URL → 같은 id


def test_enrich_red_trigger_dsr():
    s = filters.enrich(Signal(title="스트레스 DSR 강화 검토", source="금융위",
                              summary="DSR 한도 조정"))
    assert s.category == "policy"
    assert s.trigger == "red"
    assert "DSR" in s.keywords


def test_enrich_detects_area_and_newhigh():
    s = filters.enrich(Signal(title="등촌주공3단지 59㎡ 신고가", source="RTMS"))
    assert "등촌주공3단지" in s.areas
    assert s.trigger == "red"
    assert s.category == "price"


def test_enrich_yellow_hynix():
    s = filters.enrich(Signal(title="SK하이닉스 실적 서프라이즈", source="DART",
                              summary="영업이익 급증"))
    assert s.category == "semicon"
    assert s.trigger == "yellow"


def test_manual_trigger_preserved():
    s = Signal(title="일반 뉴스", source="s", trigger="yellow")
    s = filters.enrich(s)
    assert s.trigger in ("yellow", "red")  # 수동 등급이 강등되지 않음


def test_daily_report_renders():
    sigs = [
        filters.enrich(Signal(title="스트레스 DSR 강화", source="금융위",
                              implication="천장 하락 리스크", category="policy")),
        filters.enrich(Signal(title="가양 신고가", source="RTMS", category="price",
                              implication="상승기")),
    ]
    out = report.render_daily(sigs, day="2026-06-19")
    assert "Daily" in out
    assert "🔴 핵심 트리거" in out
    assert "천장 하락 리스크" in out


def test_weekly_report_table():
    sigs = [filters.enrich(Signal(title="등촌주공3 신고가", source="RTMS",
                                  category="price", implication="x"))]
    out = report.render_weekly(sigs, "2026-06-15", "2026-06-21")
    assert "Weekly" in out
    assert "등촌주공3단지" in out
    assert "부읽남" in out


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
