"""/ozl find 의 도우미(.claude/skills/ozl/find/board_view.py) 시험.

후보 판은 지어낸 것(tests/fixtures/skills/board.json)만 쓰고, 자료 루트는 시험마다 임시 폴더로 준다(OZL_DESK_ROOT).
실제 후보 판과 실제 자료 루트는 읽지도 쓰지도 않는다.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "skills" / "ozl" / "find" / "board_view.py"
BOARD = ROOT / "tests" / "fixtures" / "skills" / "board.json"
NOW = "2099-01-01T09:30:00+09:00"          # 지어낸 판의 기준 시각(09:05:06)에서 24분 54초 뒤

_spec = importlib.util.spec_from_file_location("ozl_skill_board_view", SCRIPT)
bv = importlib.util.module_from_spec(_spec)
_keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True      # 스킬 폴더에 __pycache__ 를 남기지 않는다
try:
    _spec.loader.exec_module(bv)
finally:
    sys.dont_write_bytecode = _keep


@pytest.fixture
def desk(tmp_path, monkeypatch):
    d = tmp_path / "desk"
    d.mkdir()
    monkeypatch.setenv("OZL_DESK_ROOT", str(d))
    return d


def run(capsys, *args, now=NOW, board=BOARD):
    """도우미를 같은 프로세스에서 부른다. (종료 코드, 표준 출력, 표준 오류)"""
    argv = list(args)
    if board is not None and (not argv or argv[0] in ("note",) or argv[0].startswith("-")):
        argv += ["--board", str(board)]
    code = bv.main(argv + ["--now", now])
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def table(out: str) -> list[list[str]]:
    """표의 줄을 칸으로: [번호, 화제 번호, 제목, 분야, 며칠째, 매체, 민감, 한 줄, 이미]"""
    rows = []
    for line in out.splitlines():
        if re.match(r"\| \d+ \|", line):
            rows.append([c.strip() for c in line.strip()[1:-1].split("|")])
    return rows


def row(out: str, issue_id: str) -> list[str]:
    hit = [r for r in table(out) if r[1] == issue_id]
    assert len(hit) == 1, f"{issue_id} 줄이 {len(hit)}개"
    return hit[0]


# ── 표 ──────────────────────────────────────────────────────────────────

def test_fixture_board_is_invented_and_out_of_order():
    d = json.loads(BOARD.read_text(encoding="utf-8"))
    assert d["schema"] == "ozl.board/1" and d["asof"].startswith("2099-")
    ko = [c["story_rank"] for c in d["candidates"] if c.get("lang", "ko") == "ko"]
    assert ko != sorted(ko), "파일 안의 순서가 이미 story_rank 순이면 정렬을 시험하지 못한다"
    assert sum(1 for c in d["candidates"] if (c.get("sensitivity") or {}).get("level") == "RED") == 1
    assert len(d["searches_unmatched"]) == 2
    assert all("news.example" in l["url"] for c in d["candidates"] for l in c.get("links") or [])


def test_table_is_in_story_rank_order_korean_first(desk, capsys):
    code, out, err = run(capsys)
    assert code == 0 and err == ""
    ids = [r[1] for r in table(out)]
    assert ids == [f"t20990101-{n:03d}" for n in range(1, 11)]       # 한국어 1~9위, 그 뒤 영문 1위
    assert [r[0] for r in table(out)] == [str(n) for n in range(1, 11)]
    assert "(영문)" in row(out, "t20990101-010")[3]
    assert out.splitlines()[0].startswith("기준 시각 2099-01-01 09:05 KST(24분 전)")
    assert "후보 10줄 가운데 10줄" in out.splitlines()[0]


def test_sensitive_high_row_is_marked_not_removed(desk, capsys):
    _, out, _ = run(capsys)
    red = row(out, "t20990101-004")
    assert red[6].startswith("높음 · 덱 제외")
    assert [r[1] for r in table(out) if "덱 제외" in r[6]] == ["t20990101-004"]
    assert row(out, "t20990101-003")[6].startswith("주의")
    assert row(out, "t20990101-001")[6] == "없음"


def test_one_line_uses_summary_when_present_else_status_and_numbers(desk, capsys):
    _, out, _ = run(capsys)
    with_summary = row(out, "t20990101-002")[7]
    assert with_summary.startswith("가람은행이 1월 2일부터") and "왜 지금: 다른 은행 두 곳" in with_summary
    assert "왜 지금" not in row(out, "t20990101-003")[7]            # why_now 가 빈 글이면 붙이지 않는다
    assert row(out, "t20990101-001")[7] == "3일째 · 커지는 중 · 기사 31건 · 화제 점수 77"


def test_row_without_optional_fields_still_prints(desk, capsys):
    _, out, _ = run(capsys)
    bare = row(out, "t20990101-008")
    assert bare[4] == "2일째" and bare[5] == "오늘 3곳"
    assert bare[6] == "정리 전"                                      # 민감 칸이 없으면 지어내지 않는다
    assert bare[7] == "2일째 · 기사 4건 · 화제 점수 28"


def test_partial_day_shows_yesterday_outlets(desk, capsys):
    _, out, _ = run(capsys)
    assert row(out, "t20990101-001")[5] == "오늘 14곳, 어제 11곳"
    assert row(out, "t20990101-001")[4] == "3일째 · 이어지는 것"
    assert row(out, "t20990101-002")[4] == "1일째 · 새로 뜬 것"


def test_top_category_and_match(desk, capsys):
    _, out, _ = run(capsys, "--top", "3")
    assert [r[1][-3:] for r in table(out)] == ["001", "002", "003"]
    assert "조건에 맞는 후보가 7줄 더 있다" in out
    _, out, _ = run(capsys, "--category", "경제")
    assert [r[1][-3:] for r in table(out)] == ["002", "008"]
    _, out, _ = run(capsys, "--match", "태블릿")
    assert [r[1][-3:] for r in table(out)] == ["003"]
    _, out, _ = run(capsys, "--match", "불꽃")
    assert table(out) == [] and "조건에 맞는 후보가 없다" in out and "한빛시 불꽃축제(2000+)" in out


def test_unknown_category_lists_board_categories(desk, capsys):
    code, out, err = run(capsys, "--category", "날씨")
    assert code == 2 and out == ""
    assert "없는 분야: 날씨" in err and "경제 2" in err


def test_searches_listed_by_grade(desk, capsys):
    _, out, _ = run(capsys)
    line = next(l for l in out.splitlines() if l.startswith("검색에서만 보이는 낱말"))
    assert line.index("솔빛 마라톤 접수(5000+)") < line.index("한빛시 불꽃축제(2000+)")


def test_stale_board_warns_and_says_no_collect(desk, capsys):
    code, out, _ = run(capsys, now="2099-01-01T11:06:00+09:00")       # 기준 시각에서 2시간 1분
    assert code == 0
    assert out.splitlines()[1].startswith("경고: 후보 판이 2시간보다 오래됐다")
    assert "수집을 돌리지 않는다" in out.splitlines()[1]
    assert len(table(out)) == 10                                      # 알리기만 하고 표는 그대로 찍는다
    _, out, _ = run(capsys, now="2099-01-01T11:04:00+09:00")
    assert "경고:" not in out


def test_missing_or_wrong_board(desk, capsys, tmp_path):
    code, out, err = run(capsys, board=tmp_path / "none.json")
    assert code == 1 and "후보 판이 없다" in err and "수집을 돌리지 않는다" in err
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other/1", "candidates": []}), encoding="utf-8")
    code, _, err = run(capsys, board=bad)
    assert code == 1 and "꼴이 맞지 않는다" in err


def test_view_reads_only(desk, capsys):
    before = hashlib.sha256(BOARD.read_bytes()).hexdigest()
    run(capsys)
    run(capsys, "--json")
    run(capsys, "picks", board=None)
    assert hashlib.sha256(BOARD.read_bytes()).hexdigest() == before
    assert list(desk.rglob("*")) == [], "표 찍기와 기록 보기는 자료 루트에 아무것도 만들지 않는다"


def test_json_output(desk, capsys):
    code, out, _ = run(capsys, "--json", "--top", "4")
    v = json.loads(out)
    assert code == 0 and [r["issue_id"][-3:] for r in v["rows"]] == ["001", "002", "003", "004"]
    assert v["stale"] is False and v["age_min"] == 24 and v["total"] == 10
    assert v["rows"][3]["deck_blocked"] is True and v["rows"][3]["sensitivity"] == "높음"
    assert {"n", "issue_id", "title", "category", "day_n", "outlets_n", "line", "already", "dropped"} <= set(v["rows"][0])


def test_sens_words_same_as_ops_screen():
    from ozl.ops import candidates
    assert bv.SENS_WORD == candidates.SENS_WORD
    assert bv.BOARD_SCHEMA == candidates.BOARD_SCHEMA


# ── 고르기 기록 ───────────────────────────────────────────────────────────

def note(capsys, *args, now="2099-01-01T09:31:00+09:00"):
    return run(capsys, "note", *args, now=now)


def test_note_writes_record_under_desk_root(desk, capsys):
    code, out, err = note(capsys, "--pick", "t20990101-002", "t20990101-004", "--drop", "t20990101-005",
                          "--add", "한빛시 불꽃축제", "--add", "가람역 환승 통로 폐쇄")
    assert code == 0 and err == ""
    files = sorted((desk / "find").glob("*.json"))
    assert [f.name for f in files] == ["20990101_093100.json"]
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["schema"] == "ozl.find/1" and rec["chosen_by"] == "사람" and rec["at"] == "2099-01-01T09:31:00+09:00"
    assert [p["key"] for p in rec["picks"]] == ["t20990101-002", "t20990101-004", "a20990101_093100-1", "a20990101_093100-2"]
    assert [p["kind"] for p in rec["picks"]] == ["topic", "topic", "search", "manual"]   # 급상승어와 같은 제목은 search
    assert all(p["state"] == "대기" and p["issue"] is None for p in rec["picks"])
    first = rec["picks"][0]
    assert first["title"].startswith("가람은행") and first["status_line"] == "1일째 · 새로 뜸" and len(first["links"]) == 2
    assert rec["picks"][1]["deck_blocked"] is True
    assert rec["drops"] == [{"key": "t20990101-005", "title": "솔빛 축구단, 창단 12년 만에 1부 승격 확정",
                             "until": "2099-01-04T09:31:00+09:00"}]
    assert "/ozl make t20990101-002" in out and '/ozl make "가람역 환승 통로 폐쇄"' in out
    assert "민감 높음: t20990101-004" in out and "덱 제외" in out


def test_note_rejects_bad_input_and_writes_nothing(desk, capsys):
    for args, word in ((("--pick", "t20990101-999"), "후보 판에 없는 화제 번호"),
                       (("--pick", "3"), "화제 번호 꼴이 아니다"),
                       (("--pick", "t20990101-002", "--drop", "t20990101-002"), "두 번"),
                       ((), "하나는 준다"),
                       (("--add", " "), "1~120자")):
        code, out, err = note(capsys, *args)
        assert code == 2 and word in err, (args, err)
    assert list(desk.rglob("*")) == [], "거부한 입력은 폴더도 기록도 만들지 않는다"


def test_two_notes_in_same_second_get_two_files(desk, capsys):
    note(capsys, "--pick", "t20990101-001")
    note(capsys, "--pick", "t20990101-002")
    assert [f.name for f in sorted((desk / "find").glob("*.json"))] == ["20990101_093100.json", "20990101_093101.json"]


def test_dropped_rows_fold_for_three_days(desk, capsys):
    note(capsys, "--drop", "t20990101-005")
    _, out, _ = run(capsys, now="2099-01-02T09:00:00+09:00")
    assert "t20990101-005" not in [r[1] for r in table(out)]
    assert "버려서 접어 둔 후보 1줄(--all 로 본다)" in out
    assert [r[0] for r in table(out)] == [str(n) for n in range(1, 10)]      # 번호는 보이는 줄만 다시 센다
    _, out, _ = run(capsys, "--all", now="2099-01-02T09:00:00+09:00")
    assert row(out, "t20990101-005")[8].startswith("버림(2099-01-04 09:31 까지 접음)")
    _, out, _ = run(capsys, now="2099-01-04T09:32:00+09:00")                  # 사흘이 지나면 다시 보인다
    assert row(out, "t20990101-005")[8] == ""


def test_pick_after_drop_unfolds(desk, capsys):
    note(capsys, "--drop", "t20990101-005")
    note(capsys, "--pick", "t20990101-005", now="2099-01-01T10:00:00+09:00")
    _, out, _ = run(capsys, now="2099-01-01T10:01:00+09:00")
    assert row(out, "t20990101-005")[8] == "골라 둠(대기)"


def test_add_only_note_works_without_board(desk, capsys, tmp_path):
    code, out, _ = run(capsys, "note", "--add", "가람역 환승 통로 폐쇄", board=tmp_path / "none.json")
    assert code == 0 and '/ozl make "가람역 환승 통로 폐쇄"' in out


def test_picks_next_and_result(desk, capsys):
    note(capsys, "--pick", "t20990101-002", "t20990101-003", "--add", "가람역 환승 통로 폐쇄")
    code, out, _ = run(capsys, "picks", "--json", board=None, now="2099-01-01T09:40:00+09:00")
    v = json.loads(out)
    assert code == 0 and [x["key"] for x in v["remaining"]] == ["t20990101-002", "t20990101-003", "a20990101_093100-1"]
    assert v["next"]["key"] == "t20990101-002" and v["next"]["make"] == "t20990101-002"
    assert v["remaining"][2]["make"] == '"가람역 환승 통로 폐쇄"'

    code, out, _ = run(capsys, "result", "t20990101-002", "--state", "실행 중", board=None)
    assert code == 0 and "t20990101-002 → 실행 중" in out
    code, out, _ = run(capsys, "result", "t20990101-002", "--state", "끝남", "--issue", "i20990101-01",
                       "--note", "다른 계열 검토 대기", board=None, now="2099-01-01T10:20:00+09:00")
    assert code == 0 and "끝남, 글 i20990101-01, 다른 계열 검토 대기" in out
    rec = json.loads((desk / "find" / "20990101_093100.json").read_text(encoding="utf-8"))
    assert (rec["picks"][0]["state"], rec["picks"][0]["issue"], rec["picks"][0]["updated_at"]) == \
        ("끝남", "i20990101-01", "2099-01-01T10:20:00+09:00")

    _, out, _ = run(capsys, "picks", "--json", board=None, now="2099-01-01T10:21:00+09:00")
    assert json.loads(out)["next"]["key"] == "t20990101-003"
    _, out, _ = run(capsys, "picks", board=None, now="2099-01-01T10:21:00+09:00")
    assert "[끝남] t20990101-002" in out and "글 i20990101-01 · 다른 계열 검토 대기" in out
    assert "다음 건: t20990101-003" in out
    _, out, _ = run(capsys, now="2099-01-01T10:22:00+09:00")
    assert row(out, "t20990101-002")[8] == "글 i20990101-01"
    assert row(out, "t20990101-003")[8] == "골라 둠(대기)"


def test_result_rejects_unknown_key_and_bad_issue(desk, capsys):
    note(capsys, "--pick", "t20990101-002")
    code, _, err = run(capsys, "result", "t20990101-009", "--state", "끝남", board=None)
    assert code == 2 and "고르기 기록에 없는 key" in err
    code, _, err = run(capsys, "result", "t20990101-002", "--state", "끝남", "--issue", "20990101-01", board=None)
    assert code == 2 and "이슈 번호 꼴이 아니다" in err


def test_old_records_are_not_offered_as_next(desk, capsys):
    note(capsys, "--pick", "t20990101-002")
    _, out, _ = run(capsys, "picks", "--json", board=None, now="2099-01-05T09:00:00+09:00")     # 나흘 뒤
    v = json.loads(out)
    assert v["next"] is None and len(v["records"]) == 1


def test_no_records_message(desk, capsys):
    code, out, _ = run(capsys, "picks", board=None)
    assert code == 0 and out.strip() == "고르기 기록이 없다."


# ── 이미 만든 글 ──────────────────────────────────────────────────────────

def test_existing_issues_listed_with_titles(desk, capsys):
    shutil.copytree(ROOT / "tests" / "fixtures" / "issues", desk / "issues")
    _, out, _ = run(capsys)
    assert "이미 만든 글 2건(제목을 위 표와 견준다):" in out
    assert any(l.startswith("- i20990101-01 · ") and "버스 400원 인상" in l for l in out.splitlines())


def test_queue_item_links_topic_to_issue(desk, capsys):
    (desk / "ops").mkdir()
    q = {"schema": 1, "items": [
        {"job_id": "m20990101-0001", "key": "t:t20990101-001", "kind": "topic", "title": "지어낸 항목", "topic_id": "t20990101-001",
         "keyword": None, "deck": False, "state": "끝남", "issue_id": "i20990101-01", "note": ""},
        {"job_id": "m20990101-0002", "key": "t:t20990101-006", "kind": "topic", "title": "지어낸 항목", "topic_id": "t20990101-006",
         "keyword": None, "deck": False, "state": "대기", "issue_id": None, "note": ""}]}
    (desk / "ops" / "make_queue.json").write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
    _, out, _ = run(capsys)
    assert row(out, "t20990101-001")[8] == "글 i20990101-01"
    assert row(out, "t20990101-006")[8] == "대기열 m20990101-0002(대기)"


def test_no_issues_message(desk, capsys):
    _, out, _ = run(capsys)
    assert out.rstrip().endswith("이미 만든 글: 없다.")


# ── 실제 명령으로 한 번 ───────────────────────────────────────────────────

def test_cli_runs_from_repo_with_test_root(tmp_path):
    """스킬 문서가 적은 꼴 그대로(.venv/bin/python <스크립트>) 돌려 본다. 자료 루트는 임시 폴더."""
    env = dict(os.environ, OZL_DESK_ROOT=str(tmp_path / "desk"))
    base = [sys.executable, str(SCRIPT.relative_to(ROOT))]
    r = subprocess.run(base + ["--board", str(BOARD.relative_to(ROOT))], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert len(table(r.stdout)) == 10 and r.stdout.startswith("기준 시각 2099-01-01 09:05 KST")
    r = subprocess.run(base + ["note", "--board", str(BOARD.relative_to(ROOT)), "--pick", "t20990101-001"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert len(list((tmp_path / "desk" / "find").glob("*.json"))) == 1
    for sub in ((), ("note",), ("picks",), ("result",)):
        h = subprocess.run(base + [*sub, "--help"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert h.returncode == 0 and "usage:" in h.stdout


def test_alias_of_real_root_is_refused(tmp_path, monkeypatch, capsys):
    """실제 자료 루트를 다른 철자로 가리키면 기록을 쓰지 않는다."""
    monkeypatch.setenv("OZL_DESK_ROOT", str(tmp_path / "desk"))
    monkeypatch.setattr(bv.paths, "is_alias_of_real_root", lambda: True)
    code, _, err = note(capsys, "--add", "가람역 환승 통로 폐쇄")
    assert code == 2 and "기록을 쓰지 않는다" in err
    assert not (tmp_path / "desk").exists()
