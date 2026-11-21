"""지어낸 라이브와 클립으로 0행 보존과 정상 결과의 파일 교체를 확인한다."""
import csv
import json

import pytest

from ozl.analyze import catalog, live_align


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    meta = tmp_path / "meta"
    meta.mkdir()
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    mapping = meta / "live_clip_map_syukaworld.csv"
    aligned = meta / "align.csv"
    report = tmp_path / "report.md"
    monkeypatch.setattr(catalog, "META", meta)
    monkeypatch.setattr(catalog, "EXPORT_IDX", tmp_path / "index.csv")
    monkeypatch.setattr(live_align, "MAP", mapping)
    monkeypatch.setattr(live_align, "EXP", transcripts)
    monkeypatch.setattr(live_align, "OUT_CSV", aligned)
    monkeypatch.setattr(live_align, "OUT_MD", report)
    for path in (mapping, aligned, report):
        path.write_bytes(b"previous\n")
    return mapping, aligned, report


def write_videos(rows):
    path = catalog.META / "syukaworld_videos.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_livemap_zero_preserves_previous(outputs, capsys):
    mapping, _, _ = outputs
    write_videos([])
    assert catalog.main(["livemap"]) == 1
    assert "0행" in capsys.readouterr().err
    assert mapping.read_bytes() == b"previous\n"


def test_alignment_zero_preserves_both_files(outputs, capsys):
    mapping, aligned, report = outputs
    mapping.write_text("live_published_kst,live_id\n2026-05-17 20:00,vidTEST0001\n", encoding="utf-8")
    assert live_align.main() == 1
    assert "정렬 결과 0행 — 기존 파일을 그대로 둔다" in capsys.readouterr().err
    assert aligned.read_bytes() == report.read_bytes() == b"previous\n"


@pytest.mark.parametrize("clip_text,coverage", [
    ("달빛나라 사람들이 반짝돌로 풍차를 만드는 이야기", 1.0),
    ("무지개마을 도서관에서는 매주 새로운 그림책을 읽습니다", 0.0),
])
def test_livemap_then_alignment_replaces_files(outputs, clip_text, coverage):
    mapping, aligned, report = outputs
    previous = {p: p.stat().st_ino for p in outputs}
    write_videos([
        {"video_id": "vidTEST0001", "title": "달빛나라 방송", "kind": "live", "duration_sec": 7200,
         "published_at": "2026-05-17T11:00:00Z"},
        {"video_id": "vidTEST0002", "title": "달빛나라 소식", "kind": "video", "duration_sec": 900,
         "published_at": "2026-05-18T11:00:00Z"},
    ])
    assert catalog.main(["livemap"]) == 0
    with mapping.open(encoding="utf-8") as stream:
        mapped, = csv.DictReader(stream)
    assert (mapped["live_id"], mapped["clip_id"]) == ("vidTEST0001", "vidTEST0002")

    for vid, text in [(mapped["live_id"], "달빛나라 사람들이 반짝돌로 풍차를 만드는 이야기"),
                      (mapped["clip_id"], clip_text)]:
        (live_align.EXP / f"{vid}.json").write_text(json.dumps({"text": text}), encoding="utf-8")
    assert live_align.main() == 0
    with aligned.open(encoding="utf-8") as stream:
        row, = csv.DictReader(stream)
    assert float(row["coverage"]) == coverage
    assert "클립 1편" in report.read_text(encoding="utf-8")
    assert all(p.stat().st_ino != previous[p] for p in outputs)
