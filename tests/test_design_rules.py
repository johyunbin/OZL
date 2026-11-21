"""지어낸 편으로 설계표의 모집단, 장 번호와 시각 경계를 확인한다."""
import codecs
import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from ozl.analyze import design_rules as rules


SCHEMA = """
CREATE TABLE videos(video_id TEXT PRIMARY KEY, title, upload_at, duration_sec, kind);
CREATE TABLE sd_videos(video_id TEXT PRIMARY KEY, duration_sec, n_slides);
CREATE TABLE sd_slides(video_id, no, flash, kind, layout, n_graphics, title_color, title, t_first);
CREATE TABLE sd_lines(video_id, no, line_no, size_class, color, text);
CREATE TABLE sd_picture_labels(video_id, no, labeler, primary_kind);
CREATE TABLE v3_segments(video_id, seg, start_sec, end_sec, field, field2, korea_level,
                         evergreen, topic_line, question);
"""
TITLE = "꾸며낸 제목 표식"
TOPIC = "꾸며낸 소재, 두 번째 칸"
QUESTION = "꾸며낸 질문 표식"
BODY = "꾸며낸 본문 표식"
ASOF = "2026-04-01"
PUBLISHED = "2025-01-01 09:00"
FETCHED = "2026-03-31T15:00:00Z"  # 한국 시각 4월 1일 0시


def composition(vid, n, stages):
    return dict(video_id=vid, n_slides=n, stages=[dict(stage=s, slide_from=a, slide_to=b)
                                                  for s, a, b in stages],
                slide_roles=[dict(no=i, role="data", source_type="official") for i in range(1, n + 1)],
                reversals=[], korea_link={}, humor_slides=[])


def seed_db(db):
    long_form = ["a", "b", "c", "d", "e", "f", "stale", "young", "future", "old"]
    with closing(sqlite3.connect(db)) as con, con:
        con.executescript(SCHEMA)
        for vid in [*long_form, "live"]:
            con.execute("INSERT INTO videos VALUES(?,?,?,?,?)",
                        (vid, TITLE, PUBLISHED, 1200, "본편" if vid != "live" else "생방송 전체"))
            field = "해외 경제" if vid == "f" else "기업·증시"
            con.execute("INSERT INTO v3_segments VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (vid, 1, 0, 100, field, "역사", "직접", "상시", TOPIC, QUESTION))
        # 같은 길이는 1번 토막, 더 길면 2번 토막을 대표로 쓴다.
        con.executemany("INSERT INTO v3_segments VALUES(?,?,?,?,?,?,?,?,?,?)", [
            ("a", 2, 100, 200, "부동산", "", "간접", "시사", TOPIC, QUESTION),
            ("f", 2, 100, 201, "문화·생활", "", "간접", "중간", TOPIC, QUESTION),
            ("a", 3, 200, 225, "기업·증시", "", "간접", "시사", TOPIC, QUESTION)])
        con.executemany("INSERT INTO sd_videos VALUES(?,?,99)",
                        [("a", 900), ("b", 1200), ("c", 600), ("live", 4000)])
        con.executemany("INSERT INTO sd_slides VALUES(?,?,?,?,?,?,?,?,?*10)", [
            ("a", 9, 0, "slide", "image_left", 0, "red", TITLE, 9),
            ("a", 2, 0, "slide", None, None, None, TITLE, 2),
            ("a", 5, 1, "slide", "flash", 99, "other", TITLE, 5),
            ("a", 7, 0, "media", "image_full", 1, "black", TITLE, 7),
            ("b", 1, 0, "slide", None, None, None, TITLE, 1),
            ("live", 1, 0, "slide", None, None, None, TITLE, 1)])
        con.executemany("INSERT INTO sd_lines VALUES('a',?,?,?,?,?)", [
            (2, 1, "body", None, BODY), (5, 1, "body", "red", BODY),
            (7, 1, "body", "red", BODY), (9, 1, "large", "red", BODY),
            (9, 2, "body", "black", BODY), (9, 3, "body", "mixed", BODY)])
        con.executemany("INSERT INTO sd_picture_labels VALUES('a',?,?,?)", [
            (5, "z", "logo"), (7, "a", "chart"), (7, "z", "photo"), (9, "b", "table")])


def seed_catalog(path):
    columns = "video_id title published_kst duration_sec kind view_count fetched_at".split()
    data = [(vid, n, PUBLISHED, FETCHED) for vid, n in zip("abcdef", (0, 10, 20, 30, 40, 80))]
    data[0] = ("a", 0, PUBLISHED, "2026-03-01T15:00:00Z")  # 30일 전
    data[1] = ("b", 10, "2026-03-18 00:00", FETCHED)  # 정확히 14일
    data.extend([
        ("stale", 9001, PUBLISHED, "2026-03-01T14:59:59Z"),
        ("young", 9002, "2026-03-18 00:01", FETCHED),
        ("future", 9003, PUBLISHED, "2026-04-01T15:00:00Z"),
        ("old", 9004, "2024-12-31 23:59", FETCHED),
        ("live", 9005, PUBLISHED, FETCHED)])
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        for vid, count, published, fetched in data:
            writer.writerow((vid, TITLE, published, 1200, "video", count, fetched))


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "fake #1?.db"
    base, extra = Path("private/compose"), Path("extra")
    base.mkdir(parents=True)
    extra.mkdir()
    seed_db(db)
    seed_catalog(Path("catalog.csv"))
    a = composition("a", 3, [("hook", 1, 1), ("other:" + BODY, 1, 2), ("other:2", 3, 3)])
    a.update(reversals=[{"slide_no": 3}, {"slide_no": 2}], korea_link={"present": True, "slide_no": 3},
             humor_slides=[2])
    a["slide_roles"][1] = dict(no=2, role="quote", source_type="foreign_press")
    for directory, doc in [(base, composition("a", 8, [("discarded", 1, 8)])), (extra, a),
                           (base, composition("b", 1, [("hook", 1, 1)])),
                           (base, composition("f", 1, [("closing", 1, 1)])),
                           (base, composition("no_v3", 1, [("closing", 1, 1)]))]:
        (directory / (doc["video_id"] + ".json")).write_text(json.dumps(doc), encoding="utf-8")
    (base / "_notes.json").write_text(json.dumps({"memo": "꾸며낸 메모"}), encoding="utf-8")  # video_id 없는 JSON 은 건너뛴다
    (base / "README.md").write_text("invalid")
    before = db.read_bytes()
    rules.main(["--db", str(db), "--catalog", "catalog.csv", "--compose-dirs", str(extra),
                "--labeler", "absent", "z", "--asof", ASOF, "--out", "out"])
    assert db.read_bytes() == before
    return Path("out")


def report(out, name):
    return json.loads((out / (name + ".json")).read_text(encoding="utf-8"))


def test_durations_and_origin_fit(outputs):
    data = report(outputs, "slides_by_duration")
    assert data["n_videos"] == 3
    assert data["videos"] == [
        dict(video_id="a", minutes=15, n_slides=2, n_media=1, sec_per_slide=450),
        dict(video_id="b", minutes=20, n_slides=1, n_media=0, sec_per_slide=1200),
        dict(video_id="c", minutes=10, n_slides=0, n_media=0, sec_per_slide=None)]
    assert [v["n_videos"] for v in data["bins"].values()] == [1, 1, 1, 0, 0, 0]
    assert data["bins"]["[15,20)"]["n_slides_median"] == 2
    assert data["bins"]["[35,∞)"]["n_slides_p75"] is None
    assert data["origin_fit"]["slides_per_minute"] == pytest.approx(50 / 725)
    assert data["origin_fit"]["r2_uncentered"] == pytest.approx(2500 / (725 * 5))


def test_stage_join_overlap_and_denominators(outputs):
    data = report(outputs, "stage_mix")
    assert data["n_videos"] == 4
    assert data["total"]["n_slides"] == 6
    assert set(data["stages"]) == {"hook", "other", "closing"}
    assert data["stages"]["hook"]["n_slides"] == 2
    assert data["stages"]["hook"]["red_body_share"] == {"denominator": 0, "mean": None}
    other = data["stages"]["other"]
    assert (other["n_slides"], other["n_videos"], other["slide_share"]) == (2, 1, 2 / 6)
    assert other["role"]["shares"] == {"quote": .5, "data": .5}
    assert other["source_type"]["shares"] == {"foreign_press": .5, "official": .5}
    assert other["layout"] == {"denominator": 2, "shares": {"image_full": .5, "image_left": .5}}
    assert other["primary_kind"] == {"denominator": 2, "shares": {"photo": .5, "table": .5}}
    assert other["red_body_share"] == {"denominator": 2, "mean": .5}
    assert other["n_graphics"] == {"denominator": 2, "mean": .5}
    assert other["title_color"]["shares"] == {"red": .5, "black": .5}
    assert data["total"]["layout"] == other["layout"]


def test_skeletons(outputs):
    groups = report(outputs, "skeletons")["branches"]
    assert groups["시장·기업"]["video_ids"] == ["a", "b"]
    assert groups["국내"]["video_ids"] == ["f"]
    assert groups["분류 없음"]["video_ids"] == ["no_v3"]
    assert groups["국제"]["skeleton"] == []
    branch = groups["시장·기업"]
    assert branch["n_stages_median"] == 2
    assert branch["first_reversal_median"] == 2 / 3
    assert branch["korea_link_position_median"] == 1
    assert branch["n_humor_slides_median"] == .5
    assert branch["n_reversals_median"] == 1
    assert branch["skeleton"] == [
        dict(stage="hook", first_position_median=(1 / 3 + 1) / 2,
             slide_share_median=(1 / 3 + 1) / 2, video_share=1),
        dict(stage="other", first_position_median=2 / 3, slide_share_median=2 / 3, video_share=.5)]
    assert rules.BRANCH["전쟁·안보"] == "국제"


def test_view_cohort_and_small_groups(outputs):
    stats = report(outputs, "views_stats")
    assert (stats["asof"], stats["n_videos"]) == (ASOF, 6)
    assert stats["discarded_stale"] == 1
    assert stats["discarded_rows"] == 5
    assert stats["discarded_by_reason"] == dict(stale=1, future=1, under_14_days=1, publication_date=1, not_main=1)
    assert stats["fetched_at_min"] == "2026-03-01T15:00:00+00:00"
    assert stats["fetched_at_max"] == "2026-03-31T15:00:00+00:00"
    assert (stats["median"], stats["p25"], stats["p75"], stats["p90"], stats["mean"]) == (25, 12.5, 37.5, 60, 30)
    groups = stats["groups"]
    assert groups["branch"]["국내"] == dict(n_videos=1)
    assert groups["field"]["기업·증시"] == dict(n_videos=5, median=20, multiple_of_overall=.8)
    assert groups["korea_level"]["간접"] == groups["evergreen"]["중간"] == dict(n_videos=1)
    assert groups["year"]["2026"] == dict(n_videos=1)
    assert groups["weekday"]["수"]["n_videos"] == groups["duration"]["[20,25)"]["n_videos"] == 6


def test_ledger_and_provenance(outputs):
    ledger = outputs / "topic_ledger.csv"
    assert ledger.read_bytes().startswith(codecs.BOM_UTF8)
    with ledger.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames == list(rules.LEDGER_COLUMNS)
        rows = list(reader)
    assert len(rows) == 13
    assert all(r["topic_line"] == TOPIC for r in rows)
    assert all(TITLE not in str(r) and QUESTION not in str(r) and BODY not in str(r) for r in rows)
    by_id = {r["video_id"]: r for r in rows}
    assert by_id["a"]["view_count"] == "0"
    assert by_id["b"]["age_days_at_fetch"] == "14"
    assert by_id["young"]["age_days_at_fetch"] == "13"
    assert all(by_id[k]["view_count"] == "" for k in ("stale", "young", "future", "old"))
    stats = report(outputs, "topic_ledger_summary")
    assert stats["n_videos"] == 10
    assert stats["fields"]["기업·증시"] == dict(n_videos=9, n_segments=10)
    assert stats["videos_by_year"] == {"2025": 10}
    assert stats["videos_by_month"] == {"2025-01": 10}
    assert stats["evergreen_share"] == 10 / 13
    jsons = sorted(outputs.glob("*.json"))
    assert len(jsons) == 5
    for path in jsons:
        raw = path.read_text(encoding="utf-8")
        assert all(marker not in raw for marker in (TITLE, TOPIC, QUESTION, BODY))
        obj = json.loads(raw)
        assert list(obj)[:3] == ["generated_at", "inputs", "n_videos"]
        inputs = obj["inputs"]
        assert Path(inputs["db"]).name == "fake #1?.db"
        assert len(inputs["compose"]) == 5
        for source in [inputs["catalog"], *inputs["compose"]]:
            assert source["sha256"] == hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()


def test_untimed_segments_do_not_choose_an_arbitrary_field():
    with closing(sqlite3.connect(":memory:")) as con:
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        con.executemany("""
            INSERT INTO v3_segments(video_id,seg,start_sec,end_sec,field) VALUES(?,?,?,?,?)
        """, [("one", 1, None, None, "역사"), ("unknown", 1, None, None, "역사"),
              ("unknown", 2, None, None, "부동산"), ("timed", 1, None, None, "역사"),
              ("timed", 2, 0, 300, "해외 경제")])
        reps = rules.representative_segments(con)
    assert {vid: row["field"] for vid, row in reps.items()} == {"one": "역사", "timed": "해외 경제"}


def test_cli_with_empty_cohorts_and_missing_db(tmp_path):
    db = tmp_path / "empty.db"
    with closing(sqlite3.connect(db)) as con:
        con.executescript(SCHEMA)
    (tmp_path / "labels").mkdir()
    (tmp_path / "meta.csv").write_text("video_id,fetched_at\n", encoding="utf-8")
    command = [sys.executable, "-m", "ozl.analyze.design_rules", "--catalog", "meta.csv",
               "--compose-dirs", "labels", "--asof", ASOF, "--out", "result", "--db"]
    subprocess.run([*command, db.name], cwd=tmp_path, check=True)
    out = tmp_path / "result"
    assert len(list(out.iterdir())) == 6
    for file in out.glob("*.json"):
        assert report(out, file.stem)["n_videos"] == 0
    assert report(out, "slides_by_duration")["origin_fit"]["slides_per_minute"] is None
    assert report(out, "views_stats")["median"] is None
    failure = subprocess.run([*command, "missing.db"], cwd=tmp_path, capture_output=True, text=True)
    assert failure.returncode != 0
    assert "unable to open database file" in failure.stderr
    assert not (tmp_path / "missing.db").exists()


def test_slide_features_by_time(tmp_path):
    """라벨 목록 시각이 있으면 순번이 아니라 t_first 로 잇는다(3초 넘게 떨어지면 잇지 않는다)."""
    db = tmp_path / "s.db"
    seed_db(db)
    with closing(sqlite3.connect(db)) as con:
        by_order = rules.slide_features(con, "a", [])
        by_time = rules.slide_features(con, "a", [], [70, 21, 40])
    assert [by_order[i]["layout"] for i in (1, 2, 3)] == [None, "image_full", "image_left"]
    assert by_time[1]["layout"] == "image_full" and by_time[2]["layout"] is None and 3 not in by_time
    lists = tmp_path / "lists"
    lists.mkdir()
    # no 가 적힌 목록은 순서가 아니라 no 로 잇고, 시각 없는 줄은 잇지 않는다
    (lists / "a.slides.json").write_text(json.dumps({"slides": [{"no": 2, "t_first": 90}, {"no": 1, "t_first": 70},
                                                                {"no": 3, "t_first": None}]}), encoding="utf-8")
    assert rules.slide_times([lists], "a") == {2: 90, 1: 70, 3: None}
    with closing(sqlite3.connect(db)) as con:
        mapped = rules.slide_features(con, "a", [], rules.slide_times([lists], "a"))
    assert mapped[1]["layout"] == "image_full" and mapped[2]["layout"] == "image_left" and 3 not in mapped
    # 어휘 밖 값(문구가 섞였을 수 있다)은 집계에 옮기지 않는다
    assert rules.category("꾸며낸 문구가 든 단계") == rules.UNKNOWN
    assert rules.category("other:꾸며낸 이름") == "other"
    assert rules.category("꾸며낸 출처", "source_type") == rules.UNKNOWN
    assert rules.slide_times([lists], "b") is None
