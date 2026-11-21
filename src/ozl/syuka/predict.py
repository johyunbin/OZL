"""방송 예측의 원문과 해시를 장부에 고정하고, 보관한 파일을 다시 대조한다."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date as Date, datetime, timedelta
from pathlib import Path

from . import db, ledger
from .catalog import ROOT

PRED_ROOT = ROOT / "private" / "syuka" / "predictions"
SCHEMA = "ozl.syuka.prediction/1"
STORY_KEY = re.compile(r"[a-z0-9_]{2,60}")
BASELINE_KEY = re.compile(r"[A-Za-z0-9_-]{2,60}")
DETAIL = {"A": "A_engine_top15", "B": "B_domain_top15"}


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_new(outputs):
    """한 출력이라도 만들 수 없으면 이번 호출에서 만든 파일만 거둔다."""
    created = []
    try:
        for path, content in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                created.append(path)
                stream.write(content)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _compact(c):
    title = c["title"]
    score = c["score"]
    return {"id": c["issue_id"], "rank": c["story_rank"], "score": None if score is None else round(score),
            "cat": c["category"], "lang": c["lang"], "day_n": c["day_n"],
            "first_day": c["first_day"], "state": c["state"],
            "fam3d": (c.get("story") or {}).get("families_3d"),
            "prev_articles": (c.get("prev_day") or {}).get("articles_n"),
            "blocked": bool(c["deck_blocked"]), "sens": (c.get("sensitivity") or {}).get("level"),
            "title": title, "aliases": c.get("aliases") or [],
            "more_titles": [link["title"] for link in c.get("links", []) if link["title"] != title][:2]}


def prepare(con, board, out, weeks=8, asof=None):
    """판의 후보와 기준 시각 직전의 방송 제목을 예측 입력으로 뽑는다."""
    data = json.loads(Path(board).read_bytes())
    if weeks < 0:
        raise ValueError("조회 기간은 음수일 수 없다")
    end = datetime.fromisoformat(data["asof"] if asof is None else asof)
    if end.tzinfo is None:
        raise ValueError("asof: 시간대가 있는 ISO 시각이어야 한다")
    end = end.astimezone(db.KST)
    start = end - timedelta(weeks=weeks)
    rows = con.execute("""SELECT upload_at, title FROM videos
                          WHERE kind IN ('본편', '생방송 전체') AND upload_at >= ? AND upload_at < ?
                          ORDER BY upload_at, video_id""",
                       (start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M")))
    titles = "".join(f"{stamp[:10]} {title}\n" for stamp, title in rows)
    compact = [_compact(c) for c in data["candidates"]]
    folder = Path(out)
    _write_new([(folder / "candidates_compact.json", json.dumps(compact, ensure_ascii=False, indent=0)),
                (folder / "recent_titles_8w.txt", titles)])


def _top_stories(candidates, story_keys, n):
    chosen = {}
    for c in candidates:
        if len(chosen) == n:
            break
        issue = c["issue_id"]
        key = story_keys.get(issue, issue)
        if key not in chosen:
            chosen[key] = {"story_key": key, "top_id": issue, "rank": c["story_rank"],
                           "cat": c["category"], "title": c["title"]}
    return list(chosen.values())


def baselines(board, clusters, out, n=15):
    """같은 판과 묶음에서 전체 후보(A)와 덱 허용 분야 후보(B)의 기준선을 만든다."""
    if n < 0:
        raise ValueError("기준선 건수는 음수일 수 없다")
    board_raw = Path(board).read_bytes()
    clusters_raw = Path(clusters).read_bytes()
    story_keys = {issue: group["story_key"] for group in json.loads(clusters_raw)["clusters"]
                  for issue in group["member_ids"]}
    ranked = sorted((c for c in json.loads(board_raw)["candidates"] if c["story_rank"] is not None),
                    key=lambda c: (c["story_rank"], c["score_raw"] is None, -(c["score_raw"] or 0)))
    domain = (c for c in ranked if c["category"] in ("경제", "국제", "과학기술") and not c["deck_blocked"])
    a = _top_stories(ranked, story_keys, n)
    b = _top_stories(domain, story_keys, n)
    result = {"rule_A": f"전체 후보를 story_rank 오름차순, score_raw 내림차순으로 보고 이야기마다 첫 후보만 {n}건까지.",
              "rule_B": f"경제·국제·과학기술의 덱 허용 후보에 같은 순서와 이야기 기준을 적용해 {n}건까지.",
              DETAIL["A"]: a, DETAIL["B"]: b,
              "A": [r["story_key"] for r in a], "B": [r["story_key"] for r in b],
              "board_sha256": hashlib.sha256(board_raw).hexdigest(),
              "clusters_sha256": hashlib.sha256(clusters_raw).hexdigest()}
    _write_new([(Path(out), json.dumps(result, ensure_ascii=False, indent=1) + "\n")])


def _broadcast(doc):
    description = doc.get("broadcast", "")
    if not isinstance(description, str):
        raise ValueError("broadcast: 방송 날짜로 시작하는 문자열이어야 한다")
    match = re.match(r"\d{4}-\d{2}-\d{2}(?!\d)", description)
    day = doc.get("broadcast_date", match[0] if match else None)
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("broadcast_date: YYYY-MM-DD 방송 날짜가 필요하다")
    if match and match[0] != day:
        raise ValueError("broadcast: 방송 날짜와 맞지 않는다")
    try:
        date = Date.fromisoformat(day)
        at = None
        if "broadcast_at" in doc:
            stamp = doc["broadcast_at"]
            if not isinstance(stamp, str) or len(stamp) <= 10:
                raise ValueError
            at = datetime.fromisoformat(stamp)
            if at.tzinfo is None:
                at = at.replace(tzinfo=db.KST)
        elif clock := re.search(r"(?<!\d)(\d{2}):(\d{2})(?!\d)", description):
            at = datetime.fromisoformat(f"{day}T{clock[0]}").replace(tzinfo=db.KST)
    except ValueError:
        raise ValueError("broadcast_date/broadcast_at: 올바른 방송 날짜와 시각이어야 한다") from None
    if at and at.astimezone(db.KST).date() != date:
        raise ValueError("broadcast_at: 방송 날짜와 맞지 않는다")
    return date, at


def _is_key(value, pattern=STORY_KEY):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _baselines(doc, name):
    base = doc["baselines"]
    if not isinstance(base, dict) or not isinstance(base.get(name), list):
        raise ValueError(f"baselines.{name}: 목록이어야 한다")
    detail = base.get("detail", {})
    if not isinstance(detail, dict) or not isinstance(detail.get(DETAIL[name], []), list):
        raise ValueError(f"baselines.detail.{DETAIL[name]}: 목록이어야 한다")
    by_key = {}
    for item in detail.get(DETAIL[name], []):
        if not isinstance(item, dict) or not _is_key(item.get("story_key"), BASELINE_KEY):
            raise ValueError(f"baselines.detail.{DETAIL[name]}: story_key가 필요하다")
        by_key[item["story_key"]] = item
    seen = set()
    for item in base[name]:
        if isinstance(item, str):
            item = by_key.get(item, {"story_key": item})
        elif isinstance(item, dict):
            missing = {"top_id", "rank", "cat", "title"} - item.keys()
            if missing:
                raise ValueError(f"baselines.{name}: 빠진 칸 {', '.join(sorted(missing))}")
        if not isinstance(item, dict) or not _is_key(item.get("story_key"), BASELINE_KEY):
            raise ValueError(f"baselines.{name}: story_key가 올바르지 않다")
        key = item["story_key"]
        if key in seen:
            raise ValueError(f"baselines.{name}: story_key 중복 ({key})")
        seen.add(key)
        for field in ("label", "cat", "title", "top_id"):
            if item.get(field) is not None and not isinstance(item[field], str):
                raise ValueError(f"baselines.{name}: {field}는 문자열이어야 한다")
        if item.get("rank") is not None and type(item["rank"]) is not int:
            raise ValueError(f"baselines.{name}: rank는 정수여야 한다")
        yield item


def validate(doc, kind) -> list[str]:
    if not isinstance(doc, dict):
        return ["예측: JSON 객체여야 한다"]
    errors = []
    if doc.get("schema") != SCHEMA:
        errors.append(f"schema: {SCHEMA}여야 한다")
    if kind not in ("official", "retro") or doc.get("kind", "official") != kind:
        errors.append("kind: 파일의 종류와 --retro 선택이 다르다")
    try:
        fixed = datetime.fromisoformat(doc.get("fixed_at", ""))
        if fixed.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError):
        fixed = None
        errors.append("fixed_at: 시간대가 붙은 ISO 시각이어야 한다")
    try:
        date, at = _broadcast(doc)
        if fixed and kind == "official":
            late = fixed >= at if at else fixed.astimezone(db.KST).date() > date
            if late:
                errors.append("fixed_at: 공식 예측은 방송 전에 고정해야 한다")
    except ValueError as exc:
        errors.append(str(exc))

    picks = doc.get("picks")
    if not isinstance(picks, list):
        errors.append("picks: 목록이어야 한다")
        picks = []
    if (kind == "official" and not picks) or len(picks) > 30:
        errors.append("picks: 공식은 1~30건, 소급 시험은 0~30건이다")
    seen, marked = set(), set()
    for index, pick in enumerate(picks):
        field = f"picks[{index}]"
        if not isinstance(pick, dict):
            errors.append(f"{field}: 객체여야 한다")
            continue
        key = pick.get("story_key")
        if not _is_key(key) or key in seen:
            errors.append(f"{field}.story_key: 허용하지 않는 값 또는 중복")
        else:
            seen.add(key)
            if pick.get("confident") is True:
                marked.add(key)
        if type(pick.get("n")) is not int:
            errors.append(f"{field}.n: 정수여야 한다")
        for name in ("label", "category"):
            if not isinstance(pick.get(name), str) or not pick[name].strip():
                errors.append(f"{field}.{name}: 빈 문자열일 수 없다")
        members = pick.get("member_ids")
        if not isinstance(members, list) or not members or not all(isinstance(m, str) for m in members):
            errors.append(f"{field}.member_ids: 문자열이 하나 이상 있어야 한다")
        if type(pick.get("confident")) is not bool:
            errors.append(f"{field}.confident: 참·거짓이어야 한다")
        if pick.get("overlap") is not None and not isinstance(pick["overlap"], str):
            errors.append(f"{field}.overlap: 문자열이어야 한다")
        if pick.get("engine_rank") is not None and type(pick["engine_rank"]) is not int:
            errors.append(f"{field}.engine_rank: 정수여야 한다")

    confident = doc.get("confident")
    if (not isinstance(confident, list) or len(confident) > 3 or not all(_is_key(k) for k in confident)
            or len(set(confident)) != len(confident) or set(confident) != marked):
        errors.append("confident: 확신으로 표시한 picks와 같은 0~3개의 고유한 story_key여야 한다")
    if "baselines" not in doc:
        errors.append("baselines: A와 B 목록이 필요하다")
    else:
        baseline_count = 0
        for name in DETAIL:
            try:
                baseline_count += len(list(_baselines(doc, name)))
            except ValueError as exc:
                errors.append(str(exc))
        if kind == "retro" and not baseline_count:
            errors.append("소급 시험은 기준선 A 또는 B에 후보가 하나 이상 있어야 한다")
    skeletons = doc.get("skeletons", [])
    if not isinstance(skeletons, list) or not all(
        isinstance(s, dict) and _is_key(s.get("story_key")) and s["story_key"] in seen for s in skeletons
    ):
        errors.append("skeletons: picks에 있는 story_key만 써야 한다")
    return errors


def _items(doc):
    for item in doc["picks"]:
        yield ("pick", item["n"], item["story_key"], item["label"], item["category"], item["confident"],
               item.get("overlap"), ledger.dumps(item["member_ids"]), None, item.get("engine_rank"), None)
    for name in DETAIL:
        for rank, item in enumerate(_baselines(doc, name), 1):
            top = item.get("top_id")
            yield (name, rank, item["story_key"], item.get("label"), item.get("cat"), 0, None,
                   ledger.dumps([top] if top else []), top, item.get("rank"), item.get("title"))


def _insert(con, path, raw, doc, kind, revises):
    """날짜와 개정을 검사하고 원문과 항목을 같은 쓰기 트랜잭션에 넣는다."""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    date, at = _broadcast(doc)
    day = date.isoformat()
    row = con.execute("SELECT prediction_id FROM predictions WHERE sha256=?", (digest,)).fetchone()
    if row:
        return row[0], digest, False
    previous = {r[0] for r in con.execute("SELECT prediction_id FROM predictions WHERE broadcast_date=?", (day,))}
    if (previous or revises is not None) and revises not in previous:
        raise ValueError(f"revises: {day}의 기존 예측 id를 지정해야 한다")
    pid = f"{day}-{digest[:10]}"
    con.execute("""INSERT INTO predictions
        (prediction_id,broadcast_date,broadcast_at,kind,file_path,sha256,fixed_at,registered_at,revises,schema,json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (pid, day, at.isoformat() if at else None, kind,
        ledger.path_name(path), digest, doc["fixed_at"], db.now(), revises, SCHEMA, raw))
    con.executemany("""INSERT INTO prediction_items
        (prediction_id,set_name,rank,story_key,label,category,confident,overlap,member_ids,top_id,engine_rank,title)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", ((pid, *item) for item in _items(doc)))
    return pid, digest, True


def _check(doc, kind):
    if errors := validate(doc, kind):
        raise ValueError("\n".join(errors))


def register(con, path, kind="official", revises=None) -> str:
    path = Path(path)
    raw = path.read_bytes().decode("utf-8")
    doc = json.loads(raw)
    _check(doc, kind)
    ledger.ensure(con)
    with ledger.write(con):
        pid, digest, added = _insert(con, path, raw, doc, kind, revises)
        if added and path.stat().st_mode & 0o222:
            path.chmod(0o444)
        if sha256_file(path) != digest:
            raise ValueError("등록 중 예측 파일의 해시가 바뀌었다")
    return pid


def fix(con, draft_path, date, revises=None, now=None) -> tuple[Path, str]:
    doc = json.loads(Path(draft_path).read_bytes())
    if not isinstance(doc, dict):
        raise ValueError("예측: JSON 객체여야 한다")
    now = now if now is not None else datetime.now(db.KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=db.KST)
    now = now.astimezone(db.KST)
    doc["fixed_at"] = now.isoformat(timespec="seconds")
    _check(doc, "official")
    if _broadcast(doc)[0].isoformat() != date:
        raise ValueError("--date: 초안의 방송 날짜와 다르다")
    folder = PRED_ROOT / date
    path = folder / f"prediction_{now:%Y%m%d_%H%M%S}_fixed.json"
    hash_path = folder / "HASH.txt"
    raw = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"

    ledger.ensure(con)
    wrote_file = False
    hash_offset = None
    hash_existed = False
    con.execute("BEGIN IMMEDIATE")
    try:
        if path.exists():
            raise FileExistsError(f"이미 고정 파일이 있다: {path}")
        pid, digest, _ = _insert(con, path, raw, doc, "official", revises)
        folder.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as output:
            wrote_file = True
            output.write(raw)
        path.chmod(0o444)
        if sha256_file(path) != digest:
            raise ValueError("고정 중 예측 파일의 해시가 바뀌었다")
        hash_existed = hash_path.exists()
        with hash_path.open("a+b") as output:
            hash_offset = output.tell()
            if hash_offset:
                output.seek(-1, 2)
                if output.read(1) != b"\n":
                    output.write(b"\n")
            line = f"{digest}  {path.name}  (고정 {doc['fixed_at']})\n"
            output.write(line.encode("utf-8"))
        con.commit()
    except BaseException:
        try:
            if wrote_file:
                path.unlink(missing_ok=True)
            if hash_offset is not None:
                if hash_existed:
                    with hash_path.open("r+b") as output:
                        output.truncate(hash_offset)
                else:
                    hash_path.unlink(missing_ok=True)
        finally:
            con.rollback()
        raise
    return path, pid


def verify(con, prediction_id=None, expect=None) -> list[dict]:
    ledger.ensure(con)
    sql = "SELECT prediction_id, file_path, sha256 FROM predictions"
    args = ()
    if prediction_id is not None:
        sql += " WHERE prediction_id=?"
        args = (prediction_id,)
    results = []
    for pid, filename, digest in con.execute(sql + " ORDER BY broadcast_date, prediction_id", args):
        path = ROOT / filename
        problems = []
        actual = recorded = None
        try:
            actual = sha256_file(path)
            if actual != digest:
                problems.append("파일과 장부 해시가 다르다")
        except OSError as exc:
            problems.append(f"파일을 읽지 못했다: {exc}")
        hash_path = path.with_name("HASH.txt")
        if hash_path.exists():
            try:
                lines = hash_path.read_text(encoding="utf-8").splitlines()
                hashes = []
                for line in lines:
                    fields = line.split("  ", 2)
                    if len(fields) >= 2 and fields[1] == path.name:
                        hashes.append(fields[0])
                if hashes:
                    recorded = hashes[0]
                if not hashes or any(h != digest for h in hashes):
                    problems.append("HASH.txt에 해당 파일이 없거나 해시가 다르다")
            except (OSError, UnicodeError) as exc:
                problems.append(f"HASH.txt를 읽지 못했다: {exc}")
        if expect is not None and (expect != digest or expect != actual):
            problems.append("지정한 해시와 다르다")
        results.append(dict(prediction_id=pid, file=filename, sha256_file=actual, sha256_ledger=digest,
                            sha256_hashtxt=recorded, expect=expect, ok=not problems, problems=problems))
    if prediction_id is not None and not results:
        raise ValueError(f"장부에 없는 예측: {prediction_id}")
    return results


def list_predictions(con) -> list[dict]:
    ledger.ensure(con)
    return [dict(row) for row in con.execute("""
        SELECT p.prediction_id, p.kind, p.broadcast_date, p.fixed_at, p.sha256,
               count(CASE WHEN i.set_name='pick' THEN 1 END) AS pick,
               count(CASE WHEN i.set_name='A' THEN 1 END) AS A,
               count(CASE WHEN i.set_name='B' THEN 1 END) AS B
        FROM predictions p LEFT JOIN prediction_items i USING (prediction_id)
        GROUP BY p.prediction_id ORDER BY p.broadcast_date, p.fixed_at, p.prediction_id
    """)]
