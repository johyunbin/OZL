"""원본 비교표(ozl.render.compare) — 지어낸 원본 분석 파일과 지어낸 사양으로만 잰다(실제 원본 문구 없음)."""
from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from ozl.render import compare as CMP


def _video(vid: str, dur: int, layouts: list[str], titles: list[str | None], dwell: int = 20, flash_first: bool = False) -> dict:
    slides = []
    if flash_first:
        slides.append({"no": 0, "dwell_sec": 3, "kind": "media", "layout": "media", "flash": True, "title": None})
    for i, (lay, t) in enumerate(zip(layouts, titles), 1):
        slides.append({"no": i, "dwell_sec": dwell, "kind": "media" if lay == "media" else "titled", "layout": lay, "title": t})
    return {"video_id": vid, "duration_sec": dur, "slides": slides}


def _write(d: pathlib.Path, v: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{v['video_id']}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")


def _stored(vid, s):
    return CMP._stored_layout(vid, s)


SPEC = {
    "card_id": "시험-01", "style": "syuka",
    "slides": [
        {"kind": "full_picture", "picture": "p1", "seconds": 10},
        {"kind": "image_text", "title": "골목 빵집은 왜 일찍 열까?", "image": {"what": "빵집 그림"}, "seconds": 30},
        {"kind": "image_text", "title": "새벽 반죽", "seconds": 20},   # 그림 자리가 비면 글만
        {"kind": "closing", "title": "오늘의 정리다", "body": ["줄은 시간에서 생긴다"], "seconds": 20},
    ],
}


def test_deck_metrics_counts_layouts_titles_and_seconds():
    m = CMP.deck_metrics(SPEC)
    assert m["slides"] == 4 and m["duration_sec"] == 80
    assert m["per_30min"] == pytest.approx(4 * 1800 / 80, abs=0.1)
    assert m["sec_median"] == 20 and m["sec_mean"] == 20
    assert m["layout"]["media"] == 0.25 and m["layout"]["image_left"] == 0.25 and m["layout"]["text_only"] == 0.5
    assert m["picture_share"] == 0.5
    assert m["titled"] == 3   # full_picture 는 제목이 없다
    assert m["ending"]["물음"] == pytest.approx(1 / 3, abs=1e-3) and m["ending"]["~다"] == pytest.approx(1 / 3, abs=1e-3)
    assert m["first3"] == ["media", "image_left", "text_only"]


def test_pick_video_closest_length_and_explicit(tmp_path):
    lab = tmp_path / "label"
    _write(lab, _video("aaa", 1800, ["media", "image_left"], [None, "가"]))
    _write(lab, _video("bbb", 900, ["media", "text_only"], [None, "나"]))
    _write(lab, _video("ccc", 0, ["media"], [None]))   # 길이 없는 편은 고르지 않는다
    assert CMP.pick_video(800, lab)["video_id"] == "bbb"
    assert CMP.pick_video(1500, lab)["video_id"] == "aaa"
    assert CMP.pick_video(800, lab, "aaa")["video_id"] == "aaa"
    with pytest.raises(SystemExit):
        CMP.pick_video(800, lab, "없는편")


def test_video_metrics_drops_flash_and_uses_dwell(tmp_path):
    v = _video("ddd", 600, ["media", "image_left", "image_stack", "text_only"], [None, "하나 둘?", "셋", "넷이다"], dwell=30, flash_first=True)
    m = CMP.video_metrics(v)
    assert m["slides"] == 4 and m["sec_median"] == 30
    assert m["per_30min"] == 12.0
    assert m["picture_share"] == 0.75
    assert m["first3"] == ["media", "image_left", "image_stack"]
    assert m["titled"] == 3 and m["ending"]["물음"] == pytest.approx(1 / 3, abs=1e-3)


def test_corpus_median_and_first3_mode(tmp_path):
    dense = tmp_path / "dense"
    _write(dense, _video("e1", 1800, ["media", "image_left", "image_left", "text_only"], [None, "가", "나", "다"], dwell=20))
    _write(dense, _video("e2", 1800, ["media", "image_left", "image_left"], [None, "라", "마"], dwell=30))
    _write(dense, _video("e3", 1200, ["media", "image_stack", "image_left"], [None, "바", "사"], dwell=40))
    c = CMP.corpus_median(dense, _stored)
    assert c["videos"] == 3 and c["slides"] == 3 and c["sec_median"] == 30
    assert c["first3"] == ["media", "image_left", "image_left"] and c["first3_videos"] == 2
    assert set(c["layout"]) == set(CMP.LAYOUTS)


def test_table_rows_fill_every_cell(tmp_path):
    lab, dense = tmp_path / "label", tmp_path / "dense"
    _write(lab, _video("f1", 100, ["media", "image_left", "text_only"], [None, "물음일까?", "명사"]))
    _write(dense, _video("f2", 1800, ["media", "image_left", "image_left"], [None, "가", "나"]))
    deck = CMP.deck_metrics(SPEC)
    one = CMP.video_metrics(CMP.pick_video(deck["duration_sec"], lab))
    rows = CMP.table_rows(deck, one, CMP.corpus_median(dense, _stored))
    names = [r[0] for r in rows]
    for want in ("장수", "30분 환산 장수", "장당 초 중앙값", "그림 든 장 비율('글만'이 아닌 장)", "제목 글자 수 중앙값(공백 제외)", "첫 세 장의 꼴"):
        assert want in names
    assert sum(n.startswith("장 모양: ") for n in names) == 7
    assert sum(n.startswith("제목 끝맺음: ") for n in names) == 5
    assert all(len(r) == 4 and all(str(c).strip() for c in r) for r in rows)


def test_md_has_no_original_titles(tmp_path):
    """원본 쪽은 수와 갈래만 — 원본 제목 글이 표에 옮겨지지 않는다."""
    lab, dense = tmp_path / "label", tmp_path / "dense"
    secret = "지어낸원본제목문구"
    _write(lab, _video("g1", 100, ["media", "image_left"], [None, secret]))
    _write(dense, _video("g2", 1800, ["media", "image_left"], [None, secret]))
    deck = CMP.deck_metrics(SPEC)
    md = CMP.to_md(pathlib.Path("s.yaml"), "시험-01", deck, CMP.video_metrics(CMP.pick_video(80, lab)), CMP.corpus_median(dense, _stored), "2099-01-01T00:00:00+09:00")
    assert secret not in md
    assert "| 잣대 | 원본 한 편 | 원본 전체 중앙값 | 우리 덱 |" in md


def test_resolve_spec_file_or_single_yaml_folder(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(SPEC, allow_unicode=True), encoding="utf-8")
    assert CMP.resolve_spec(p) == p
    assert CMP.resolve_spec(tmp_path) == p
    (tmp_path / "t.yaml").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        CMP.resolve_spec(tmp_path)


def test_main_writes_md_and_json(tmp_path, monkeypatch):
    lab, dense, out = tmp_path / "label", tmp_path / "dense", tmp_path / "out"
    _write(lab, _video("h1", 100, ["media", "image_left"], [None, "가"]))
    _write(dense, _video("h2", 1800, ["media", "image_left"], [None, "나"]))
    monkeypatch.setattr(CMP, "LABEL", lab)
    monkeypatch.setattr(CMP, "DENSE", dense)
    monkeypatch.setattr(CMP, "frame_layout", _stored)
    monkeypatch.setattr(CMP.compare, "__defaults__", (None, lab, dense))
    monkeypatch.setattr(CMP.corpus_median, "__defaults__", (dense, _stored))
    sp = tmp_path / "s.yaml"
    sp.write_text(yaml.safe_dump(SPEC, allow_unicode=True), encoding="utf-8")
    assert CMP.main([str(sp), "--out", str(out), "--no-pdf"]) == 0
    mds = list(out.glob("원본_비교표_시험-01_*.md"))
    assert len(mds) == 1 and mds[0].with_suffix(".json").is_file()
    assert CMP.main([]) == 2


# ── 모양을 모르는 장(대표 프레임도 저장된 layout 도 없다) ─────────────────────
def _bare(no: int, **kw) -> dict:
    return {"no": no, "dwell_sec": 20, "kind": "titled", "title": "지어낸 제목", **kw}


def test_slides_without_frame_or_stored_layout_are_not_counted_as_text_only(tmp_path, monkeypatch):
    """대표 프레임도 저장된 layout 도 없는 장은 모양을 모른다. '글만'으로 세지 않고 따로 세며 비율의 분모에서 뺀다.
    실제 프레임 결측 길(frame_layout)을 그대로 탄다 — 프레임 폴더가 비어 있다."""
    monkeypatch.setattr(CMP.NM, "FRAMES", tmp_path / "frames")
    only = {"video_id": "u1", "duration_sec": 300, "slides": [_bare(1), _bare(2, best_frame="없는 프레임.png"), _bare(3)]}
    m = CMP.video_metrics(only, CMP.frame_layout)
    assert m["slides"] == 3 and (m["layout_known"], m["layout_unknown"]) == (0, 3)
    assert m["layout"]["text_only"] is None and m["picture_share"] is None      # '글만 100% · 그림 0%' 가 아니다
    assert m["first3"] == [CMP.UNKNOWN] * 3
    mixed = {"video_id": "u2", "duration_sec": 600, "slides": [
        _bare(1), _bare(2, best_frame="없는 프레임.png"), _bare(3, layout="image_left"), _bare(4, layout="text_only"),
        {"no": 5, "dwell_sec": 20, "kind": "media", "title": None}]}
    m = CMP.video_metrics(mixed, CMP.frame_layout)
    assert m["slides"] == 5 and (m["layout_known"], m["layout_unknown"]) == (3, 2)
    assert m["layout"]["text_only"] == pytest.approx(1 / 3, abs=1e-3) and m["layout"]["image_left"] == pytest.approx(1 / 3, abs=1e-3)
    assert m["picture_share"] == pytest.approx(2 / 3, abs=1e-3)                  # 분모는 모양을 아는 3장
    assert sum(m["layout"].values()) == pytest.approx(1.0, abs=1e-3)
    assert CMP.video_metrics(mixed)["layout_unknown"] == 2                       # 라벨 편(저장된 칸만 읽는 길)도 같다


def test_unknown_slides_show_in_table_and_leave_the_median(tmp_path, monkeypatch):
    monkeypatch.setattr(CMP.NM, "FRAMES", tmp_path / "frames")
    lab, dense = tmp_path / "label", tmp_path / "dense"
    _write(lab, {"video_id": "k1", "duration_sec": 100, "slides": [_bare(1), _bare(2, layout="image_left")]})
    _write(dense, {"video_id": "k2", "duration_sec": 1800, "slides": [_bare(1), _bare(2), _bare(3)]})              # 모양을 아는 장이 없다
    _write(dense, {"video_id": "k3", "duration_sec": 1800, "slides": [_bare(1, layout="image_left"), _bare(2), _bare(3, layout="text_only")]})
    c = CMP.corpus_median(dense)                                                # 기본 길: frame_layout
    assert c["videos"] == 2 and c["layout_unknown"] == 4 and c["layout_videos"] == 1
    assert c["layout"]["image_left"] == 0.5 and c["layout"]["text_only"] == 0.5 and c["picture_share"] == 0.5   # 모양을 아는 편(k3)만으로 잰 중앙값
    deck = CMP.deck_metrics(SPEC)
    assert deck["layout_unknown"] == 0 and deck["picture_share"] == 0.5
    one = CMP.video_metrics(CMP.pick_video(deck["duration_sec"], lab))
    rows = {r[0]: r for r in CMP.table_rows(deck, one, c)}
    assert rows["모양을 모르는 장(비율의 분모에서 뺌)"][1:] == ("1장", "4장(2편 가운데 모양을 아는 장이 있는 편 1편)", "0장")
    assert rows["장 모양: 좌 그림 + 우 글"][1] == "100.0%" and rows["그림 든 장 비율('글만'이 아닌 장)"][1] == "100.0%"
    assert all(len(r) == 4 and all(str(x).strip() for x in r) for r in rows.values())
    none = tmp_path / "dense0"
    _write(none, {"video_id": "k4", "duration_sec": 1800, "slides": [_bare(1), _bare(2)]})
    c0 = CMP.corpus_median(none)
    assert c0["layout_videos"] == 0 and c0["picture_share"] is None
    r0 = {r[0]: r for r in CMP.table_rows(deck, one, c0)}
    assert r0["장 모양: 글만"][2] == "모름" and r0["그림 든 장 비율('글만'이 아닌 장)"][2] == "모름"
    md = CMP.to_md(pathlib.Path("s.yaml"), "시험-01", deck, one, c, "2099-01-01T00:00:00+09:00")
    assert "모양을 모르는 장" in md and "분모에서 뺐다" in md


def test_layout_outside_the_list_is_unknown_not_a_picture_slide():
    """허용 목록(LAYOUTS) 밖의 layout 값은 모양을 모르는 장이다 — 그림이 있는 장으로 세지 않는다(재확인 지적 4)."""
    only = {"video_id": "n1", "duration_sec": 100, "slides": [_bare(1, layout="not_measured")]}
    m = CMP.video_metrics(only)
    assert (m["layout_known"], m["layout_unknown"]) == (0, 1)
    assert m["picture_share"] is None and m["layout"]["text_only"] is None and m["first3"] == [CMP.UNKNOWN]
    mixed = {"video_id": "n2", "duration_sec": 400, "slides": [
        _bare(1, layout="not_measured"), _bare(2, layout="image_left"), _bare(3, layout="text_only"), _bare(4, layout=7), _bare(5, layout=["image_left"])]}
    m = CMP.video_metrics(mixed)
    assert m["slides"] == 5 and (m["layout_known"], m["layout_unknown"]) == (2, 3)
    assert m["picture_share"] == 0.5 and sum(m["layout"].values()) == pytest.approx(1.0, abs=1e-3)
    assert m["first3"] == [CMP.UNKNOWN, "image_left", "text_only"]
    rows = [{"layout": "지어낸 모양", "sec": 10, "title": "지어낸 제목"}, {"layout": "image_full", "sec": 10, "title": ""}]
    m = CMP._metrics(rows, 20)                                             # 덱 쪽도 같은 함수로 잰다
    assert (m["layout_known"], m["layout_unknown"]) == (1, 1) and m["picture_share"] == 1.0
