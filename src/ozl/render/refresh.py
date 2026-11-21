"""덱의 마지막 판 뒤에 붙은 후속 기사를 읽기 전용으로 찾는다.

    python -m ozl.render refresh-candidates [<card_id>…] [--since YYYY-MM-DD] [--all] [--json] [--db <engine.db>]

후속 기사는 갱신 후보이지 수치의 근거가 아니다. 같은 지표의 새 기준일과 T1·T2 원문을
확인한 뒤에만 새 타임코드의 사양을 쓰고 check → build, 관련 장 재검사, 변경 메모를 남긴다.

- 카드와 엔진 이슈는 카드 `discovery` 글로 잇는다: 글 안의 엔진 이슈 번호(t…), 그리고 「YYYY-MM-DD 방송 예측」과
  그 예측의 story_key 가 함께 있으면 고정 예측 파일의 member_ids. 합쳐진 번호는 별칭 표로 따라간다.
- 엔진은 하루가 확정된 계산에서만 `issue_followups` 를 쓴다. 그래서 오늘 붙은 후속은 다음 날 확정 뒤에 보인다.
- 마지막 판 = 사양 폴더에서 파일 이름 타임코드가 가장 늦은 사양. 그 시각보다 뒤에 처음 묶인 후속 단위가 후보다.
- DB 내용과 예측·카드·사양 파일을 바꾸지 않는다. DB 는 다른 읽기 경로(pulse.serve, signals.explain)와 같은
  `mode=ro` 로 열고, 읽기 트랜잭션은 조회가 끝나면 바로 닫는다(WAL 공유 메모리 파일은 SQLite 가 관리한다).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, time
from pathlib import Path

import yaml

from ozl import paths as ozlpaths
from ozl.render import spec
from ozl.research import cards
from ozl.signals.config import KST, parse_ts

RULE = ("후속 기사는 갱신 후보일 뿐이다. 수치는 같은 지표의 새 기준일과 원출처(T1·T2 원문)를 열어 확인했을 때만 고친다. "
        "고칠 때는 사양을 새 타임코드로 쓰고 check → build 를 다시 하고, 바뀐 기록을 쓰는 장을 모두 다시 검사하고, "
        "변경 메모를 남긴다(agent/deck.md 「덱 갱신」).")
NO_LINK = "카드 discovery 에 엔진 이슈 번호(t…)를 적으면 잇는다(discovery 는 승인 지문 밖)"
HASH_STEPS = ("검토", "빌드", "게이트", "재확인")
PRIVATE = ozlpaths.root()
ISSUE_ID = re.compile(r"(?<![0-9A-Za-z])t\d{8}-\d{3,}(?!\d)")
BROADCAST = re.compile(r"(\d{4}-\d{2}-\d{2})\s+방송\s+예측")
EDITION = re.compile(r"(\d{8}_\d{6})(?:_(.+))?")


def open_db(path: Path) -> sqlite3.Connection:
    """엔진의 초기화나 스키마 변경 없이 기존 DB만 연다."""
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def latest_specs(folder: Path, notices: list[str]) -> dict[str, tuple[datetime, Path]]:
    found = {}
    for path in sorted(folder.glob("*.yaml")):
        cid, _, edition = path.stem.partition("_")
        match = EDITION.fullmatch(edition)
        if not (cards.CARD_ID.fullmatch(cid) and match and path.is_file()):
            continue
        stamp, suffix = match.groups()
        try:
            at = datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=KST)
        except ValueError:
            notices.append(f"{path.name}: 사양 파일 이름의 타임코드가 날짜가 아니라 건너뜀")
            continue
        # 시각이 같으면 꼬리 없는 판, 모두 꼬리가 있으면 이름순 마지막 판.
        rank = (at, suffix is None, suffix or "")
        if cid not in found or rank > found[cid][0]:
            found[cid] = (rank, path)
    return {cid: (rank[0], path) for cid, (rank, path) in found.items()}


def issue_links(discovery: str, predictions_dir: Path, aliases: dict) -> list[dict]:
    sources = defaultdict(set)
    for issue in ISSUE_ID.findall(discovery):
        sources[issue].add("discovery")
    # split 결과는 머리글 뒤로 방송 날짜와 그 언급에 딸린 글이 번갈아 나온다.
    parts = BROADCAST.split(discovery)
    for day, segment in zip(parts[1::2], parts[2::2]):
        fixed = max((predictions_dir / day).glob("prediction_*_fixed.json"), default=None)
        if fixed is None:
            continue
        prediction = json.loads(fixed.read_text(encoding="utf-8"))
        for pick in prediction["picks"]:
            key = pick["story_key"]
            if key and re.search(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])", segment):
                for issue in pick["member_ids"]:
                    if ISSUE_ID.fullmatch(issue):
                        sources[issue].add(f"예측 {day} {key}")

    pending = list(sources)
    while pending:
        for other in aliases.get(pending.pop(), ()):
            if other not in sources:
                sources[other].add("별칭")
                pending.append(other)
    return [{"issue_id": issue, "via": via} for issue in sorted(sources) for via in sorted(sources[issue])]


def progress_info(path: Path, spec_bytes: bytes) -> dict:
    state = cards.load_yaml(path) if path.is_file() else {}
    steps = state.get("steps", [])
    last_hash = next((s["spec_sha256"] for s in reversed(steps) if s.get("spec_sha256")), None)
    comparison = "기록 없음"
    note = None
    if last_hash:
        edition_hash = hashlib.sha256(spec_bytes).hexdigest()
        comparison = "같음" if last_hash == edition_hash else "다름"
        if comparison == "다름":
            recorded = {s.get("step") for s in steps if s.get("spec_sha256") == edition_hash}
            missing = [step for step in HASH_STEPS if step not in recorded]
            if missing:
                note = "마지막 판으로 기록되지 않은 단계: " + "·".join(missing)
    return {"status": state.get("status", "없음"), "spec_hash": comparison, "note": note}


def claim_pages(spec_bytes: bytes) -> dict[str, list[int]]:
    pages = defaultdict(list)
    for page, slide in enumerate((yaml.safe_load(spec_bytes) or {}).get("slides", []), 1):
        for claim in spec.cited_ids({"slides": [slide]}, all_refs=True):
            pages[claim].append(page)
    return dict(sorted(pages.items()))


def articles_for(con: sqlite3.Connection, members: list[str]) -> list[dict]:
    articles = []
    urls = set()
    for key in members:
        row = con.execute("SELECT outlet, canon_url FROM articles WHERE item_key=?", (key,)).fetchone()
        if row and row["canon_url"] and row["canon_url"] not in urls:
            articles.append(dict(row))
            urls.add(row["canon_url"])
            if len(articles) == 3:
                break
    return articles


def followups(con: sqlite3.Connection, links: list[dict], cutoff: datetime, show_all: bool) -> tuple[list, list]:
    units = {}
    issue_ids = sorted({link["issue_id"] for link in links})
    if not issue_ids:
        return [], []
    marks = ",".join("?" for _ in issue_ids)
    for row in con.execute(f"SELECT * FROM issue_followups WHERE issue_id IN ({marks}) ORDER BY day, unit_id", issue_ids):
        unit = units.setdefault(row["unit_id"], {"unit_id": row["unit_id"], "day": row["day"],
                                                "issue_ids": set(), "families": set(), "new_terms": set()})
        unit["issue_ids"].add(row["issue_id"])
        for field in ("families", "new_terms"):
            unit[field].update(json.loads(row[field] or "[]"))

    candidates, before = [], []
    for uid, unit in units.items():
        group = con.execute("""SELECT title, first_at, members FROM groups WHERE group_id=?
                               ORDER BY final DESC, calc_id DESC LIMIT 1""", (uid,)).fetchone()
        first = parse_ts(group["first_at"]) if group else None
        day = date.fromisoformat(unit["day"])
        same_day_unknown = first is None and day == cutoff.date()
        is_candidate = first > cutoff if first else day >= cutoff.date()
        if not is_candidate and not show_all:
            continue
        for field in ("issue_ids", "families", "new_terms"):
            unit[field] = sorted(unit[field])
        unit.update(title=(group["title"] if group else None) or uid,
                    first_at=first.astimezone(KST).isoformat() if first else None,
                    same_day_unknown=same_day_unknown,
                    articles=articles_for(con, json.loads(group["members"] or "[]")) if group else [])
        (candidates if is_candidate else before).append(unit)
    return candidates, before


def report(con: sqlite3.Connection, card_ids: list[str], since: date | None, show_all: bool, *,
           cards_dir: Path, specs_dir: Path, builds_dir: Path, predictions_dir: Path) -> dict:
    notices = []
    editions = latest_specs(specs_dir, notices)
    aliases = defaultdict(set)
    for old, new in con.execute("SELECT old_id, new_id FROM issue_aliases"):
        aliases[old].add(new)
        aliases[new].add(old)

    results = []
    for cid in dict.fromkeys(card_ids or sorted(editions)):
        path = cards_dir / f"{cid}.yaml"
        if not path.is_file():
            notices.append(f"{cid}: 카드 파일이 없어 건너뜀")
            continue
        if cid not in editions:
            notices.append(f"{cid}: 덱 사양이 없어 건너뜀")
            continue
        at, edition = editions[cid]
        spec_bytes = edition.read_bytes()
        card = cards.load_yaml(path)
        links = issue_links(card.get("discovery") or "", predictions_dir, aliases)
        cutoff = datetime.combine(since, time.min, KST) if since else at
        candidates, before = followups(con, links, cutoff, show_all)
        results.append({"card_id": cid, "topic": card.get("topic", ""), "last_spec": edition.name,
                        "last_spec_at": at.isoformat(), "cutoff": cutoff.isoformat(),
                        "progress": progress_info(builds_dir / cid / "state.yaml", spec_bytes),
                        "links": links, "link_hint": None if links else NO_LINK,
                        "candidates": candidates, "before": before, "claim_pages": claim_pages(spec_bytes)})
    return {"cards": results, "notices": notices, "rule": RULE}


def print_text(result: dict, show_all: bool, since: date | None) -> None:
    for notice in result["notices"]:
        print(notice)
    for card in result["cards"]:
        print(f"== {card['card_id']} · {card['topic'][:40]}")
        print(f"   마지막 판: {card['last_spec']} ({card['last_spec_at']})")
        if since:
            print(f"   조회 기준: {card['cutoff']}")
        progress = card["progress"]
        note = f" · {progress['note']}" if progress["note"] else ""
        print(f"   진행 기록: {progress['status']} · 마지막 사양 해시 {progress['spec_hash']}{note}")
        by_via = defaultdict(list)   # 같은 번호가 출처마다 한 줄씩 있으므로 출처별로 묶어 찍는다
        for link in card["links"]:
            by_via[link["via"]].append(link["issue_id"])
        if not by_via:
            print("   연결 이슈: 연결 없음")
        for via, ids in sorted(by_via.items()):
            print(f"   연결 이슈({via}): {' '.join(ids)}")
        if card["link_hint"]:
            print(f"   {card['link_hint']}")
        before_label = "조회 기준 이전 후속" if since else "판 이전 후속"
        for key, label in (("candidates", "갱신 후보"), ("before", before_label)):
            if key == "before" and not show_all:
                continue
            print(f"   {label} {len(card[key])}건")
            for unit in card[key]:
                clock = unit["first_at"][11:16] if unit["first_at"] else "시각 모름"
                if unit["same_day_unknown"]:
                    clock = "같은 날(시각 모름)"
                print(f"     - {unit['day']} {clock} [{', '.join(unit['issue_ids'])}] {unit['title']}"
                      f"  · 계열 {len(unit['families'])}곳 · 새 낱말 {', '.join(unit['new_terms'])}")
                for article in unit["articles"]:
                    print(f"         {article['outlet']} {article['canon_url']}")
        print("   이 판이 쓰는 기록:")
        for claim, pages in card["claim_pages"].items():
            print(f"     {claim} → {', '.join(map(str, pages))}")
    print(result["rule"])


def main(argv: list[str], *, db_path: Path = ozlpaths.at("pulse", "engine.db"),
         cards_dir: Path = cards.CARDS, specs_dir: Path = spec.SPECS,
         builds_dir: Path = cards.DESK / "builds", predictions_dir: Path = ozlpaths.at("syuka", "predictions")) -> int:
    parser = argparse.ArgumentParser(prog="python -m ozl.render refresh-candidates", allow_abbrev=False,
                                     description="덱에 연결된 이슈의 후속 기사를 읽습니다.")
    parser.add_argument("card_ids", nargs="*", metavar="card_id")
    parser.add_argument("--since", metavar="YYYY-MM-DD")
    parser.add_argument("--all", action="store_true", help="판 이전 후속도 표시")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    parser.add_argument("--db", type=Path, default=db_path, metavar="engine.db")
    args, unknown = parser.parse_known_intermixed_args(argv)
    if unknown:
        raise SystemExit(f"모르는 옵션: {' '.join(unknown)}")
    for cid in args.card_ids:
        if not cards.CARD_ID.fullmatch(cid):
            raise SystemExit(f"카드 ID 형식 오류: {cid}")
    since = None
    if args.since is not None:
        try:
            since = date.fromisoformat(args.since)
            if since.isoformat() != args.since:
                raise ValueError
        except ValueError:
            raise SystemExit("--since 뒤에 YYYY-MM-DD 날짜가 있어야 한다") from None
    try:
        with closing(open_db(args.db)) as con:
            # 별칭부터 원기사까지 같은 시점의 WAL을 읽는다. 쓰기 예약이나 배타 잠금은 잡지 않는다.
            con.execute("BEGIN")
            result = report(con, args.card_ids, since, args.all, cards_dir=cards_dir, specs_dir=specs_dir,
                            builds_dir=builds_dir, predictions_dir=predictions_dir)
    except sqlite3.Error as exc:
        print(f"엔진 DB를 읽지 못했다: {args.db} ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print_text(result, args.all, since)
    return 0
