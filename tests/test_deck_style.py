"""style: syuka 덱 규칙(장수 · 장당 초 · 장 모양) · 새 장 종류(full_picture · image_stack) · outline · 견본집 · 원본 집계 시험.
네트워크와 원본 자료 없이 돈다. 예시 문장과 이름은 전부 지어낸 것이다(원본 방송의 문구를 쓰지 않는다)."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from ozl.render import build as B  # noqa: E402
from ozl.render import norms as NM  # noqa: E402
from ozl.render import pictures as PIC  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.render import style as ST  # noqa: E402
from ozl.render.__main__ import main as render_main  # noqa: E402

TEMPLATE = V.TEMPLATE


@pytest.fixture
def png(tmp_path):
    from PIL import Image
    p = tmp_path / "pic.png"
    Image.new("RGB", (1600, 900), (200, 210, 230)).save(p)
    return p


def entry(png, pid="p1"):
    return {"id": pid, "path": str(png), "kind": "직접 그린 도표", "source_url": "시험이 그린 도형", "origin": "직접 그림",
            "rights_holder": "가상 작업실", "license": "직접 제작", "commercial_ok": True, "modify_ok": True, "attribution": "가상 작업실 그림",
            "reverse_search": {"did": "직접 그린 도형", "result": "해당 없음"}, "synthetic_check": "직접 그림", "content_check": "인물 없음, 로고 없음",
            "checked_at": "2099-01-02T10:00:00+09:00", "as_is": True, "map": False, "sha256": PIC.file_sha256(png)}


def run(sp, draft=False):
    return S.check(sp, {}, TEMPLATE, draft=draft, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems)


def syuka(slides=(), **top):
    sp = V.spec_of(list(slides))
    sp["style"] = "syuka"
    sp.update(top)
    return sp


# ── 옛 규칙은 그대로 ─────────────────────────────────────────────────────

def test_old_rule_spec_unchanged():
    """style 칸이 없는 사양: 새 검사를 받지 않고, seconds 가 없으면 예전처럼 경고 한 줄뿐이다."""
    sp = V.spec_of([])
    r = run(sp)
    assert r.ok and r.warnings == []
    sp2 = copy.deepcopy(sp)
    del sp2["slides"][3]["seconds"]
    for s in sp2["slides"]:
        s["seconds"] = 90   # 옛 규칙에는 장 체류 상한이 없다
    del sp2["slides"][3]["seconds"]
    r = run(sp2)
    assert r.ok
    assert r.warnings == ["4쪽: 예상 발화 시간(seconds)이 없다"]


def test_unknown_style_fails():
    sp = V.spec_of([])
    sp["style"] = "other"
    assert any("style 'other' 를 모른다" in e for e in run(sp).errors)


# ── 새 규칙의 실패 ──────────────────────────────────────────────────────

def test_syuka_baseline_passes_without_warnings():
    """장수 · 장당 초 · 장 모양 검사는 경고 0. 시험 사양은 image_text 로 열고 물음형 제목이 없어 여는 장 경고 두 줄만 남는다(P4)."""
    r = run(syuka())
    assert r.ok, r.errors
    assert len(r.warnings) == 2 and r.warnings[0].startswith("1쪽: 첫 장이 image_text 다") and "첫 5장" in r.warnings[1], r.warnings


def test_syuka_seconds_required():
    sp = syuka()
    del sp["slides"][2]["seconds"]
    r = run(sp)
    assert any("3쪽: seconds" in e and "장마다" in e for e in r.errors)
    assert not any("예상 발화 시간" in w for w in r.warnings)


def test_syuka_average_seconds_range():
    sp = syuka()
    for s in sp["slides"]:
        s["seconds"] = 10
    assert any("장당 평균 10.0초" in e for e in run(sp).errors)
    for s in sp["slides"]:
        s["seconds"] = 40
    assert any("장당 평균 40.0초" in e for e in run(sp).errors)
    for s in sp["slides"]:
        s["seconds"] = 25
    assert not any("장당 평균" in e for e in run(sp).errors)


def test_syuka_dwell_cap():
    sp = syuka()
    sp["slides"][1]["seconds"] = ST.DWELL_MAX + 1
    errs = run(sp).errors
    assert any(e.startswith("2쪽:") and "95% 분위" in e for e in errs)
    sp["slides"][1]["seconds"] = ST.DWELL_MAX
    assert not any("95% 분위 57초" in e for e in run(sp).errors)


def test_syuka_body_line_cap(monkeypatch):
    monkeypatch.setattr(ST, "BODY_LINES_MAX", 2)
    sp = syuka()
    sp["slides"][1]["body"] = ["첫째 줄은 짧다", "둘째 줄도 짧다", "셋째 줄까지 쓴다"]
    errs = run(sp).errors
    assert any(e.startswith("2쪽: 본문 3줄") for e in errs)


def test_syuka_bad_seconds_value():
    sp = syuka()
    sp["slides"][0]["seconds"] = "많이"
    assert any("1쪽: seconds '많이' 는 양수" in e for e in run(sp).errors)


# ── 새 규칙의 경고 ──────────────────────────────────────────────────────

def test_syuka_speech_amount_warning():
    sp = syuka()
    sp["slides"][1]["spoken"] = "감자는 땅속에서 자란다 " * 20   # 공백 빼고 200자 > 20초 × 5자 × 1.3
    assert any(w.startswith("2쪽: 말로 할 문장") for w in run(sp).warnings)
    sp["slides"][1]["spoken"] = "감자는 땅속에서 자란다"
    assert not any("말로 할 문장" in w for w in run(sp).warnings)


def test_syuka_text_only_and_table_warnings():
    sp = syuka()
    for s in sp["slides"][2:6]:
        s.pop("image", None)   # 그림 자리가 빈 image_text 는 '글만'으로 센다
    ws = run(sp).warnings
    assert any(w.startswith("글만 있는 장 5장") for w in ws)
    sp = syuka([{"stage": "비교", "kind": "compare_table", "title": "두 섬의 감자", "seconds": 20,
                 "table": {"header": ["", "북섬", "남섬"], "rows": [["맛", "달다", "고소하다"]]}}])
    ws = run(sp).warnings
    assert any(w.startswith("compare_table 1장") for w in ws)


def test_syuka_layout_distribution_warning(png):
    sl = {"stage": "전개", "kind": "image_stack", "title": "감자 줄기", "body": ["줄기가 먼저 자란다"], "picture": "p1", "seconds": 20}
    sp = syuka([dict(sl) for _ in range(6)], pictures=[entry(png)])
    ws = run(sp).warnings
    assert any("'그림 위아래 + 글'" in w for w in ws)
    assert ST.layout_of({"kind": "image_text", "body": ["x"]}) == "text_only"
    assert ST.layout_of({"kind": "image_text", "body": ["x"], "picture": "p1"}) == "image_left"
    assert ST.layout_of({"kind": "full_picture", "picture": "p1"}) == "media"


def test_no_45_slide_cap():
    sp = syuka()
    sp["slides"] = sp["slides"][:2] + [copy.deepcopy(sp["slides"][3]) for _ in range(60)] + sp["slides"][2:]
    r = run(sp)
    assert r.ok, r.errors[:3]


# ── 새 종류 ──────────────────────────────────────────────────────────────

def full_pic(**kw):
    base = {"stage": "전개", "kind": "full_picture", "picture": "p1", "seconds": 15}
    base.update(kw)
    return base


def stack(**kw):
    base = {"stage": "전개", "kind": "image_stack", "title": "감자꽃이 피는 때", "picture": "p1", "body": ["꽃이 지면 알이 굵어진다"], "seconds": 20}
    base.update(kw)
    return base


def test_full_picture_accepts_and_fits(png):
    r = run(V.spec_of([full_pic(caption="감자밭 위로 해가 뜬다")]) | {"pictures": [entry(png)]})
    assert r.ok, r.errors
    pl = B.plan_slide(full_pic(caption="감자밭 위로 해가 뜬다"))
    assert len(pl.imgs) == 1 and [b.name for b in pl.boxes] == ["한마디"]
    im, cap = pl.imgs[0], pl.boxes[0]
    assert im.top + im.height + B.PIC_CREDIT_H <= B.SH + 1e-6        # 그림 밑 표기 두 줄이 쪽 안에 든다
    assert im.top <= cap.top and cap.top + cap.height <= im.top + im.height   # 한마디는 그림 자리 안 아래


def test_full_picture_rules(png):
    pics = {"pictures": [entry(png)]}
    errs = run(V.spec_of([full_pic(title="감자")]) | pics).errors
    assert any("full_picture 에는 제목" in e for e in errs)
    errs = run(V.spec_of([full_pic(body=["감자"])]) | pics).errors
    assert any("full_picture 에는 본문" in e for e in errs)
    sl = full_pic()
    del sl["picture"]
    errs = run(V.spec_of([sl])).errors
    assert any("그림 자리에" in e for e in errs)
    grey = full_pic(image={"what": "감자밭", "source": "가상 농업청"})
    del grey["picture"]
    assert any("회색 자리" in e for e in run(V.spec_of([grey])).errors)
    assert run(V.spec_of([grey]), draft=True).ok
    errs = run(V.spec_of([full_pic(caption="감자밭 위로 해가 뜨고 바람이 불고 새가 날고 구름이 흘러가고 비가 오다가 그친다")]) | pics).errors
    assert any("한마디" in e and "줄 넘침" in e for e in errs)


def test_image_stack_accepts_and_fits(png):
    sl = stack(body=["꽃이 지면 알이 굵어진다", "잎이 누렇게 변한다", {"text": "그때 캔다", "red": True}])
    r = run(V.spec_of([sl]) | {"pictures": [entry(png)]})
    assert r.ok, r.errors
    pl = B.plan_slide(sl)
    im, body = pl.imgs[0], [b for b in pl.boxes if b.name == "본문"][0]
    assert im.top + im.height + B.PIC_CREDIT_H <= body.top + 1e-6    # 그림 밑 표기와 본문이 겹치지 않는다
    assert body.capacity() == 3 and body.top + body.height <= B.BODY_BOTTOM + 1e-6


def test_image_stack_rules(png):
    pics = {"pictures": [entry(png)]}
    errs = run(V.spec_of([stack(body=["하나", "둘", "셋", "넷"])]) | pics).errors
    assert any("image_stack 의 본문은 1~3줄" in e for e in errs)
    long = "감자는 땅속에서 천천히 자라며 줄기와 잎이 햇빛을 받아 양분을 만들어 덩이줄기로 보낸다"
    errs = run(V.spec_of([stack(body=[long, long])]) | pics).errors
    assert any("줄 넘침" in e for e in errs)
    sl = stack()
    del sl["title"]
    assert any("image_stack 에는 'title'" in e for e in run(V.spec_of([sl]) | pics).errors)


def test_new_kinds_build_pptx(png, tmp_path, monkeypatch):
    from pptx import Presentation
    sp = syuka([full_pic(caption="해가 뜬다"), stack()], pictures=[entry(png)])
    out = tmp_path / "d.pptx"
    info = B.build_pptx(sp, {}, {}, out)
    prs = Presentation(str(out))
    names = [[sh.name for sh in s.shapes] for s in prs.slides]
    assert "그림 파일" in names[2] and "한마디" in names[2] and "제목" not in names[2]
    assert "그림 파일" in names[3] and "본문" in names[3] and "제목" in names[3]
    assert info["main"] == len(sp["slides"])
    info2 = B.build_pptx(sp, {}, {}, tmp_path / "e.pptx", appendix=False)
    assert info2["appendix"] == [] and info2["total"] == info2["main"]


# ── outline ─────────────────────────────────────────────────────────────

def test_outline_counts():
    o = ST.outline(30)
    assert o["target"] == 72
    assert sum(n for _, _, n, _ in o["rows"]) == 72
    rows = {k: n for k, _, n, _ in o["rows"]}
    assert rows["media"] >= 1 and rows["image_left"] > rows["image_stack"] > rows["text_only"]
    assert o["table_max"] == 3
    o = ST.outline(1)
    assert o["target"] == 2 and sum(n for _, _, n, _ in o["rows"]) == 2 and dict((k, n) for k, _, n, _ in o["rows"])["media"] == 1
    assert ST.outline(0.1)["target"] == 1


def test_outline_cli(capsys):
    assert render_main(["outline", "--minutes", "20"]) == 0
    out = capsys.readouterr().out
    assert "목표 장수 48장" in out and "full_picture" in out
    assert render_main(["outline", "--minutes", "x"]) == 2
    assert render_main(["outline"]) == 2


# ── 견본집 ──────────────────────────────────────────────────────────────

def test_sample_spec_covers_every_kind_without_numbers(tmp_path):
    sp = ST.sample_spec(tmp_path / "그림")
    # capture_full 은 받아들여진 기록의 원문 사본이 있어야 그릴 수 있어 견본집(기록 인용 없음)에서 뺀다
    assert {s["kind"] for s in sp["slides"]} == set(S.KINDS) - {"capture_full"}
    assert ST.sample_problems(sp) == []
    assert sp["card_id"] == ST.SAMPLE_CARD and not any(s.get("claim_ids") for s in sp["slides"])


def test_samples_builds_without_appendix(tmp_path):
    from pptx import Presentation
    info = ST.samples(tmp_path, export=False, link=None)
    prs = Presentation(info["pptx"])
    assert len(prs.slides) == info["slides"] == len(ST.sample_spec(tmp_path / "x")["slides"])
    note = prs.slides[0].notes_slide.notes_text_frame.text
    assert "full_picture" in note and "제목 없는 화면" in note
    assert list(pathlib.Path(info["dir"]).glob("견본_사양_*.yaml"))


# ── 원본 집계 ────────────────────────────────────────────────────────────

def test_title_ending_classes():
    assert NM.title_ending("감자 값이 오른 까닭?") == "물음"
    assert NM.title_ending("드디어 감자철!") == "느낌"
    assert NM.title_ending("감자 값이 올랐다") == "~다"
    assert NM.title_ending("감자 값이 올랐어요") == "말투 어미"
    assert NM.title_ending("올해의 감자 값") == "명사 등"
    assert NM.title_len("감자 값 이야기") == 6


def test_collect_counts_without_text(tmp_path):
    d = tmp_path / "dense"
    d.mkdir()
    slides = [{"kind": "media", "flash": True, "dwell_sec": 3, "title": None},
              {"kind": "media", "flash": False, "dwell_sec": 12, "title": None, "layout": "media"},
              {"kind": "slide", "flash": False, "dwell_sec": 30, "title": "가상의 감자 값", "body_text_lines": 4, "layout": "image_left"},
              {"kind": "slide", "flash": False, "dwell_sec": 18, "title": "감자 값은 왜?", "body_text_lines": 2, "layout": "text_only"}]
    (d / "vidA.json").write_text(json.dumps({"video_id": "vidA", "duration_sec": 60, "slides": slides}, ensure_ascii=False), encoding="utf-8")
    r = NM.collect(use_frames=False, dense=d)
    assert r["videos"] == 1 and r["slides"] == 3
    assert r["sec_per_slide"]["median"] == 20.0 and r["sec_per_slide_with_flash"]["median"] == 15.0
    assert r["layout"]["image_left"]["n"] == 1 and r["opening"]["first_media"] == 1
    assert r["title_ending"]["물음"]["n"] == 1
    md = NM.to_md(r)
    assert "가상의 감자 값" not in md and "가상의 감자 값" not in json.dumps(r, ensure_ascii=False)


def test_style_constants_match_a_norms_file():
    """style.py 의 상수가 가리키는 집계 파일이 있으면 그 값과 같아야 한다(다시 셌으면 상수도 옮긴다)."""
    p = ST.ROOT / ST.NORMS_FILE
    if not p.is_file():
        pytest.skip("원본 집계 파일이 없는 환경")
    r = json.loads(p.read_text(encoding="utf-8"))
    assert r["videos"] == ST.NORMS_VIDEOS
    assert r["sec_per_slide"]["median"] == ST.SEC_PER_SLIDE_MEDIAN
    assert (r["sec_per_slide"]["min"], r["sec_per_slide"]["max"]) == ST.SEC_PER_SLIDE_RANGE
    assert r["dwell_sec"]["p95"] == ST.DWELL_MAX and r["body_lines"]["p95"] == ST.BODY_LINES_MAX
    assert {k: round(v["share"], 3) for k, v in r["layout"].items()} == ST.LAYOUT_SHARE


# ── 제목 말투와 여는 장(경고) ──────────────────────────────────────────────
# 예시 제목은 전부 지어낸 것이다. 끝맺음 갈래는 원본 집계와 같은 함수(norms.title_ending)로 나눈다.

def opener(**kw):
    return {"kind": "full_picture", "stage": "여는 장", "picture": "p1", "seconds": 12, **kw}


def titled(title, kind="image_text"):
    return {"kind": kind, "stage": "전개", "title": title, "body": ["감자는 땅속에서 자란다"], "seconds": 25}


def tw(slides):
    return ST.title_warnings(slides)


def good_deck(n=8):
    """경고가 하나도 나지 않는 짜임: 그림으로 열고, 셋째 장에 물음형 제목, 나머지는 명사형 제목."""
    return [opener(), opener(caption="감자밭에 비가 내린다"), titled("감자는 왜 땅속에서 자랄까?")] + [titled(f"감자밭의 하루 {chr(65 + k)}") for k in range(n - 3)]


def test_title_warnings_none_for_good_deck():
    assert tw(good_deck()) == []
    assert tw(good_deck(25)) == []


def test_title_too_long_warns_only_above_q3():
    t_ok = "가" * ST.TITLE_LEN_MAX              # 사분위 상단과 같은 길이는 통과
    t_long = "가 " * (ST.TITLE_LEN_MAX + 1)      # 공백은 세지 않는다 — 공백 제외 26자
    d = good_deck()
    d[4] = titled(t_ok)
    assert tw(d) == []
    d[4] = titled(t_long.strip())
    w = tw(d)
    assert len(w) == 1 and w[0].startswith("5쪽: 제목 26자") and f"{ST.TITLE_LEN_MAX}자보다 길다" in w[0], w


def test_report_style_da_ending_warns_above_twice_source_share():
    assert abs(ST.TITLE_DA_MAX - 0.264) < 1e-9
    d = good_deck(10)                           # 제목 있는 장 8장
    d[3], d[4] = titled("감자값이 올랐다"), titled("밭이 넓어졌다")      # 2/8 = 25% — 경고선 26.4% 아래
    assert tw(d) == []
    d[5] = titled("비가 그쳤다")                 # 3/8 = 37.5%
    w = tw(d)
    assert len(w) == 1 and "'~다'로 끝나는 제목 3장" in w[0] and "4, 5, 6쪽" in w[0], w


def test_da_share_not_judged_on_few_titles():
    d = [opener(), titled("감자는 어디서 왔을까?"), titled("감자값이 올랐다"), titled("밭이 넓어졌다")]   # 제목 3장 — 비율을 보지 않는다
    assert tw(d) == []


def test_no_question_title_warns_from_twenty_slides():
    d = [opener(caption="감자밭에 비가 내린다?")] + [titled(f"감자밭의 하루 {k}") for k in range(19)]   # 20장, 물음은 caption 에만
    w = tw(d)
    assert any("본편 20장에 물음형 제목이 없다" in x for x in w), w
    assert not any("첫 5장" in x for x in w), w   # 첫 다섯 장 물음은 caption 으로도 선다
    assert not any("본편" in x for x in tw(d[:19]))   # 19장이면 보지 않는다


def test_first_slide_not_full_picture_warns():
    d = good_deck()
    d[0] = {"kind": "title_hook", "stage": "여는 장", "title": "감자는 어디서 왔을까?", "seconds": 15}
    w = tw(d)
    assert len(w) == 1 and w[0].startswith("1쪽: 첫 장이 title_hook 다") and "full_picture 로 연다" in w[0], w


def test_no_question_in_first_five_warns():
    d = good_deck()
    d[2] = titled("감자의 고향")
    w = tw(d)
    assert len(w) == 1 and "첫 5장" in w[0] and "나1" in w[0], w
    d[4] = titled("감자의 고향은 어디일까")      # 물음표 없는 물음은 물음으로 세지 않는다(원본 집계와 같은 갈래 — 말투 어미)
    assert len(tw(d)) == 1
    d[4] = titled("감자의 고향은 어디일까?")     # 다섯째 장의 물음은 통과
    assert tw(d) == []
    d[4], d[5] = titled("감자의 고향"), titled("감자의 고향은 어디일까?")   # 여섯째 장은 늦다
    assert any("첫 5장" in x for x in tw(d))


def test_title_warnings_reach_check_only_for_syuka(png):
    """spec.check 를 거쳐도 경고만 붙고(실패 아님), 옛 사양에는 붙지 않는다."""
    old = V.spec_of([])                         # 첫 장 image_text, 물음 없음
    r = run(old)
    assert not any("첫 장이" in w or "물음형" in w for w in r.warnings), r.warnings
    sp = syuka()
    r = run(sp)
    assert any(w.startswith("1쪽: 첫 장이 image_text 다") for w in r.warnings), r.warnings
    assert any("첫 5장" in w for w in r.warnings), r.warnings
    assert not any("첫 장이" in e or "물음형" in e for e in r.errors), r.errors


def test_samples_show_opening_question_and_caption_slots(tmp_path):
    sp = ST.sample_spec(tmp_path / "그림")
    sl = sp["slides"]
    assert [s["kind"] for s in sl[:2]] == ["full_picture", "full_picture"]
    assert any(ST._asks(s) for s in sl[:5])
    assert sum(1 for s in sl if NM.title_ending(s.get("title") or "") == "물음") >= 2   # 여는 쪽과 본편에 하나씩
    assert any(s.get("stage") == "여담" and s.get("caption") for s in sl)
    assert ST.title_warnings(sl) == []
    assert ST.sample_problems(sp) == []
    assert "유머 자리" in ST._note_extra(next(s for s in sl if s.get("stage") == "여담"))


# ── 그림 자리의 읽힘과 채움 기준, 견본집의 그림 ─────────────────────────────────

def test_placement_constants_are_the_documented_values():
    """기준값은 style.py 한 곳에 둔다(가정한 본문 글자 크기, 읽힘 하한, 자리 채움 하한) — pictures.placement_warnings 가 읽는다."""
    assert (ST.SCREEN_WEB_BODY_PX, ST.SCREEN_DOC_BODY_PT, ST.SCREEN_MIN_PT, ST.PICTURE_FILL_MIN) == (14, 10, 7.0, 0.5)


def test_sample_pictures_fill_their_slots(tmp_path):
    """견본집의 그림은 들어갈 자리의 가로세로 비에 맞춰 그린다 — 자리 넓이의 절반을 못 채우는 그림 자리(빈칸)가 없다."""
    sp = ST.sample_spec(tmp_path / "그림")
    pics, _ = PIC.ledger(sp)
    assert len(sp["slides"]) == 15                                           # 종류별 13장 + 광고 구간 두 장
    seen = 0
    for i, sl in enumerate(sp["slides"], 1):
        for im in B.plan_slide(sl).imgs:
            assert im.kind == "picture", (i, im.kind)                         # 회색 자리도 [그림 대기]도 없다
            w, h = PIC.placed_size(pics[im.ref], im.width, im.height)
            assert (w * h) / (im.width * im.height) >= ST.PICTURE_FILL_MIN, (i, im.ref, w, h)
            assert PIC.placement_warnings(pics[im.ref], im.width, im.height) == []
            seen += 1
    assert seen >= 11
