"""지어낸 문구와 획만으로 색 판정과 적재를 확인한다."""
import hashlib
import io
import json
import sqlite3
from contextlib import closing

import numpy as np
import pytest
from PIL import Image, ImageDraw

from ozl.analyze import slide_db


def swatch(background, strokes):
    image = Image.new("RGB", (120, 40), background)
    draw = ImageDraw.Draw(image)
    x = 10
    for width, color in strokes:
        draw.rectangle((x, 10, x + width - 1, 19), fill=color)
        x += width
    return image


@pytest.mark.parametrize(("background", "strokes", "expected", "fractions"), [
    ("white", [(100, "#c00000")], "red", (1, 0, 0)),
    ("white", [(100, "black")], "black", (0, 1, 0)),
    ("white", [(49, "#c00000"), (51, "black")], "mixed", (.49, .51, 0)),
    ("white", [(50, "#c00000"), (50, "black")], "red", (.5, .5, 0)),
    ("#202020", [(100, "white")], "on_dark", (0, 0, 1)),
    ("#202020", [(100, "#c8c8c8")], "on_dark", (0, 0, 1)),  # 어두운 바탕의 밝은 회색은 검정이 아니다
    ("white", [(100, "#505050")], "black", (0, 1, 0)),  # 압축으로 회색이 된 검정
    ("white", [(100, "blue")], "other", (0, 0, 1)),
    ("white", [], "none", (0, 0, 0)),
    ("white", [(2, "black")], "none", (0, 1, 0)),
    ("white", [(3, "black")], "black", (0, 1, 0)),
])
def test_line_color(background, strokes, expected, fractions):
    pixels = np.asarray(swatch(background, strokes))
    result = slide_db.line_color(pixels, (0, 0, 120, 40))
    count = sum(width * 10 for width, _ in strokes)
    assert result["color"] == expected
    assert result["ink_px"] == count
    assert result["ink_density"] == pytest.approx(count / (116 * 36))
    assert tuple(result[key] for key in ("red_frac", "black_frac", "other_frac")) == pytest.approx(fractions)


@pytest.mark.parametrize(("stroke", "color"), [("#c00000", "red"), ("black", "black")])
def test_jpeg_and_clipping(stroke, color):
    stream = io.BytesIO()
    swatch("white", [(30, stroke)]).save(stream, "JPEG", quality=60)
    stream.seek(0)
    with Image.open(stream) as image:
        pixels = np.asarray(image)
        assert slide_db.line_color(pixels, (-20, -10, 170, 60))["color"] == color
        assert slide_db.line_color(pixels, (-100, -100, 10, 10))["ink_px"] == 0
        assert slide_db.line_color(pixels, (10, 10, 4, 20))["color"] == "none"


@pytest.fixture
def dataset(tmp_path):
    src = tmp_path / "src"
    frames = tmp_path / "frames"
    src.mkdir()
    folder = frames / "paper"
    folder.mkdir(parents=True)
    image = Image.new("RGB", (1152, 680), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 90, 125, 99), fill="#c00000")
    draw.rectangle((150, 85, 224, 143), fill="black")
    draw.rectangle((105, 185, 135, 193), fill="black")
    image.save(folder / "page.png")

    common = dict(t_first=2, t_last=6, dwell_sec=6, n_samples=3, flash=False,
                  builds=1, kind="slide", body_text_lines=1, body_chars=5,
                  has_en=False, has_num=False, white_ratio=.95, best_t=4, sample_ts=[2, 4, 6])
    first = dict(common, no=1, title="종이별 실험", title_box=[100, 80, 140, 110],
                 body=["파도 획", "구름 획", "연 획", "달 획"],
                 body_boxes=[[100, 180, 44, h] for h in (25, 26, 52, 53)],
                 best_frame="page.png", layout="image_pair", boxes_ok=True, overlay_rep=False,
                 graphics=[[300, 300, 350, 400], [325, 300, 375, 400]])
    second = dict(common, no=2, title=None, title_box=None, body=["빈 종이"],
                  body_boxes=[[20, 20, 80, 34]], best_frame="absent.png")
    third = dict(common, no=3, title="달 모양", title_box=[40, 30, 120, 60],
                 body=[], body_boxes=[], graphics=[])
    data = dict(video_id="paper", duration_sec=40, step_sec=2, n_samples=20,
                classes={"clean": 17, "dialog": 3}, revisits=2, slides=[first, second, third])
    path = src / "paper.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, frames, data


def test_load_and_reload(dataset):
    path, frames, data = dataset
    con = sqlite3.connect(":memory:")
    expected = dict(videos=1, slides=3, lines=5, missing_frames=2)
    assert slide_db.load(con, path.parent, frames) == expected
    assert con.execute("SELECT count(*) FROM sd_picture_labels").fetchone() == (0,)
    con.execute("INSERT INTO sd_picture_labels(video_id,no,labeler,kinds) VALUES(?,?,?,?)",
                ("paper", 1, "tester", '["drawing"]'))
    con.commit()
    assert slide_db.load(con, path.parent, frames, ["paper"]) == expected
    assert con.execute("SELECT count(*), n_slides, n_clean, n_faded, n_dialog, frames_dir_ok, "
                       "src_sha256 FROM sd_videos GROUP BY video_id").fetchall() == [
        (1, 3, 17, 0, 3, 1, hashlib.sha256(path.read_bytes()).hexdigest())]
    assert con.execute("SELECT no, layout, n_graphics, graphics_area, title_color, frame_ok "
                       "FROM sd_slides ORDER BY no").fetchall() == [
        (1, "image_pair", 2, 10000 / (1152 * 680), "red", 1),
        (2, None, None, None, None, 0), (3, None, 0, 0, None, 0)]
    title_box, graphics = con.execute("SELECT title_box, graphics FROM sd_slides WHERE no=1").fetchone()
    assert json.loads(title_box) == data["slides"][0]["title_box"]
    assert json.loads(graphics) == data["slides"][0]["graphics"]
    assert con.execute("SELECT line_no, text, size_class, color FROM sd_lines ORDER BY no, line_no"
                       ).fetchall() == [
        (0, "파도 획", "small", "black"), (1, "구름 획", "body", "black"),
        (2, "연 획", "body", "black"), (3, "달 획", "large", "black"),
        (0, "빈 종이", "body", None)]
    assert con.execute("SELECT red_frac, black_frac, other_frac, ink_px, ink_density "
                       "FROM sd_lines WHERE no=2").fetchone() == (None,) * 5
    # 첫 장이 빠지면 줄은 사라져도 다음 단계의 라벨은 남아야 한다.
    data["slides"].pop(0)
    path.write_text(json.dumps(data), encoding="utf-8")
    slide_db.load(con, path.parent, frames)
    assert con.execute("SELECT count(*) FROM sd_lines").fetchone() == (1,)
    assert con.execute("SELECT no, kinds FROM sd_picture_labels").fetchall() == [(1, '["drawing"]')]
    con.close()


def test_failure_rolls_back_one_video(dataset, tmp_path):
    path, frames, data = dataset
    db = tmp_path / "atomic.db"
    con = sqlite3.connect(db)
    original = path.read_bytes()
    slide_db.load(con, path.parent, frames)
    new = dict(data, video_id="other", slides=[])
    (path.parent / "other.json").write_text(json.dumps(new), encoding="utf-8")
    data["slides"].append(data["slides"][0])
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(sqlite3.IntegrityError):
        slide_db.load(con, path.parent, frames, ["other", "paper"])
    con.close()
    con = sqlite3.connect(db)
    assert con.execute("SELECT video_id, frames_dir_ok, n_slides, src_sha256 FROM sd_videos "
                       "ORDER BY video_id").fetchall() == [
        ("other", 0, 0, hashlib.sha256(json.dumps(new).encode()).hexdigest()),
        ("paper", 1, 3, hashlib.sha256(original).hexdigest())]
    assert con.execute("SELECT count(*) FROM sd_lines").fetchone() == (5,)
    con.close()


def test_cli_counts_only(dataset, tmp_path, monkeypatch, capsys):
    path, frames, _ = dataset
    (path.parent / "unused.json").write_text("{}", encoding="utf-8")
    db = tmp_path / "counts.db"
    nice_calls = []
    monkeypatch.setattr(slide_db.os, "nice", nice_calls.append)
    slide_db.main(["load", "--db", str(db), "--src", str(path.parent), "--frames", str(frames),
                   "--only", "paper"])
    assert json.loads(capsys.readouterr().out) == dict(videos=1, slides=3, lines=5, missing_frames=2)
    slide_db.main(["stats", "--db", str(db)])
    assert json.loads(capsys.readouterr().out) == dict(
        videos=1, slides=3, lines=5, line_colors={"black": 4, "NULL": 1},
        size_class_by_color={"small": {"black": 1}, "body": {"black": 2, "NULL": 1},
                             "large": {"black": 1}}, title_colors={"red": 1, "NULL": 2})
    assert nice_calls == [19, 19]


def test_validate_kinds():
    assert slide_db.validate_kinds(("photo", "chart")) == ["photo", "chart"]
    with pytest.raises(ValueError):
        slide_db.validate_kinds(["chart", "unlisted"])


def test_moved_representative_frame_skips_body_color(dataset):
    """대표 프레임을 다른 시각으로 바꾼 장(rep_t != best_t)은 본문 색을 재지 않는다(제목 색은 잰다)."""
    path, frames, data = dataset
    data["slides"][0]["rep_t"] = 6
    path.write_text(json.dumps(data), encoding="utf-8")
    with closing(sqlite3.connect(":memory:")) as con:
        slide_db.load(con, path.parent, frames)
        colors = [r[0] for r in con.execute("SELECT color FROM sd_lines WHERE no=1")]
        title = con.execute("SELECT title_color FROM sd_slides WHERE no=1").fetchone()[0]
    assert colors and all(c is None for c in colors)
    assert title is not None
