import json

import pytest
from PIL import Image, ImageDraw

from ozl.analyze import slide_structure as structure


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    for name in ("DENSE", "LABEL", "REP"):
        folder = tmp_path / name
        folder.mkdir()
        monkeypatch.setattr(structure, name, folder)
    monkeypatch.setattr(structure, "OUT_MD", tmp_path / "summary.md")
    monkeypatch.setattr(structure, "reocr", lambda record: None)
    structure.OUT_MD.write_text("기존 집계\n", encoding="utf-8")

    frame = Image.new("RGB", (1152, 680), "white")
    ImageDraw.Draw(frame).rectangle((80, 140, 480, 540), fill="black")
    for vid in ("A", "B", "C"):
        frames = structure.REP / vid
        frames.mkdir()
        frame.save(frames / "left.png")
        slides = []
        for index in range(3):
            slide = {
                "flash": index == 1,
                "t_first": index * 5,
                "dwell_sec": 1 if index == 1 else 5,
                "kind": "media" if index == 1 else "slide",
                "best_frame": "left.png",
                "title": f"가상 풍차 {index}",
                "body": ["종이 날개", "나무 받침"],
                "body_boxes": [[620, 220, 160, 34], [620, 290, 160, 34]],
            }
            if index != 0:
                slide["white_ratio"] = 0.2
            if vid == "C" and not slide["flash"]:
                slide["layout"] = "text_only"
            slides.append(slide)
        record = {"video_id": vid, "duration_sec": 15, "slides": slides}
        (structure.DENSE / f"{vid}.json").write_text(json.dumps(record), encoding="utf-8")
        (structure.LABEL / f"{vid}.json").write_bytes(b"{}\n")
    return tmp_path


def snapshot(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_missing_dry_run(corpus, monkeypatch, capsys):
    monkeypatch.setattr(structure, "enrich", lambda _: pytest.fail("미리보기에서 enrich 호출"))
    before = snapshot(corpus)
    assert structure.main(["--missing", "--dry-run"]) == 0
    assert capsys.readouterr().out.splitlines() == ["A", "B", "합계: 2편"]
    assert snapshot(corpus) == before


def test_only_updates_selected_inputs(corpus, capsys):
    before = snapshot(corpus)
    assert structure.main(["--only", "A"]) == 0
    after = snapshot(corpus)
    dense = structure.DENSE / "A.json"
    label = structure.LABEL / "A.json"
    assert before.keys() == after.keys()
    assert {p for p in before if before[p] != after[p]} == {dense, label}
    assert [s["layout"] for s in json.loads(after[dense])["slides"]] == ["image_left", "media", "media"]
    assert [(s["no"], s["t_first"]) for s in json.loads(after[label])["slides"]] == [(1, 0), (2, 10)]
    assert capsys.readouterr().out.splitlines() == [
        "A: 3장, layout 추가 3장, media 전환 1장",
        "합계: 1편 3장, layout 추가 3장, media 전환 1장",
    ]


def test_missing_updates_both_and_skips_flash_only_gap(corpus, capsys):
    before = snapshot(corpus)
    assert structure.main(["--missing"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "A: 3장, layout 추가 3장, media 전환 1장",
        "B: 3장, layout 추가 3장, media 전환 1장",
        "합계: 2편 6장, layout 추가 6장, media 전환 2장",
    ]
    after = snapshot(corpus)
    expected = {folder / name for folder in (structure.DENSE, structure.LABEL) for name in ("A.json", "B.json")}
    assert before.keys() == after.keys()
    assert {p for p in before if before[p] != after[p]} == expected
    for path in expected:
        assert all(s["layout"] for s in json.loads(after[path])["slides"])
    assert structure.main(["--missing"]) == 0
    assert capsys.readouterr().out.splitlines() == ["합계: 0편 0장, layout 추가 0장, media 전환 0장"]


def test_unknown_id_continues_with_valid_id(corpus, capsys):
    assert structure.main(["--only", "absent", "B"]) == 1
    output = capsys.readouterr()
    assert output.err.splitlines() == ["absent: dense 파일 없음"]
    assert "B: 3장" in output.out
    assert json.loads((structure.DENSE / "B.json").read_bytes())["slides"][0]["layout"] == "image_left"


def test_only_and_missing_are_exclusive(corpus):
    before = snapshot(corpus)
    with pytest.raises(SystemExit) as exc:
        structure.main(["--only", "A", "--missing"])
    assert exc.value.code == 2
    assert snapshot(corpus) == before
