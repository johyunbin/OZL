"""/syuka deck 의 도우미 — 검토 묶음에 지난 방송을 가리키는 것이 실렸는지 본다.

    .venv/bin/python .claude/skills/syuka/deck/bundle_guard.py <묶음.md> [--card <card_id>] [--json]

검토 묶음(`python -m ozl.render bundle <사양>` 이 만든 글)은 다른 모델 계열로 나가는 하나뿐인 글이다. 사양의 장마다 적은
메모(notes)까지 실리므로, 사양에 지난 방송의 영상 번호나 올린 날을 적으면 그대로 나간다. 이 검사는 묶음을 보내기 전에 돌린다.
묶음과 함께 보내는 머리말(skills/ozl/review/external_head.md 를 채운 글)도 같은 검사로 본다. 머리말에는 카드 번호 줄이 없으므로
`--card` 를 준다.

걸리는 것(하나라도 있으면 종료 코드 1. 그 묶음은 보내지 않는다):
  - 카드 coverage.videos 의 영상 번호, 제목, 올린 날(연도가 붙은 날짜 표기. 각주와 인용 줄, 검증 기록 절은 날짜를 보지 않는다)
  - 영상 목록(private/meta/catalog_syukaworld.csv)에 있는 영상 번호
  - 유튜브 영상 주소(검증 기록 절의 출처 주소는 영상 목록에 있는 번호일 때만)
  - 영상 번호 꼴(11자)이 "방송(…)", "영상(…)", "video_id: …" 자리에 있는 것

읽기만 한다: 묶음, 그 카드, 영상 목록의 번호 칸. 아무것도 쓰지 않고 웹 요청을 보내지 않는다.
종료 코드: 0 실린 것 없음 · 1 실렸다 · 2 검사하지 못했다(묶음이나 카드가 없다).
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys

from ozl import paths as ozlpaths
from ozl.research import cards as C

CATALOG = ozlpaths.at("meta", "catalog_syukaworld.csv")
HEAD = re.compile(r"^# 검토 묶음 — (\S+)\s*$", re.M)
CLAIMS_HEAD = "## 인용한 검증 기록"
RUN = re.compile(r"[A-Za-z0-9_-]+")
YT_URL = re.compile(r"(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:watch\?(?:[^\s`)\]]*&)?v=|shorts/|live/|embed/|v/))([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
# 영상 번호가 놓이는 자리: "방송(번호)", "영상 [번호]", "video_id: 번호", "영상 번호 번호"
IN_BRACKETS = re.compile(r"(?:방송|영상|회차|편)\s*[(\[（]\s*([A-Za-z0-9_-]{11})\s*[)\]）]")
LABELLED = re.compile(r"(?:video_id|영상\s*번호|영상\s*ID)\s*[:=]?\s*[`'\"(\[]?\s*([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", re.I)
NO_DATE_LINES = ("각주:", "인용:")     # 묶음이 기록에서 뽑아 적는 줄. 근거 문서의 날짜가 들어간다
TITLE_MIN = 6

K_COV_ID, K_COV_TITLE, K_COV_DATE = "카드 coverage 의 영상 번호", "카드 coverage 의 영상 제목", "카드 coverage 의 올린 날"
K_CATALOG, K_URL, K_SHAPE = "영상 목록에 있는 영상 번호", "유튜브 영상 주소", "영상 번호 꼴"


class Stop(Exception):
    """한 문장으로 알리고 끝낼 일. code 는 종료 코드."""

    def __init__(self, msg: str, code: int = 2) -> None:
        super().__init__(msg)
        self.code = code


def looks_like_id(tok: str) -> bool:
    """유튜브 영상 번호처럼 보이는 11자: 글자가 있고, 숫자가 섞였거나 대소문자가 섞였다."""
    if len(tok) != 11 or not re.search(r"[A-Za-z]", tok):
        return False
    return bool(re.search(r"\d", tok)) or (tok != tok.lower() and tok != tok.upper())


def date_pattern(date: str) -> re.Pattern | None:
    """YYYY-MM-DD 한 날짜의 여러 표기(2098-06-03, 2098.6.3, 2098/06/03, 2098년 6월 3일)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(date).strip())
    if not m:
        return None
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    return re.compile(rf"(?<!\d){y}\s*[-./년]\s*0?{mo}\s*[-./월]\s*0?{d}(?!\d)")


def squeeze(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def coverage_videos(card: dict | None) -> list[dict]:
    cov = (card or {}).get("coverage") or {}
    return [v for v in (cov.get("videos") or []) if isinstance(v, dict)]


def catalog_ids(path: pathlib.Path | None = None) -> set[str] | None:
    """영상 목록의 영상 번호. 파일이 없으면 None(없는 것과 0편을 구분한다)."""
    path = path or CATALOG
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as f:
        return {r["video_id"].strip() for r in csv.DictReader(f) if (r.get("video_id") or "").strip()}


def scan(bundle: str, videos: list[dict], known: set[str] | None) -> list[dict]:
    """묶음 글에서 걸리는 곳의 목록. 항목은 {line, kind, value}. 같은 줄의 같은 값은 한 번만 적는다."""
    known = known or set()
    cov_ids = [str(v.get("video_id") or "").strip() for v in videos]
    cov_ids = [x for x in cov_ids if x]
    titles = [squeeze(v.get("title") or "") for v in videos]
    titles = [t for t in titles if len(t) >= TITLE_MIN]
    dates = [(str(v.get("date")), date_pattern(v.get("date"))) for v in videos]
    hits: list[dict] = []
    seen: set[tuple[int, str]] = set()

    def add(n: int, kind: str, value: str) -> None:
        if (n, value) not in seen:
            seen.add((n, value))
            hits.append({"line": n, "kind": kind, "value": value})

    in_claims = False
    for n, line in enumerate(bundle.splitlines(), 1):
        if line.startswith(CLAIMS_HEAD):
            in_claims = True
        flat = squeeze(line)
        for vid in cov_ids:
            if vid in line:
                add(n, K_COV_ID, vid)
        for t in titles:
            if t in flat:
                add(n, K_COV_TITLE, t)
        if not in_claims and not line.lstrip().startswith(NO_DATE_LINES):
            for raw, pat in dates:
                if pat and pat.search(line):
                    add(n, K_COV_DATE, raw)
        for tok in RUN.findall(line):
            if tok in known:
                add(n, K_CATALOG, tok)
        for m in YT_URL.finditer(line):
            if not in_claims or m.group(1) in known:
                add(n, K_URL, m.group(1))
        for pat in (IN_BRACKETS, LABELLED):
            for m in pat.finditer(line):
                if looks_like_id(m.group(1)):
                    add(n, K_SHAPE, m.group(1))
    return hits


def check(path: pathlib.Path, card_id: str | None = None) -> dict:
    if not path.is_file():
        raise Stop(f"묶음 파일이 없다: {path}")
    body = path.read_text(encoding="utf-8")
    m = HEAD.search(body)
    cid = card_id or (m.group(1) if m else "")
    if not C.CARD_ID.match(cid or ""):
        raise Stop("묶음의 첫 줄에서 카드 번호를 읽지 못했다. `--card <card_id>` 로 준다")
    if not C.card_path(cid).exists():
        raise Stop(f"카드가 없어 coverage 를 대조하지 못했다: {C.card_path(cid)}")
    videos = coverage_videos(C.load_card(cid))
    known = catalog_ids()
    return {"bundle": str(path), "card_id": cid, "coverage_videos": len(videos),
            "catalog_videos": None if known is None else len(known), "hits": scan(body, videos, known)}


def report(res: dict) -> str:
    seen = f"카드 coverage 의 영상 {res['coverage_videos']}편"
    seen += " · 영상 목록을 읽지 못했다(카드의 coverage 와 영상 번호 꼴만 봤다)" if res["catalog_videos"] is None \
        else f" · 영상 목록 {res['catalog_videos']}편"
    if not res["hits"]:
        return f"[bundle_guard] 실린 것 없음 · 대조한 것: {seen} · {res['bundle']}"
    L = [f"[bundle_guard] 실렸다 {len(res['hits'])}곳 · 대조한 것: {seen} · {res['bundle']}"]
    L += [f"  {h['line']}행 · {h['kind']} · {h['value']}" for h in res["hits"]]
    L.append("이 묶음을 보내지 않는다. 사양에서 그 대목을 지우고(겹침은 카드의 coverage 와 진행 기록의 메모에만 둔다) "
             "묶음을 다시 만든 뒤 이 검사를 다시 돌린다.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="검토 묶음에 지난 방송을 가리키는 것(영상 번호, 제목, 올린 날)이 실렸는지 본다. 읽기만 한다")
    ap.add_argument("bundle", help="검토 묶음 파일(private/desk/builds/<card_id>/reviews/bundle_<타임코드>.md). 채운 머리말 파일도 받는다(--card 와 함께)")
    ap.add_argument("--card", help="카드 번호. 없으면 묶음의 첫 줄에서 읽는다")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 으로 찍는다")
    a = ap.parse_args(argv)
    try:
        res = check(pathlib.Path(a.bundle), a.card)
    except Stop as e:
        print(f"[bundle_guard] 검사하지 못했다: {e}", file=sys.stderr)
        return e.code
    print(json.dumps(res, ensure_ascii=False) if a.json else report(res))
    return 1 if res["hits"] else 0


if __name__ == "__main__":
    sys.exit(main())
