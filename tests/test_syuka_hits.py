"""방송 사건과 가림 판정, 일대일 짝짓기를 임시 장부의 가상 자료로 대조한다."""
import hashlib
import json
import random
import subprocess

import pytest

from ozl.syuka import __main__ as cli
from ozl.syuka import db, db_v3, hits
from test_syuka_v3 import doc as video_doc
from test_syuka_v3 import seg


def write(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(folder, *args):
    return cli.main(["--db", str(folder / "test.db"), *map(str, args)])


def register(folder, retro=False):
    keys = [f"story_{i}" for i in range(10)]
    board = write(folder / "board.json", {"candidates": [
        {"issue_id": f"id_{i}", "title": f"가상 소식 {i}"} for i in range(1, 22)]})
    clusters = write(folder / "clusters.json", {"clusters": [
        {"story_key": keys[5], "member_ids": ["id_5", "id_10", "id_5"]}]})
    picks = [{"n": i, "story_key": keys[i], "label": f"내부 선정명 {i}", "category": "가상 분야",
              "member_ids": [f"id_{i}"], "confident": i in (1, 3)} for i in range(1, 5)]
    picks[0]["member_ids"] += [f"id_{i}" for i in range(11, 22)]
    def baseline(numbers):
        return [{"story_key": keys[i], "top_id": f"id_{i}", "rank": rank, "cat": "가상 분야",
                 "title": f"가상 소식 {i}"} for rank, i in enumerate(numbers, 1)]

    doc = {"schema": "ozl.syuka.prediction/1", "kind": "retro" if retro else "official",
           "fixed_at": "2026-02-01T10:00:00+09:00", "broadcast_date": "2026-02-08",
           "input": {"board_file": board.name, "board_sha256": digest(board),
                     "codex_cluster_sha256": digest(clusters)},
           "picks": [] if retro else picks, "confident": [] if retro else [keys[1], keys[3]],
           "baselines": {"A": baseline([2, 5, 6, 9]), "B": baseline([4, 6, 7, 8])}}
    path = write(folder / "prediction.json", doc)
    assert run(folder, "predict", "add", path, *(["--retro"] if retro else [])) == 0
    return f"2026-02-08-{digest(path)[:10]}"


def event_doc():
    rows = [{"event_id": f"E{i:02}", "start": f"{i}:00", "end": f"{i+1}:00", "minutes": 1,
             "label": f"가상 발표 {i}", "summary": f"가상 기관이 실험 {i}번을 정리했다.",
             "trigger": "가상 보고서", "key_entities": ["상상 연구소"], "key_numbers": [],
             "timing": timing, "minor": i == 6}
            for i, timing in enumerate(["시사", "시사", "시사", "중간", "상시", "중간", "상시"], 1)]
    rows[-1].update(official=False, video_id="vidTEST0002")
    return {"video_id": "vidTEST0001", "events": rows}


@pytest.fixture
def con(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def fixed(tmp_path, con):
    pid = register(tmp_path)
    path = write(tmp_path / "events.json", event_doc())
    assert run(tmp_path, "score", "events", pid, "--from-json", path) == 0
    es, = con.execute("SELECT DISTINCT event_set FROM broadcast_events").fetchone()
    return pid, es


def test_events_raw_content_address_and_replace(tmp_path, con, fixed):
    pid, original = fixed
    path = tmp_path / "events.json"
    assert tuple(con.execute("SELECT DISTINCT source_kind, source_sha256 FROM broadcast_events").fetchone()) == (
        "events_json", digest(path))
    assert con.execute("SELECT json FROM ledger_files WHERE sha256=?", (digest(path),)).fetchone()[0] == path.read_text()
    stored = json.loads(con.execute("SELECT json FROM ledger_files WHERE kind='events_doc'").fetchone()[0])
    compact = json.dumps(stored, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(compact.encode()).hexdigest()[:12] == original
    changed = event_doc()
    changed["events"][0]["label"] = "가상 기관의 정정 발표"
    write(path, changed)
    args = ("score", "events", pid, "--from-json", path)
    assert run(tmp_path, *args) == 1
    assert run(tmp_path, *args, "--replace") == 0
    versions = {r[0] for r in con.execute("SELECT DISTINCT event_set FROM broadcast_events")}
    newer, = versions - {original}
    assert len(versions) == 2
    args = ("score", "packet", pid, "--out", tmp_path, "--clusters", tmp_path / "clusters.json", "--skip-gate")
    assert run(tmp_path, *args) == 0
    assert (tmp_path / f"packet_{pid}_{newer}.json").exists()
    assert run(tmp_path, *args, "--event-set", original) == 0
    assert (tmp_path / f"packet_{pid}_{original}.json").exists()


def test_events_from_v3_and_weekday(tmp_path, con, capsys):
    pid = register(tmp_path)
    args = ("score", "events", pid, "--from-v3", "vidTEST0001", "--merge", "3,4",
            "--minor", 4, "--weekday", "vidTEST0002")
    assert run(tmp_path, *args) == 1
    assert "먼저 load-v3" in capsys.readouterr().err
    slices = [seg(i, span={"start_sec": 6000 + 100*i, "end_sec": 6100 + 100*i},
                  question=f"가상 도시의 {i}번째 결정은?", topic_line=f"가상 결정 {i}",
                  keywords=[f"실험 {i}"]) for i in range(1, 5)]
    for vid, parts in [("vidTEST0001", slices), ("vidTEST0002", slices[:1])]:
        db_v3.put(con, video_doc(video_id=vid, segments=parts, n_segments=len(parts)))
    assert run(tmp_path, *args) == 0
    rows = list(con.execute("SELECT * FROM broadcast_events ORDER BY event_id"))
    assert [r["event_id"] for r in rows] == ["E01", "E02", "E03", "E04"]
    merged = rows[2]
    assert (merged["start"], merged["end"], merged["minutes"]) == ("105:00", "108:20", 3)
    assert (merged["label"], merged["summary"], merged["timing"]) == (
        slices[2]["topic_line"], " / ".join(s["question"] for s in slices[2:]), slices[2]["evergreen"])
    assert json.loads(merged["key_entities"]) == [
        *slices[2]["people"], *slices[2]["orgs"], *slices[2]["countries"], "실험 3", "실험 4"]
    assert json.loads(merged["key_numbers"]) == ["생필품 값 상승: 12% (2025-05)", "금리 인상으로 대응: 1.5%p (2025-04)"]
    assert (json.loads(merged["segs"]), merged["minor"], merged["official"]) == ([3, 4], 1, 1)
    assert (rows[-1]["official"], rows[-1]["video_id"], json.loads(rows[-1]["segs"])) == (0, "vidTEST0002", [1])
    for row in rows:
        raw, = con.execute("SELECT json FROM v3_videos WHERE video_id=?", (row["video_id"],)).fetchone()
        sha = hashlib.sha256(raw.encode()).hexdigest()
        assert (row["source_kind"], row["source_sha256"]) == ("v3_extract", sha)
        assert tuple(con.execute("SELECT kind,json FROM ledger_files WHERE sha256=?", (sha,)).fetchone()) == ("v3_extract", raw)


def test_empty_event_set_keeps_old_events_and_has_null_recall(tmp_path, con, fixed, capsys):
    pid, old_set = fixed
    path = write(tmp_path / "empty.json", {"video_id": "vidTEST0001", "events": []})
    assert run(tmp_path, "score", "events", pid, "--from-json", path, "--replace") == 0
    assert run(tmp_path, "score", "packet", pid, "--out", tmp_path, "--skip-gate") == 0
    capsys.readouterr()
    assert run(tmp_path, "hits", pid, "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["events"] == [] and report["event_set"] != old_set
    packet = json.loads((tmp_path / f"packet_{pid}_{report['event_set']}.json").read_text())
    none = [{"cand_id": c["cand_id"], "grade": "none", "event_id": "", "reason": "비교할 사건이 없다."}
            for c in packet["candidates"]]
    for name in ("codex", "gemini"):
        assert submit(tmp_path, pid, name, none, "--event-set", report["event_set"]) == 0
    assert run(tmp_path, "score", "finalize", pid) == 0
    metrics = con.execute("SELECT events_n, recall_weighted FROM weekly_metrics").fetchall()
    assert list(map(tuple, metrics)) == [(0, None)] * 3
    capsys.readouterr()
    assert run(tmp_path, "hits", pid, "--event-set", old_set, "--json") == 0
    assert len(json.loads(capsys.readouterr().out)["events"]) == 7


@pytest.mark.parametrize("change", [
    {"event_id": "E01"}, {"event_id": "3"}, {"label": "  "}, {"summary": ""},
    {"key_numbers": [9]}, {"key_entities": "상상 연구소"}, {"timing": "가끔"},
])
def test_invalid_replacement_preserves_original(tmp_path, con, fixed, change):
    pid, original = fixed
    doc = event_doc()
    doc["events"][-1].update(change)
    path = write(tmp_path / "bad.json", doc)
    assert run(tmp_path, "score", "events", pid, "--replace", "--from-json", path) == 1
    assert list(map(tuple, con.execute("SELECT DISTINCT event_set FROM broadcast_events"))) == [(original,)]


@pytest.fixture
def masked(tmp_path, con, fixed):
    pid, es = fixed
    out = tmp_path / "blind"
    args = ("score", "packet", pid, "--clusters", tmp_path / "clusters.json", "--out", out, "--skip-gate")
    assert run(tmp_path, *args, "--seed", 43) == 0
    path = out / f"packet_{pid}_{es}.json"
    first = path.read_bytes()
    assert run(tmp_path, *args, "--seed", 21) == 0
    assert path.read_bytes() == first
    mask = dict(con.execute("SELECT story_key, cand_id FROM judge_masks"))
    return pid, es, out, mask


def test_blind_packet(tmp_path, masked):
    pid, es, out, mask = masked
    packet_file = out / f"packet_{pid}_{es}.json"
    prompt_file = out / f"prompt_judge_{pid}_{es}.txt"
    assert set(out.iterdir()) == {packet_file, prompt_file}
    packet = json.loads(packet_file.read_text())
    assert set(packet) == {"events", "candidates", "grades"}
    assert set(packet["grades"]) == {"full", "adjacent", "none"}
    assert all(set(e) == {"event_id", "label", "summary", "trigger", "key_entities", "key_numbers"}
               for e in packet["events"])
    assert len(packet["events"]) == 7
    candidates = packet["candidates"]
    assert [c["cand_id"] for c in candidates] == [f"K{i:02}" for i in range(1, 10)]
    assert all(set(c) == {"cand_id", "label", "titles"} and c["label"] == c["titles"][0] for c in candidates)
    by_id = {c["cand_id"]: c["titles"] for c in candidates}
    assert by_id[mask["story_5"]] == ["가상 소식 5", "가상 소식 10"]
    assert by_id[mask["story_1"]] == ["가상 소식 1", *[f"가상 소식 {i}" for i in range(11, 18)]]
    for path in (packet_file, prompt_file):
        visible = path.read_text()
        for hidden in [*mask, "내부 선정명", "가상 분야", "vidTEST0001", '"rank"', '"confident"']:
            assert hidden not in visible


@pytest.mark.parametrize("changed", ["board.json", "clusters.json"])
def test_packet_input_digest_checked_before_output(tmp_path, fixed, changed):
    pid, es = fixed
    path = tmp_path / changed
    path.write_bytes(path.read_bytes() + b" ")
    out = tmp_path / "blind"
    assert run(tmp_path, "score", "packet", pid, "--out", out, "--clusters", tmp_path / "clusters.json", "--skip-gate") == 1
    assert not (out / f"packet_{pid}_{es}.json").exists()


def test_gate_failure_removes_both_files(tmp_path, fixed, monkeypatch):
    pid, es = fixed
    out = tmp_path / "blind"
    calls = []
    def deny(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="가상 거부")
    monkeypatch.setattr(subprocess, "run", deny)
    assert run(tmp_path, "score", "packet", pid, "--out", out, "--clusters", tmp_path / "clusters.json") == 1
    assert calls and "scripts/publish_gate.py" in list(map(str, calls[0]))
    assert not (out / f"packet_{pid}_{es}.json").exists()
    assert not (out / f"prompt_judge_{pid}_{es}.txt").exists()


def ballots(mask, grades, reason):
    return [{"cand_id": mask[f"story_{n}"], "grade": grade, "event_id": eid, "reason": reason}
            for n, (grade, eid) in grades.items()]


def submit(folder, pid, judge, rows, *args):
    file = write(folder / f"{judge}.json", {"judgments": rows})
    return run(folder, "score", "judge", pid, "--judge", judge, file, *args)


@pytest.mark.parametrize("eid", ["E06", "E07"])
def test_confident_precision_excludes_minor_and_weekday(tmp_path, con, masked, eid):
    pid, _, _, mask = masked
    rows = [{"cand_id": cand, "grade": "none", "event_id": None, "reason": "가상 사건과 다르다."}
            for cand in mask.values()]
    next(r for r in rows if r["cand_id"] == mask["story_1"]).update(grade="full", event_id=eid)
    for name in ("codex", "gemini"):
        assert submit(tmp_path, pid, name, rows) == 0
    assert run(tmp_path, "score", "finalize", pid) == 0
    p = con.execute("SELECT * FROM weekly_metrics WHERE set_name='pick'").fetchone()
    assert json.loads(p["matched"])[eid] == {"story_key": "story_1", "grade": "full"}
    assert (p["confident_n"], p["confident_full"], p["confident_weighted"], p["confident_precision"]) == (2, 0, 0, 0)


def test_recheck_is_stable_blind_and_available_before_arbitration(tmp_path, con, masked):
    pid, es, folder, mask = masked
    grades = {i: ("none", None) for i in range(1, 10)}
    grades.update({1: ("full", "E02"), 3: ("adjacent", "E04"), 5: ("full", "E06")})
    assert submit(tmp_path, pid, "codex", ballots(mask, grades, "가상 판정 근거 하나")) == 0
    other = grades | {5: ("full", "E03")}
    assert submit(tmp_path, pid, "gemini", ballots(mask, other, "가상 판정 근거 둘")) == 0
    out = tmp_path / "재확인"
    args = ("score", "finalize", pid, "--out", out)
    assert run(tmp_path, *args) == 2
    path = out / f"recheck_{pid}_{es}.json"
    raw = path.read_text()
    data = json.loads(raw)
    packet = json.loads((folder / f"packet_{pid}_{es}.json").read_text())
    expected = random.Random(f"{pid}:{es}").choice(sorted([mask["story_1"], mask["story_3"]]))
    assert data == {"events": packet["events"],
                    "recheck": [next(c for c in packet["candidates"] if c["cand_id"] == expected)],
                    "note": "두 판정자가 같은 판정을 낸 건의 재확인 표본이다. 앞 판정은 보여 주지 않는다."}
    for hidden in ("grade", "reason", "judge", "codex", "gemini", "chatgpt", "가상 판정 근거", *mask):
        assert hidden not in raw
    assert run(tmp_path, *args, "--provisional") == 0
    assert path.read_text() == raw
    story = next(key for key, cand in mask.items() if cand == expected)
    for (judging,) in con.execute("SELECT judging FROM weekly_metrics"):
        assert json.loads(judging)["recheck"] == [story]

    none = ballots(mask, {i: ("none", None) for i in grades}, "가상 사건과 다르다.")
    for name in ("codex", "gemini"):
        assert submit(tmp_path, pid, name, none) == 0
    assert run(tmp_path, *args) == 0
    assert not path.exists()
    assert all(json.loads(r[0])["recheck"] == [] for r in con.execute("SELECT judging FROM weekly_metrics"))


def test_judges_finalize_and_metrics(tmp_path, con, masked, capsys):
    pid, es, _, mask = masked
    base = {1: ("full", "E01"), 2: ("full", "E01"), 3: ("adjacent", "E04"), 4: ("full", "E07"),
            5: ("full", "E03"), 6: ("full", "E06"), 7: ("none", None), 8: ("none", None), 9: ("none", None)}
    first = ballots(mask, base, "가상 자료에서 근거를 읽었다.")
    second = ballots(mask, base | {3: ("none", None), 4: ("full", "E02")}, "가상 자료와 대조했다.")
    assert submit(tmp_path, pid, "codex", first) == 0
    assert submit(tmp_path, pid, "gemini", second) == 0
    assert submit(tmp_path, pid, "codex", [first[0], *first[:-1]]) == 1
    assert submit(tmp_path, pid, "gemini", second[1:]) == 1
    assert submit(tmp_path, pid, "chatgpt", first[:1]) == 1
    assert submit(tmp_path, pid, "chatgpt", first[2:3]) == 0
    out = tmp_path / "arbitration"
    capsys.readouterr()
    assert run(tmp_path, "score", "finalize", pid, "--out", out) == 2
    captured = capsys.readouterr()
    assert mask["story_4"] in captured.err + captured.out
    assert con.execute("SELECT COUNT(*) FROM weekly_metrics").fetchone()[0] == 0
    arb = json.loads((out / f"arbitrate_{pid}_{es}.json").read_text())
    dispute = next(d for d in arb["disputed"] if d["cand_id"] == mask["story_4"])
    assert set(dispute) == {"cand_id", "label", "titles", "judge_1", "judge_2"}
    assert {dispute[k]["event_id"] for k in ("judge_1", "judge_2")} == {"E07", "E02"}
    assert run(tmp_path, "score", "finalize", pid, "--provisional") == 0
    p = con.execute("SELECT * FROM weekly_metrics WHERE set_name='pick'").fetchone()
    assert p["status"] == "속보" and json.loads(p["judging"])["pending"] == ["story_4"]
    assert json.loads(p["weekday"]) == {"n": 1, "full": 0, "weighted": 0}
    assert submit(tmp_path, pid, "chatgpt", first[2:4]) == 0
    assert run(tmp_path, "score", "finalize", pid) == 0
    rows = {r["set_name"]: r for r in con.execute("SELECT * FROM weekly_metrics")}
    assert set(rows) == {"pick", "A", "B"} and all(r["status"] == "확정" for r in rows.values())
    p = rows["pick"]
    assert (p["events_n"], p["full_hits"], p["adjacent_hits"], p["weighted_hits"]) == (5, 1, 1, 1.5)
    assert (p["recall_full"], p["recall_weighted"]) == (0.2, 0.3)
    assert json.loads(p["matched"]) == {"E01": {"story_key": "story_1", "grade": "full"},
                                       "E04": {"story_key": "story_3", "grade": "adjacent"},
                                       "E07": {"story_key": "story_4", "grade": "full"}}
    assert json.loads(p["by_timing"]) == {
        "시사": {"n": 3, "full": 1, "weighted": 1}, "중간": {"n": 1, "full": 0, "weighted": .5},
        "상시": {"n": 1, "full": 0, "weighted": 0}}
    assert json.loads(p["weekday"]) == {"n": 1, "full": 1, "weighted": 1}
    assert (p["confident_n"], p["confident_full"], p["confident_weighted"], p["confident_precision"]) == (2, 1, 1.5, .75)
    assert rows["A"]["weighted_hits"] == 2 and "E06" in json.loads(rows["A"]["matched"])
    assert rows["B"]["weighted_hits"] == 0 and json.loads(rows["B"]["weekday"])["full"] == 1
    assert all(rows[s][field] is None for s in ("A", "B") for field in ("vs_baselines", "confident_precision"))
    assert json.loads(p["vs_baselines"]) == {
        "A": {"diff_weighted": -.5, "ratio_weighted": .75, "diff_full": -1},
        "B": {"diff_weighted": 1.5, "ratio_weighted": None, "diff_full": 1}}
    judging = json.loads(p["judging"])
    assert (judging["n"], judging["agree"], judging["rate"]) == (9, 7, pytest.approx(7 / 9))
    assert set(judging["disputed"]) == set(judging["arbitrated"]) == {"story_3", "story_4"}
    assert not judging["pending"]
    capsys.readouterr()
    assert run(tmp_path, "hits", pid, "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert {"prediction_id", "event_set", "kind", "events", "metrics", "judging"} <= report.keys()
    assert len(report["events"]) == 7 and len(report["metrics"]) == 3


@pytest.mark.parametrize("retro", [True, False])
def test_mask_import_and_retro_exclusion(tmp_path, con, retro, capsys):
    pid = register(tmp_path, retro=retro)
    event = event_doc()
    for row in event["events"]:
        row["minor"] = True
    assert run(tmp_path, "score", "events", pid, "--from-json", write(tmp_path / "events.json", event)) == 0
    keys = [r[0] for r in con.execute("SELECT DISTINCT story_key FROM prediction_items ORDER BY story_key")]
    mask = {f"K{i:02}": key for i, key in enumerate(keys, 1)}
    items = [{"cand_id": k, "label": f"가상 제목 {i}", "titles": [f"가상 제목 {i}"]} for i, k in enumerate(mask, 1)]
    key_path = write(tmp_path / "mask.json", mask)
    packet = write(tmp_path / "packet.json", {"items": items})
    args = ("score", "mask-import", pid, "--mask", key_path, "--packet", packet)
    if not retro:
        assert run(tmp_path, *args) == 1
        assert con.execute("SELECT COUNT(*) FROM judge_masks").fetchone()[0] == 0
        return
    write(key_path, mask | {"K01": "not_in_prediction"})
    assert run(tmp_path, *args) == 1
    write(key_path, mask)
    assert run(tmp_path, *args) == 0
    assert dict(con.execute("SELECT cand_id,story_key FROM judge_masks")) == mask
    for path, kind in ((key_path, "mask_key"), (packet, "mask_packet")):
        assert tuple(con.execute("SELECT kind,json FROM ledger_files WHERE sha256=?", (digest(path),)).fetchone()) == (
            kind, path.read_text())
    for judge in ("codex", "gemini"):
        assert submit(tmp_path, pid, judge, [{"cand_id": key, "grade": "none", "event_id": None,
                                            "reason": f"가상 판정 {judge}"} for key in mask]) == 0
    assert run(tmp_path, "score", "finalize", pid) == 0
    assert set(map(tuple, con.execute("SELECT set_name,events_n,recall_full,recall_weighted FROM weekly_metrics"))) == {
        ("A", 0, None, None), ("B", 0, None, None)}
    capsys.readouterr()
    assert run(tmp_path, "hits") == 0
    assert pid not in capsys.readouterr().out
    assert run(tmp_path, "hits", "--include-retro") == 0
    assert "소급 시험(공식 기록 아님)" in capsys.readouterr().out
    assert run(tmp_path, "hits", pid) == 0
    assert capsys.readouterr().out.splitlines()[0] == "소급 시험 — 공식 적중 기록이 아니다"


@pytest.mark.parametrize("options, expected", [
    # 가장 먼저 온 full 쌍을 택하면 뒤 이야기의 full 쌍을 잃는다.
    ([("aa", "E01", "full"), ("aa", "E02", "adjacent"), ("bb", "E01", "full")],
     {"E01": ("bb", "full"), "E02": ("aa", "adjacent")}),
    # 한 full과 두 adjacent가 동점이면 full 수가 우선이다.
    ([("aa", "E01", "full"), ("aa", "E02", "adjacent"), ("bb", "E01", "adjacent")],
     {"E01": ("aa", "full")}),
    # 같은 등급일 때만 확신, 그다음 순위 합을 비교한다.
    ([("aa", "E01", "adjacent"), ("bb", "E01", "full")], {"E01": ("bb", "full")}),
    ([("aa", "E01", "full"), ("bb", "E01", "full")], {"E01": ("aa", "full")}),
    ([("bb", "E01", "full"), ("cc", "E01", "full")], {"E01": ("bb", "full")}),
])
def test_maximum_matching(options, expected):
    items = [{"story_key": key, "rank": rank, "confident": key == "aa"}
             for key, rank in [("aa", 30), ("bb", 1), ("cc", 2)]]
    edges = [{"story_key": key, "event_id": eid, "grade": grade} for key, eid, grade in options]
    result = hits.match(items, edges)
    assert result == {eid: {"story_key": key, "grade": grade} for eid, (key, grade) in expected.items()}


def test_judge_requires_unambiguous_set_and_its_packet(tmp_path, con, masked, capsys):
    pid, original, _, mask = masked
    doc = event_doc()
    doc["events"][0]["summary"] = "가상 도시가 새 실험을 예고했다."
    newer = hits.events(con, pid, from_json=write(tmp_path / "new.json", doc), replace=True)
    rows = [{"cand_id": cand, "grade": "full", "event_id": "E01", "reason": "가상 계기가 같다."}
            for cand in mask.values()]
    # 가림 번호만 복사돼 있어도 새 묶음의 가림 원문까지 고정된 것은 아니다.
    con.executemany("INSERT INTO judge_masks VALUES(?,?,?,?)",
                    [(pid, newer, cand, story) for story, cand in mask.items()])
    con.commit()
    assert submit(tmp_path, pid, "codex", rows) == 1
    err = capsys.readouterr().err
    assert all(value in err for value in ("--event-set", original, newer))
    assert submit(tmp_path, pid, "codex", rows, "--event-set", newer) == 1
    assert "가림" in capsys.readouterr().err
    assert not con.execute("SELECT 1 FROM hit_judgments").fetchone()
    assert submit(tmp_path, pid, "codex", rows, "--event-set", original) == 0
    assert {r[0] for r in con.execute("SELECT event_set FROM hit_judgments")} == {original}


def test_packet_rejects_all_titleless_stories_atomically(tmp_path, con, fixed, capsys):
    pid, _ = fixed
    # 판이 없으면 기준선 제목만 남아, pick 전용 이야기 둘은 제목이 없다.
    (tmp_path / "board.json").unlink()
    out = tmp_path / "blind"
    assert run(tmp_path, "score", "packet", pid, "--out", out, "--skip-gate") == 1
    err = capsys.readouterr().err
    assert "story_1" in err and "story_3" in err
    assert not con.execute("SELECT 1 FROM judge_masks").fetchone()
    assert not con.execute("SELECT 1 FROM ledger_files WHERE kind IN ('mask_key','mask_packet')").fetchone()
    assert not out.exists()


@pytest.mark.parametrize("command", ["judge", "finalize", "finalize_out"])
def test_titleless_archive_blocks_judge_and_finalize(tmp_path, con, fixed, capsys, command):
    pid, es = fixed
    keys = [r[0] for r in con.execute("SELECT DISTINCT story_key FROM prediction_items ORDER BY story_key")]
    mapping = {f"K{i:02}": key for i, key in enumerate(keys, 1)}
    items = [{"cand_id": cand, "label": "옛 이름", "titles": ["가상 기사"]} for cand in mapping]
    items[-1]["titles"] = [" ", ""]
    # 옛 장부에는 제목 없는 후보와, 그 후보를 보고 내린 판정도 남아 있을 수 있다.
    with con:
        hits._put_mask(con, fixed, mapping)
        hits._archive_packet(con, fixed, json.dumps({"items": items}), None, json.dumps(mapping), None)
        if command != "judge":
            con.executemany("INSERT INTO hit_judgments(prediction_id,event_set,story_key,judge,grade,judged_at) "
                            "VALUES(?,?,?,?,'none','2030-01-01')",
                            [(pid, es, key, name) for key in keys for name in ("codex", "gemini")])
    out = tmp_path / "blind"
    if command == "judge":
        rows = [{"cand_id": cand, "grade": "none", "event_id": None, "reason": "가상 사건이 다르다."}
                for cand in mapping]
        assert submit(tmp_path, pid, "codex", rows) == 1
        assert not con.execute("SELECT 1 FROM ledger_files WHERE kind='judge_codex'").fetchone()
        assert not con.execute("SELECT 1 FROM hit_judgments").fetchone()
    else:
        options = ["--out", out] if command == "finalize_out" else []
        assert run(tmp_path, "score", "finalize", pid, *options) == 1
    assert f"기사 제목이 없는 이야기: {keys[-1]}" in capsys.readouterr().err
    assert not con.execute("SELECT 1 FROM hit_judgments WHERE judge='final'").fetchone()
    assert not con.execute("SELECT 1 FROM weekly_metrics").fetchone()
    assert not out.exists()


@pytest.mark.parametrize("options", [(), ("--provisional",)])
def test_finalize_rejects_legacy_empty_story_union(tmp_path, con, fixed, capsys, options):
    pid, _ = fixed
    with con:
        con.execute("DELETE FROM prediction_items WHERE prediction_id=?", (pid,))
    assert run(tmp_path, "score", "packet", pid, "--out", tmp_path / "blind", "--skip-gate") == 0
    assert run(tmp_path, "score", "finalize", pid, *options) == 1
    assert "이야기가 없다" in capsys.readouterr().err
    assert not con.execute("SELECT 1 FROM hit_judgments WHERE judge='final'").fetchone()
    assert not con.execute("SELECT 1 FROM weekly_metrics").fetchone()


def test_imported_labels_never_reach_judges(tmp_path, con):
    pid = register(tmp_path, retro=True)
    es = hits.events(con, pid, from_json=write(tmp_path / "events.json", event_doc()))
    keys = [r[0] for r in con.execute("SELECT DISTINCT story_key FROM prediction_items ORDER BY story_key")]
    mapping = {f"K{i:02}": key for i, key in enumerate(keys, 1)}
    def titles(cand):
        return [f"가상 기사 {cand} {i}" for i in range(10)]

    items = [{"cand_id": k, "label": "가상 내부 선정명", "titles": [" ", titles(k)[0], "", *titles(k)]}
             for k in reversed(mapping)]
    archived = write(tmp_path / "import.json", {"items": items})
    args = ("score", "mask-import", pid, "--mask", write(tmp_path / "mask.json", mapping), "--packet", archived)
    write(archived, {"items": [items[0] | {"titles": ["  "]}, *items[1:]]})
    assert run(tmp_path, *args) == 1
    assert not con.execute("SELECT 1 FROM judge_masks").fetchone()
    write(archived, {"items": items})
    assert run(tmp_path, *args) == 0
    assert run(tmp_path, *args) == 0
    assert con.execute("SELECT json FROM ledger_files WHERE sha256=?", (digest(archived),)).fetchone()[0] == archived.read_text()
    out = tmp_path / "blind"
    assert run(tmp_path, "score", "packet", pid, "--out", out, "--skip-gate") == 0
    rows = [{"cand_id": k, "grade": "full", "event_id": "E01", "reason": "가상 계기가 같다."} for k in mapping]
    assert submit(tmp_path, pid, "codex", rows) == 0
    for row in rows[:2]:
        row.update(grade="none", event_id=None)
    assert submit(tmp_path, pid, "gemini", rows) == 0
    assert run(tmp_path, "score", "finalize", pid, "--provisional", "--out", out) == 0
    for prefix, field in (("packet", "candidates"), ("arbitrate", "disputed"), ("recheck", "recheck")):
        candidates = json.loads((out / f"{prefix}_{pid}_{es}.json").read_text())[field]
        ids = [c["cand_id"] for c in candidates]
        assert ids and ids == sorted(ids)
        for candidate in candidates:
            expected = titles(candidate["cand_id"])[:8]
            assert candidate["titles"] == expected
            assert candidate["label"] == expected[0]
    assert all("가상 내부 선정명" not in path.read_text() for path in out.iterdir())
    assert con.execute("SELECT json FROM ledger_files WHERE sha256=?", (digest(archived),)).fetchone()[0] == archived.read_text()


@pytest.mark.parametrize("weekdays", [("vidTEST0002", "vidTEST0002"), ("vidTEST0001",)])
def test_weekday_must_be_distinct_from_all_videos(tmp_path, con, weekdays, capsys):
    pid = register(tmp_path)
    for vid in ("vidTEST0001", "vidTEST0002"):
        db_v3.put(con, video_doc(video_id=vid))
    args = [arg for vid in weekdays for arg in ("--weekday", vid)]
    assert run(tmp_path, "score", "events", pid, "--from-v3", "vidTEST0001", *args) == 1
    assert "--weekday" in capsys.readouterr().err
    assert not con.execute("SELECT 1 FROM broadcast_events").fetchone()
    assert not con.execute("SELECT 1 FROM ledger_files").fetchone()


def test_replace_rejects_existing_canonical_event_set(tmp_path, con, fixed, capsys):
    pid, original = fixed
    doc = event_doc()
    doc["events"][0]["label"] = "가상 발표 정정"
    latest = hits.events(con, pid, from_json=write(tmp_path / "new.json", doc), replace=True)
    path = tmp_path / "events.json"
    path.write_bytes(path.read_bytes() + b"  ")
    assert run(tmp_path, "score", "events", pid, "--from-json", path, "--replace") == 1
    assert f"이미 있는 사건 묶음 {original} — 이후 명령에 --event-set {original} 를 준다" in capsys.readouterr().err
    assert hits._latest_sets(con)[pid] == latest
    assert not con.execute("SELECT 1 FROM ledger_files WHERE sha256=?", (digest(path),)).fetchone()


def test_recheck_record_does_not_depend_on_out(tmp_path, con, masked):
    pid, es, _, mask = masked
    grades = {i: ("adjacent", "E01") for i in range(1, 10)}
    for judge in ("codex", "gemini"):
        assert submit(tmp_path, pid, judge, ballots(mask, grades, "가상 수치가 겹친다.")) == 0
    args = ("score", "finalize", pid)
    assert run(tmp_path, *args) == 0
    records = [json.loads(row[0])["recheck"] for row in con.execute("SELECT judging FROM weekly_metrics")]
    out = tmp_path / "blind"
    assert not list(tmp_path.rglob("recheck_*.json"))
    assert run(tmp_path, *args, "--out", out) == 0
    candidate, = json.loads((out / f"recheck_{pid}_{es}.json").read_text())["recheck"]
    story = next(key for key, cand in mask.items() if cand == candidate["cand_id"])
    assert records == [[story]] * 3
    assert [json.loads(r[0])["recheck"] for r in con.execute("SELECT judging FROM weekly_metrics")] == records


def test_blind_titles_dedupe_after_strip():
    """공백 수만 다른 같은 제목은 하나로 센다(지어낸 제목)."""
    from ozl.syuka import hits as _h
    items = [{"cand_id": "K01", "titles": ["가상 기사 A" + " " * n for n in range(8)] + ["가상 기사 B"]}]
    out = _h._blind_candidates(items, {"K01": "aa"})
    assert out[0]["titles"] == ["가상 기사 A", "가상 기사 B"] and out[0]["label"] == "가상 기사 A"
