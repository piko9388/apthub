"""파이프라인 단위 테스트. 실행: PYTHONPATH=src python3 -m pytest -q (또는 이 파일 직접 실행)."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from apthub import filters, report  # noqa: E402
from apthub.schema import Signal, normalize_date  # noqa: E402


def test_normalize_date():
    assert normalize_date("2026-06-19") == "2026-06-19"
    assert normalize_date("2026.6.9") == "2026-06-09"
    assert normalize_date("2026년 6월 19일") == "2026-06-19"
    assert normalize_date("Wed, 19 Jun 2026 09:30:00 +0900") == "2026-06-19"  # RFC822(RSS)
    assert normalize_date("01 Jan 2025") == "2025-01-01"
    assert normalize_date("미정") is None
    assert normalize_date(None) is None


def test_id_dedup():
    # 같은 URL+제목 → 같은 id(진짜 중복)
    a = Signal(title="제목", source="s", url="https://x/a")
    b = Signal(title="제목", source="s", url="https://x/a")
    assert a.id == b.id
    # 같은 URL이라도 제목이 다르면 다른 id(집계사이트 공유 URL의 서로 다른 거래 보존)
    c = Signal(title="다른 제목", source="s", url="https://x/a")
    assert a.id != c.id


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


def test_region_detection():
    s = filters.enrich(Signal(title="강서구 등촌주공3 신고가", source="RTMS", category="price"))
    assert s.sido == "서울" and "강서구" in s.region
    s2 = filters.enrich(Signal(title="검단신도시 우미린 59㎡ 5억", source="x", category="price"))
    assert s2.sido == "인천" and "서구" in s2.region
    s3 = filters.enrich(Signal(title="분당 판교 시세", source="x", category="price"))
    assert s3.sido == "경기" and "성남시" in s3.region
    # 전국 정책은 sido=전국 폴백
    s4 = filters.enrich(Signal(title="스트레스 DSR 3단계 시행", source="금융위", category="policy"))
    assert s4.sido == "전국"


def test_data_kind_and_price_excluded():
    # 정량 지표(metric+value) → 자동 data 트랙, 실거래 중위 표본에서 제외
    import importlib, sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parents[1] / "scripts"))
    B = importlib.import_module("build_site")
    d = Signal(title="서울 아파트 매매가격지수 +1.06%", source="부동산원",
               category="price", metric="매매가격지수 변동률", value=1.06, unit="%")
    assert d.kind == "data"
    assert B.parse_sale_prices(d) == []     # 지수는 매매 표본이 아니다
    # 일반 뉴스는 news, 실거래가는 표본으로 잡힘
    n = Signal(title="잠실엘스 84㎡ 28.5억 실거래", source="RTMS", category="price")
    assert n.kind == "news"
    assert 28.5 in B.parse_sale_prices(n)


def test_segment_bands_roundtrip():
    # 가격대·면적대 밴드 + 평당가·세대수가 적재 왕복에서 보존
    s = Signal.from_dict({"kind": "data", "title": "서울 60-85㎡ 매매변동률", "source": "부동산원",
                          "category": "price", "metric": "매매가격지수 변동률", "value": 0.8, "unit": "%",
                          "sido": "서울", "area_band": "60-85", "price_band": "9-15",
                          "pyeong_price": 6350, "households": 1140})
    d = s.to_dict()
    assert s.kind == "data" and d["area_band"] == "60-85" and d["price_band"] == "9-15"
    assert d["pyeong_price"] == 6350.0 and d["households"] == 1140


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


def test_region_detection_deterministic():
    """지역 태깅은 PYTHONHASHSEED 와 무관하게 같은 결과를 내야 한다.

    회귀 배경: detect_regions 가 매칭 구를 set 에 담고 list(set) 로 꺼내
    region[0] 이 문자열 해시 순서에 좌우됐다. 동일 입력 재빌드에서 66건의
    gu 가 바뀌어, 지역 드릴다운 카운트·지도 마커가 빌드마다 흔들렸다.

    해시 랜덤화는 프로세스마다 한 번 정해지므로 같은 프로세스 안에서 반복 호출해도
    잡히지 않는다. PYTHONHASHSEED 를 달리한 서브프로세스로 비교해야 한다.
    """
    src = str(Path(__file__).resolve().parents[1] / "src")
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from apthub import filters\n"
        "ts = ['평택 고덕동 파라곤 전용 42평 13억 신고가',\n"
        "      '고양 일산서구 평당가 — 2026년 시세 추적',\n"
        "      \"동작구 흑석·노량진, 동작 대장 입지 경쟁 부각\",\n"
        "      '동탄·용인 주택 수요 자극 반도체 머니']\n"
        "print([filters.detect_regions(t) for t in ts])\n" % src
    )
    outs = set()
    for seed in ("0", "1", "42", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outs.add(subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True, check=True).stdout)
    assert len(outs) == 1, f"해시시드에 따라 지역 태깅이 달라짐: {outs}"


def test_region_detection_prefers_subject():
    """본문에 먼저 나온(=제목의) 지명이 대표 지역이 된다.

    _text 는 "제목\\n요약" 순서라 위치가 작을수록 기사 주제에 가깝다.
    '평택 고덕동'이 서울 강동구로, '고양 일산서구'가 인천 서구로 가던 오태깅을 막는다.
    """
    sido, regions = filters.detect_regions("평택 고덕동 파라곤 전용 42평 13억 신고가")
    assert sido == "경기" and regions[0] == "평택시"

    sido, regions = filters.detect_regions("고양 일산서구 평당가 — 2026년 시세 추적")
    assert sido == "경기" and regions[0] == "고양시"

    sido, regions = filters.detect_regions("동작구 흑석·노량진, 동작 대장 입지 경쟁 부각")
    assert sido == "서울" and regions[0] == "동작구"


# --- normalize_signals (scripts/build_site.py) -------------------------------
# 데이터 정합성의 핵심인데 커버리지가 0이었다. 전수 점검에서 드러난 오염
# (1분위 혼입·개별 주택형 혼입·단위 표기 불일치)을 회귀로 고정한다.

def _build_site():
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("bs", root / "scripts" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _data_sig(**kw):
    kw.setdefault("source", "KB")
    kw.setdefault("url", "https://kbland.kr/x")
    kw.setdefault("summary", "")
    s = Signal(**{k: v for k, v in kw.items()
                  if k in ("title", "summary", "source", "url")})
    s.kind = "data"
    for f in ("metric", "value", "unit", "sido", "date"):
        if f in kw:
            setattr(s, f, kw[f])
    return s


def test_normalize_blocks_quintile1_in_quintile5_metric():
    """'5분위 평균매매가'에 1분위(하위 20%) 수치가 섞이면 시계열이 톱니가 된다.

    실측: 서울이 34.38 → 4.99 → 34.66 → 5.01 → 34.71 로 스파크라인이 거짓이었다.
    """
    bs = _build_site()
    pure1 = _data_sig(title="서울 아파트 1분위 평균 매매가 4.99억 (2025-12·KB)",
                      metric="5분위 평균매매가", value=4.99, unit="억",
                      sido="서울", date="2025-12-31")
    both = _data_sig(title="서울 아파트 5분위 평균 34.38억·1분위 4.99억 (2025-12·KB)",
                     metric="5분위 평균매매가", value=34.38, unit="억",
                     sido="서울", date="2025-12-31")
    bs.normalize_signals([pure1, both])
    assert pure1.kind == "news", "1분위 단독 수치는 지표에서 빠져야 한다"
    assert both.kind == "data", "5분위 값을 실은 기사는 유지돼야 한다"


def test_normalize_blocks_single_unit_subscription_rate():
    """청약경쟁률은 지역 1순위 평균만 지표. 개별 주택형은 뉴스로.

    실측: 서울 최신값이 '오티에르반포 59㎡B 1,180.9대1'로 잡혀 지역 평균처럼 보였다.
    요약에 '1순위'가 들어 있어 txt 검사만으로는 걸러지지 않으므로 제목의 ㎡로 판별한다.
    """
    bs = _build_site()
    one = _data_sig(title="서울 오티에르반포 59㎡B 청약 1,180.9대1 (2026-06·청약Home)",
                    summary="서초 잠원동 전용 59㎡B 1순위 청약경쟁률 1,180.87대1",
                    metric="청약경쟁률", value=1180.87, unit="대1",
                    sido="서울", date="2026-06-11")
    avg = _data_sig(title="서울 아파트 1순위 청약경쟁률 153대1 (2026-05)",
                    metric="청약경쟁률", value=153.0, unit="대1",
                    sido="서울", date="2026-05-31")
    bs.normalize_signals([one, avg])
    assert one.kind == "news", "개별 주택형 경쟁률은 지표에서 빠져야 한다"
    assert avg.kind == "data", "지역 1순위 평균은 유지돼야 한다"


def test_normalize_unifies_units():
    """같은 지표에 '대 1'/'대1', '억'/'억원', ''/'p'/'지수'가 섞여 라벨이 들쭉날쭉했다."""
    bs = _build_site()
    sigs = [
        _data_sig(title="서울 아파트 1순위 청약경쟁률 153대 1", metric="청약경쟁률",
                  value=153.0, unit="대 1", sido="서울", date="2026-06-19"),
        _data_sig(title="전국 아파트 5분위 평균매매가 15.45억원", metric="5분위 평균매매가",
                  value=15.45, unit="억원", sido="전국", date="2026-05-31"),
        _data_sig(title="서울 매매전망지수 135.6", metric="매매전망지수",
                  value=135.6, unit="지수", sido="서울", date="2026-06-15"),
        _data_sig(title="서울 매수우위지수 46", metric="매수우위지수",
                  value=46.0, unit="", sido="서울", date="2026-06-01"),
    ]
    bs.normalize_signals(sigs)
    assert [s.unit for s in sigs] == ["대1", "억", "p", "p"]


def test_normalize_keeps_existing_guards():
    """기존 가드(입주물량 반기 강등·분양가 단위 이상치·매수우위지수 범위)가 유지되는지."""
    bs = _build_site()
    half = _data_sig(title="서울 입주물량 상반기 6,145호", metric="입주물량",
                     value=6145, unit="가구", sido="서울", date="2026-06-30")
    bogus = _data_sig(title="분양가 9,500만원", metric="분양가",
                      value=9500, unit="만원", sido="서울", date="2026-05-31")
    oor = _data_sig(title="매수우위지수 420", metric="매수우위지수",
                    value=420.0, unit="p", sido="서울", date="2026-05-31")
    bs.normalize_signals([half, bogus, oor])
    assert half.kind == "news" and bogus.kind == "news" and oor.kind == "news"
