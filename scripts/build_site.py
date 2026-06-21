#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""정적 사이트 생성기 — data/seed/*.json → site/index.html(+ 레포 루트 index.html).

UI: 좌측 지역 드릴다운 메뉴 · 상단 검색/정렬/필터 · 중앙 카드 리스트 · 지도(Leaflet).
데이터(시그널/지역집계)를 인라인 JSON으로 임베드하고 클라이언트에서 동적 렌더링.
APTHUB_PUBLIC=1 이면 개인(정훈) 보조 탭 제외.

실행: python3 scripts/build_site.py
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
BUILD_DATA = ROOT / ".build_data"
SITE = ROOT / "site"
PUBLIC_ONLY = os.environ.get("APTHUB_PUBLIC") == "1"

shutil.rmtree(BUILD_DATA, ignore_errors=True)
os.environ["APTHUB_DATA_DIR"] = str(BUILD_DATA)
sys.path.insert(0, str(ROOT / "src"))

from apthub import config, manual, store  # noqa: E402

SIDO_ORDER = ["서울", "경기", "인천", "전국"]
CAT_LABEL = {"policy": "정책·세제", "price": "시세·실거래", "macro": "금리·거시", "semicon": "반도체"}

TRUST = {
    "공식": ["data.go.kr", "ecos.bok.or.kr", "opendart.fss.or.kr", "dart.fss.or.kr",
             "fss.or.kr", "reb.or.kr", "rt.molit.go.kr", "molit.go.kr", "korea.kr",
             "fsc.go.kr", "moef.go.kr", "nts.go.kr", "bok.or.kr", "myhome.go.kr",
             "applyhome.co.kr", "seoul.go.kr", "assembly.go.kr", "news.skhynix.co.kr",
             "kbland.kr", "kbstar.com", "nanet.go.kr"],
    "언론": ["hankyung.com", "mk.co.kr", "edaily.co.kr", "heraldcorp.com", "thelec.kr",
             "esgeconomy.com", "fnnews.com", "newsis.com", "asiatime.co.kr", "mt.co.kr",
             "housingherald.co.kr", "kukinews.com", "etoday.co.kr", "viva100.com",
             "dataeconomy.co.kr", "rcast.co.kr", "conslove.co.kr", "karnews.or.kr",
             "youthassembly.kr", "mygoyang.com", "news1.kr", "newdaily.co.kr",
             "choicestock.co.kr", "incheonin.com", "news-wa.com", "mstoday.co.kr",
             "seouleconews.com", "tradingeconomics.com", "kfenews.co.kr"],
}


def confidence_of(url: str, given: str = "") -> str:
    if given:
        for k in ("공식", "언론", "추정"):
            if k in given:
                return k
    host = ""
    if url:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    for tier, domains in TRUST.items():
        if any(d in host for d in domains):
            return tier
    return "추정"


# 수도권 시군구 중심 좌표 (지도 마커용, 근사치)
COORDS = {
    "서울": {
        "강남구": [37.495, 127.063], "서초구": [37.484, 127.033], "송파구": [37.505, 127.115],
        "강동구": [37.530, 127.124], "용산구": [37.532, 126.990], "마포구": [37.566, 126.901],
        "성동구": [37.563, 127.037], "광진구": [37.538, 127.082], "영등포구": [37.526, 126.896],
        "동작구": [37.512, 126.939], "양천구": [37.517, 126.866], "강서구": [37.551, 126.850],
        "구로구": [37.495, 126.887], "금천구": [37.457, 126.895], "관악구": [37.478, 126.951],
        "동대문구": [37.574, 127.040], "중랑구": [37.606, 127.092], "성북구": [37.589, 127.016],
        "강북구": [37.640, 127.011], "도봉구": [37.668, 127.047], "노원구": [37.654, 127.056],
        "은평구": [37.603, 126.929], "서대문구": [37.579, 126.937], "종로구": [37.573, 126.979],
        "중구": [37.564, 126.997],
    },
    "경기": {
        "성남시": [37.420, 127.127], "과천시": [37.429, 126.988], "하남시": [37.539, 127.215],
        "광명시": [37.479, 126.865], "수원시": [37.263, 127.029], "용인시": [37.241, 127.178],
        "안양시": [37.394, 126.957], "고양시": [37.658, 126.832], "남양주시": [37.636, 127.216],
        "화성시": [37.199, 126.831], "부천시": [37.504, 126.766], "의왕시": [37.345, 126.968],
        "군포시": [37.361, 126.935], "김포시": [37.615, 126.715], "구리시": [37.594, 127.130],
        "시흥시": [37.380, 126.803], "평택시": [36.992, 127.113], "안산시": [37.322, 126.831],
    },
    "인천": {
        "서구": [37.545, 126.676], "연수구": [37.410, 126.678], "남동구": [37.447, 126.731],
        "부평구": [37.507, 126.722], "계양구": [37.537, 126.738], "미추홀구": [37.464, 126.650],
        "중구": [37.474, 126.622], "동구": [37.474, 126.643],
    },
}

PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*억")
AREA_PRICE_RE = re.compile(r"㎡[^0-9]{0,7}(\d+(?:\.\d+)?)\s*억")
DELTA_KW = ("대비", "상승", "하락", "올라", "내려", "오른", "내린", "뛰", "급등", "급락", "연속")
PRICE_MIN, PRICE_MAX = 3.0, 200.0   # 수도권 아파트 현실 범위(억) — 초고가 한강변 포함


def parse_sale_prices(sig) -> list[float]:
    if sig.category != "price":
        return []
    if ("전세" in sig.title or "월세" in sig.title) and "매매" not in sig.title:
        return []
    text = sig.title + " " + sig.summary
    anchored = [float(m) for m in AREA_PRICE_RE.findall(text)]      # ㎡ 뒤 가격(신뢰)
    anchored = [v for v in anchored if PRICE_MIN <= v <= PRICE_MAX]
    if anchored:
        return anchored
    for m in PRICE_RE.finditer(text):                              # 폴백: 첫 비-델타 토큰
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if not (PRICE_MIN <= v <= PRICE_MAX):
            continue
        pre = text[max(0, m.start() - 6):m.start()]
        if any(k in pre for k in DELTA_KW):                        # '대비 13억 상승' 델타 배제
            continue
        return [v]
    return []


TOPIC_KEYS = ("zone", "tax", "loan", "supply", "rate", "market")


def topic_of(sig) -> str | None:
    if sig.category == "semicon":
        return None
    t = (sig.title + " " + sig.summary).lower()

    def has(*ws):
        return any(w.lower() in t for w in ws)

    if has("토지거래", "토허", "투기과열", "조정대상", "규제지역"):
        return "zone"
    if has("취득세", "양도세", "종부세", "증여", "비과세", "세제"):
        return "tax"
    if has("dsr", "ltv", "주담대", "생애최초", "디딤돌", "보금자리", "신생아", "대출"):
        return "loan"
    if has("공급", "입주", "분양", "택지", "재건축", "정비", "노후계획도시",
           "스타필드", "cj", "착공", "gtx", "급행", "홍대선", "예타", "청약", "개발"):
        return "supply"
    if has("기준금리", "금통위", "코픽스", "금리", "전세", "통화", "한국은행"):
        return "rate"
    if sig.category == "macro":
        return "rate"
    return "market"


def load_all():
    for f in sorted((ROOT / "data" / "seed").glob("*.json")):
        manual.ingest_json(f.read_text(encoding="utf-8"), by_date=True)
    seen, sigs = set(), []
    for day in store.all_days():
        for s in store.load_day(day):
            if s.id in seen:        # 교차일 중복 제거(같은 id가 여러 날짜 파일에)
                continue
            seen.add(s.id)
            sigs.append(s)
    rank = {"red": 0, "yellow": 1, "none": 2}
    sigs.sort(key=lambda s: (s.date or "", rank.get(s.trigger, 2)), reverse=True)
    return sigs


def client_signal(s) -> dict:
    prices = parse_sale_prices(s)
    return {
        "date": s.date or "",
        "title": s.title, "summary": s.summary, "source": s.source, "url": s.url,
        "cat": s.category or "", "sido": (s.sido or "전국"),
        "gu": (s.region[0] if s.region else ""),
        "trig": s.trigger, "conf": confidence_of(s.url, s.confidence),
        "comment": s.comment, "topic": (topic_of(s) or ""),
        "price": (round(median(prices), 1) if prices else None),
    }


def region_agg(sigs) -> list[dict]:
    by: dict[tuple, dict] = {}
    for s in sigs:
        if not s.region:
            continue
        sido = s.sido or "전국"
        if sido == "전국":
            continue
        key = (sido, s.region[0])
        d = by.setdefault(key, {"n": 0, "prices": [], "red": 0})
        d["n"] += 1
        d["prices"] += parse_sale_prices(s)
        if s.trigger == "red":
            d["red"] += 1
    out = []
    for (sido, gu), v in by.items():
        c = COORDS.get(sido, {}).get(gu)
        med = round(median(v["prices"]), 1) if len(v["prices"]) >= 3 else None
        out.append({"sido": sido, "gu": gu, "n": v["n"], "red": v["red"], "med": med,
                    "lat": (c[0] if c else None), "lng": (c[1] if c else None)})
    return out


def personal_html(sigs) -> str:
    if PUBLIC_ONLY:
        return ""
    ceil = config.ceilings_text()
    blocks = [
        ("매수 타이밍 2안", ["<b>8월(희망#1)</b> 천장 ~8.5억 · 희주 단독 생애최초 LTV70%",
                         "<b>27.2(희망#2)</b> 천장 ~10.5억 · 성과급(PS) 보강 후",
                         "가격상승 vs 자기자본증가 트레이드오프"]),
        ("자기자본 조달", ["대출 <b>6억 상한</b> 고정 → 8.5억 매수 시 갭 2.5억",
                       "PS 26.2 세전 ~1.48억 + 증여 양가 최대 3억 무세",
                       "검단 보유분 가치상승이 점프 자기자본에 기여"]),
        ("후보 단지", ["<b>천장 내</b> 가양·발산·염창·우장산 구축 59㎡",
                    "<b>관찰</b> 등촌주공3·5·마곡(천장 초과)",
                    "토허 실거주 의무=실거주 계획과 일치"]),
        ("27.2 업사이드", ["하이닉스 2026 영업이익 <b>250조+</b> 전망",
                        "27.2 PS 1인 수억 → 천장 10.5억은 보수적일 수",
                        "8월 vs 27.2 = 금리·PS·천장 3박자 비교"]),
    ]
    cards = ""
    for t, items in blocks:
        lis = "".join(f"<li>{x}</li>" for x in items)
        cards += f'<div class="dcard"><h4>{t}</h4><ul>{lis}</ul></div>'
    impls = ""
    for s in sigs:
        if s.implication:
            impls += (f'<li><span class="d">{html.escape(s.date or "")}</span>'
                      f'<b>{html.escape(s.title)}</b> — {html.escape(s.implication)}</li>')
    return (f'<div class="lead">천장 {html.escape(ceil)} · 희주 단독 생애최초</div>'
            f'<div class="dgrid">{cards}</div>'
            f'<h3 class="sub">전체 함의</h3><ul class="impls">{impls}</ul>')


def frames_html() -> str:
    path = ROOT / "config" / "budreadnam-frames.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = f'<div class="lead">{html.escape(data["source"])}</div>'
    for th in data["themes"]:
        prins = "".join(f"<li>{html.escape(p)}</li>" for p in th["principles"])
        out += (f'<article class="frame"><div class="lec">{html.escape(th["lectures"])}</div>'
                f'<h3>{html.escape(th["title"])}</h3><ul>{prins}</ul>'
                f'<p class="cmt"><b>2026</b> {html.escape(th["note2026"])}</p></article>')
    return out


def _sido_median(sigs, sido) -> str:
    ps = []
    for s in sigs:
        if (s.sido or "전국") == sido:
            ps += parse_sale_prices(s)
    return f"{round(median(ps), 1)}" if ps else "—"


def report_html(sigs, stats) -> str:
    path = ROOT / "config" / "report.json"
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8")
    for k, v in stats.items():
        raw = raw.replace("{" + k + "}", str(v))
    rep = json.loads(raw)
    out = (f'<div class="rep-head"><h2>{html.escape(rep["title"])}</h2>'
           f'<div class="asof">{rep["asof"]}</div></div>')
    out += (
      '<details class="guide"><summary>📖 사용설명서</summary>'
      '<ul>'
      '<li><b>종합 동향</b> — 기사·실거래를 요약·분석한 흐름 브리핑(현재 화면)</li>'
      '<li><b>월별 정리</b> — 월 단위 시그널 묶음·트리거 집계와 전월 대비 증감 흐름</li>'
      '<li><b>지역별 보기</b> — 좌측 메뉴/지도에서 시·도·구 선택, 상단 칩으로 분류·트리거 필터, 검색창으로 단지·키워드 조회</li>'
      '<li><b>트리거</b> — <span class="lr">🔴 즉시</span>: 발견 즉시 주목 사안 · <span class="ly">🟡 주목</span>: 주간 점검 사안</li>'
      '<li><b>출처</b> — 공식(정부·기관) · 언론 · 추정 순의 신뢰도 표기</li>'
      '<li><b>상단 제목(APT-SIGNAL) 클릭</b> — 종합 동향 첫 화면으로 복귀</li>'
      '<li><b>참고용</b> — 매수·매도 판단의 보조 자료, 투자 권유 아님</li>'
      '</ul></details>')
    for sec in rep["sections"]:
        when = f'<span class="when">{html.escape(sec["when"])}</span>' if sec.get("when") else ""
        out += f'<section class="rsec"><h3>{html.escape(sec["h"])}{when}</h3>'
        t = sec.get("type", "para")
        if t == "table":
            cols = "".join(f"<th>{html.escape(c)}</th>" for c in sec["columns"])
            body = ""
            for row in sec["rows"]:
                body += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
            out += (f'<div class="tw"><table class="rt"><thead><tr>{cols}</tr></thead>'
                    f'<tbody>{body}</tbody></table></div>')
        elif t == "bullets":
            out += "<ul>" + "".join(f"<li>{it}</li>" for it in sec["items"]) + "</ul>"
        else:
            out += "".join(f'<p class="rp">{it}</p>' for it in sec["items"])
        out += "</section>"
    out += f'<p class="rdisc">{html.escape(rep.get("disclaimer", ""))}</p>'
    return out


def build():
    sigs = load_all()
    reds = sum(1 for s in sigs if s.trigger == "red")
    yellows = sum(1 for s in sigs if s.trigger == "yellow")
    data = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(sigs), "reds": reds, "yellows": yellows,
        "public": PUBLIC_ONLY,
        "sig": [client_signal(s) for s in sigs],
        "regions": region_agg(sigs),
    }
    dates = sorted(s.date for s in sigs if s.date)
    def _ym(d):
        return f"{d[:4]}.{int(d[5:7])}" if d else ""
    # 기준 기간: 초기 희소 표본(아웃라이어)을 제외하고 최근 시그널 95%가 들어오는
    # 핵심 구간만 표기 — 2024~2026 같은 과대 기간으로 추세가 묻히는 것 방지
    period = ""
    if dates:
        cut = int(len(dates) * 0.05)              # 앞쪽 5% 절단
        core = dates[cut:] or dates
        period = f"{_ym(core[0])}~{_ym(dates[-1])}"
    stats = {
        "total": len(sigs), "reds": reds, "yellows": yellows,
        "updated": data["updated"], "period": period,
        "seoul_med": _sido_median(sigs, "서울"),
        "gg_med": _sido_median(sigs, "경기"),
        "ic_med": _sido_median(sigs, "인천"),
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    doc = (TEMPLATE
           .replace("__DATA__", blob)
           .replace("__REPORT__", report_html(sigs, stats))
           .replace("__PERSONAL__", personal_html(sigs))
           .replace("__FRAMES__", frames_html())
           .replace("__PUBLIC__", "1" if PUBLIC_ONLY else "0"))
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(doc, encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    (ROOT / "index.html").write_text(doc, encoding="utf-8")
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"index.html 생성(site/ + 루트): 시그널 {len(sigs)}건 (🔴{reds} 🟡{yellows}) "
          f"· {'공개판매' if PUBLIC_ONLY else '개인 포함'}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>APT-SIGNAL · 수도권 부동산 동향</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<style>
  :root{
    --bg:#eef0f4;--surface:#fff;--navy:#1e2d44;--navy2:#33445f;--accent:#2f5d8a;
    --muted:#5f6873;--border:#e2e5ea;--red:#b8403d;--redbg:#f7ebeb;--amber:#876419;
    --amberbg:#f7f1e0;--radius:12px;--shadow:0 1px 3px rgba(20,30,50,.06),0 4px 16px rgba(20,30,50,.04);
    --side:240px;
  }
  *{box-sizing:border-box}html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--navy);font-size:14px;line-height:1.55;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}
  a{color:inherit}
  /* 헤더 */
  header{position:fixed;top:0;left:0;right:0;height:56px;background:var(--navy);color:#fff;
    display:flex;align-items:center;gap:12px;padding:0 16px;z-index:1000}
  header h1{font-size:16px;margin:0;letter-spacing:.2px;font-weight:700;white-space:nowrap}
  header .tag{font-size:12px;color:#c2cee0;white-space:nowrap}
  header .stat{font-size:12px;color:#cdd6e4;margin-left:6px}
  #q{flex:1;max-width:520px;margin-left:auto;border:none;border-radius:999px;padding:9px 14px;font-size:13px;font-family:inherit;outline:none}
  #burger{display:none;background:none;border:none;color:#fff;font-size:20px;cursor:pointer;padding:4px}
  /* 좌측 메뉴 */
  aside{position:fixed;top:56px;bottom:0;left:0;width:var(--side);background:var(--surface);
    border-right:1px solid var(--border);overflow-y:auto;padding:10px 0;z-index:900}
  .navsec{padding:6px 12px}
  .navttl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin:8px 6px 4px}
  .navitem{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:13.5px;color:var(--navy2)}
  .navitem:hover{background:#f2f4f7}
  .navitem.on{background:var(--navy);color:#fff}
  .navitem .c{font-size:11px;color:var(--muted)}
  .navitem.on .c{color:#b9c4d6}
  .gu{padding-left:22px;font-size:13px}
  .gu.hidden{display:none}
  .caret{display:inline-block;width:14px;color:var(--muted);transition:transform .15s}
  .caret.open{transform:rotate(90deg)}
  /* 본문 */
  main{margin-left:var(--side);margin-top:56px;padding:14px 16px 60px;max-width:1100px}
  .toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
  .chip{border:1px solid var(--border);background:var(--surface);color:var(--navy2);border-radius:999px;
    padding:6px 12px;font-size:12.5px;cursor:pointer;font-family:inherit}
  .chip.on{background:var(--navy);color:#fff;border-color:var(--navy)}
  .chip em{font-style:normal;color:var(--muted);margin-left:3px}.chip.on em{color:#b9c4d6}
  select{border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12.5px;font-family:inherit;background:var(--surface)}
  .crumb{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:2px 2px 12px}
  .crumb .cp{display:inline-flex;align-items:center;gap:5px;font-size:12px;border-radius:999px;
    padding:4px 11px;background:var(--surface);border:1px solid var(--border);color:var(--navy2)}
  .crumb .cp.loc{background:var(--navy);color:#fff;border-color:var(--navy);font-weight:600}
  .crumb .cp.loc i{color:#b9c4d6;font-style:normal;font-weight:400}
  .crumb .cp.n{font-variant-numeric:tabular-nums}.crumb .cp.n b{color:var(--navy)}
  .crumb .cp.red{background:var(--redbg);color:var(--red);border-color:#f3d4d4}
  .crumb .cp.yellow{background:var(--amberbg);color:var(--amber);border-color:#f0e4c4}
  .crumb .creset{display:inline-flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;
    border-radius:999px;padding:4px 11px;background:#fff;border:1px solid var(--border);color:var(--muted);font-family:inherit}
  .crumb .creset:hover{border-color:var(--accent);color:var(--accent)}
  #map{height:340px;border-radius:var(--radius);border:1px solid var(--border);margin-bottom:14px;background:#dde3ea}
  .maphint{font-size:11px;color:var(--muted);margin:-10px 2px 12px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:13px 15px 11px;margin-bottom:9px;box-shadow:var(--shadow)}
  .meta{display:flex;align-items:center;gap:7px;margin-bottom:3px;flex-wrap:wrap}
  .date{color:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}
  .loc{font-size:11px;color:var(--accent);background:#eef2f7;border-radius:5px;padding:1px 7px;cursor:pointer}
  .conf{font-size:11px;border-radius:5px;padding:1px 6px}
  .conf.공식{color:#2e7d52;background:#eaf3ee}.conf.언론{color:#9a6b3a;background:#f3eee9}.conf.추정{color:var(--muted);background:#f0f1f3}
  .bd{font-size:11px;padding:1px 7px;border-radius:5px;font-weight:600}
  .bd.red{background:var(--redbg);color:var(--red)}.bd.yellow{background:var(--amberbg);color:var(--amber)}
  .pr{font-size:11px;color:#2e7d52;font-weight:600;font-variant-numeric:tabular-nums}
  .card h3{margin:2px 0 5px;font-size:15px;line-height:1.4;letter-spacing:-.2px}
  .sum{margin:0 0 7px;color:var(--navy2);font-size:13.5px}
  .cmt{margin:0 0 7px;padding:7px 11px;background:#f3f6f4;border-left:3px solid #4e8a6a;border-radius:0 7px 7px 0;font-size:12.5px;color:var(--navy2)}
  .cmt b{color:#3a6b51;margin-right:5px;font-size:11px}
  .impl{margin:0 0 7px;padding:7px 11px;background:#f6f8fb;border-left:3px solid var(--accent);border-radius:0 7px 7px 0;font-size:12.5px}
  .impl b{color:var(--accent);margin-right:5px;font-size:11px}
  .foot{display:flex;justify-content:flex-end}.src{color:var(--muted);font-size:11.5px;text-decoration:none}.src:hover{color:var(--accent)}
  .empty{text-align:center;color:var(--muted);padding:40px 0}
  /* 패널(부읽남/개인) */
  .panel{display:none}.panel.on{display:block}
  /* 동향 리포트 */
  .rep-head{margin:2px 2px 14px}
  .rep-head h2{margin:0 0 4px;font-size:20px;letter-spacing:-.4px}
  .rep-head .asof{font-size:12px;color:var(--muted)}
  .guide{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:2px 16px;margin-bottom:11px;box-shadow:var(--shadow)}
  .guide summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--accent);padding:11px 0;list-style:none}
  .guide summary::-webkit-details-marker{display:none}
  .guide summary::after{content:"▸";float:right;color:var(--muted);transition:transform .15s;display:inline-block}
  .guide[open] summary::after{transform:rotate(90deg)}
  .guide[open] summary{border-bottom:1px solid var(--border)}
  .guide ul{margin:10px 0 12px;padding-left:18px}
  .guide li{font-size:12.5px;color:var(--navy2);padding:3px 0;line-height:1.55}
  .guide b{color:var(--navy)}
  .rsec{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:14px 17px;margin-bottom:11px;box-shadow:var(--shadow)}
  .rsec h3{margin:0 0 9px;font-size:15.5px;color:var(--accent);letter-spacing:-.2px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
  .rsec h3 .when{font-size:11px;font-weight:400;color:var(--muted)}
  .tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
  table.rt{border-collapse:collapse;width:100%;font-size:12.5px;min-width:0}
  table.rt th{background:#f4f6f9;color:var(--navy2);text-align:left;padding:7px 10px;border-bottom:1px solid var(--border);white-space:nowrap;font-size:11.5px}
  table.rt td{padding:7px 10px;border-bottom:1px solid #f0f2f5;color:var(--navy2);vertical-align:top}
  table.rt td:first-child{white-space:nowrap;font-weight:600;color:var(--navy)}
  table.rt tr:last-child td{border-bottom:none}
  table.rt b{color:var(--navy)}
  .rsec ul{margin:0;padding-left:18px}
  .rsec li{font-size:13.5px;color:var(--navy2);padding:3px 0;line-height:1.6}
  .rsec .rp{margin:0 0 8px;font-size:13.5px;color:var(--navy2);line-height:1.65}
  .rsec .rp:last-child{margin-bottom:0}
  .rsec b{color:var(--navy)}
  .rdisc{font-size:11px;color:var(--muted);margin:6px 2px 0;line-height:1.5}
  /* 월별 정리 */
  .lgd{font-size:11px;color:var(--muted)}
  .lr{color:var(--red);font-weight:600}.ly{color:var(--amber);font-weight:600}
  .wk{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 15px;margin-bottom:9px;box-shadow:var(--shadow)}
  .wkh{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
  .wwk{display:inline-flex;align-items:center;font-size:12px;font-weight:700;letter-spacing:.2px;
    color:#fff;background:var(--navy);border-radius:7px;padding:3px 10px;font-variant-numeric:tabular-nums}
  .wkh .up{font-size:11px;font-weight:700;color:var(--accent)}
  .wkh .dn{font-size:11px;font-weight:700;color:var(--muted)}
  .wkh .eq{font-size:11px;color:var(--muted)}
  .wkh b{font-size:13.5px;font-variant-numeric:tabular-nums;font-weight:600}
  .wkn{font-size:11.5px;color:var(--muted);margin-left:auto}
  .bar{height:6px;border-radius:4px;background:#eef1f5;margin:8px 0 2px;overflow:hidden}
  .bar span{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--navy));border-radius:4px}
  .wkc{margin:7px 0 2px;display:flex;flex-wrap:wrap;gap:5px}
  .wcat{font-size:11px;color:var(--navy2);background:#eef1f5;border-radius:6px;padding:2px 8px}
  .wkl{list-style:none;margin:7px 0 0;padding:0}
  .wkl li{font-size:12.5px;color:var(--navy2);padding:4px 0;border-top:1px solid #f3f5f7;line-height:1.5}
  .wkl li:first-child{border-top:none}
  .wkl .d{color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums;margin-right:3px}
  .wkl .wb{font-size:10px;margin-right:3px}
  .wkl .loc2{font-size:10.5px;color:var(--accent);background:#eef2f7;border-radius:4px;padding:0 5px}
  .wkl .more{color:var(--muted);font-style:italic}
  .wkempty{font-size:12px;color:var(--muted);margin-top:6px}
  .ftr{margin-top:24px;padding-top:14px;border-top:1px solid var(--border);text-align:center;font-size:11.5px;color:var(--muted);line-height:1.7}
  .ftr a{color:var(--accent);text-decoration:none}.ftr b{color:var(--navy2)}
  @media(min-width:721px){.rsec{padding:16px 20px}}
  .lead{font-size:12.5px;color:var(--muted);margin:4px 2px 12px}
  .dgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:11px}
  @media(max-width:620px){.dgrid{grid-template-columns:1fr}}
  .dcard{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:13px 15px;box-shadow:var(--shadow)}
  .dcard h4{margin:0 0 7px;font-size:12.5px;color:var(--accent)}.dcard ul{margin:0;padding:0;list-style:none}
  .dcard li{font-size:12.5px;color:var(--navy2);padding:3px 0}.dcard li+li{border-top:1px solid #f0f2f5}.dcard b{color:var(--navy)}
  .impls{list-style:none;padding:0;margin:8px 0 0}.impls li{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:9px 11px;margin-bottom:7px;font-size:12.5px;color:var(--navy2)}
  .impls .d{color:var(--muted);margin-right:6px;font-size:11px}.impls b{color:var(--navy)}
  .sub{font-size:14px;margin:16px 2px 8px}
  .frame{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:13px 15px;margin-bottom:9px;box-shadow:var(--shadow)}
  .frame .lec{font-size:11px;color:var(--accent)}.frame h3{margin:3px 0 7px;font-size:15px}.frame ul{margin:0 0 7px;padding-left:17px}.frame li{font-size:12.5px;color:var(--navy2)}
  .frame .cmt b{font-size:11px}
  .backdrop{display:none}
  @media(max-width:820px){
    aside{transform:translateX(-100%);transition:transform .2s;box-shadow:0 0 40px rgba(0,0,0,.2)}
    aside.open{transform:none}
    main{margin-left:0;padding:12px 12px 60px}
    #burger{display:block}
    .backdrop.on{display:block;position:fixed;inset:56px 0 0 0;background:rgba(0,0,0,.3);z-index:850}
  }
  @media(max-width:560px){
    header{gap:8px;padding:0 10px}
    header h1{font-size:15px}
    .stat,.tag{display:none}
    #q{margin-left:0;min-width:0}
    .rep-head h2{font-size:17px}
    #map{height:260px}
    .toolbar{gap:6px}
  }
</style>
</head>
<body>
<header>
  <button id="burger" aria-label="메뉴 열기" aria-expanded="false" aria-controls="side">☰</button>
  <h1 id="brand" title="처음으로" role="button" tabindex="0">APT-SIGNAL</h1>
  <span class="tag">수도권 부동산 동향</span>
  <span class="stat" id="hstat"></span>
  <input id="q" type="search" aria-label="단지·지역·키워드 검색" placeholder="🔍 검색 — 단지·지역·키워드">
</header>
<div class="backdrop" id="backdrop"></div>
<aside id="side"></aside>
<main>
  <div class="crumb" id="crumb"></div>
  <div class="panel" id="view-report">__REPORT__</div>
  <div class="panel" id="view-monthly"></div>
  <div id="view-list" style="display:none">
    <div id="map"></div>
    <div class="maphint" id="maphint">지도 마커: 시군구별 시그널(크기=건수, 색=매매중위). 클릭 시 해당 지역만.</div>
    <div class="toolbar">
      <button class="chip on" data-cat="">전체</button>
      <button class="chip" data-cat="policy">정책·세제</button>
      <button class="chip" data-cat="price">시세·실거래</button>
      <button class="chip" data-cat="macro">금리·거시</button>
      <button class="chip" data-cat="semicon">반도체</button>
      <button class="chip tg" data-trig="red">🔴</button>
      <button class="chip tg" data-trig="yellow">🟡</button>
      <select id="sort">
        <option value="date_desc">최신순</option>
        <option value="date_asc">오래된순</option>
        <option value="price_desc">매매가 높은순</option>
        <option value="price_asc">매매가 낮은순</option>
        <option value="region">지역순</option>
      </select>
    </div>
    <div id="list"></div>
    <div class="empty" id="empty" style="display:none">조건에 맞는 시그널이 없습니다.</div>
  </div>
  <div class="panel" id="view-frames">__FRAMES__</div>
  <div class="panel" id="view-personal">__PERSONAL__</div>
  <footer class="ftr">APT-SIGNAL · 수도권 부동산 정책·시장 동향 — 공개 기사·실거래 시그널 요약·분석(참고용)<br>
    제작·문의 <b>이정훈</b> · <a href="mailto:piko9388@gmail.com">piko9388@gmail.com</a></footer>
</main>

<script>
var DATA = __DATA__;
var PUBLIC = "__PUBLIC__" === "1";
var SIG = DATA.sig, REG = DATA.regions;
var S = {view:"report", sido:null, gu:null, cat:"", trig:null, q:"", sort:"date_desc"};
var CAT={policy:"정책·세제",price:"시세·실거래",macro:"금리·거시",semicon:"반도체"};
var CONF={"공식":"● 공식","언론":"◐ 언론","추정":"○ 추정"};
function esc(s){return (s||"").replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
function priceBand(m){return m==null?"#9aa3ad":m<8?"#2e8b57":m<12?"#2f5d8a":m<20?"#c8860b":"#c0504d";}

document.getElementById("hstat").textContent =
  DATA.total+"건 · 🔴"+DATA.reds+" · 업데이트 "+DATA.updated;

/* ---------- 좌측 메뉴(드릴다운) ---------- */
function counts(){
  var bySido={서울:0,경기:0,인천:0,전국:0}, byGu={};
  SIG.forEach(function(s){ bySido[s.sido]=(bySido[s.sido]||0)+1;
    if(s.gu){var k=s.sido+"|"+s.gu; byGu[k]=(byGu[k]||0)+1;} });
  return {bySido:bySido, byGu:byGu};
}
function buildSidebar(){
  var c=counts(), gus={};
  REG.forEach(function(r){ (gus[r.sido]=gus[r.sido]||[]).push(r.gu); });
  Object.keys(gus).forEach(function(k){gus[k].sort();});
  var h='<div class="navsec"><div class="navttl">보기</div>';
  h+=navrow("📋 종합 동향","__view_report",S.view==="report");
  h+=navrow("🗓 월별 정리","__view_monthly",S.view==="monthly");
  h+=navrow("🗂 지역별 보기","__view_list",S.view==="list");
  h+=navrow("📚 부읽남 참고","__view_frames",S.view==="frames");
  if(!PUBLIC) h+=navrow("개인 맞춤(정훈)","__view_personal",S.view==="personal");
  h+='</div><div class="navsec"><div class="navttl">지역 드릴다운</div>';
  h+=navrow('<b>전체 수도권</b>','all',!S.sido,c.bySido["서울"]+c.bySido["경기"]+c.bySido["인천"]+c.bySido["전국"]);
  ["서울","경기","인천"].forEach(function(sido){
    var open=S.sido===sido;
    h+='<div class="navitem '+(S.sido===sido&&!S.gu?"on":"")+'" data-sido="'+sido+'">'
      +'<span><span class="caret '+(open?"open":"")+'">▸</span>'+sido+'</span>'
      +'<span class="c">'+(c.bySido[sido]||0)+'</span></div>';
    (gus[sido]||[]).forEach(function(gu){
      var n=c.byGu[sido+"|"+gu]||0;
      h+='<div class="navitem gu '+(open?"":"hidden")+' '+(S.sido===sido&&S.gu===gu?"on":"")+'" '
        +'data-sido="'+sido+'" data-gu="'+gu+'"><span>'+gu+'</span><span class="c">'+n+'</span></div>';
    });
  });
  h+='</div>';
  var side=document.getElementById("side"); side.innerHTML=h;
  side.querySelectorAll(".navitem[data-sido]").forEach(function(el){
    el.onclick=function(){
      var sido=el.getAttribute("data-sido"), gu=el.getAttribute("data-gu");
      if(gu){ S.sido=sido;S.gu=gu;S.view="list"; }
      else{ S.sido=(S.sido===sido?null:sido); S.gu=null; S.view="list"; }
      render(); closeSide();
    };
  });
  // 뷰 전환 / 전체
  side.querySelectorAll('[data-key]').forEach(function(el){
    el.onclick=function(){ var k=el.getAttribute("data-key");
      if(k==="all"){S.sido=null;S.gu=null;S.view="list";}
      else if(k==="__view_report"){S.view="report";}
      else if(k==="__view_monthly"){S.view="monthly";}
      else if(k==="__view_list"){S.view="list";}
      else if(k==="__view_frames"){S.view="frames";}
      else if(k==="__view_personal"){S.view="personal";}
      render(); closeSide(); };
  });
}
function navrow(label,key,on,c){
  return '<div class="navitem '+(on?"on":"")+'" data-key="'+key+'"><span>'+label+'</span>'
    +(c!=null?'<span class="c">'+c+'</span>':'')+'</div>';
}

/* ---------- 필터/정렬 ---------- */
function filtered(){
  return SIG.filter(function(s){
    if(S.sido && s.sido!==S.sido) return false;
    if(S.gu && s.gu!==S.gu) return false;
    if(S.cat && s.cat!==S.cat) return false;
    if(S.trig && s.trig!==S.trig) return false;
    if(S.q){ var h=((s.title||"")+" "+(s.summary||"")+" "+(s.gu||"")+" "+(s.source||"")+" "+(s.comment||"")).toLowerCase();
      if(h.indexOf(S.q)<0) return false; }
    return true;
  });
}
function sortSig(arr){
  var a=arr.slice();
  if(S.sort==="date_desc") a.sort(function(x,y){return (y.date||"").localeCompare(x.date||"");});
  else if(S.sort==="date_asc") a.sort(function(x,y){return (x.date||"").localeCompare(y.date||"");});
  else if(S.sort==="price_desc") a.sort(function(x,y){return (y.price==null?-1:y.price)-(x.price==null?-1:x.price);});
  else if(S.sort==="price_asc") a.sort(function(x,y){return (x.price==null?1e9:x.price)-(y.price==null?1e9:y.price);});
  else if(S.sort==="region") a.sort(function(x,y){return (x.sido+x.gu).localeCompare(y.sido+y.gu);});
  return a;
}
function cardHTML(s){
  var loc=s.sido+(s.gu?" · "+s.gu:"");
  var bd=s.trig==="red"?'<span class="bd red">🔴</span>':s.trig==="yellow"?'<span class="bd yellow">🟡</span>':"";
  var pr=s.price!=null?'<span class="pr">매매 '+s.price+'억</span>':"";
  var cmt=s.comment?'<p class="cmt"><b>해석</b> '+esc(s.comment)+'</p>':"";
  var src=s.url?'<a class="src" href="'+esc(s.url)+'" target="_blank" rel="noopener">'+esc(s.source)+' ↗</a>':'<span class="src">'+esc(s.source)+'</span>';
  return '<article class="card"><div class="meta"><span class="date">'+esc(s.date)+'</span>'
    +'<span class="loc" data-sido="'+esc(s.sido)+'" data-gu="'+esc(s.gu)+'">'+esc(loc)+'</span>'
    +'<span class="conf '+s.conf+'">'+CONF[s.conf]+'</span>'+pr+bd+'</div>'
    +'<h3>'+esc(s.title)+'</h3><p class="sum">'+esc(s.summary)+'</p>'+cmt
    +'<div class="foot">'+src+'</div></article>';
}
function renderList(){
  var arr=sortSig(filtered());
  var list=document.getElementById("list");
  list.innerHTML=arr.map(cardHTML).join("");
  document.getElementById("empty").style.display=arr.length?"none":"block";
  list.querySelectorAll(".loc").forEach(function(el){
    el.onclick=function(){ S.sido=el.getAttribute("data-sido")||null;
      var g=el.getAttribute("data-gu"); S.gu=g||null; buildSidebar(); render(); };
  });
}
function renderCrumb(){
  var loc=S.sido?(esc(S.sido)+(S.gu?' <i>›</i> '+esc(S.gu):"")):"전체 수도권";
  var n=filtered().length;
  var h='<span class="cp loc">📍 '+loc+'</span>'
    +'<span class="cp n"><b>'+n+'</b>건</span>';
  if(S.cat) h+='<span class="cp">'+esc(CAT[S.cat])+'</span>';
  if(S.trig==="red") h+='<span class="cp red">🔴 즉시</span>';
  if(S.trig==="yellow") h+='<span class="cp yellow">🟡 주목</span>';
  if(S.q) h+='<span class="cp">🔍 '+esc(S.q)+'</span>';
  if(S.sido||S.gu||S.cat||S.trig||S.q) h+='<button class="creset" id="reset">✕ 초기화</button>';
  document.getElementById("crumb").innerHTML=h;
  var r=document.getElementById("reset");
  if(r) r.onclick=function(e){e.preventDefault();S.sido=S.gu=S.trig=null;S.cat="";S.q="";S.sort="date_desc";
    document.getElementById("q").value="";var so=document.getElementById("sort");if(so)so.value="date_desc";
    document.querySelectorAll(".chip").forEach(function(c){c.classList.remove("on");});
    document.querySelector('.chip[data-cat=""]').classList.add("on");buildSidebar();render();};
}

/* ---------- 지도 ---------- */
var map=null, layer=null;
var SUDO=[[36.92,126.55],[37.74,127.35]];  // 서울·경기·인천 커버 범위(기본 범례)
function initMap(){
  if(typeof L==="undefined"){ document.getElementById("map").style.display="none";
    document.getElementById("maphint").style.display="none"; return; }
  map=L.map("map",{scrollWheelZoom:false,minZoom:8}).fitBounds(SUDO);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {maxZoom:18,attribution:"© OpenStreetMap"}).addTo(map);
  layer=L.layerGroup().addTo(map);
  renderMap();
  if(S.view==="list") setTimeout(function(){ map.invalidateSize(); renderMap(); },60);
}
function renderMap(){
  if(!map) return; layer.clearLayers();
  var rs=REG.filter(function(r){ return r.lat!=null && (!S.sido||r.sido===S.sido); });
  rs.forEach(function(r){
    var m=L.circleMarker([r.lat,r.lng],{radius:Math.min(6+r.n*0.7,26),
      color:"#fff",weight:1,fillColor:priceBand(r.med),fillOpacity:.82});
    m.bindPopup("<b>"+r.sido+" "+r.gu+"</b><br>시그널 "+r.n+"건"
      +(r.med!=null?"<br>매매중위 "+r.med+"억":"<br>매매 표본 부족")
      +(r.red?"<br>🔴 즉시 "+r.red:""));
    m.on("click",function(){ S.sido=r.sido;S.gu=r.gu; buildSidebar(); render(); });
    m.addTo(layer);
  });
  // 컨테이너가 보일 때만 마커 범위로 맞춤, 아니면 수도권 기본 범위
  var visible=document.getElementById("map").offsetParent!==null;
  if(visible && rs.length){ try{ map.fitBounds(L.featureGroup(layer.getLayers()).getBounds().pad(0.12)); }catch(e){ map.fitBounds(SUDO); } }
  else { map.fitBounds(SUDO); }
}

/* ---------- 월별 정리 ---------- */
function monthLabel(ym){var p=ym.split("-");return p[0]+"년 "+parseInt(p[1],10)+"월";}
function renderMonthly(){
  var g={};
  SIG.forEach(function(s){ if(!s.date)return; var k=s.date.slice(0,7); (g[k]=g[k]||[]).push(s); });
  var months=Object.keys(g).sort().reverse();
  var CAP=18, shown=months.slice(0,CAP);
  var peak=0; months.forEach(function(m){ if(g[m].length>peak)peak=g[m].length; });
  var h='<div class="lead">월별 시그널 흐름 — 최신순'+(months.length>CAP?(" · 최근 "+CAP+"개월"):"")
    +' &nbsp;<span class="lgd"><span class="lr">🔴 즉시</span>=발견 즉시 주목 · <span class="ly">🟡 주목</span>=주간 점검 · 막대=월 시그널량</span></div>';
  shown.forEach(function(ym,i){
    var arr=g[ym].slice().sort(function(a,b){return (b.date||"").localeCompare(a.date||"");});
    var reds=arr.filter(function(s){return s.trig==="red";});
    var yel=arr.filter(function(s){return s.trig==="yellow";});
    var prev=shown[i+1]?g[shown[i+1]].length:null;   // 직전(더 오래된) 달
    var delta=prev==null?"":(arr.length>prev?'<span class="up">▲'+(arr.length-prev)+'</span>'
      :arr.length<prev?'<span class="dn">▼'+(prev-arr.length)+'</span>':'<span class="eq">―</span>');
    var pct=peak?Math.round(arr.length/peak*100):0;
    var byc={}; arr.forEach(function(s){byc[s.cat]=(byc[s.cat]||0)+1;});
    var chips=Object.keys(byc).sort(function(a,b){return byc[b]-byc[a];})
      .map(function(c){return '<span class="wcat">'+(CAT[c]||c)+" "+byc[c]+'</span>';}).join("");
    var top=reds.concat(yel).slice(0,8).map(function(s){
      return '<li><span class="wb">'+(s.trig==="red"?"🔴":"🟡")+'</span>'
        +'<span class="d">'+esc(s.date)+'</span> '+esc(s.title)
        +(s.gu?' <span class="loc2">'+esc(s.sido+" "+s.gu)+'</span>':'')+'</li>';
    }).join("");
    var more=(reds.length+yel.length>8)?'<li class="more">그 외 트리거 '+(reds.length+yel.length-8)+'건…</li>':'';
    h+='<section class="wk"><div class="wkh"><span class="wwk">'+monthLabel(ym)+'</span>'+delta
      +'<span class="wkn">총 '+arr.length+' · <span class="lr">🔴 즉시 '+reds.length+'</span> · <span class="ly">🟡 주목 '+yel.length+'</span></span></div>'
      +'<div class="bar"><span style="width:'+pct+'%"></span></div>'
      +(chips?'<div class="wkc">'+chips+'</div>':'')
      +(top?'<ul class="wkl">'+top+more+'</ul>':'<div class="wkempty">트리거 없음 · 일반 시그널 '+arr.length+'건</div>')
      +'</section>';
  });
  document.getElementById("view-monthly").innerHTML=h;
}

/* ---------- 렌더 ---------- */
function render(){
  buildSidebar();
  document.getElementById("view-list").style.display=S.view==="list"?"block":"none";
  document.getElementById("view-report").classList.toggle("on",S.view==="report");
  document.getElementById("view-monthly").classList.toggle("on",S.view==="monthly");
  document.getElementById("view-frames").classList.toggle("on",S.view==="frames");
  document.getElementById("view-personal").classList.toggle("on",S.view==="personal");
  var crumb=document.getElementById("crumb");
  if(S.view==="list"){ crumb.style.display=""; renderCrumb(); renderList();
    setTimeout(function(){ if(map){ map.invalidateSize(); renderMap(); } },60); }
  else {
    if(S.view==="monthly") renderMonthly();
    if(S.view==="report"){ crumb.style.display="none"; crumb.innerHTML=""; }
    else { crumb.style.display=""; crumb.innerHTML='<span class="cp">'
      +(S.view==="monthly"?"🗓 월별 정리 — 월별 시그널 흐름"
       :S.view==="frames"?"📚 부읽남 38강 판단 프레임":"👤 개인 맞춤(정훈) — 보조")+'</span>'; }
  }
}

/* ---------- 이벤트 ---------- */
document.querySelectorAll(".chip[data-cat]").forEach(function(b){
  b.onclick=function(){ document.querySelectorAll(".chip[data-cat]").forEach(function(x){x.classList.remove("on");});
    b.classList.add("on"); S.cat=b.getAttribute("data-cat"); S.view="list"; render(); };
});
document.querySelectorAll(".chip.tg").forEach(function(b){
  b.onclick=function(){ var t=b.getAttribute("data-trig");
    if(S.trig===t){S.trig=null;b.classList.remove("on");}
    else{S.trig=t;document.querySelectorAll(".chip.tg").forEach(function(x){x.classList.remove("on");});b.classList.add("on");}
    S.view="list"; render(); };
});
document.getElementById("sort").onchange=function(e){S.sort=e.target.value;renderList();};
document.getElementById("q").oninput=function(e){S.q=e.target.value.toLowerCase().trim();S.view="list";render();};
function closeSide(){document.getElementById("side").classList.remove("open");document.getElementById("backdrop").classList.remove("on");
  document.getElementById("burger").setAttribute("aria-expanded","false");}
document.getElementById("burger").onclick=function(){var o=document.getElementById("side").classList.toggle("open");
  document.getElementById("backdrop").classList.toggle("on",o);this.setAttribute("aria-expanded",o?"true":"false");};
document.getElementById("backdrop").onclick=closeSide;
function goHome(){ S={view:"report",sido:null,gu:null,cat:"",trig:null,q:"",sort:"date_desc"};
  document.getElementById("q").value=""; var so=document.getElementById("sort"); if(so)so.value="date_desc";
  document.querySelectorAll(".chip").forEach(function(x){x.classList.remove("on");});
  var a=document.querySelector('.chip[data-cat=""]'); if(a)a.classList.add("on"); render(); closeSide(); }
document.getElementById("brand").onclick=goHome;
document.getElementById("brand").onkeydown=function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();goHome();}};

render();
window.addEventListener("load",initMap);
</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
