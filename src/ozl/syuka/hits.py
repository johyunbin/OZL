"""방송 사건을 고정하고, 후보를 가린 두 판정과 중재로 적중을 계산한다."""
from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import db, ledger
from .catalog import ROOT

TIMINGS = ("시사", "중간", "상시")
GRADES = {"full": "계기가 같은 사건",
          "adjacent": "계기는 다르지만 핵심 개체(기업·나라·지표)나 핵심 근거 수치가 직접 겹침",
          "none": "직접 겹치지 않음"}
JUDGE_PROMPT = """후보마다 정확히 하나를 판정한다.
full은 계기가 같은 사건이다. adjacent는 계기가 다르지만 핵심 개체(기업·나라·지표)나 핵심 근거 수치가
직접 겹칠 때만 쓴다. 같은 분야나 막연히 비슷한 주제만으로는 안 된다. 나머지는 none이다.
full·adjacent면 가장 가까운 사건 하나의 event_id를, none이면 빈 값을 적는다.
근거는 한글 한 문장으로 적고 자료에 없는 사실은 넣지 않는다. 출력은 다음 꼴의 JSON 하나다.
{"judgments":[{"cand_id":"…","grade":"…","event_id":"…","reason":"…"}]}
"""


def _prediction(con, pid):
    row = con.execute("SELECT * FROM predictions WHERE prediction_id=?", (pid,)).fetchone()
    if row is None:
        raise ValueError(f"장부에 없는 예측: {pid}")
    return row


def _event_sets(con, pid=None):
    # 사건이 하나도 없는 회차는 broadcast_events에 넣을 행이 없어 고정 영수증을 쓴다.
    sql = """SELECT prediction_id, event_set, max(fixed_at) AS fixed_at
             FROM broadcast_events GROUP BY prediction_id, event_set
             UNION ALL
             SELECT json_extract(json,'$.prediction_id'), json_extract(json,'$.event_set'),
                    json_extract(json,'$.fixed_at') FROM ledger_files
             WHERE kind='events_doc' AND path='빈 사건 묶음'"""
    params = ()
    if pid is not None:
        sql = f"SELECT * FROM ({sql}) WHERE prediction_id=?"
        params = (pid,)
    return con.execute(sql + " ORDER BY fixed_at, event_set", params)


def _latest_sets(con):
    return {r["prediction_id"]: r["event_set"] for r in _event_sets(con)}


def _scope(con, pid, event_set, *, require_explicit=False):
    sets = [r["event_set"] for r in _event_sets(con, pid)]
    if not sets or (event_set is not None and event_set not in sets):
        raise ValueError(f"장부에 없는 사건 묶음: {pid} {event_set or ''}")
    if require_explicit and event_set is None and len(sets) > 1:
        raise ValueError(f"판정할 사건 묶음을 --event-set 으로 지정해야 한다: {', '.join(sets)}")
    return pid, event_set or sets[-1]


def _str_list(values):
    return isinstance(values, list) and all(isinstance(v, str) for v in values)


def _checked_event(raw, video):
    if not isinstance(raw, dict) or not re.fullmatch(r"E[0-9]{2,3}", str(raw.get("event_id", ""))):
        raise ValueError("event_id: E와 숫자 두세 자리여야 한다")
    for key in ("label", "summary"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ValueError(f"{raw['event_id']} {key}: 빈 글일 수 없다")
    if raw.get("timing") not in TIMINGS:
        raise ValueError("timing: 시사·중간·상시 중 하나여야 한다")
    for key in ("key_entities", "key_numbers"):
        if not _str_list(raw.get(key)):
            raise ValueError(f"{key}: 문자열 목록이어야 한다")
    event = {k: raw.get(k) for k in ("event_id", "label", "summary", "trigger", "start", "end",
                                      "minutes", "key_entities", "key_numbers", "timing", "segs")}
    event["video_id"] = raw.get("video_id", video)
    for key, default in (("minor", False), ("official", True)):
        value = raw.get(key, default)
        if value not in (0, 1):
            raise ValueError(f"{key}: 참 또는 거짓이어야 한다")
        event[key] = int(value)
    return event


def _segment_groups(segments, merges, minors):
    numbers = {s["seg"] for s in segments}
    if not set(minors) <= numbers:
        raise ValueError("--minor: 영상에 없는 토막")
    groups, taken = {}, set()
    for arg in merges:
        ids = [int(x) for x in arg.split(",")]
        if (len(ids) < 2 or ids != sorted(set(ids)) or not set(ids) <= numbers
                or taken.intersection(ids)):
            raise ValueError(f"--merge: 겹치거나 잘못된 토막 번호 {arg}")
        groups[ids[0]] = ids
        taken.update(ids)
    return [groups.get(i, [i]) for i in sorted(numbers) if i not in taken or i in groups]


def _mss(seconds):
    if seconds is None:
        return None
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02}"


def _v3_events(con, video, official, merges=(), minors=()):
    loaded = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v3_videos'").fetchone()
    row = loaded and con.execute("SELECT json FROM v3_videos WHERE video_id=?", (video,)).fetchone()
    if not row:
        raise ValueError(f"{video}: 먼저 load-v3")
    digest = ledger.save(con, "v3_extract", row["json"])
    segments = json.loads(row["json"])["segments"]
    by_number = {s["seg"]: s for s in segments}
    events = []
    for group in _segment_groups(segments, merges, minors):
        parts = [by_number[i] for i in group]
        first = parts[0]
        start = first["span"].get("start_sec")
        end = parts[-1]["span"].get("end_sec")
        entities = [name for s in parts for k in ("people", "orgs", "countries", "keywords") for name in s[k]]
        numbers = []
        for s in parts:
            for c in s["claims"]:
                if c["value"] is not None:
                    line = f"{c['point']}: {c['value']}{c['unit'] or ''}"
                    numbers.append(line + (f" ({c['as_of']})" if c["as_of"] else ""))
        events.append(dict(video_id=video, official=official, minor=bool(set(group).intersection(minors)),
                           start=_mss(start), end=_mss(end),
                           minutes=round((end-start)/60) if None not in (start, end) else None,
                           label=first["topic_line"], summary=" / ".join(s["question"] for s in parts),
                           trigger="", key_entities=list(dict.fromkeys(entities)),
                           key_numbers=list(dict.fromkeys(numbers)), timing=first["evergreen"], segs=group))
    return events, digest


def events(con, pid, from_json=None, from_v3=None, merge=(), minor=(), weekday=(), replace=False):
    with ledger.write(con):
        _prediction(con, pid)
        previous = {r["event_set"] for r in _event_sets(con, pid)}
        if previous and not replace:
            raise ValueError("이미 고정한 사건 묶음이 있다. 추가하려면 --replace")
        if from_json is not None:
            if merge or minor or weekday:
                raise ValueError("--merge, --minor, --weekday는 --from-v3에만 쓴다")
            raw = Path(from_json).read_bytes().decode("utf-8")
            document = json.loads(raw)
            if not isinstance(document, dict) or not isinstance(document.get("video_id"), str):
                raise ValueError("사건 문서에 video_id가 없다")
            video, items = document["video_id"], document.get("events")
            if not isinstance(items, list):
                raise ValueError("events: 목록이어야 한다")
            kind = "events_json"
            sources = [ledger.save(con, kind, raw, ledger.path_name(from_json))] * len(items)
        else:
            kind, video = "v3_extract", from_v3
            if video in weekday or len(set(weekday)) != len(weekday):
                raise ValueError("--weekday: 주 방송 영상이나 같은 주중 영상을 다시 지정할 수 없다")
            items, digest = _v3_events(con, video, 1, merge, minor)
            sources = [digest] * len(items)
            for vid in weekday:
                extra, digest = _v3_events(con, vid, 0)
                items.extend(extra)
                sources.extend([digest] * len(extra))
            for i, item in enumerate(items, 1):
                item["event_id"] = f"E{i:02}"
        items = [_checked_event(item, video) for item in items]
        if len({item["event_id"] for item in items}) != len(items):
            raise ValueError("event_id가 겹친다")
        canonical = json.dumps({"video_id": video, "events": items}, sort_keys=True,
                               ensure_ascii=False, separators=(",", ":"))
        es = ledger.save(con, "events_doc", canonical)[:12]
        if es in previous:
            raise ValueError(f"이미 있는 사건 묶음 {es} — 이후 명령에 --event-set {es} 를 준다")
        stamp = datetime.now(db.KST).isoformat(timespec="microseconds")
        if not items:
            receipt = dict(prediction_id=pid, event_set=es, fixed_at=stamp)
            ledger.save(con, "events_doc", ledger.dumps(receipt), "빈 사건 묶음")
        for item, digest in zip(items, sources):
            row = dict(item, prediction_id=pid, event_set=es, fixed_at=stamp,
                       source_kind=kind, source_sha256=digest)
            for key in ("key_entities", "key_numbers", "segs"):
                if row[key] is not None:
                    row[key] = ledger.dumps(row[key])
            con.execute(f"INSERT INTO broadcast_events ({','.join(row)}) VALUES "
                        f"({','.join(':'+k for k in row)})", row)
    return es


def _public_events(con, scope):
    rows = con.execute("""SELECT event_id,label,summary,trigger,key_entities,key_numbers FROM broadcast_events
                          WHERE prediction_id=? AND event_set=? ORDER BY CAST(substr(event_id,2) AS INTEGER)""", scope)
    return [dict(r) | {k: json.loads(r[k]) for k in ("key_entities", "key_numbers")} for r in rows]


def _mask(con, scope):
    return dict(con.execute("""SELECT cand_id, story_key FROM judge_masks
                               WHERE prediction_id=? AND event_set=? ORDER BY cand_id""", scope))


def _stories(con, pid):
    stories = {}
    for row in con.execute("SELECT * FROM prediction_items WHERE prediction_id=? ORDER BY set_name, rank", (pid,)):
        stories.setdefault(row["story_key"], {})[row["set_name"]] = row
    return stories


def _checked_json(path, expected):
    raw = Path(path).read_bytes()
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"해시 불일치: {path}")
    return json.loads(raw)


def _title_inputs(prediction, clusters):
    inputs = json.loads(prediction["json"]).get("input", {})
    if not isinstance(inputs, dict):
        raise ValueError("input: 객체여야 한다")
    board = inputs.get("board_file")
    if board is not None and not isinstance(board, str):
        raise ValueError("board_file: 파일 이름이어야 한다")
    board_path = ROOT / Path(prediction["file_path"]).parent / board if board else None
    titles = {}
    if board_path and board_path.exists():
        data = _checked_json(board_path, inputs.get("board_sha256"))
        rows = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(rows, list) or any(not isinstance(r, dict)
                or not isinstance(r.get("issue_id"), str) or not isinstance(r.get("title"), str) for r in rows):
            raise ValueError("방송 판 candidates: issue_id와 title이 필요하다")
        titles = {r["issue_id"]: r["title"] for r in rows}
    cluster_ids = {}
    if clusters is not None:
        data = _checked_json(clusters, inputs.get("codex_cluster_sha256"))
        rows = data.get("clusters") if isinstance(data, dict) else None
        if not isinstance(rows, list) or any(not isinstance(r, dict)
                or not isinstance(r.get("story_key"), str) or not _str_list(r.get("member_ids")) for r in rows):
            raise ValueError("clusters: story_key와 member_ids가 필요하다")
        cluster_ids = {r["story_key"]: r["member_ids"] for r in rows}
    return titles, cluster_ids


def _titles(stories, titles, cluster_ids):
    result = {}
    for key, sets in stories.items():
        baselines = [sets[s] for s in ("A", "B") if s in sets]
        if "pick" in sets:
            members = json.loads(sets["pick"]["member_ids"])
        else:
            members = cluster_ids.get(key, [r["top_id"] for r in baselines if r["top_id"]][:1])
        found = [titles[m] for m in members if m in titles and titles[m].strip()]
        if not found:
            found = [r["title"] for r in baselines if r["title"] and r["title"].strip()]
        result[key] = found
    return result


def _archive_packet(con, scope, packet_text, path, mask_text, mask_path):
    packet_sha = ledger.save(con, "mask_packet", packet_text, path)
    key_sha = ledger.save(con, "mask_key", mask_text, mask_path)
    # 같은 원문이 여러 회차에 쓰여도 원문 행을 고치지 않고 찾을 수 있게 한다.
    pid, es = scope
    ref = dict(prediction_id=pid, event_set=es, packet_sha256=packet_sha, key_sha256=key_sha)
    ledger.save(con, "mask_packet", ledger.dumps(ref), f"가림 묶음/{pid}/{es}")


def _archived_candidates(con, scope):
    pid, es = scope
    row = con.execute("""SELECT p.json FROM ledger_files ref JOIN ledger_files p
                         ON p.sha256=json_extract(ref.json,'$.packet_sha256')
                         WHERE ref.kind='mask_packet' AND ref.path=?""", (f"가림 묶음/{pid}/{es}",)).fetchone()
    if row is None:
        raise ValueError("먼저 score packet 또는 mask-import 로 가림 묶음을 고정해야 한다")
    doc = json.loads(row["json"])
    return doc["items"] if "items" in doc else doc["candidates"]


def _blind_candidates(items, mask):
    candidates, missing = [], []
    for item in items:
        cand = item["cand_id"]
        # 양끝 공백을 뺀 값으로 빈 제목과 중복을 가린다(공백 수만 다른 같은 제목이 자리를 차지하지 않게)
        titles = list(dict.fromkeys(t.strip() for t in item["titles"] if isinstance(t, str) and t.strip()))[:8]
        if not titles:
            missing.append(mask[cand])
        else:
            candidates.append(dict(cand_id=cand, label=titles[0], titles=titles))
    if missing:
        raise ValueError(f"기사 제목이 없는 이야기: {', '.join(sorted(missing))}")
    return sorted(candidates, key=lambda candidate: candidate["cand_id"])


def _put_mask(con, scope, mask):
    con.executemany("INSERT INTO judge_masks VALUES(?,?,?,?)",
                    [(*scope, cand, story) for cand, story in mask.items()])


def packet(con, pid, out, clusters=None, seed=None, event_set=None, skip_gate=False):
    with ledger.write(con):
        scope = _scope(con, pid, event_set)
        es = scope[1]
        stories = _stories(con, pid)
        mask = _mask(con, scope)
        title_inputs = _title_inputs(_prediction(con, pid), clusters)
        archived = con.execute("SELECT 1 FROM ledger_files WHERE kind='mask_packet' AND path=?",
                               (f"가림 묶음/{pid}/{es}",)).fetchone()
        if archived:
            items = _archived_candidates(con, scope)
        else:
            if not mask:
                keys = sorted(stories)
                rand = random.Random(seed) if seed is not None else secrets.SystemRandom()
                rand.shuffle(keys)
                mask = {f"K{i:02}": key for i, key in enumerate(keys, 1)}
                _put_mask(con, scope, mask)
            elif set(mask.values()) != set(stories):
                raise ValueError("가림 대응표와 예측의 이야기 집합이 다르다")
            titles = _titles(stories, *title_inputs)
            items = [dict(cand_id=k, titles=titles[s]) for k, s in mask.items()]
        candidates = _blind_candidates(items, mask)
        data = dict(events=_public_events(con, scope), candidates=candidates, grades=GRADES)
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        folder = Path(out).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"packet_{pid}_{es}.json"
        prompt = folder / f"prompt_judge_{pid}_{es}.txt"
        try:
            path.write_text(raw, encoding="utf-8")
            prompt.write_text(JUDGE_PROMPT + "\n" + raw, encoding="utf-8")
            if not skip_gate:
                gate = subprocess.run([sys.executable, "scripts/publish_gate.py", str(path), str(prompt)],
                                      cwd=ROOT, capture_output=True)
                if gate.returncode:
                    raise ValueError(f"가림 묶음 공개 검사 실패: 종료 코드 {gate.returncode}")
            if not archived:
                _archive_packet(con, scope, raw, ledger.path_name(path), ledger.dumps(mask), None)
        except BaseException:
            path.unlink(missing_ok=True)
            prompt.unlink(missing_ok=True)
            raise
    return path


def mask_import(con, pid, mask, packet, event_set=None):
    with ledger.write(con):
        if _prediction(con, pid)["kind"] != "retro":
            raise ValueError("가림 대응표 가져오기는 소급 시험에만 허용한다")
        scope = _scope(con, pid, event_set)
        raw_mask = Path(mask).read_bytes().decode("utf-8")
        raw_packet = Path(packet).read_bytes().decode("utf-8")
        mapping, document = json.loads(raw_mask), json.loads(raw_packet)
        stories = _stories(con, pid)
        if (not isinstance(mapping, dict) or len(mapping) != len(stories)
                or not all(re.fullmatch(r"K[0-9]{2,}", k) and isinstance(v, str) for k, v in mapping.items())
                or set(mapping.values()) != set(stories)):
            raise ValueError("가림 대응표와 예측의 이야기 집합이 다르다")
        items = document.get("items") if isinstance(document, dict) else None
        if not isinstance(items, list) or any(
                not isinstance(i, dict) or set(i) != {"cand_id", "label", "titles"}
                or not isinstance(i["cand_id"], str) or not isinstance(i["label"], str)
                or not _str_list(i["titles"]) for i in items):
            raise ValueError("가림 묶음 items 형식이 다르다")
        if len(items) != len(mapping) or {i["cand_id"] for i in items} != set(mapping):
            raise ValueError("가림 묶음과 대응표 번호가 다르다")
        _blind_candidates(items, mapping)
        old = _mask(con, scope)
        if old:
            if old != mapping or _archived_candidates(con, scope) != items:
                raise ValueError("이미 고정한 가림 묶음과 다르다")
            return
        _put_mask(con, scope, mapping)
        _archive_packet(con, scope, raw_packet, ledger.path_name(packet), raw_mask, ledger.path_name(mask))


# 판정 원문과 그 원문에서 다시 계산할 수 있는 결과를 구분한다.
WEIGHTS = {"full": 1.0, "adjacent": 0.5, "none": 0.0, "pending": 0.0}


def _judgments(con, scope):
    rows = con.execute(
        "SELECT story_key, judge, grade, event_id, reason FROM hit_judgments "
        "WHERE prediction_id=? AND event_set=? AND judge != 'final'", scope)
    result = {"codex": {}, "gemini": {}, "chatgpt": {}}
    for row in rows:
        result[row["judge"]][row["story_key"]] = {
            k: row[k] for k in ("grade", "event_id", "reason")}
    return result


def _agree(first, second):
    return first["grade"] == second["grade"] and first["event_id"] == second["event_id"]


def judge(con, pid, judge, path, event_set=None):
    if judge not in ("codex", "gemini", "chatgpt"):
        raise ValueError(f"판정자 이름을 확인한다: {judge}")
    raw = Path(path).read_bytes().decode("utf-8")
    doc = json.loads(raw)
    if not isinstance(doc, dict) or not isinstance(doc.get("judgments"), list):
        raise ValueError("judgments: 판정 목록이 필요하다")
    with ledger.write(con):
        scope = _scope(con, pid, event_set, require_explicit=True)
        mask = _mask(con, scope)
        if not mask and con.execute("SELECT 1 FROM prediction_items WHERE prediction_id=?", (pid,)).fetchone():
            raise ValueError("가림 번호가 없다 — 먼저 score packet 또는 mask-import")
        _blind_candidates(_archived_candidates(con, scope), mask)
        events = {r[0] for r in con.execute(
            "SELECT event_id FROM broadcast_events WHERE prediction_id=? AND event_set=?", scope)}
        previous = _judgments(con, scope)
        incoming = {}
        for item in doc["judgments"]:
            if not isinstance(item, dict):
                raise ValueError("judgments: 항목은 객체여야 한다")
            cand = item.get("cand_id")
            if not isinstance(cand, str) or cand not in mask or mask[cand] in incoming:
                raise ValueError(f"cand_id: 없거나 중복된 가림 번호 {cand!r}")
            story = mask[cand]
            grade = item.get("grade")
            event = item.get("event_id")
            if grade not in ("full", "adjacent", "none"):
                raise ValueError(f"{cand}: grade 값이 잘못됐다")
            if grade == "none":
                if event not in ("", None):
                    raise ValueError(f"{cand}: none이면 event_id는 빈 값이어야 한다")
                event = None
            elif not isinstance(event, str) or event not in events:
                raise ValueError(f"{cand}: 사건 묶음에 없는 event_id")
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{cand}: 근거 한 문장이 필요하다")
            if judge == "chatgpt":
                first, second = previous["codex"].get(story), previous["gemini"].get(story)
                if not first or not second or _agree(first, second):
                    raise ValueError(f"{cand}: 두 판정이 갈린 후보만 중재할 수 있다")
            incoming[story] = {"grade": grade, "event_id": event, "reason": reason}
        if judge != "chatgpt" and set(incoming) != set(mask.values()):
            raise ValueError("대응표의 모든 cand_id를 정확히 한 번씩 판정해야 한다")
        sha = ledger.save(con, "judge_" + judge, raw, path)
        changed = [s for s in incoming if previous[judge].get(s) != incoming[s]]
        if changed:
            con.execute("DELETE FROM weekly_metrics WHERE prediction_id=? AND event_set=?", scope)
            con.execute("DELETE FROM hit_judgments WHERE prediction_id=? AND event_set=? AND judge='final'", scope)
            if judge != "chatgpt":
                # 근거가 바뀐 건만 중재를 다시 받는다. 다른 건의 중재와 원문은 보존한다.
                con.executemany("DELETE FROM hit_judgments WHERE prediction_id=? AND event_set=? "
                                "AND story_key=? AND judge='chatgpt'", [(*scope, s) for s in changed])
        stamp = db.now()
        con.executemany(
            "INSERT OR REPLACE INTO hit_judgments(prediction_id,event_set,story_key,judge,grade,event_id,"
            "reason,source_sha256,judged_at) VALUES(?,?,?,?,?,?,?,?,?)",
            [(*scope, s, judge, v["grade"], v["event_id"], v["reason"], sha, stamp) for s, v in incoming.items()])
    return len(incoming)


def _assignment(weights):
    """직사각 헝가리안: 행 ≤ 열인 행렬에서 무게 합이 최대인 (행, 열) 짝을 구한다."""
    rows, cols = len(weights), len(weights[0])
    # 최소화 비용은 -무게. 0번 열은 이번에 더할 행을 연결하는 가상 시작점이다.
    row_price, col_price = [0] * (rows + 1), [0] * (cols + 1)
    owner = [0] * (cols + 1)
    for row in range(1, rows + 1):
        owner[0] = row
        column = 0
        visited = [False] * (cols + 1)
        slack = [float("inf")] * (cols + 1)
        previous = [0] * (cols + 1)
        while owner[column]:
            visited[column] = True
            current = owner[column]
            next_column = 0
            for j in range(1, cols + 1):
                if visited[j]:
                    continue
                reduced = -weights[current - 1][j - 1] - row_price[current] - col_price[j]
                if reduced < slack[j]:
                    slack[j] = reduced
                    previous[j] = column
                if slack[j] < slack[next_column]:
                    next_column = j
            delta = slack[next_column]
            for j in range(cols + 1):
                if visited[j]:
                    row_price[owner[j]] += delta
                    col_price[j] -= delta
                else:
                    slack[j] -= delta
            column = next_column
        # 빈 열까지 찾은 교대 경로에서 짝을 뒤집는다.
        while column:
            parent = previous[column]
            owner[column] = owner[parent]
            column = parent
    return [(owner[j] - 1, j - 1) for j in range(1, cols + 1) if owner[j]]


def match(items, judgments):
    """양의 판정만 일대일로 짝짓는다. 한 이야기의 여러 사건 후보도 함께 최적화한다."""
    stories = {item["story_key"]: item for item in items}
    edges = {}
    for judgment in judgments:
        key = judgment["story_key"], judgment["event_id"]
        grade = judgment["grade"]
        if key[0] in stories and WEIGHTS[grade] > WEIGHTS[edges.get(key, "none")]:
            edges[key] = grade
    if not edges:
        return {}
    keys = sorted(stories)
    events = sorted({event for _, event in edges})
    # 순위 합의 가능한 차이보다 큰 기수를 쓰면 하위 기준이 상위 기준을 뒤집지 못한다.
    rank_base = 1 + sum(abs(story["rank"]) for story in stories.values())
    count_base = 1 + len(keys)
    matrix = []
    for story in keys:
        row = []
        for event in events:
            grade = edges.get((story, event))
            if grade:
                primary = int(2 * WEIGHTS[grade]) * count_base + int(grade == "full")
                priority = primary * count_base + int(stories[story]["confident"])
                row.append(priority * rank_base - stories[story]["rank"])
            else:
                row.append(0)
        # 비용 0인 짝은 결과에 넣지 않는다. 행이 더 많으면 가상 열을 붙인다.
        matrix.append(row + [0] * max(0, len(keys) - len(events)))
    result = {}
    for i, j in _assignment(matrix):
        if matrix[i][j]:
            event, story = events[j], keys[i]
            result[event] = {"story_key": story, "grade": edges[story, event]}
    return result


def _metrics(items, finals, events, is_pick):
    matched = match(items, finals)
    by_timing = {t: {"n": 0, "full": 0, "weighted": 0.0} for t in ("시사", "중간", "상시")}
    weekday = {"n": 0, "full": 0, "weighted": 0.0}
    for event in events:
        if event["minor"]:
            continue
        bucket = by_timing[event["timing"]] if event["official"] else weekday
        grade = matched.get(event["event_id"], {}).get("grade", "none")
        bucket["n"] += 1
        bucket["full"] += int(grade == "full")
        bucket["weighted"] += WEIGHTS[grade]
    n = sum(b["n"] for b in by_timing.values())
    full = sum(b["full"] for b in by_timing.values())
    weighted = sum(b["weighted"] for b in by_timing.values())
    confident_n = confident_full = confident_weighted = precision = None
    if is_pick:
        confident = {row["story_key"] for row in items if row["confident"]}
        official_ids = {e["event_id"] for e in events if e["official"] and not e["minor"]}
        grades = [m["grade"] for eid, m in matched.items() if eid in official_ids and m["story_key"] in confident]
        confident_n = len(confident)
        confident_full = grades.count("full")
        confident_weighted = sum((WEIGHTS[g] for g in grades), 0.0)
        precision = confident_weighted / confident_n if confident_n else None
    return dict(events_n=n, full_hits=full, adjacent_hits=int(2 * (weighted - full)), weighted_hits=weighted,
                recall_full=full / n if n else None, recall_weighted=weighted / n if n else None,
                by_timing=ledger.dumps(by_timing), weekday=ledger.dumps(weekday), matched=ledger.dumps(matched),
                confident_n=confident_n, confident_full=confident_full, confident_weighted=confident_weighted,
                confident_precision=precision, vs_baselines=None)


def _save_metrics(con, scope, finals, judging, stamp):
    pid, es = scope
    kind, date = con.execute("SELECT kind,broadcast_date FROM predictions WHERE prediction_id=?", (pid,)).fetchone()
    events = list(con.execute("SELECT event_id,minor,official,timing FROM broadcast_events "
                              "WHERE prediction_id=? AND event_set=?", scope))
    sets = {"pick": [], "A": [], "B": []}
    for item in con.execute("SELECT set_name,story_key,rank,confident FROM prediction_items WHERE prediction_id=?",
                            (pid,)):
        sets[item["set_name"]].append(dict(item))
    confident = {s["story_key"] for s in sets["pick"] if s["confident"]}
    metrics = {}
    for name, items in sets.items():
        if name == "pick" and not items:
            continue
        for item in items:
            item["confident"] = item["story_key"] in confident
        metrics[name] = _metrics(items, finals, events, name == "pick")
    if "pick" in metrics:
        pick = metrics["pick"]
        comparisons = {}
        for name in ("A", "B"):
            base = metrics[name]
            weight = base["weighted_hits"]
            comparisons[name] = dict(diff_weighted=pick["weighted_hits"] - weight,
                                     ratio_weighted=pick["weighted_hits"] / weight if weight else None,
                                     diff_full=pick["full_hits"] - base["full_hits"])
        pick["vs_baselines"] = ledger.dumps(comparisons)
    status = "속보" if judging["pending"] else "확정"
    for name, metric in metrics.items():
        metric.update(prediction_id=pid, event_set=es, set_name=name, kind=kind, status=status,
                      broadcast_date=date, judging=ledger.dumps(judging), computed_at=stamp)
        columns = ", ".join(metric)
        placeholders = ", ".join("?" for _ in metric)
        con.execute(f"INSERT OR REPLACE INTO weekly_metrics({columns}) VALUES({placeholders})", tuple(metric.values()))


def finalize(con, pid, event_set=None, provisional=False, out=None):
    with ledger.write(con):
        scope = _scope(con, pid, event_set)
        mask = _mask(con, scope)
        all_stories = {r[0] for r in con.execute("SELECT DISTINCT story_key FROM prediction_items WHERE prediction_id=?", (pid,))}
        if not all_stories:
            raise ValueError("확정할 예측 이야기가 없다")
        if set(mask.values()) != all_stories:
            raise ValueError("대응표와 예측 이야기가 다르다 — 먼저 score packet 또는 mask-import")
        candidates = {c["cand_id"]: c for c in _blind_candidates(_archived_candidates(con, scope), mask)}
        votes = _judgments(con, scope)
        for name in ("codex", "gemini"):
            if votes[name].keys() != all_stories:
                raise ValueError(f"{name}: 전체 후보 판정이 필요하다")
        disputes, pending_ids, finals = [], [], []
        agreed_hits = []
        judging = {"n": len(mask), "agree": 0, "disputed": [], "arbitrated": [], "pending": [], "recheck": []}
        for cand, story in sorted(mask.items()):
            first, second = votes["codex"][story], votes["gemini"][story]
            if _agree(first, second):
                decision, rule = first, "일치"
                judging["agree"] += 1
                if first["grade"] in ("full", "adjacent"):
                    agreed_hits.append(cand)
            else:
                judging["disputed"].append(story)
                disputes.append(dict(**candidates[cand], judge_1=first, judge_2=second))
                if story in votes["chatgpt"]:
                    decision, rule = votes["chatgpt"][story], "중재"
                    judging["arbitrated"].append(story)
                else:
                    decision = {"grade": "pending", "event_id": None, "reason": None}
                    rule = "미중재"
                    pending_ids.append(cand)
                    judging["pending"].append(story)
            finals.append(dict(story_key=story, by_rule=rule, **decision))
        judging["rate"] = judging["agree"] / len(mask) if mask else None
        # 가림 번호 순으로 모았으므로 출력 폴더나 판정 입력 순서에 기대지 않는다.
        sample = random.Random(f"{pid}:{scope[1]}").choice(agreed_hits) if agreed_hits else None
        if sample is not None:
            judging["recheck"] = [mask[sample]]
        if out is not None:
            out = Path(out)
            out.mkdir(parents=True, exist_ok=True)
            packet = dict(events=_public_events(con, scope), disputed=disputes)
            (out / f"arbitrate_{pid}_{scope[1]}.json").write_text(
                json.dumps(packet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            recheck_path = out / f"recheck_{pid}_{scope[1]}.json"
            if sample is not None:
                candidate = candidates[sample]
                recheck = {"events": packet["events"],
                           "recheck": [{k: candidate[k] for k in ("cand_id", "label", "titles")}],
                           "note": "두 판정자가 같은 판정을 낸 건의 재확인 표본이다. 앞 판정은 보여 주지 않는다."}
                recheck_path.write_text(json.dumps(recheck, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            else:
                # 판정이 바뀐 뒤 같은 폴더를 다시 쓰면 예전 표본이 남지 않게 한다.
                recheck_path.unlink(missing_ok=True)
        stamp = db.now()
        con.executemany(
            "INSERT OR REPLACE INTO hit_judgments(prediction_id,event_set,story_key,judge,grade,event_id,"
            "reason,by_rule,judged_at) VALUES(?,?,?,'final',?,?,?,?,?)",
            [(*scope, f["story_key"], f["grade"], f["event_id"], f["reason"], f["by_rule"], stamp) for f in finals])
        if pending_ids and not provisional:
            print("중재 대기: " + ", ".join(pending_ids), file=sys.stderr)
            return 2
        _save_metrics(con, scope, finals, judging, stamp)
        return 0
