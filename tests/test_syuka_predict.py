"""지어낸 예측만 고정하고, 날짜·개정·중복·원문 대조를 검사한다."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest

from ozl.syuka import __main__ as cli
from ozl.syuka import db, predict


def prediction_doc():
    def detail(i):
        return {"story_key": f"story_{i}", "rank": i * 2, "cat": "가상 경제",
                "top_id": f"item_{i}", "title": f"가상 연구소의 실험 {i}"}

    a = [detail(i) for i in (1, 3, 5, 6)]
    b = [detail(i) for i in (1, 4, 7, 8)]
    picks = [{"n": i, "story_key": f"story_{i}", "label": f"지은 이름 {i}", "category": "가상 경제",
              "member_ids": [f"item_{i}"], "confident": i <= 2} for i in range(1, 5)]
    return {"schema": "ozl.syuka.prediction/1", "broadcast": "2030-05-05 (일) 20:00 KST",
            "fixed_at": "2030-05-04T09:00:00+09:00", "picks": picks,
            "confident": ["story_1", "story_2"], "skeletons": [{"story_key": "story_1"}],
            "baselines": {"A": [r["story_key"] for r in a], "B": b, "detail": {"A_engine_top15": a}}}


def write(path, doc):
    path.write_bytes((json.dumps(doc, ensure_ascii=False, indent=2) + "\n").replace("\n", "\r\n").encode())
    return path


@pytest.fixture
def board(tmp_path):
    specs = [
        ("item_lo", 2, 62, "국제", False), ("item_block", 1, 99, "경제", True),
        ("item_other", 1, 80, "문화", False), ("item_hi", 2, 85, "과학기술", False),
        ("item_twin", 3, 75, "경제", False), ("item_tail", 4, 84, "경제", False),
        ("item_null", None, 100, "국제", False), ("item_last", 5, 42, "국제", False),
    ]
    rows = [{"issue_id": issue, "story_rank": rank, "score": 53.75, "score_raw": raw, "category": cat,
             "deck_blocked": blocked, "lang": "ko", "day_n": 2, "first_day": "2030-02-25",
             "state": "계속", "title": f"가상 소식 {issue}", "links": []}
            for issue, rank, raw, cat, blocked in specs]
    rows[0].update(story={"families_3d": 4}, prev_day={"articles_n": 7}, sensitivity={"level": "GREEN"},
                   aliases=["가상 별칭"], links=[{"title": title} for title in
                   ("가상 후속 가", rows[0]["title"], "가상 후속 나", "가상 후속 다")])
    return write(tmp_path / "board.json", {"asof": "2030-02-26T01:45:00+00:00", "candidates": rows})


def test_prepare_files_and_half_open_kst_window(tmp_path, board):
    db_path = tmp_path / "test.db"
    con = db.connect(db_path)
    rows = [("2030-02-26 10:44", "생방송 전체", "가상 끝 직전"),
            ("2030-01-01 10:45", "본편", "가상 시작"),
            ("2030-01-01 10:44", "본편", "가상 시작 전"),
            ("2030-02-26 10:45", "본편", "가상 끝"),
            ("2030-01-05 12:00", "예고", "가상 예고")]
    con.executemany("INSERT INTO videos(video_id,upload_at,kind,title) VALUES(?,?,?,?)",
                    [(f"vidTEST{i:04}", *row) for i, row in enumerate(rows)])
    con.commit()
    con.close()
    args = ["--db", str(db_path), "predict", "prepare", str(board), "--out"]
    out = tmp_path / "준비"
    assert cli.main([*args, str(out)]) == 0
    compact = out / "candidates_compact.json"
    items = json.loads(compact.read_text())
    assert compact.read_text() == json.dumps(items, ensure_ascii=False, indent=0)
    assert [r["id"] for r in items] == [c["issue_id"] for c in json.loads(board.read_bytes())["candidates"]]
    assert items[0] == {"id": "item_lo", "rank": 2, "score": 54, "cat": "국제", "lang": "ko", "day_n": 2,
                        "first_day": "2030-02-25", "state": "계속", "fam3d": 4, "prev_articles": 7,
                        "blocked": False, "sens": "GREEN", "title": "가상 소식 item_lo", "aliases": ["가상 별칭"],
                        "more_titles": ["가상 후속 가", "가상 후속 나"]}
    assert [items[1][k] for k in ("fam3d", "prev_articles", "sens", "blocked", "aliases", "more_titles")] == [
        None, None, None, True, [], []]
    recent = out / "recent_titles_8w.txt"
    assert recent.read_text() == "2030-01-01 가상 시작\n2030-02-26 가상 끝 직전\n"
    other = tmp_path / "다른 기간"
    assert cli.main([*args, str(other), "--weeks", "1", "--asof", "2030-01-08T10:45:00+09:00"]) == 0
    assert (other / recent.name).read_text() == "2030-01-01 가상 시작\n"
    for keep, absent in ((recent, compact), (compact, recent)):
        keep.write_bytes(b"existing")
        absent.unlink(missing_ok=True)
        assert cli.main([*args, str(out)]) == 1
        assert keep.read_bytes() == b"existing" and not absent.exists()


def test_baselines_order_filter_and_input_hashes(tmp_path, board):
    clusters = write(tmp_path / "clusters.json", {"clusters": [
        {"story_key": "story_pair", "member_ids": ["item_block", "item_twin"]}]})
    out = tmp_path / "baselines.json"
    unused_db = tmp_path / "unused.db"
    args = ["--db", str(unused_db), "predict", "baselines", str(board), "--clusters", str(clusters),
            "--out", str(out)]
    assert cli.main(args) == 0
    raw = out.read_bytes()
    data = json.loads(raw)
    assert data["A"] == ["story_pair", "item_other", "item_hi", "item_lo", "item_tail", "item_last"]
    assert data["B"] == ["item_hi", "item_lo", "story_pair", "item_tail", "item_last"]
    assert data["rule_A"] and data["rule_B"]
    assert data["board_sha256"] == hashlib.sha256(board.read_bytes()).hexdigest()
    assert data["clusters_sha256"] == hashlib.sha256(clusters.read_bytes()).hexdigest()
    doc = prediction_doc()
    doc["baselines"] = {"A": data["A"], "B": data["B"], "detail": {
        "A_engine_top15": data["A_engine_top15"], "B_domain_top15": data["B_domain_top15"]}}
    assert predict.validate(doc, "official") == []
    for name, detail, top in (("A", "A_engine_top15", "item_block"), ("B", "B_domain_top15", "item_twin")):
        assert [r["story_key"] for r in data[detail]] == data[name]
        row = next(r for r in data[detail] if r["story_key"] == "story_pair")
        assert row == {"story_key": "story_pair", "top_id": top, "rank": 1 if name == "A" else 3,
                       "cat": "경제", "title": f"가상 소식 {top}"}
    assert cli.main([*args, "--n", "3"]) == 1
    assert out.read_bytes() == raw
    out.unlink()
    assert cli.main([*args, "--n", "3"]) == 0
    shorter = json.loads(out.read_bytes())
    for name in ("A", "B"):
        assert shorter[name] == data[name][:3]
    assert not unused_db.exists()


def test_register_preserves_original_and_is_idempotent(tmp_path):
    doc = prediction_doc()
    doc["baselines"]["A"][-1] = "no_detail"
    path = write(tmp_path / "장부.json", doc)
    raw = path.read_bytes()
    con = db.connect(tmp_path / "temp.db")
    digest = hashlib.sha256(raw).hexdigest()
    pid = predict.register(con, path)
    assert pid == f"2030-05-05-{digest[:10]}"
    assert predict.register(con, path) == pid
    assert predict.sha256_file(path) == digest
    assert path.stat().st_mode & 0o777 == 0o444
    raw_row = con.execute("SELECT * FROM predictions").fetchone()
    assert raw_row["sha256"] == digest and raw_row["json"].encode() == raw
    assert raw_row["broadcast_at"] == "2030-05-05T20:00:00+09:00"
    assert con.execute("SELECT count(*) FROM predictions").fetchone()[0] == 1
    groups = con.execute("SELECT set_name,count(*) FROM prediction_items GROUP BY set_name")
    assert dict(groups) == {"pick": 4, "A": 4, "B": 4}
    rows = con.execute("SELECT * FROM prediction_items WHERE set_name='A' ORDER BY rank").fetchall()
    assert [(r["rank"], r["engine_rank"], json.loads(r["member_ids"])) for r in rows] == [
        (1, 2, ["item_1"]), (2, 6, ["item_3"]), (3, 10, ["item_5"]), (4, None, [])]
    assert rows[1]["title"] == "가상 연구소의 실험 3"
    assert predict.list_predictions(con)[0]["A"] == 4
    con.close()


def test_fix_rejects_overwrite_and_invalid_without_leaving_files(tmp_path, monkeypatch):
    folder = tmp_path / "fixed"
    monkeypatch.setattr(predict, "PRED_ROOT", folder)
    doc = prediction_doc()
    doc.pop("fixed_at")
    draft = write(tmp_path / "draft.json", doc)
    db_path = tmp_path / "temp.db"
    con = db.connect(db_path)
    date = "2030-05-05"
    too_late = datetime.fromisoformat("2030-05-05T12:00:00+00:00")
    with pytest.raises(ValueError, match="fixed_at"):
        predict.fix(con, draft, date, now=too_late)
    assert not folder.exists()
    now = datetime.fromisoformat("2030-05-04T00:00:12.345678+00:00")
    path, pid = predict.fix(con, draft, date, now=now)
    assert path == folder / date / "prediction_20300504_090012_fixed.json"
    doc["fixed_at"] = "2030-05-04T09:00:12+09:00"
    assert path.read_bytes() == (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode()
    assert path.stat().st_mode & 0o777 == 0o444
    digest = predict.sha256_file(path)
    manifest = path.with_name("HASH.txt")
    line = f"{digest}  {path.name}  (고정 {doc['fixed_at']})\n"
    with pytest.raises(FileExistsError):
        predict.fix(con, draft, date, now=now)
    with pytest.raises(ValueError, match="revises"):
        predict.fix(con, draft, date, now=now.replace(minute=1))
    assert list(sorted(p.name for p in path.parent.iterdir())) == ["HASH.txt", path.name]
    assert manifest.read_text() == line
    assert predict.verify(con, pid, digest) == [dict(prediction_id=pid, file=str(path), sha256_file=digest,
        sha256_ledger=digest, sha256_hashtxt=digest, expect=digest, ok=True, problems=[])]
    assert cli.main(["--db", str(db_path), "predict", "verify"]) == 0
    assert not predict.verify(con, pid, "1" * 64)[0]["ok"]
    manifest.write_text(line.replace(path.name, f"other_{path.name}"))
    assert not predict.verify(con, pid)[0]["ok"]
    manifest.write_text(line)
    path.chmod(0o644)
    with path.open("ab") as f:
        f.write(b" ")
    assert not predict.verify(con, pid)[0]["ok"]
    assert cli.main(["--db", str(db_path), "predict", "verify"]) == 1
    path.unlink()
    assert not predict.verify(con, pid)[0]["ok"]
    con.close()


def test_revision_preserves_both_files(tmp_path):
    con = db.connect(tmp_path / "temp.db")
    doc = prediction_doc()
    first = predict.register(con, write(tmp_path / "first.json", doc))
    changed = write(tmp_path / "second.json", doc | {"confident": ["story_2", "story_1"]})
    for revises in (None, "other"):
        with pytest.raises(ValueError, match="revises"):
            predict.register(con, changed, revises=revises)
    second = predict.register(con, changed, revises=first)
    assert first != second
    assert con.execute("SELECT revises FROM predictions WHERE prediction_id=?", (second,)).fetchone()[0] == first
    assert all(r["ok"] for r in predict.verify(con))
    con.close()


def test_fix_manifest_write_failure_rolls_back(tmp_path, monkeypatch):
    folder = tmp_path / "fixed"
    monkeypatch.setattr(predict, "PRED_ROOT", folder)
    date = "2030-05-05"
    (folder / date / "HASH.txt").mkdir(parents=True)
    draft = write(tmp_path / "draft.json", prediction_doc())
    con = db.connect(tmp_path / "temp.db")
    with pytest.raises(OSError):
        predict.fix(con, draft, date, now=datetime(2030, 5, 4, tzinfo=db.KST))
    assert not list((folder / date).glob("*.json"))
    assert con.execute("SELECT count(*) FROM predictions").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM prediction_items").fetchone()[0] == 0
    con.close()


def test_concurrent_first_registration_requires_revision(tmp_path):
    db_path = tmp_path / "temp.db"
    doc = prediction_doc()
    paths = [write(tmp_path / f"{i}.json", doc | {"note": i}) for i in range(2)]
    barrier = Barrier(2)

    def run(path):
        con = db.connect(db_path)
        try:
            barrier.wait(timeout=5)
            return predict.register(con, path)
        except ValueError as exc:
            assert "revises" in str(exc)
            return None
        finally:
            con.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, paths))
    assert sum(pid is not None for pid in results) == 1


@pytest.mark.parametrize("bad", [
    {"fixed_at": "2030-05-05T11:00:00+00:00"}, {"fixed_at": "2030-05-05T19:00:00"},
    {"schema": "다른 양식"}, {"kind": "retro"}, {"picks": []}, {"confident": ["story_1"]},
    {"confident": ["story_1", "story_2", "story_2"]}, {"skeletons": [{"story_key": "absent"}]},
    {"baselines": {"A": ["same", "same"], "B": []}}, {"picks": [{"n": True, "story_key": []}]},
])
def test_invalid_prediction(bad):
    assert predict.validate(prediction_doc() | bad, "official")


def test_unknown_time_and_retro_flags():
    doc = prediction_doc()
    del doc["broadcast"]
    doc.update(broadcast_date="2030-05-05", fixed_at="2030-05-05T23:59:00+09:00")
    assert predict.validate(doc, "official") == []
    doc["fixed_at"] = "2030-05-06T00:00:00+09:00"
    assert predict.validate(doc, "official")
    assert predict.validate(doc, "retro")
    doc.update(picks=[], confident=[], skeletons=[], kind="retro")
    assert predict.validate(doc, "retro") == []
    assert predict.validate(doc, "official")


def test_legacy_agree_uses_selected_db_and_output_folder(tmp_path, monkeypatch):
    unused = tmp_path / "기본 경로"
    monkeypatch.setattr(db, "DB_PATH", unused / "default.db")
    selected = tmp_path / "선택 경로" / "chosen.db"
    con = db.connect(selected)
    for model in ("opus", "sonnet"):
        db.put_record(con, "vidTEST0001", model, 2, {}, 12)
    con.close()
    assert cli.main(["--db", str(selected), "agree"]) == 0
    assert json.loads((selected.parent / "agree_v2.json").read_text())["n_videos"] == 1
    assert not unused.exists()


def test_baseline_issue_keys_round_trip_to_add(tmp_path, board):
    data = json.loads(board.read_bytes())
    keys = ["t20300504-001", "T20300504-002"]
    for row, key in zip(data["candidates"], keys):
        row["issue_id"] = key
    write(board, data)
    clusters = write(tmp_path / "clusters.json", {"clusters": []})
    path = tmp_path / "baselines.json"
    db_path = tmp_path / "test.db"
    args = ["--db", str(db_path), "predict"]
    assert cli.main([*args, "baselines", str(board), "--clusters", str(clusters), "--out", str(path)]) == 0
    base = json.loads(path.read_bytes())
    doc = prediction_doc()
    doc["baselines"] = {"A": base["A"], "B": base["B_domain_top15"], "detail": {"A_engine_top15": base["A_engine_top15"]}}
    assert cli.main([*args, "add", str(write(tmp_path / "draft.json", doc))]) == 0
    con = db.connect(db_path)
    try:
        stored = dict(con.execute("SELECT story_key,top_id FROM prediction_items WHERE set_name='A'"))
        assert all(stored[key] == key for key in keys)
    finally:
        con.close()
    doc["picks"][-1]["story_key"] = keys[1]
    assert any("picks[3].story_key" in e for e in predict.validate(doc, "official"))


def test_register_detects_change_at_chmod(tmp_path, monkeypatch):
    path = write(tmp_path / "prediction.json", prediction_doc())
    path_type = type(path)
    chmod = path_type.chmod

    def change_then_lock(self, mode):
        if self == path and mode == 0o444:
            self.write_bytes(self.read_bytes() + b" ")
        return chmod(self, mode)

    monkeypatch.setattr(path_type, "chmod", change_then_lock)
    con = db.connect(tmp_path / "test.db")
    try:
        with pytest.raises(ValueError, match="해시"):
            predict.register(con, path)
        assert path.stat().st_mode & 0o777 == 0o444
        assert not con.execute("SELECT 1 FROM predictions").fetchone()
        assert not con.execute("SELECT 1 FROM prediction_items").fetchone()
    finally:
        con.close()


def test_fix_detects_change_at_chmod_before_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "PRED_ROOT", tmp_path)
    date = "2030-05-05"
    folder = tmp_path / date
    folder.mkdir()
    manifest = folder / "HASH.txt"
    previous = "기존 고정 기록".encode()
    manifest.write_bytes(previous)
    draft = write(tmp_path / "draft.json", prediction_doc())
    path_type = type(draft)
    chmod = path_type.chmod

    def change_then_lock(path, mode):
        if path.parent == folder and mode == 0o444:
            with path.open("ab") as output:
                output.write(b" ")
        return chmod(path, mode)

    monkeypatch.setattr(path_type, "chmod", change_then_lock)
    con = db.connect(tmp_path / "test.db")
    try:
        with pytest.raises(ValueError, match="해시"):
            predict.fix(con, draft, date, now=datetime(2030, 5, 4, tzinfo=db.KST))
        assert list(folder.iterdir()) == [manifest]
        assert manifest.read_bytes() == previous
        assert not con.execute("SELECT 1 FROM predictions").fetchone()
        assert not con.execute("SELECT 1 FROM prediction_items").fetchone()
    finally:
        con.close()


def test_nullable_scores_in_prepare_and_baselines(tmp_path, board):
    data = json.loads(board.read_bytes())
    rows = data["candidates"][:4]
    for row, rank, raw in zip(rows, (1, 1, 1, 2), (None, -1, 0, 99)):
        row.update(story_rank=rank, score_raw=raw, score=None, category="국제", deck_blocked=False)
    write(board, data | {"candidates": rows})
    db_path = tmp_path / "test.db"
    db.connect(db_path).close()
    args = ["--db", str(db_path), "predict"]
    assert cli.main([*args, "prepare", str(board), "--out", str(tmp_path)]) == 0
    assert [r["score"] for r in json.loads((tmp_path / "candidates_compact.json").read_bytes())] == [None] * 4
    clusters = write(tmp_path / "clusters.json", {"clusters": []})
    out = tmp_path / "baselines.json"
    assert cli.main([*args, "baselines", str(board), "--clusters", str(clusters), "--out", str(out)]) == 0
    result = json.loads(out.read_bytes())
    assert result["A"] == result["B"] == [rows[i]["issue_id"] for i in (2, 1, 0, 3)]


def test_empty_candidate_sets_cannot_be_registered(tmp_path):
    doc = prediction_doc() | {"kind": "retro", "picks": [], "confident": [], "skeletons": [],
                              "baselines": {"A": [], "B": []}}
    path = write(tmp_path / "empty.json", doc)
    con = db.connect(tmp_path / "test.db")
    try:
        with pytest.raises(ValueError, match="후보"):
            predict.register(con, path, "retro")
        assert predict.list_predictions(con) == []
    finally:
        con.close()
    for name in ("A", "B"):
        assert predict.validate(doc | {"baselines": doc["baselines"] | {name: ["story_only"]}}, "retro") == []
    picks_only = prediction_doc() | {"baselines": {"A": [], "B": []}}
    assert predict.validate(picks_only, "official") == []
    assert any("후보" in e for e in predict.validate(picks_only | {"kind": "retro"}, "retro"))
