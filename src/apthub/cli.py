"""apthub CLI.

  python -m apthub add [--file f.json | --stdin] [--day YYYY-MM-DD]
  python -m apthub enrich [--day YYYY-MM-DD | --all]
  python -m apthub report daily  [--day YYYY-MM-DD] [--save]
  python -m apthub report weekly [--day YYYY-MM-DD] [--save]
  python -m apthub list [--day YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import config, filters, manual, report, store
from .schema import KST


def _today() -> str:
    return datetime.now(KST).date().isoformat()


def cmd_add(args) -> int:
    if args.file:
        text = open(args.file, encoding="utf-8").read()
    else:
        text = sys.stdin.read()
    if not text.strip():
        print("입력이 비어 있습니다 (JSON 배열/단건).", file=sys.stderr)
        return 1
    sigs = manual.ingest_json(text, day=args.day, replace=args.replace,
                              by_date=args.by_date)
    if args.by_date:
        print(f"저장 {len(sigs)}건 (발행일별 백데이터 적재)")
    else:
        mode = "덮어쓰기" if args.replace else "병합"
        print(f"저장 {len(sigs)}건 ({mode}, day={args.day or _today()})")
    for s in sigs:
        tag = {"red": "🔴", "yellow": "🟡", "none": "·"}[s.trigger]
        print(f"  {tag} [{s.category}] {s.title}  areas={s.areas} kw={s.keywords}")
    return 0


def cmd_enrich(args) -> int:
    days = store.all_days() if args.all else [args.day or _today()]
    total = 0
    for day in days:
        sigs = filters.enrich_all(store.load_day(day))
        if sigs:
            store.add(sigs, day=day)
            total += len(sigs)
    print(f"enrich 완료: {total}건 / {len(days)}일")
    return 0


def cmd_clear(args) -> int:
    ok = store.clear(args.day)
    print(f"{'삭제됨' if ok else '대상 없음'}: {args.day}")
    return 0


def cmd_report(args) -> int:
    config.ensure_dirs()
    if args.kind == "daily":
        day = args.day or _today()
        sigs = store.load_day(day)
        out = report.render_daily(sigs, day=day)
        fname = f"daily-{day}.md"
    else:
        anchor = args.day or _today()
        start, end = report.week_bounds(anchor)
        sigs = store.load_range(start, end)
        out = report.render_weekly(sigs, start, end)
        fname = f"weekly-{end}.md"
    if args.save:
        path = config.REPORTS_DIR / fname
        path.write_text(out, encoding="utf-8")
        print(f"저장: {path}")
    else:
        print(out)
    return 0


def cmd_list(args) -> int:
    day = args.day or _today()
    sigs = store.load_day(day)
    if not sigs:
        print(f"{day}: 시그널 없음")
        return 0
    for s in sigs:
        tag = {"red": "🔴", "yellow": "🟡", "none": "·"}[s.trigger]
        print(f"{tag} [{s.category}] {s.title} | {s.source} | {s.areas}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="apthub", description="정훈 부동산 시그널 — m-SIGNAL")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="파싱 JSON 시그널 추가")
    a.add_argument("--file", help="JSON 파일 경로")
    a.add_argument("--stdin", action="store_true", help="stdin 에서 읽기(기본)")
    a.add_argument("--day", help="저장 날짜 YYYY-MM-DD")
    a.add_argument("--replace", action="store_true", help="해당 날짜를 비우고 새로 저장")
    a.add_argument("--by-date", action="store_true",
                   help="각 시그널을 자신의 발행일 파일에 저장(백데이터 적재)")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("clear", help="해당 날짜 시그널 삭제")
    c.add_argument("--day", required=True, help="삭제할 날짜 YYYY-MM-DD")
    c.set_defaults(func=cmd_clear)

    e = sub.add_parser("enrich", help="저장된 시그널 재태깅")
    e.add_argument("--day", help="대상 날짜")
    e.add_argument("--all", action="store_true", help="전체 날짜")
    e.set_defaults(func=cmd_enrich)

    r = sub.add_parser("report", help="리포트 생성")
    r.add_argument("kind", choices=["daily", "weekly"])
    r.add_argument("--day", help="기준 날짜 YYYY-MM-DD")
    r.add_argument("--save", action="store_true", help="data/reports 에 저장")
    r.set_defaults(func=cmd_report)

    l = sub.add_parser("list", help="저장된 시그널 목록")
    l.add_argument("--day", help="대상 날짜")
    l.set_defaults(func=cmd_list)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
