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


def test_rate_nonevent_not_red():
    # "기준금리 결정은 7월" 같은 비(非)이벤트는 🔴가 아니어야 함(none_of 가드).
    s = filters.enrich(Signal(title="한은 6월 금통위는 금융안정회의 — 기준금리 결정은 7월",
                              source="한은", summary="6월엔 기준금리 결정 회의가 없고"))
    assert s.category == "macro"
    assert s.trigger == "none"
    # 실제 인상/인하는 여전히 🔴
    s2 = filters.enrich(Signal(title="한국은행 기준금리 0.25%p 인하", source="한은"))
    assert s2.trigger == "red"


def test_weekly_table_no_cross_unit_bleed():
    # 등촌3 제목이 '가양'을 언급해도, 가양 행에 등촌3 메모가 새지 않아야 함.
    s = filters.enrich(Signal(title="등촌주공3단지 10.9억 신고가 — 가양·등촌 정비 수혜",
                              source="RTMS", category="price", implication="x"))
    out = report.render_weekly([s], "2026-06-15", "2026-06-21")
    rows = {ln.split("|")[1].strip(): ln for ln in out.splitlines()
            if ln.startswith("| ") and "전용59" not in ln and "---" not in ln}
    assert "신규 시그널" in rows["등촌주공3단지"]
    assert "신규 시그널" not in rows["가양"]
    assert "신규 시그널" not in rows["마곡"]


def test_daily_surfaces_semicon():
    # 정책 🔴가 많아도 반도체(🟡)가 Top3 에서 사라지지 않아야 함.
    sigs = [
        filters.enrich(Signal(title="DSR 강화", source="금융위", category="policy", implication="a")),
        filters.enrich(Signal(title="LTV 인하 변경", source="금융위", category="policy", implication="b")),
        filters.enrich(Signal(title="생애최초 요건 강화", source="금융위", category="policy", implication="c")),
        filters.enrich(Signal(title="SK하이닉스 실적 서프라이즈", source="DART", category="semicon", implication="d")),
    ]
    out = report.render_daily(sigs, day="2026-06-19")
    top3 = out.split("Top 3")[1]
    assert "하이닉스" in top3  # 반도체가 Top3 에 노출


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
