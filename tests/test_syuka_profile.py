"""지어낸 예측 장부만으로 채택 표본, 로그 오즈와 금지 특징을 확인한다."""
import json
import math

import pytest

from ozl.syuka import db, ledger, profile
from ozl.syuka.__main__ import main


def _prediction(con, pid, kind):
    con.execute("""
        INSERT INTO predictions(prediction_id, broadcast_date, kind, file_path, sha256,
                                fixed_at, registered_at, schema, json)
        VALUES (?, '2031-01-05', ?, '가상자료.json', ?, '2031-01-01', '2031-01-01',
                'ozl.syuka.prediction/1', '{}')
    """, (pid, kind, pid))


def _event(con, pid, event_set, fixed_at):
    con.execute("""
        INSERT INTO broadcast_events(prediction_id, event_set, event_id, video_id, official, minor,
            label, summary, key_entities, key_numbers, timing, source_kind, source_sha256, fixed_at)
        VALUES (?, ?, 'E01', 'vidTEST0001', 1, 0, '가상국 잔치', '가상국은 잔치를 앞당겼다.',
                '[]', '[]', '시사', 'events_json', '가상해시', ?)
    """, (pid, event_set, fixed_at))


def _item(con, pid, story, name, category, *, members=1, rank=None, overlap=None):
    ids = [f"가상기사{i}" for i in range(members)]
    con.execute("""
        INSERT INTO prediction_items(prediction_id, story_key, set_name, rank, category,
                                     member_ids, engine_rank, overlap)
        VALUES (?, ?, ?, 1, ?, ?, ?, ?)
    """, (pid, story, name, category, json.dumps(ids), rank, overlap))


def _grade(con, pid, event_set, story, grade, judge="final"):
    con.execute("""
        INSERT INTO hit_judgments(prediction_id, event_set, story_key, judge, grade, judged_at)
        VALUES (?, ?, ?, ?, ?, '2031-01-10')
    """, (pid, event_set, story, judge, grade))


def test_fit_from_latest_ledger(tmp_path, capsys):
    con = db.connect(tmp_path / "test.db")
    try:
        ledger.ensure(con)
        _prediction(con, "official_test", "official")
        _prediction(con, "retro_test", "retro")
        _event(con, "official_test", "옛묶음", "2031-01-06")
        _event(con, "official_test", "새묶음", "2031-01-07")
        _event(con, "retro_test", "새묶음", "2031-01-07")
        _item(con, "official_test", "story_a", "pick", "가상 농업", members=6, overlap="후속")
        _item(con, "official_test", "story_a", "A", "다른 분류", rank=5)
        _item(con, "official_test", "story_a", "B", "다른 분류", rank=17)
        _item(con, "official_test", "story_b", "pick", "가상 농업", members=2)
        _item(con, "official_test", "story_c", "B", "가상 축제", rank=15)
        _item(con, "official_test", "story_d", "pick", "가상 축제")
        _item(con, "retro_test", "story_a", "A", "가상 소급 분류", rank=16)
        _grade(con, "official_test", "옛묶음", "story_a", "none")
        _grade(con, "official_test", "새묶음", "story_a", "full")
        _grade(con, "official_test", "새묶음", "story_b", "adjacent")
        _grade(con, "official_test", "새묶음", "story_c", "none")
        _grade(con, "official_test", "새묶음", "story_d", "pending")
        _grade(con, "official_test", "새묶음", "story_d", "full", "codex")
        _grade(con, "retro_test", "새묶음", "story_a", "none")
        samples = profile.rows(con)
        assert [(r["story_key"], r["adopted"]) for r in samples] == [
            ("story_a", 1), ("story_b", 1), ("story_c", 0)]
        assert [(r["in_A"], r["in_B"], r["picked"]) for r in samples] == [
            (True, True, True), (False, False, True), (False, True, False)]
        assert [r["overlap"] for r in samples] == ["후속", None, None]
        assert [r["engine_rank_band"] for r in samples] == ["1–5", "없음", "6–15"]
        assert [r["members_band"] for r in samples] == ["6+", "2–5", "모름"]
        with_retro = profile.rows(con, include_retro=True)
        assert len(with_retro) == 4
        assert with_retro[-1]["engine_rank_band"] == "16+"

        model = profile.fit(samples)
        assert model.n == 3
        categories = {r["value"]: r for r in model.table() if r["feature"] == "category"}
        assert categories["가상 농업"]["adopted"] == categories["가상 농업"]["n"] == 2
        assert categories["가상 농업"]["contribution"] == pytest.approx(math.log(2))
        assert categories["가상 축제"]["contribution"] == pytest.approx(math.log(1 / 3))
        score, parts = model.score({"category": "가상 농업", "overlap": "이미 다룸"})
        assert parts[0][:2] == ("category", "가상 농업")
        assert parts[0][2] == pytest.approx(math.log(2))
        assert parts[0][3] == 2
        assert parts[1] == ("overlap", "이미 다룸", 0.0, 0)
        assert score == pytest.approx(math.log(2))
        con.commit()
    finally:
        con.close()

    args = ["--db", str(tmp_path / "test.db"), "hits", "--profile"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "표본이 적어 참고용" in out and "가상 농업" in out and "가상 소급 분류" not in out
    assert main(args + ["--include-retro"]) == 0
    assert "가상 소급 분류" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["views_total", "LIKE_count", "comments", "전일조회수", "좋아요수", "댓글수"])
def test_reject_response_features(name):
    item = {"category": "가상 축제", name: 100}
    with pytest.raises(ValueError, match=name):
        profile.fit([dict(item, adopted=1)])
    with pytest.raises(ValueError, match=name):
        profile.fit([]).score(item)


def test_only_picks_have_a_known_member_count(tmp_path):
    con = db.connect(tmp_path / "test.db")
    try:
        ledger.ensure(con)
        _prediction(con, "test", "official")
        _event(con, "test", "묶음", "2031-01-06")
        for name in ("A", "B"):
            _item(con, "test", "only_baseline", name, "가상 분류")
        _item(con, "test", "one_member", "pick", "가상 분류")
        for story in ("only_baseline", "one_member"):
            _grade(con, "test", "묶음", story, "full")
        assert {r["story_key"]: r["members_band"] for r in profile.rows(con)} == {
            "only_baseline": "모름", "one_member": "1"}
    finally:
        con.close()
