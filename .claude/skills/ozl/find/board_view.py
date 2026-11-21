"""/ozl find 의 도우미 — 화제 엔진의 후보 판(board.json)을 표로 찍고, 고르기 기록을 쓴다.

읽기만 하는 것: 후보 판, 만들기 대기열, 이슈 기록(번호, 상태, 제목). 쓰는 것: <자료 루트>/find/ 의 고르기 기록뿐이다.
수집을 돌리지 않는다. 판이 2시간보다 오래됐으면 그렇게 알리기만 한다. 자료 루트는 ozl.issues.paths 가 정한다
(OZL_DESK_ROOT, 없으면 private/desk).

    .venv/bin/python .claude/skills/ozl/find/board_view.py [--board 경로] [--top 15] [--category 분야] [--match 낱말] [--all] [--json]
    .venv/bin/python .claude/skills/ozl/find/board_view.py note [--pick t… …] [--drop t… …] [--add "제목"]
    .venv/bin/python .claude/skills/ozl/find/board_view.py picks [--json]
    .venv/bin/python .claude/skills/ozl/find/board_view.py result <key> --state <상태> [--issue i…] [--note "한 줄"]

표의 순서는 큰 이야기 순서(story_rank)다. 한국어 후보가 먼저, 영문 후보가 뒤다(순위는 언어마다 따로 매겨져 있다).
버린 건은 사흘 동안 표에서 접는다(--all 로 다시 본다). 운영 화면의 [버리기] 기록과는 따로다.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

from ozl import paths as ozlpaths
from ozl.issues import paths

KST = timezone(timedelta(hours=9))
BOARD_SCHEMA = "ozl.board/1"
FIND_SCHEMA = "ozl.find/1"
TOPIC_ID = re.compile(r"t[0-9]{8}-[0-9]{3,4}")
ISSUE_ID = re.compile(r"i[0-9]{8}-[0-9]{2}")
SENS_WORD = {"GREEN": "없음", "YELLOW": "주의", "RED": "높음"}      # 운영 화면(ozl.ops.candidates)과 같은 낱말
ZONE_WORD = {"new": "새로 뜬 것", "ongoing": "이어지는 것"}
TBD = "정리 전"
DECK_OUT = "덱 제외"
STALE = timedelta(hours=2)
FOLD_DAYS = 3          # 버린 건을 표에서 접어 두는 날 수
RECENT_DAYS = 3        # 인자 없는 /ozl make 가 남은 건을 찾아보는 고르기 기록의 범위
SEARCHES_SHOWN = 10
LINKS_KEPT = 5
TITLE_MAX = 120
WAITING, RUNNING, DONE, STOPPED, CANCELLED = "대기", "실행 중", "끝남", "멈춤", "취소"
STATES = (WAITING, RUNNING, DONE, STOPPED, CANCELLED)
NO_COLLECT = "이 스킬은 수집을 돌리지 않는다."
PULSE_JOB = "com.hyunbin.ozl-pulse"


class Stop(Exception):
    """사용자에게 한 문장으로 알리고 끝낼 일. code 는 종료 코드."""

    def __init__(self, msg: str, code: int = 2) -> None:
        super().__init__(msg)
        self.code = code


# ── 시각 ────────────────────────────────────────────────────────────────

def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=KST)).astimezone(KST)


def now_kst(s: str | None = None) -> datetime:
    if s:
        t = parse_time(s)
        if t is None:
            raise Stop(f"--now 를 읽지 못했다: {s}")
        return t
    return datetime.now(KST)


def hm(t: datetime | None) -> str:
    return t.strftime("%Y-%m-%d %H:%M") if t else "모름"


def ago(d: timedelta) -> str:
    m = int(d.total_seconds() // 60)
    if m < 60:
        return f"{m}분 전"
    return f"{m // 60}시간 {m % 60}분 전"


# ── 후보 판 ──────────────────────────────────────────────────────────────

def default_board() -> pathlib.Path:
    return ozlpaths.at("pulse", "out", "board.json")


def load_board(p: pathlib.Path) -> dict:
    p = pathlib.Path(p)
    if not p.exists():
        raise Stop(f"후보 판이 없다: {p}. 매시 수집(launchd {PULSE_JOB})이 쓰는 파일이다. {NO_COLLECT}", 1)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        raise Stop(f"후보 판을 읽지 못했다: {p}", 1) from None
    if not isinstance(d, dict) or d.get("schema") != BOARD_SCHEMA or not isinstance(d.get("candidates"), list):
        raise Stop(f"후보 판의 꼴이 맞지 않는다({BOARD_SCHEMA} 가 아니다): {p}", 1)
    return d


def _int(v, default=None):
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _cell(s) -> str:
    """표의 한 칸: 줄바꿈과 세로줄을 없앤다."""
    return re.sub(r"\s+", " ", str(s or "")).replace("|", "/").strip()


def one_line(c: dict) -> str:
    """한 줄 설명. summary 와 why_now 칸이 있으면 그것을, 없으면 상태 줄과 수치로 만든다."""
    s, w = _cell(c.get("summary")), _cell(c.get("why_now"))
    if s or w:
        return " ".join(x for x in (s, f"왜 지금: {w}" if w else "") if x)
    day = _int(c.get("day_n"))
    bits = [_cell(c.get("status_line")) or (f"{day}일째" if day else "")]
    n = _int(c.get("articles_n"))
    if n is not None:
        bits.append(f"기사 {n}건")
    sc = c.get("score")
    if isinstance(sc, (int, float)) and not isinstance(sc, bool):
        bits.append(f"화제 점수 {int(sc)}")
    new = _cell(c.get("new_thing"))
    if new:
        bits.append(f"새로 나온 것: {new}")
    return " · ".join(b for b in bits if b) or TBD


def sens(c: dict) -> tuple[str, str]:
    """(낱말, 까닭). 칸이 없거나 모르는 값이면 ('정리 전', '')."""
    s = c.get("sensitivity")
    if not isinstance(s, dict) or s.get("level") not in SENS_WORD:
        return TBD, ""
    return SENS_WORD[s["level"]], _cell(s.get("reason"))


def deck_blocked(c: dict) -> bool:
    s = c.get("sensitivity")
    return bool(c.get("deck_blocked")) or (isinstance(s, dict) and s.get("level") == "RED")


def sens_cell(c: dict) -> str:
    word, why = sens(c)
    if deck_blocked(c):
        word = f"{word} · {DECK_OUT}"
    return f"{word}: {why}" if why and word != SENS_WORD["GREEN"] else word


def sort_key(c: dict):
    rank = _int(c.get("story_rank"))
    raw = c.get("score_raw")
    raw = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else -1.0
    return (0 if c.get("lang", "ko") == "ko" else 1, rank if rank is not None else 10 ** 9, -raw, str(c.get("issue_id")))


def candidates(board: dict) -> tuple[list[dict], int]:
    """번호 꼴이 맞는 후보를 큰 이야기 순서로. (후보, 번호 꼴이 아니어서 뺀 수)"""
    ok = [c for c in board["candidates"] if isinstance(c, dict) and TOPIC_ID.fullmatch(str(c.get("issue_id") or ""))]
    return sorted(ok, key=sort_key), len(board["candidates"]) - len(ok)


def matches(c: dict, word: str) -> bool:
    w = word.casefold()
    hay = [c.get("title"), c.get("new_thing"), c.get("summary"), *(c.get("aliases") or [])]
    hay += [l.get("title") for l in c.get("links") or [] if isinstance(l, dict)]
    return any(w in str(h).casefold() for h in hay if h)


# ── 고르기 기록 ───────────────────────────────────────────────────────────

def find_dir() -> pathlib.Path:
    return paths.desk_root() / "find"


def records() -> list[tuple[pathlib.Path, dict]]:
    """고르기 기록을 오래된 것부터. 읽지 못하는 파일은 건너뛴다."""
    out = []
    d = find_dir()
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(r, dict) and r.get("schema") == FIND_SCHEMA:
            r["picks"] = [x for x in r.get("picks") or [] if isinstance(x, dict)]
            r["drops"] = [x for x in r.get("drops") or [] if isinstance(x, dict)]
            out.append((p, r))
    return out


def folded(recs, now: datetime) -> dict[str, datetime]:
    """지금 접어 둔 화제 번호 → 접는 끝 시각. 버린 뒤에 다시 고른 건은 접지 않는다."""
    out: dict[str, datetime] = {}
    for _, r in recs:
        for x in r["drops"]:
            until = parse_time(x.get("until"))
            if x.get("key") and until and until > now:
                out[str(x["key"])] = until
        for x in r["picks"]:
            out.pop(str(x.get("key")), None)
    return out


def latest_picks(recs) -> dict[str, dict]:
    """화제 번호 → 가장 늦은 고르기 줄."""
    out = {}
    for _, r in recs:
        for x in r["picks"]:
            if x.get("kind") == "topic" and x.get("key"):
                out[str(x["key"])] = x
    return out


@contextlib.contextmanager
def find_lock():
    d = find_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def save_record(p: pathlib.Path, r: dict) -> None:
    paths.write_atomic(p, json.dumps(r, ensure_ascii=False, indent=1) + "\n")
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)


def require_safe_root() -> None:
    if paths.is_alias_of_real_root():
        raise Stop("자료 루트가 실제 자료 루트(private/desk)와 같은 폴더를 다른 철자나 링크로 가리킨다. 기록을 쓰지 않는다.")


# ── 이미 만든 글 ──────────────────────────────────────────────────────────

def issue_rows() -> tuple[list[dict], str]:
    """자료 루트의 이슈마다 번호, 상태, 제목. 읽지 못하면 ([], 까닭)."""
    try:
        from ozl.issues import article, model, revisions
        out = []
        for r in revisions.status_rows():
            iid = r["id"]
            art = article.load_article(iid)
            title = (art or {}).get("title") or ((model.load_issue(iid).get("titles") or {}).get("chosen")) or ""
            state = str(r.get("shown_state") or r.get("work_state") or "")
            if r.get("approval") and r["approval"] != "미승인":
                state += f", {r['approval']}"
            out.append({"id": iid, "state": state, "title": _cell(title), "article": art is not None})
        return out, ""
    except Exception as e:      # 깨진 기록 하나 때문에 표를 못 찍지 않게 한다
        return [], f"{type(e).__name__}"


def made_map(recs, issues: list[dict]) -> dict[str, str]:
    """화제 번호 → '이미' 칸의 글. 대기열과 고르기 기록이 화제 번호와 이슈 번호를 함께 적은 것만 잇는다."""
    state = {i["id"]: i["state"] for i in issues}
    out: dict[str, str] = {}
    try:
        from ozl.ops import queue
        for j in queue.load()["items"]:
            tid, iid = j.get("topic_id"), j.get("issue_id")
            if isinstance(tid, str) and iid:
                out[tid] = f"글 {iid}" + (f"({state[iid]})" if iid in state else "")
            elif isinstance(tid, str) and j.get("state") in ("대기", "실행 중"):
                out.setdefault(tid, f"대기열 {j.get('job_id')}({j.get('state')})")
    except Exception:
        pass
    for key, x in latest_picks(recs).items():
        iid = x.get("issue")
        if iid:
            out[key] = f"글 {iid}" + (f"({state[iid]})" if iid in state else "")
        elif x.get("state") in (WAITING, RUNNING):
            out.setdefault(key, f"골라 둠({x.get('state')})")
    return out


# ── 표 ──────────────────────────────────────────────────────────────────

def view(board: dict, *, top: int, category: str | None, match: str | None, show_all: bool, now: datetime) -> dict:
    cands, skipped = candidates(board)
    partial = bool(board.get("base_day_partial"))
    cats: dict[str, int] = {}
    for c in cands:
        cats[str(c.get("category") or "기타")] = cats.get(str(c.get("category") or "기타"), 0) + 1
    if category and category not in cats:
        raise Stop(f"없는 분야: {category}. 판의 분야: " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])))
    recs = records()
    fold = folded(recs, now)
    issues, issue_err = issue_rows()
    made = made_map(recs, issues)
    pool = [c for c in cands if (not category or c.get("category") == category) and (not match or matches(c, match))]
    hidden = [c for c in pool if c["issue_id"] in fold]
    if not show_all:
        pool = [c for c in pool if c["issue_id"] not in fold]
    rows = []
    for n, c in enumerate(pool[:top], 1):
        day, outlets = _int(c.get("day_n")), _int(c.get("outlets_n"))
        prev = c.get("prev_day") if isinstance(c.get("prev_day"), dict) else {}
        iid = c["issue_id"]
        already = made.get(iid, "")
        if iid in fold:
            already = "; ".join(x for x in (already, f"버림({hm(fold[iid])} 까지 접음)") if x)
        rows.append({"n": n, "issue_id": iid, "title": _cell(c.get("title")), "lang": c.get("lang", "ko"),
                     "category": str(c.get("category") or "기타"), "story_rank": _int(c.get("story_rank")),
                     "day_n": day, "outlets_n": outlets, "outlets_prev": _int(prev.get("outlets_n")) if partial else None,
                     "zone": c.get("zone") if c.get("zone") in ZONE_WORD else None,
                     "sensitivity": sens(c)[0], "sensitivity_reason": sens(c)[1], "deck_blocked": deck_blocked(c),
                     "line": one_line(c), "already": already, "dropped": iid in fold})
    asof = parse_time(board.get("asof"))
    age = (now - asof) if asof else None
    searches = [s for s in board.get("searches_unmatched") or [] if isinstance(s, dict) and s.get("keyword")]
    if match:
        searches = [s for s in searches if match.casefold() in f"{s.get('keyword')} {s.get('news_title') or ''}".casefold()]
    searches.sort(key=lambda s: -(s.get("grade") if isinstance(s.get("grade"), (int, float)) else 0))
    return {"asof": board.get("asof"), "asof_text": hm(asof), "age_min": int(age.total_seconds() // 60) if age else None,
            "stale": asof is None or (age is not None and age > STALE), "base_day": board.get("base_day"),
            "base_day_partial": bool(board.get("base_day_partial")), "total": len(cands), "matched": len(pool),
            "skipped": skipped, "folded": len(hidden), "rows": rows, "categories": cats,
            "sources": [{"kind": s.get("kind"), "status": s.get("status")} for s in board.get("sources") or [] if isinstance(s, dict)],
            "missing": [str(m) for m in board.get("missing") or []],
            "searches_total": len(searches),
            "searches": [{"keyword": _cell(s["keyword"]), "traffic": _cell(s.get("traffic_raw")), "day": s.get("day")}
                         for s in searches[:SEARCHES_SHOWN]],
            "issues": issues, "issues_error": issue_err, "note": board.get("note") or ""}


def outlets_cell(n, prev, partial: bool) -> str:
    """매체 계열 수. 기준일이 아직 끝나지 않은 날이면 운영 화면처럼 어제 값을 함께 보인다."""
    if n is None:
        return TBD
    if not partial:
        return f"{n}곳"
    return f"오늘 {n}곳" + (f", 어제 {prev}곳" if prev is not None else "")


def render(v: dict, now: datetime) -> str:
    out = []
    head = f"기준 시각 {v['asof_text']} KST"
    if v["age_min"] is not None and v["age_min"] >= 0:
        head += f"({ago(timedelta(minutes=v['age_min']))})"
    if v["base_day"]:
        head += f" · 기준일 {v['base_day']}" + ("(아직 끝나지 않은 날)" if v["base_day_partial"] else "")
    out.append(head + f" · 후보 {v['total']}줄 가운데 {len(v['rows'])}줄")
    if v["stale"]:
        out.append(f"경고: 후보 판이 2시간보다 오래됐다. 매시 수집(launchd {PULSE_JOB})이 멈춘 것으로 보인다. {NO_COLLECT}")
    if v["sources"]:
        out.append("출처: " + ", ".join(f"{s['kind']} {s['status']}" for s in v["sources"])
                   + (" · 빠진 것: " + ", ".join(v["missing"]) if v["missing"] else ""))
    out.append("")
    out.append("| 번호 | 화제 번호 | 제목 | 분야 | 며칠째 | 매체 | 민감 | 한 줄 | 이미 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in v["rows"]:
        days = (f"{r['day_n']}일째" if r["day_n"] else TBD) + (f" · {ZONE_WORD[r['zone']]}" if r["zone"] else "")
        cat = r["category"] + ("(영문)" if r["lang"] != "ko" else "")
        sens_text = r["sensitivity"] + (f" · {DECK_OUT}" if r["deck_blocked"] else "")
        if r["sensitivity_reason"] and r["sensitivity"] != SENS_WORD["GREEN"]:
            sens_text += f": {r['sensitivity_reason']}"
        outlets = outlets_cell(r["outlets_n"], r["outlets_prev"], v["base_day_partial"])
        out.append(f"| {r['n']} | {r['issue_id']} | {r['title']} | {cat} | {days} | {outlets} | {sens_text} | {r['line']} | {r['already']} |")
    if not v["rows"]:
        out.append("| - | - | 조건에 맞는 후보가 없다 | | | | | | |")
    out.append("")
    out.append("순서는 큰 이야기 순서(story_rank)다. 화제 점수는 얼마나 화제인가만 재고 사실 여부와 무관하다."
               f" '{DECK_OUT}'는 민감 높음 소재라 덱을 만들지 않는다는 표시다(표에서 빼지는 않는다).")
    if v["matched"] > len(v["rows"]):
        out.append(f"조건에 맞는 후보가 {v['matched'] - len(v['rows'])}줄 더 있다(--top 으로 늘린다).")
    if v["folded"]:
        out.append(f"버려서 접어 둔 후보 {v['folded']}줄(--all 로 본다).")
    if v["skipped"]:
        out.append(f"번호 꼴이 아니어서 뺀 후보 {v['skipped']}줄.")
    out.append("분야별 줄 수: " + ", ".join(f"{k} {n}" for k, n in sorted(v["categories"].items(), key=lambda kv: -kv[1])))
    if v["searches"]:
        out.append("")
        out.append(f"검색에서만 보이는 낱말(이슈에 잇지 못한 급상승어 {v['searches_total']}개 가운데 {len(v['searches'])}개): "
                   + ", ".join(s["keyword"] + (f"({s['traffic']})" if s["traffic"] else "") for s in v["searches"]))
    out.append("")
    if v["issues_error"]:
        out.append(f"이미 만든 글: 이슈 기록을 읽지 못했다({v['issues_error']}). `ozl.issues status` 로 본다.")
    elif v["issues"]:
        out.append(f"이미 만든 글 {len(v['issues'])}건(제목을 위 표와 견준다):")
        out.extend(f"- {i['id']} · {i['state']} · {i['title'] or '(제목 없음)'}" for i in v["issues"])
    else:
        out.append("이미 만든 글: 없다.")
    return "\n".join(out)


def cmd_view(argv) -> int:
    ap = argparse.ArgumentParser(prog="board_view.py", description="후보 판을 큰 이야기 순서의 표로 찍는다(읽기만).",
                                 epilog="하위 명령: note(고르기 기록 쓰기), picks(최근 기록과 남은 건), result(만들기 결과 적기). "
                                        "각각 --help 가 있다.")
    ap.add_argument("--board", help="후보 판 파일(기본: 저장소의 private/pulse/out/board.json)")
    ap.add_argument("--top", type=int, default=15, help="보일 줄 수(기본 15)")
    ap.add_argument("--category", help="분야 하나만(판에 적힌 분야 이름 그대로)")
    ap.add_argument("--match", help="제목, 다른 이름, 대표 기사 제목에 이 낱말이 든 줄만")
    ap.add_argument("--all", action="store_true", help="버려서 접어 둔 줄도 보인다")
    ap.add_argument("--json", action="store_true", help="표 대신 JSON")
    ap.add_argument("--now", help="지금 시각(ISO, 시험용)")
    a = ap.parse_args(argv)
    if a.top < 1:
        raise Stop("--top 은 1 이상이다")
    now = now_kst(a.now)
    v = view(load_board(a.board or default_board()), top=a.top, category=a.category, match=a.match, show_all=a.all, now=now)
    print(json.dumps(v, ensure_ascii=False, indent=1) if a.json else render(v, now))
    return 0


# ── 고르기 기록 쓰기 ───────────────────────────────────────────────────────

def _pick_from(c: dict) -> dict:
    links = [{k: l.get(k) for k in ("title", "url", "outlet", "at")} for l in c.get("links") or [] if isinstance(l, dict)]
    return {"key": c["issue_id"], "kind": "topic", "title": _cell(c.get("title")), "category": str(c.get("category") or "기타"),
            "status_line": _cell(c.get("status_line")), "day_n": _int(c.get("day_n")), "outlets_n": _int(c.get("outlets_n")),
            "sensitivity": sens(c)[0], "sensitivity_reason": sens(c)[1], "deck_blocked": deck_blocked(c),
            "links": links[:LINKS_KEPT], "state": WAITING, "issue": None, "note": "", "updated_at": None}


def make_arg(x: dict) -> str:
    return x["key"] if x.get("kind") == "topic" else '"' + str(x.get("title", "")).replace('"', "'") + '"'


def cmd_note(argv) -> int:
    ap = argparse.ArgumentParser(prog="board_view.py note", description="고르기 기록을 <자료 루트>/find/ 에 쓴다.")
    ap.add_argument("--pick", nargs="+", action="extend", default=[], metavar="화제번호", help="고른 것(고른 순서대로 만든다)")
    ap.add_argument("--drop", nargs="+", action="extend", default=[], metavar="화제번호", help=f"버린 것({FOLD_DAYS}일 동안 표에서 접는다)")
    ap.add_argument("--add", action="append", default=[], metavar="제목", help="표에 없는 주제를 직접 넣는다(여러 번 줄 수 있다)")
    ap.add_argument("--board", help="후보 판 파일(기본: 저장소의 판)")
    ap.add_argument("--now", help="지금 시각(ISO, 시험용)")
    a = ap.parse_args(argv)
    adds = [_cell(t) for t in a.add]
    if not (a.pick or a.drop or adds):
        raise Stop("--pick, --drop, --add 가운데 하나는 준다")
    if any(not t or len(t) > TITLE_MAX for t in adds):
        raise Stop(f"--add 의 제목은 1~{TITLE_MAX}자다")
    ids = a.pick + a.drop
    if len(set(ids)) != len(ids):
        raise Stop("같은 화제 번호를 두 번 주었다(고른 것과 버린 것에 함께 있어도 안 된다)")
    bad = [i for i in ids if not TOPIC_ID.fullmatch(i)]
    if bad:
        raise Stop("화제 번호 꼴이 아니다(t20990101-001 꼴): " + ", ".join(bad) + ". 표의 '화제 번호' 칸을 그대로 준다")
    require_safe_root()
    now = now_kst(a.now)
    board_path = pathlib.Path(a.board) if a.board else default_board()
    # 직접 넣기만 하는 기록은 판이 없어도 쓴다
    board = load_board(board_path) if ids or board_path.exists() else {"candidates": []}
    by_id = {c["issue_id"]: c for c in candidates(board)[0]}
    gone = [i for i in ids if i not in by_id]
    if gone:
        raise Stop("후보 판에 없는 화제 번호: " + ", ".join(gone) + ". 표를 다시 찍어 번호를 확인한다. "
                   "판에서 빠진 화제를 만들려면 제목을 --add 로 넣는다")
    searches = {str(s.get("keyword")) for s in board.get("searches_unmatched") or [] if isinstance(s, dict)}
    until = now + timedelta(days=FOLD_DAYS)
    with find_lock():
        stamp, p = now, None
        while p is None or p.exists():
            p = find_dir() / (stamp.strftime("%Y%m%d_%H%M%S") + ".json")
            stamp += timedelta(seconds=1)
        code = p.stem
        picks = [_pick_from(by_id[i]) for i in a.pick]
        for n, t in enumerate(adds, 1):
            picks.append({"key": f"a{code}-{n}", "kind": "search" if t in searches else "manual", "title": t, "category": "",
                          "status_line": "", "day_n": None, "outlets_n": None, "sensitivity": TBD, "sensitivity_reason": "",
                          "deck_blocked": False, "links": [], "state": WAITING, "issue": None, "note": "", "updated_at": None})
        drops = [{"key": i, "title": _cell(by_id[i].get("title")), "until": until.isoformat(timespec="seconds")} for i in a.drop]
        rec = {"schema": FIND_SCHEMA, "at": now.isoformat(timespec="seconds"), "chosen_by": "사람",
               "board": {"path": paths.rel_or_abs(board_path), "asof": board.get("asof"), "calc_id": board.get("calc_id")},
               "picks": picks, "drops": drops}
        save_record(p, rec)
    print(f"고르기 기록: {paths.rel_or_abs(p)}")
    if picks:
        print(f"고른 것 {len(picks)}건(이 순서로 한 건씩 만든다):")
        for n, x in enumerate(picks, 1):
            print(f"  {n}. {x['key']} · {x['title']} → /ozl make {make_arg(x)}")
    if drops:
        print(f"버린 것 {len(drops)}건({hm(until)} 까지 표에서 접는다): " + ", ".join(f"{x['key']} {x['title']}" for x in drops))
    red = [x["key"] for x in picks if x["deck_blocked"]]
    if red:
        print("민감 높음: " + ", ".join(red) + f" 은(는) {DECK_OUT}다. 글도 만들기의 가드(사람에 관한 의혹, 선거 판세, 사생활이 중심인 소재)에 걸리면 멈춘다.")
    return 0


def remaining(recs, now: datetime) -> list[dict]:
    """최근 기록(RECENT_DAYS 안)에서 아직 '대기'인 줄. 가장 최근 기록의 것부터, 기록 안에서는 고른 순서대로."""
    out = []
    for p, r in reversed(recs):
        at = parse_time(r.get("at"))
        if at is None or now - at > timedelta(days=RECENT_DAYS):
            continue
        for x in r["picks"]:
            if x.get("state") == WAITING:
                out.append({"record": paths.rel_or_abs(p), "key": x.get("key"), "kind": x.get("kind"),
                            "title": x.get("title"), "make": make_arg(x)})
    return out


def cmd_picks(argv) -> int:
    ap = argparse.ArgumentParser(prog="board_view.py picks", description="최근 고르기 기록과 남은 건을 보인다(읽기만).")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=5, help="보일 기록 수(기본 5)")
    ap.add_argument("--now", help="지금 시각(ISO, 시험용)")
    a = ap.parse_args(argv)
    now = now_kst(a.now)
    recs = records()
    rest = remaining(recs, now)
    if a.json:
        print(json.dumps({"records": [{"file": paths.rel_or_abs(p), "at": r.get("at"), "picks": r["picks"], "drops": r["drops"]}
                                      for p, r in reversed(recs[-a.limit:])],
                          "remaining": rest, "next": rest[0] if rest else None}, ensure_ascii=False, indent=1))
        return 0
    if not recs:
        print("고르기 기록이 없다.")
        return 0
    print(f"고르기 기록 {len(recs)}건 가운데 최근 {min(a.limit, len(recs))}건. 남은 건(최근 {RECENT_DAYS}일, 대기) {len(rest)}건.")
    for p, r in reversed(recs[-a.limit:]):
        print(f"{p.name} · {hm(parse_time(r.get('at')))} · 고름 {len(r['picks'])}, 버림 {len(r['drops'])}")
        for x in r["picks"]:
            tail = f"글 {x['issue']}" if x.get("issue") else f"/ozl make {make_arg(x)}"
            note = f" · {x['note']}" if x.get("note") else ""
            print(f"  [{x.get('state')}] {x.get('key')} · {x.get('title')} → {tail}{note}")
    if rest:
        print(f"다음 건: {rest[0]['key']} · {rest[0]['title']} (기록 {rest[0]['record']})")
    return 0


def cmd_result(argv) -> int:
    ap = argparse.ArgumentParser(prog="board_view.py result", description="고르기 기록의 한 줄에 만들기 결과를 적는다.")
    ap.add_argument("key", help="고르기 기록의 key(화제 번호 t… 또는 직접 넣은 건의 a…)")
    ap.add_argument("--state", required=True, choices=STATES)
    ap.add_argument("--issue", help="이슈 번호(i20990101-01 꼴)")
    ap.add_argument("--note", help="남은 것이나 멈춘 까닭 한 줄")
    ap.add_argument("--record", help="기록 파일 이름이나 경로(없으면 그 key 가 든 가장 최근 기록)")
    ap.add_argument("--now", help="지금 시각(ISO, 시험용)")
    a = ap.parse_args(argv)
    if a.issue and not ISSUE_ID.fullmatch(a.issue):
        raise Stop(f"이슈 번호 꼴이 아니다: {a.issue}")
    require_safe_root()
    now = now_kst(a.now)
    with find_lock():
        recs = records()
        if a.record:
            name = pathlib.Path(a.record).name
            recs = [(p, r) for p, r in recs if p.name == name]
        hit = next(((p, r, x) for p, r in reversed(recs) for x in r["picks"] if x.get("key") == a.key), None)
        if hit is None:
            raise Stop(f"고르기 기록에 없는 key: {a.key}. `board_view.py picks` 로 본다")
        p, r, x = hit
        x["state"] = a.state
        if a.issue:
            x["issue"] = a.issue
        if a.note is not None:
            x["note"] = _cell(a.note)
        x["updated_at"] = now.isoformat(timespec="seconds")
        save_record(p, r)
    print(f"{p.name}: {x['key']} → {x['state']}" + (f", 글 {x['issue']}" if x.get("issue") else "") + (f", {x['note']}" if x.get("note") else ""))
    return 0


COMMANDS = {"note": cmd_note, "picks": cmd_picks, "result": cmd_result}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] in COMMANDS:
            return COMMANDS[argv[0]](argv[1:])
        return cmd_view(argv)
    except Stop as e:
        print(str(e), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
