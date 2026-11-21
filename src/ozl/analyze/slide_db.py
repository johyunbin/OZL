"""슬라이드 분석과 대표 프레임의 글자 색을 영상별로 적재한다."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
from PIL import Image

from ozl import paths as ozlpaths
from ozl.syuka.db import DB_PATH, connect, now

SRC_DIR = ozlpaths.at("slides_dense")
FRAMES_DIR = ozlpaths.at("frames_dense")
FRAME_AREA = 1152 * 680
BODY_H = (26, 52)

BOX_INSET = 2
BACKGROUND_BORDER = 2
INK_DISTANCE = 60
MIN_INK_PX = 30
# 영상 압축으로 검정 글자는 회색(최대 채널 중앙값 약 80, 상위 10% 약 150)이 되고 채널 차이는 0 에 가깝다.
# 그래서 검정은 밝기가 아니라 무채색(채널 차이 30 이하)으로, 빨강은 R 이 앞서는 정도로 가른다(2026-11-21 실측).
RED_MIN_R = 100
RED_MIN_LEAD = 40
BLACK_MAX_CHANNEL = 210
BLACK_MAX_SPREAD = 30
BLACK_BELOW_BACKGROUND = 40
RED_FRACTION = 0.5
BLACK_FRACTION = 0.6
MIXED_FRACTION = 0.2
DARK_BRIGHTNESS = 160

PICTURE_KINDS = ("photo", "article", "chart", "table", "logo", "person",
                 "map", "sns", "meme", "drawing", "none")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sd_videos(
  video_id TEXT NOT NULL PRIMARY KEY, duration_sec REAL, step_sec REAL, n_samples INTEGER,
  n_slides INTEGER, n_clean INTEGER, n_faded INTEGER, n_dialog INTEGER, revisits INTEGER,
  src_sha256 TEXT, frames_dir_ok INTEGER, loaded_at TEXT);
CREATE TABLE IF NOT EXISTS sd_slides(
  video_id TEXT NOT NULL, no INTEGER NOT NULL, t_first REAL, t_last REAL, dwell_sec REAL,
  n_samples INTEGER, flash INTEGER, builds INTEGER, kind TEXT, layout TEXT, boxes_ok INTEGER,
  overlay_rep INTEGER, title TEXT, title_box TEXT, body_text_lines INTEGER, body_chars INTEGER,
  has_en INTEGER, has_num INTEGER, white_ratio REAL, best_t REAL, best_frame TEXT, frame_ok INTEGER,
  n_graphics INTEGER, graphics TEXT, graphics_area REAL, title_color TEXT, PRIMARY KEY(video_id, no));
CREATE TABLE IF NOT EXISTS sd_lines(
  video_id TEXT NOT NULL, no INTEGER NOT NULL, line_no INTEGER NOT NULL, text TEXT,
  x INTEGER, y INTEGER, w INTEGER, h INTEGER, size_class TEXT, color TEXT,
  red_frac REAL, black_frac REAL, other_frac REAL, ink_px INTEGER, ink_density REAL,
  PRIMARY KEY(video_id, no, line_no));
CREATE TABLE IF NOT EXISTS sd_picture_labels(
  video_id TEXT NOT NULL, no INTEGER NOT NULL, labeler TEXT NOT NULL, model TEXT, kinds TEXT,
  primary_kind TEXT, confidence REAL, run_id TEXT, labeled_at TEXT, note TEXT,
  PRIMARY KEY(video_id, no, labeler));
"""


def validate_kinds(kinds) -> list[str]:
    """그림 종류를 검사하고 입력 순서를 보존한다."""
    if isinstance(kinds, (str, bytes)):
        raise ValueError("그림 종류는 목록으로 지정해야 합니다")
    values = list(kinds)
    for value in values:
        if value not in PICTURE_KINDS:
            raise ValueError(f"모르는 그림 종류: {value!r}")
    return values


def line_color(a: np.ndarray, box) -> dict:
    """안쪽으로 줄이고 자른 상자에서 테두리색과 다른 획을 센다."""
    x, y, w, h = box
    height, width = a.shape[:2]
    x0, y0 = max(0, x + BOX_INSET), max(0, y + BOX_INSET)
    x1, y1 = min(width, x + w - BOX_INSET), min(height, y + h - BOX_INSET)
    if x1 <= x0 or y1 <= y0:
        return dict(color="none", red_frac=0., black_frac=0., other_frac=0., ink_px=0, ink_density=0.)

    pixels = a[y0:y1, x0:x1].astype(np.float32)
    border = np.ones(pixels.shape[:2], dtype=bool)
    b = BACKGROUND_BORDER
    border[b:-b, b:-b] = False
    background = np.median(pixels[border], axis=0)
    diff = pixels - background
    ink = pixels[(diff * diff).sum(axis=2) >= INK_DISTANCE ** 2]
    count = len(ink)
    r, g, blue = ink.T
    maximum = ink.max(axis=1)
    red = np.count_nonzero((r >= RED_MIN_R) & (r - np.maximum(g, blue) >= RED_MIN_LEAD))
    # 검정은 무채색이면서 바탕보다 어두워야 한다(어두운 바탕의 밝은 회색 글자를 검정으로 세지 않는다)
    black = np.count_nonzero((maximum <= BLACK_MAX_CHANNEL) &
                             (maximum - ink.min(axis=1) <= BLACK_MAX_SPREAD) &
                             (ink.mean(axis=1) < background.mean() - BLACK_BELOW_BACKGROUND))
    denominator = max(count, 1)
    red_frac, black_frac = red / denominator, black / denominator
    if count < MIN_INK_PX:
        color = "none"
    elif red_frac >= RED_FRACTION:
        color = "red"
    elif black_frac >= BLACK_FRACTION:
        color = "black"
    elif min(red_frac, black_frac) >= MIXED_FRACTION:
        color = "mixed"
    elif background.mean() < DARK_BRIGHTNESS:
        color = "on_dark"
    else:
        color = "other"
    return dict(color=color, red_frac=red_frac, black_frac=black_frac,
                other_frac=(count - red - black) / denominator, ink_px=count,
                ink_density=count / ((x1 - x0) * (y1 - y0)))


def _size_class(h):
    if h < BODY_H[0]:
        return "small"
    if h > BODY_H[1]:
        return "large"
    return "body"


def _slide_rows(video_id, slide, frame_dir):
    frame_name = slide.get("best_frame")
    frame = None
    if frame_name:
        if Path(frame_name).name != frame_name:
            raise ValueError("대표 프레임은 파일 이름이어야 합니다")
        path = frame_dir / frame_name
        if path.is_file():
            with Image.open(path) as image:
                frame = np.asarray(image.convert("RGB"))

    title_box = slide.get("title_box")
    title_color = None
    if frame is not None and title_box is not None:
        x0, y0, x1, y1 = title_box
        title_color = line_color(frame, (x0, y0, x1 - x0, y1 - y0))["color"]

    graphics = slide.get("graphics")
    area = None
    if graphics is not None:
        area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in graphics) / FRAME_AREA
    fields = ("t_first", "t_last", "dwell_sec", "n_samples", "flash", "builds", "kind", "layout",
              "boxes_ok", "overlay_rep", "title", "body_text_lines", "body_chars", "has_en",
              "has_num", "white_ratio", "best_t")
    key = dict(video_id=video_id, no=slide["no"])
    row = {**key, **{name: slide.get(name) for name in fields},
           "title_box": json.dumps(title_box) if title_box is not None else None,
           "best_frame": frame_name, "frame_ok": int(frame is not None),
           "n_graphics": len(graphics) if graphics is not None else None,
           "graphics": json.dumps(graphics) if graphics is not None else None,
           "graphics_area": area, "title_color": title_color}

    lines = []
    for i, (text, box) in enumerate(zip(slide["body"], slide["body_boxes"], strict=True)):
        x, y, w, h = box
        line = dict(key, line_no=i, text=text, x=x, y=y, w=w, h=h, size_class=_size_class(h))
        # 대표 프레임을 다른 시각(rep_t)으로 바꾼 장은 본문 상자가 그 화면의 것이 아닐 수 있어 재지 않는다
        moved = slide.get("rep_t") is not None and slide.get("rep_t") != slide.get("best_t")
        if frame is None or moved:
            line.update(color=None, red_frac=None, black_frac=None, other_frac=None,
                        ink_px=None, ink_density=None)
        else:
            line.update(line_color(frame, box))
        lines.append(line)
    return row, lines


def _insert_rows(con, table, rows):
    if not rows:
        return
    columns = tuple(rows[0])
    params = ", ".join(":" + name for name in columns)
    con.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({params})", rows)


def load(con, src_dir, frames_dir, video_ids=None) -> dict:
    """프레임 판독 뒤 한 편씩 교체하며, 기존 그림 라벨은 보존한다."""
    src_dir, frames_dir = Path(src_dir), Path(frames_dir)
    if not src_dir.is_dir():
        raise FileNotFoundError(src_dir)
    ids = sorted(p.stem for p in src_dir.glob("*.json")) if video_ids is None else dict.fromkeys(video_ids)
    for statement in SCHEMA.split(";"):
        if statement.strip():
            con.execute(statement)
    totals = dict(videos=0, slides=0, lines=0, missing_frames=0)
    for vid in ids:
        if not vid or Path(vid).name != vid or vid in (".", ".."):
            raise ValueError("영상 번호는 파일 이름이어야 합니다")
        raw = (src_dir / f"{vid}.json").read_bytes()
        data = json.loads(raw)
        if data["video_id"] != vid:
            raise ValueError(f"파일 이름과 영상 번호가 다릅니다: {vid}")
        frame_dir = frames_dir / vid
        slides, lines = [], []
        for slide in data["slides"]:
            row, body = _slide_rows(vid, slide, frame_dir)
            slides.append(row)
            lines.extend(body)
        video = dict(video_id=vid, duration_sec=data["duration_sec"], step_sec=data["step_sec"],
                     n_samples=data["n_samples"], n_slides=len(slides), revisits=data["revisits"],
                     src_sha256=hashlib.sha256(raw).hexdigest(), frames_dir_ok=int(frame_dir.is_dir()),
                     loaded_at=now())
        for name in ("clean", "faded", "dialog"):
            video["n_" + name] = data["classes"].get(name, 0)

        # 호출자가 연 거래가 있으면 그 안에서 이 편만 되돌린다.
        con.execute("SAVEPOINT slide_video")
        try:
            for table in ("sd_lines", "sd_slides", "sd_videos"):
                con.execute(f"DELETE FROM {table} WHERE video_id=?", (vid,))
            _insert_rows(con, "sd_videos", [video])
            _insert_rows(con, "sd_slides", slides)
            _insert_rows(con, "sd_lines", lines)
        except BaseException:
            con.execute("ROLLBACK TO slide_video")
            raise
        finally:
            con.execute("RELEASE slide_video")
        totals["videos"] += 1
        totals["slides"] += len(slides)
        totals["lines"] += len(lines)
        totals["missing_frames"] += sum(not row["frame_ok"] for row in slides)
    return totals


def _stats(con):
    totals = {name: con.execute(f"SELECT count(*) FROM sd_{name}").fetchone()[0]
              for name in ("videos", "slides", "lines")}
    cross, colors = {}, {}
    for size, color, count in con.execute(
        "SELECT size_class, color, count(*) FROM sd_lines GROUP BY size_class, color"
    ):
        color = color or "NULL"
        cross.setdefault(size, {})[color] = count
        colors[color] = colors.get(color, 0) + count
    titles = dict(con.execute("SELECT coalesce(title_color, 'NULL'), count(*) FROM sd_slides "
                              "GROUP BY title_color"))
    return dict(totals, line_colors=colors, size_class_by_color=cross, title_colors=titles)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("load")
    ingest.add_argument("--db", type=Path, default=DB_PATH)
    ingest.add_argument("--src", type=Path, default=SRC_DIR)
    ingest.add_argument("--frames", type=Path, default=FRAMES_DIR)
    ingest.add_argument("--only", nargs="+")
    commands.add_parser("stats").add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    os.nice(19)
    if args.command == "load":
        with closing(connect(args.db)) as con:
            result = load(con, args.src, args.frames, args.only)
    else:
        uri = args.db.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as con, con:
            con.execute("BEGIN")
            result = _stats(con)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
