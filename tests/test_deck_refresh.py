"""덱 갱신 후보: 지어낸 카드·판·예측·기사만 임시 폴더에 두고 확인한다."""
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
import yaml

from ozl.render import __main__ as render
from ozl.render import refresh
from ozl.signals.store import SCHEMA

CARD = "2026-01-01-am-01"
OTHER = "2026-01-01-pm-02"
MISSING = "2026-01-01-wk-03"
OLD, NEW, THIRD, PICK, EXCLUDED = [f"t20260101-{n:03}" for n in range(1, 6)]
RULE = ("후속 기사는 갱신 후보일 뿐이다. 수치는 같은 지표의 새 기준일과 원출처(T1·T2 원문)를 열어 확인했을 때만 고친다. "
        "고칠 때는 사양을 새 타임코드로 쓰고 check → build 를 다시 하고, 바뀐 기록을 쓰는 장을 모두 다시 검사하고, "
        "변경 메모를 남긴다(agent/deck.md 「덱 갱신」).")


def put_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def snapshot(path):
    return path.stat().st_mtime_ns, path.stat().st_mode, path.read_bytes()


@pytest.fixture
def paths(tmp_path):
    dirs = {key + "_dir": tmp_path / key for key in ("specs", "cards", "builds", "predictions")}
    path = tmp_path / "임시 엔진?#.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
    dirs["db_path"] = path
    put_yaml(dirs["cards_dir"] / f"{CARD}.yaml", {"topic": "지어낸 소재", "discovery": OLD})
    put_yaml(dirs["specs_dir"] / f"{CARD}_20260103_120000.yaml", {"slides": []})
    return dirs


def read_json(paths, capsys, *argv):
    assert refresh.main(["--json", *argv], **paths) == 0
    return json.loads(capsys.readouterr().out)


def test_links_predictions_aliases_and_missing(paths, capsys):
    fixed = paths["predictions_dir"] / "2026-01-04"
    fixed.mkdir(parents=True)
    earlier = {"picks": [{"story_key": "toy_case", "member_ids": [EXCLUDED]}]}
    doc = {"picks": [{"story_key": "toy_case", "member_ids": [PICK]},
                     {"story_key": "toy", "member_ids": [EXCLUDED]}]}
    (fixed / "prediction_01_fixed.json").write_text(json.dumps(earlier))
    prediction = fixed / "prediction_02_fixed.json"
    prediction.write_text(json.dumps(doc))
    (fixed / "prediction_03_draft.json").write_text(json.dumps(earlier))
    original = snapshot(prediction)
    for cid, issue in ((CARD, OLD), (OTHER, NEW)):
        put_yaml(paths["cards_dir"] / f"{cid}.yaml",
                 {"topic": "지어낸 소재", "discovery": f"{issue}, 2026-01-04 방송 예측 (toy_case)."})
        put_yaml(paths["specs_dir"] / f"{cid}_20260103_120000.yaml", {})
    put_yaml(paths["specs_dir"] / f"{MISSING}_20260101_000000.yaml", {})
    with closing(sqlite3.connect(paths["db_path"])) as db:
        db.executemany("INSERT INTO issue_aliases(old_id,new_id) VALUES (?,?)",
                       [(OLD, NEW), (NEW, THIRD), (THIRD, NEW)])
        db.commit()
    result = read_json(paths, capsys)
    assert [c["card_id"] for c in result["cards"]] == [CARD, OTHER]
    for card, direct in zip(result["cards"], (OLD, NEW)):
        assert {(link["issue_id"], link["via"]) for link in card["links"]} == {
            (direct, "discovery"), (NEW if direct == OLD else OLD, "별칭"), (THIRD, "별칭"),
            (PICK, "예측 2026-01-04 toy_case")}
    assert result["notices"] == [f"{MISSING}: 카드 파일이 없어 건너뜀"]
    assert [c["card_id"] for c in read_json(paths, capsys, OTHER)["cards"]] == [OTHER]
    assert snapshot(prediction) == original


@pytest.mark.parametrize(("discovery", "expected"), [
    ("2026-01-04 방송 예측 (alpha); 2026-01-11 방송 예측 (beta)",
     [(OLD, "예측 2026-01-04 alpha"), (NEW, "예측 2026-01-11 beta")]),
    ("beta; 2026-01-04 방송 예측 alpha를", [(OLD, "예측 2026-01-04 alpha")]),
    ("2026-01-04 방송 예측 alpha_extra, pre_alpha", []),
])
def test_prediction_story_scope(paths, discovery, expected):
    picks = [{"story_key": "alpha", "member_ids": [OLD]}, {"story_key": "beta", "member_ids": [NEW]}]
    for day in ("2026-01-04", "2026-01-11"):
        folder = paths["predictions_dir"] / day
        folder.mkdir(parents=True)
        (folder / "prediction_01_fixed.json").write_text(json.dumps({"picks": picks}))
    links = refresh.issue_links(discovery, paths["predictions_dir"], {})
    assert [(link["issue_id"], link["via"]) for link in links] == expected


def test_issue_id_boundaries(paths):
    issue = "t20260101-1000"
    folder = paths["predictions_dir"] / "2026-01-04"
    folder.mkdir(parents=True)
    picks = [{"story_key": "alpha", "member_ids": [issue, OLD + "x", "1" + NEW]}]
    (folder / "prediction_01_fixed.json").write_text(json.dumps({"picks": picks}))
    discovery = f"{issue}는 연결하고 x{OLD}, 1{NEW}는 제외. 2026-01-04 방송 예측 (alpha)"
    assert refresh.issue_links(discovery, paths["predictions_dir"], {}) == [
        {"issue_id": issue, "via": "discovery"}, {"issue_id": issue, "via": "예측 2026-01-04 alpha"}]


def test_unlinked_and_rule(paths, capsys):
    put_yaml(paths["cards_dir"] / f"{CARD}.yaml", {"topic": "긴" * 41, "discovery": "2026-01-05 방송 예측 toy"})
    assert refresh.main([], **paths) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"== {CARD} · " + "긴" * 40
    assert "   연결 이슈: 연결 없음" in lines
    assert "   카드 discovery 에 엔진 이슈 번호(t…)를 적으면 잇는다(discovery 는 승인 지문 밖)" in lines
    assert "   갱신 후보 0건" in lines
    assert lines[-1] == RULE
    result = read_json(paths, capsys)
    assert result["rule"] == RULE and result["cards"][0]["links"] == []


@pytest.fixture
def events(paths):
    day = "2026-01-03"
    rows = [("final", day, "2026-01-03T03:01:00Z"), ("calc", day, "2026-01-03T03:02:00Z"),
            ("equal", day, "2026-01-03T03:00:00Z"), ("midnight", day, "2026-01-02T15:00:00Z"),
            ("missing-clock", day, None), ("later", "2026-01-04", None), ("earlier", "2026-01-02", None)]
    with closing(sqlite3.connect(paths["db_path"])) as db:
        db.execute("INSERT INTO issue_aliases(old_id,new_id) VALUES (?,?)", (OLD, NEW))
        for uid, when, first in rows:
            db.execute("INSERT INTO issue_followups VALUES (?,?,?,?,?,?)",
                       (OLD, when, uid, "a", '["x","y"]', '["하나"]'))
            db.execute("""INSERT INTO groups(group_id,day,calc_id,final,first_at,title,members)
                          VALUES (?,?,2,?,?,?,?)""",
                       (uid, when, int(uid == "final"), first, "선택 " + uid, '["없음","a","b","c","d"]'))
        db.execute("INSERT INTO issue_followups VALUES (?,?,?,?,?,?)", (NEW, day, "final", "a", '["y","z"]', '["둘"]'))
        db.executemany("""INSERT INTO groups(group_id,day,calc_id,final,first_at,title,members)
                          VALUES (?,?,?,?,?,'버릴 줄','[]')""",
                       [("final", day, 3, 0, "2026-01-02T00:00:00Z"), ("final", day, 1, 1, None),
                        ("calc", day, 1, 0, None)])
        db.executemany("INSERT INTO articles(item_key,outlet,canon_url) VALUES (?,?,?)",
                       [(k, "가상 매체 " + k, f"https://example.invalid/{k}") for k in "abcd"])
        db.commit()
    return paths


def test_candidates_units_versions_and_articles(events, capsys):
    card = read_json(events, capsys)["cards"][0]
    by_id = {u["unit_id"]: u for u in card["candidates"]}
    assert len(card["candidates"]) == len(by_id) == 4
    assert set(by_id) == {"final", "calc", "later", "missing-clock"}
    assert card["before"] == []
    assert by_id["missing-clock"]["same_day_unknown"] and not by_id["later"]["same_day_unknown"]
    final = by_id["final"]
    assert (final["issue_ids"], final["families"], set(final["new_terms"])) == ([OLD, NEW], ["x", "y", "z"], {"하나", "둘"})
    assert (final["title"], final["first_at"]) == ("선택 final", "2026-01-03T12:01:00+09:00")
    assert by_id["calc"]["title"] == "선택 calc"
    assert final["articles"] == [{"outlet": "가상 매체 " + k, "canon_url": f"https://example.invalid/{k}"} for k in "abc"]
    assert refresh.main([], **events) == 0
    output = capsys.readouterr().out
    assert "판 이전 후속" not in output and "같은 날(시각 모름)" in output
    assert f"12:01 [{OLD}, {NEW}] 선택 final  · 계열 3곳" in output


def test_since_and_all(events, capsys):
    card = read_json(events, capsys, "--all")["cards"][0]
    assert {u["unit_id"] for u in card["before"]} == {"equal", "midnight", "earlier"}
    assert refresh.main(["--all"], **events) == 0
    assert "판 이전 후속 3건" in capsys.readouterr().out
    card = read_json(events, capsys, "--since", "2026-01-03", "--all")["cards"][0]
    assert {u["unit_id"] for u in card["before"]} == {"midnight", "earlier"}
    assert {u["unit_id"] for u in card["candidates"]} == {"equal", "final", "calc", "later", "missing-clock"}
    assert refresh.main(["--since", "2026-01-03", "--all"], **events) == 0
    output = capsys.readouterr().out
    assert "조회 기준 이전 후속 2건" in output and "갱신 후보 5건" in output


def test_edition_and_claim_pages(paths, capsys):
    specs = paths["specs_dir"]
    ids = [f"{CARD}-c{n}" for n in range(1, 8)]
    slides = [{"claim_ids": [ids[0]], "chart": {"claims": [ids[1], ids[0]]}},
              {"stage": "광고", "capture": ids[2]},
              {"pair": [{"capture": ids[3]}, {"chart": {"claims": [ids[1], ids[4]]}}],
               "swap": {"set": {"claim_ids": [ids[5]]}}},
              {"number_claims": [{"claim_id": ids[6]}]}]
    suffix = put_yaml(specs / f"{CARD}_20260104_000000_검토.yaml", {"slides": slides})
    put_yaml(specs / f"{CARD}_20260103_235959.yaml", {})
    (specs / f"make_{CARD}_20270101_000000.py").write_text("")
    card = read_json(paths, capsys)["cards"][0]
    assert (card["last_spec"], card["last_spec_at"]) == (suffix.name, "2026-01-04T00:00:00+09:00")
    assert list(card["claim_pages"].items()) == list(zip(ids, [[1], [1, 3], [2], [3], [3], [3], [4]]))
    plain = put_yaml(specs / f"{CARD}_20260104_000000.yaml", {})
    card = read_json(paths, capsys)["cards"][0]
    assert card["last_spec"] == plain.name and card["claim_pages"] == {}


def test_invalid_edition_does_not_hide_valid_cards(paths, capsys):
    specs = paths["specs_dir"]
    invalid = [f"{CARD}_20260230_120000.yaml", f"{OTHER}_20260101_240000.yaml"]
    for name in invalid:
        put_yaml(specs / name, {})
    put_yaml(paths["cards_dir"] / f"{OTHER}.yaml", {})
    put_yaml(specs / f"{OTHER}_20260102_120000.yaml", {})
    result = read_json(paths, capsys)
    assert [card["last_spec"] for card in result["cards"]] == [
        f"{CARD}_20260103_120000.yaml", f"{OTHER}_20260102_120000.yaml"]
    assert result["notices"] == [f"{name}: 사양 파일 이름의 타임코드가 날짜가 아니라 건너뜀" for name in invalid]


@pytest.mark.parametrize(("history", "comparison", "missing"), [
    ([("게이트", "A"), ("재확인", "B")], "다름", "검토·빌드·재확인"),
    ([("재확인", "B"), ("게이트", "A")], "같음", None),
    ([], "기록 없음", None),
    ([("게이트", "B")], "다름", "검토·빌드·게이트·재확인"),
    ([("검토", "A"), ("빌드", "A"), ("게이트", "A"), ("재확인", "A"), ("게이트", "B")], "다름", None),
])
def test_progress(paths, capsys, history, comparison, missing):
    edition = next(paths["specs_dir"].glob("*.yaml"))
    hashes = {"A": hashlib.sha256(edition.read_bytes()).hexdigest(), "B": "0" * 64}
    steps = [{"step": step, "spec_sha256": hashes[version]} for step, version in history]
    put_yaml(paths["builds_dir"] / CARD / "state.yaml", {"status": "완성", "steps": steps + [{"step": "산출"}]})
    assert refresh.main([], **paths) == 0
    output = capsys.readouterr().out
    line = f"   진행 기록: 완성 · 마지막 사양 해시 {comparison}"
    if missing:
        line += f" · 마지막 판으로 기록되지 않은 단계: {missing}"
    assert line in output.splitlines()


def test_readonly_cli(events, capsys, monkeypatch):
    path = events["db_path"]
    initial = snapshot(path)
    main = refresh.main
    monkeypatch.setattr(refresh, "main", lambda argv: main(argv, **{**events, "db_path": path.with_suffix(".missing")}))
    assert render.main(["refresh-candidates", CARD, "--db", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cards"][0]["candidates"]
    with closing(refresh.open_db(path)) as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("UPDATE issue_followups SET day='2099-01-01'")
    assert snapshot(path) == initial


def test_concurrent_collection(events, capsys, monkeypatch):
    """매시 수집이 조회 중에 끝나도 다음 조회부터 새 묶음을 보여야 한다."""
    followups = refresh.followups
    with closing(sqlite3.connect(events["db_path"], timeout=0)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"

        def collect_then_read(*args):
            writer.execute("UPDATE groups SET title='다음 수집' WHERE group_id='final'")
            writer.commit()
            return followups(*args)

        with monkeypatch.context() as patch:
            patch.setattr(refresh, "followups", collect_then_read)
            during = read_json(events, capsys)["cards"][0]["candidates"]
        after = read_json(events, capsys)["cards"][0]["candidates"]
    assert next(u["title"] for u in during if u["unit_id"] == "final") == "선택 final"
    assert next(u["title"] for u in after if u["unit_id"] == "final") == "다음 수집"


def test_cli_errors(paths, capsys):
    missing = paths["db_path"].with_suffix(".missing")
    assert refresh.main(["--db", str(missing)], **paths) == 2
    output = capsys.readouterr()
    assert not output.out and len(output.err.splitlines()) == 1 and not missing.exists()
    with pytest.raises(SystemExit, match="모르는 옵션"):
        refresh.main(["--al"], **paths)
    with pytest.raises(SystemExit, match="YYYY-MM-DD"):
        refresh.main(["--since", "2026-02-30"], **paths)
