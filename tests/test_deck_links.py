"""style: syuka 덱의 링크 번호와 링크 목록(spec.number_sources · spec.link_plan · build 의 links 파일) 시험.
쪽 아래 출처 줄과 부록 쪽을 떼고, 화면 수치 뒤 작은 위첨자 번호와 덱 밖 링크 목록으로 출처를 잇는다. 옛 규칙(style 칸 없음)은 그대로다.
네트워크 없이 돈다. 예시 문장과 숫자는 전부 지어낸 것이다."""
from __future__ import annotations

import copy
import csv
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import test_deck_visuals as V  # noqa: E402
from test_deck_visuals import desk  # noqa: E402,F401  (pytest fixture)
from ozl.render import build as B  # noqa: E402
from ozl.render import numbers as N  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.research import cards as C  # noqa: E402
from ozl.research import capture as K  # noqa: E402

CARD, CID, OLD = V.CARD, V.CID, V.OLD
TWIN = f"{CARD}-c3"     # OLD 와 같은 표기(7.5)를 가진 다른 기록
NINE = f"{CARD}-c4"     # 환산해 적은 표기(9천)를 글자 그대로 가진 다른 기록


def twin_claim():
    return {"claim_id": TWIN, "card_id": CARD, "text": "가상의 섬 무 값도 1월 7.5였고 2월 8.75였다.", "observed": "radish 7.5 → 8.75",
            "human_verified": True, "status": "verified",
            "source": {"url": "https://example.org/radish.html", "publisher": "가상 섬 원예청", "tier": "T1"},
            "checks": {"base_period": "2098-01", "primary_doc_locator": "둘째 문단"}}


def nine_claim():
    return {"claim_id": NINE, "card_id": CARD, "text": "가상의 섬 배추 값은 1월 9천이었다.", "observed": "cabbage 9천",
            "human_verified": True, "status": "verified",
            "source": {"url": "https://example.org/cabbage.html", "publisher": "가상 섬 채소청", "tier": "T1"},
            "checks": {"base_period": "2098-01", "primary_doc_locator": "첫 문단"}}


def text_slide(**kw):
    base = {"stage": "근거 수치", "kind": "image_text", "title": "당근 값", "body": ["1월에는 7.5였다", "12월에는 9.25다"], "claim_ids": [OLD], "seconds": 20}
    base.update(kw)
    return base


def syuka(slides):
    sp = V.spec_of(slides)
    sp["style"] = "syuka"
    return sp


def claims_all(desk_dir):
    return {CID: V.machine_claim(desk_dir, image=False), OLD: V.old_claim(), TWIN: twin_claim()}


def fabricated_spec(desk_dir) -> tuple[dict, dict]:
    """지어낸 style: syuka 사양 — 글 수치(위첨자), 차트, 원문 캡처, 표(귀퉁이 번호), 숫자 없이 인용한 보도."""
    cl = claims_all(desk_dir)
    slides = [
        text_slide(),
        V.slide(chart=V.line_chart(), title="감자 값 흐름", body=["12월 감자 값은 18,250이다"]),
        {"stage": "근거 수치", "kind": "capture_full", "title": "통계청 원문", "capture": CID, "claim_ids": [CID], "seconds": 20},
        {"stage": "근거 수치", "kind": "compare_table", "title": "두 채소 값", "table": {"header": ["채소", "1월"], "rows": [["당근", "7.5"], ["무", "8.75"]]},
         "claim_ids": [OLD, TWIN], "number_claims": [{"shown": "7.5", "claim_id": OLD}], "seconds": 20, "refs": ["가상 일보"]},
        text_slide(title="다시 당근", body=["당근 값은 9.25다"]),
    ]
    sp = syuka(slides)
    return sp, cl


def card_doc():
    return {"card_id": CARD, "sources": [{"name": "가상 일보", "tier": "T3", "url": "https://news.example.org/a/1"}], "risks": ["지어낸 위험 문장"]}


# ── 수치 자리 ─────────────────────────────────────────────────────────────
def test_source_spans_map_back_to_original_text():
    t = "약  4억\t1,000만 달러와 70 만 배럴"
    got = [(x.canon, t[x.start:x.end]) for x in N.source_spans(t)]
    assert got == [("4억1000만", "4억\t1,000만"), ("70만", "70 만")]
    assert [x.canon for x in N.source_spans(t)] == [x.canon for x in N.scan(t)]   # 판독 결과는 scan 그대로


@pytest.mark.parametrize("text,token,want", [
    ("값은 7.5였다", "7.5", "7.5였다"),           # 어절 끝
    ("값은 5조 원이 넘는다", "5조", "5조 원이"),     # 띄어 쓴 단위 낱말까지
    ("값은 12%로, 늘었다", "12%", "12%로"),        # 끝 문장부호 앞
    ("값은 7.5 정도다", "7.5", "7.5"),             # 단위가 아닌 다음 어절은 넘지 않는다
])
def test_mark_position(text, token, want):
    end = text.index(token) + len(token)
    at = S._mark_at(text, end)
    assert text[text.index(token):at + 1] == want


# ── 번호 매기기 ───────────────────────────────────────────────────────────
def test_same_notation_in_two_records_is_ambiguous_until_designated(desk):
    """같은 표기(7.5)가 그 쪽이 인용한 두 기록에 다 있으면 어느 기록에 이을지 코드가 정하지 않는다 — claim_ids 의 앞 기록으로 잇지 않고 실패로 알린다."""
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[TWIN, OLD], body=["1월에는 7.5였다", "12월에는 9.25다"])
    src = S.number_sources(sl, cl)
    by = {shown: got for _, _, shown, got in src["inline"]}
    assert by == {"9.25": [OLD]}                        # 정하지 못한 수치에는 번호를 붙이지 않는다(잘못 잇지 않는다)
    assert len(src["errors"]) == 1
    e = src["errors"][0]
    assert "'7.5'" in e and "body[0]" in e and TWIN in e and OLD in e and "정할 수 없다" in e and "number_claims" in e
    lp = S.link_plan(syuka([sl]), cl)
    assert lp.numbers == {OLD: 1} and lp.errors == [f"3쪽: {e}"]
    new = S.check(syuka([sl]), cl, V.TEMPLATE, layout_fn=B.layout_problems)
    assert f"3쪽: {e}" in new.errors
    old = S.check(V.spec_of([sl]), cl, V.TEMPLATE, layout_fn=B.layout_problems)   # 옛 규칙에는 링크 번호가 없다 — 그대로
    assert not any("number_claims" in x for x in old.errors), old.errors
    with pytest.raises(SystemExit, match="링크 번호를 정할 수 없다"):
        B.build_pptx(syuka([sl]), cl, card_doc(), desk / "o" / "d.pptx")


def test_designated_record_gets_number_and_others_listed(desk):
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[OLD, TWIN], body=["1월에는 7.5였다", "12월에는 9.25다"], number_claims=[{"shown": "7.5", "claim_id": TWIN}])
    src = S.number_sources(sl, cl)
    by = {shown: got for _, _, shown, got in src["inline"]}
    assert src["errors"] == [] and by["7.5"] == [TWIN, OLD] and by["9.25"] == [OLD]   # 지정한 기록이 앞 — claim_ids 순서가 아니다
    lp = S.link_plan(syuka([sl]), cl)
    assert lp.errors == [] and lp.numbers == {TWIN: 1, OLD: 2}
    assert lp.also[1] == [OLD]                          # 같은 표기가 있는 다른 기록을 목록에 함께 적는다


def test_each_position_follows_its_own_record(desk):
    """두 기록에 같은 수(7.5)가 있고 화면에도 두 번 나온다 — 자리마다 지정한 기록으로 이어진다(둘 다 앞 기록으로 가지 않는다)."""
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[OLD, TWIN], body=["당근은 1월에 7.5였다", "무도 1월에 7.5였다"],
                    number_claims=[{"shown": "7.5", "at": "body[0]", "claim_id": OLD}, {"shown": "7.5", "at": "body[1]", "claim_id": TWIN}])
    src = S.number_sources(sl, cl)
    assert src["errors"] == []
    assert [(key, got[0]) for key, _, _, got in src["inline"]] == [(("body", 0), OLD), (("body", 1), TWIN)]
    lp = S.link_plan(syuka([sl]), cl)
    assert lp.numbers == {OLD: 1, TWIN: 2}
    marks = lp.slides[2]["inline"]
    assert list(marks[("body", 0)].values()) == ["1"] and list(marks[("body", 1)].values()) == ["2"]
    assert S.check(syuka([sl]), cl, V.TEMPLATE, layout_fn=B.layout_problems).errors == []
    # 한 칸 안에서 두 번 나오면 nth(그 칸에서 몇 번째 그 표기인가)로 가른다
    one = text_slide(claim_ids=[OLD, TWIN], body=["당근은 7.5였고 무도 7.5였다"],
                     number_claims=[{"shown": "7.5", "at": "body[0]", "nth": 1, "claim_id": OLD}, {"shown": "7.5", "at": "body[0]", "nth": 2, "claim_id": TWIN}])
    got = S.number_sources(one, cl)
    assert got["errors"] == [] and [g[0] for _, _, _, g in got["inline"]] == [OLD, TWIN]
    assert sorted(S.link_plan(syuka([one]), cl).slides[2]["inline"][("body", 0)].values()) == ["1", "2"]
    # 칸만 적고 nth 를 빼면 그 칸의 두 자리가 같은 기록으로 간다(지정이 그렇다)
    both = text_slide(claim_ids=[OLD, TWIN], body=["당근은 7.5였고 무도 7.5였다"], number_claims=[{"shown": "7.5", "at": "body[0]", "claim_id": TWIN}])
    assert [g[0] for _, _, _, g in S.number_sources(both, cl)["inline"]] == [TWIN, TWIN]


def test_conversion_claim_wins_over_same_notation_in_another_record(desk):
    """환산(conversions)이 기록 B 를 지정했는데 같은 표기가 기록 A 에 글자 그대로 있다 — 지정한 B 로 이어진다(claim_ids 의 앞 기록 A 가 아니다)."""
    cl = {**claims_all(desk), NINE: nine_claim()}
    sl = text_slide(claim_ids=[NINE, OLD], body=["당근 값은 9천 원대다"], conversions=[{"shown": "9천", "source": "9.25", "claim_id": OLD, "basis": "지어낸 환산"}])
    src = S.number_sources(sl, cl)
    assert src["errors"] == [] and [(shown, ids) for _, _, shown, ids in src["inline"]] == [("9천", [OLD, NINE])]
    assert S.link_plan(syuka([sl]), cl).numbers == {OLD: 1}
    # 같은 표기를 두 환산이 서로 다른 기록으로 지정하면 정할 수 없다 — number_claims 로 자리를 가른다
    two = text_slide(claim_ids=[NINE, OLD], body=["당근 값은 9천 원대다"],
                     conversions=[{"shown": "9천", "source": "9.25", "claim_id": OLD, "basis": "지어낸 환산"},
                                  {"shown": "9천", "source": "9천", "claim_id": NINE, "basis": "지어낸 환산"}])
    got = S.number_sources(two, cl)
    assert got["inline"] == [] and len(got["errors"]) == 1 and "conversions" in got["errors"][0] and "정할 수 없다" in got["errors"][0]
    two["number_claims"] = [{"shown": "9천", "claim_id": NINE}]
    got = S.number_sources(two, cl)
    assert got["errors"] == [] and got["inline"][0][3] == [NINE, OLD]


def test_table_and_grey_slot_follow_designation(desk):
    cl = claims_all(desk)
    tbl = {"stage": "근거 수치", "kind": "compare_table", "title": "두 채소 값", "table": {"header": ["채소", "1월"], "rows": [["당근", "7.5"], ["무", "7.5"]]},
           "claim_ids": [OLD, TWIN], "seconds": 20}
    src = S.number_sources(tbl, cl)
    assert src["corner"] == [] and len(src["errors"]) == 2 and all("table" in e and "정할 수 없다" in e for e in src["errors"])
    assert "nth: 1" in src["errors"][0] and "nth: 2" in src["errors"][1]            # 같은 칸에 두 번 나온 표기는 몇 번째인지까지 알려 준다
    tbl["number_claims"] = [{"shown": "7.5", "at": "table", "nth": 1, "claim_id": OLD}, {"shown": "7.5", "at": "table", "nth": 2, "claim_id": TWIN}]
    src = S.number_sources(tbl, cl)
    assert src["errors"] == [] and src["corner"] == [("table", "표", [OLD, TWIN])]
    grey = text_slide(claim_ids=[OLD, TWIN], body=["값이 올랐다"], image={"what": "당근 값 7.5 그림", "source": "가상 섬 농업청"})
    src = S.number_sources(grey, cl)
    assert src["corner"] == [] and len(src["errors"]) == 1 and "image" in src["errors"][0]
    grey["number_claims"] = [{"shown": "7.5", "at": "image", "claim_id": TWIN}]
    assert S.number_sources(grey, cl)["corner"] == [(-1, "그림 자리", [TWIN])]


@pytest.mark.parametrize("entries,frag", [
    ("7.5 는 c2", "목록이어야 한다"),
    ([{"shown": "7.5"}], "shown · claim_id 둘 다 있어야 한다"),
    ([{"shown": "7.5", "claim_id": f"{CARD}-c9"}], "claim_ids 에 없다"),
    ([{"shown": "당근", "claim_id": OLD}], "수치 표기 하나여야 한다"),
    ([{"shown": "7.5", "claim_id": OLD, "at": "body[7]"}], "칸 'body[7]' 가 이 쪽에 없다"),
    ([{"shown": "7.5", "claim_id": OLD, "nth": 1}], "nth 는 at 과 함께 쓴다"),
    ([{"shown": "7.5", "claim_id": OLD, "at": "body[0]", "nth": 0}], "nth 는 1 이상의 정수여야 한다"),
    ([{"shown": "7.5", "claim_id": OLD, "at": "body[0]", "nth": 3}], "칸 body[0] 에 3번째 '7.5' 표기가 없다"),
    ([{"shown": "8.75", "claim_id": TWIN}], "화면에 '8.75' 표기가 없다"),
    ([{"shown": "9.25", "claim_id": TWIN}], "'9.25' 표기가 없다"),                        # TWIN 의 기록에는 9.25 가 없다
    ([{"shown": "7.5", "claim_id": OLD}, {"shown": "7.5", "claim_id": TWIN}], "지정이 겹친다"),
])
def test_number_claims_shape_errors(desk, entries, frag):
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[OLD, TWIN], body=["1월에는 7.5였다", "12월에는 9.25다"], number_claims=entries)
    errs = S.number_sources(sl, cl)["errors"]
    assert any(frag in e and "number_claims" in e for e in errs), errs
    rep = S.check(syuka([sl]), cl, V.TEMPLATE, layout_fn=B.layout_problems)
    assert any(frag in e and e.startswith("3쪽: ") for e in rep.errors), rep.errors


def test_link_plan_numbers_in_order_once_per_claim(desk):
    sp, cl = fabricated_spec(desk)
    lp = S.link_plan(sp, cl)
    # 3쪽(spec_of 앞 두 장 뒤): OLD 가 1. 4쪽 차트·본문: CID 가 2. 표는 OLD·TWIN — TWIN 이 3. 7쪽 OLD 는 다시 1
    assert lp.numbers == {OLD: 1, CID: 2, TWIN: 3}
    pages = {n: list(dict.fromkeys(pg for pg, _ in u)) for n, u in lp.uses.items()}
    assert pages[1] == ["3", "6", "7"] and pages[2] == ["4", "5"] and pages[3] == ["6"]
    assert lp.slides[2]["inline"][("body", 0)] and lp.slides[3]["corner"] == {-1: "2"} and lp.slides[5]["corner"] == {"table": "1,3"}
    assert lp.unnumbered == {}


def test_claim_without_screen_number_is_listed_apart(desk):
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[OLD, TWIN], body=["당근 값은 9.25다"])   # TWIN 은 화면 수치를 받치지 않는다
    lp = S.link_plan(syuka([sl]), cl)
    assert lp.numbers == {OLD: 1} and lp.unnumbered == {TWIN: [3]}
    assert B.link_cell(sl, lp) == "[1] 기록 c3"


def test_conversion_shown_value_points_to_its_claim(desk):
    cl = claims_all(desk)
    sl = text_slide(body=["당근 값은 9천 원대다"], conversions=[{"shown": "9천", "source": "9.25", "claim_id": OLD, "basis": "지어낸 환산"}])
    got = S.number_sources(sl, cl)["inline"]
    assert [(shown, ids) for _, _, shown, ids in got] == [("9천", [OLD])]


# ── 배치(위첨자 폭) ───────────────────────────────────────────────────────
def _title_fits(title, links=None):
    sl = text_slide(title=title)
    if links is not None:
        sl = S.with_links(sl, links)
    return B.layout_problems(sl)


def test_superscript_width_counts_in_overflow():
    """제목 한 줄에 겨우 들어가는 글은 번호 위첨자를 붙이면 넘친다 — 넘침 검사가 번호 폭까지 본다."""
    base = "당근 값은 7.5였다"
    k = 1
    while not _title_fits("가" * k + " " + base):   # 처음으로 넘치는 길이를 찾는다
        k += 1
        assert k < 200
    t = "가" * (k - 1) + " " + base   # 번호 없이 한 줄에 들어가는 가장 긴 글
    assert _title_fits(t) == []
    at = S._mark_at(t, t.index("7.5") + 3)
    assert _title_fits(t, {"inline": {("title",): {at: "12"}}, "corner": {}}), "번호 폭을 넣으면 넘쳐야 한다"


def test_body_wrap_uses_superscript_width():
    p0 = B.Para("가나다라 " * 6 + "값은 7.5였다")
    p1 = B.Para(p0.text, marks={S._mark_at(p0.text, p0.text.index("7.5") + 3): "3"})
    m0, f0 = B.para_mask(p0)
    m1, f1 = B.para_mask(p1)
    w0 = sum(f0(p0.text[i], 26, m0[i]) for i in range(len(p0.text)))
    w1 = sum(f1(p1.text[i], 26, m1[i]) for i in range(len(p1.text)))
    assert w1 - w0 == pytest.approx(S.measure("3", B.sup_size(26)))
    assert m0 == [False] * len(p0.text)          # 번호가 없으면 종전 마스크 그대로


# ── 검사 ─────────────────────────────────────────────────────────────────
def test_record_without_url_fails_only_in_syuka(desk):
    cl = claims_all(desk)
    cl[OLD] = copy.deepcopy(cl[OLD])
    cl[OLD]["source"]["url"] = ""
    sl = text_slide()
    old = S.check(V.spec_of([sl]), cl, V.TEMPLATE, layout_fn=B.layout_problems)
    assert not any("원본 링크" in e for e in old.errors), old.errors
    new = S.check(syuka([sl]), cl, V.TEMPLATE, layout_fn=B.layout_problems)
    assert any("원본 링크(source.url)가 없다" in e for e in new.errors), new.errors


def test_fabricated_spec_passes_strict_check(desk):
    sp, cl = fabricated_spec(desk)
    rep = S.check(sp, cl, V.TEMPLATE, card_doc(), B.layout_problems, appendix_fn=B.appendix_problems)
    assert rep.ok, rep.errors


def test_link_pair_errors_both_ways():
    assert B.link_pair_errors({1, 2}, {1, 2}) == []
    e = B.link_pair_errors({1, 2, 4}, {1, 2, 3})
    assert any("[4]" in x and "목록에 없다" in x for x in e) and any("[3]" in x and "화면 어느 쪽에도 없다" in x for x in e)


# ── 빌드 ─────────────────────────────────────────────────────────────────
def _all_text(pptx):
    from pptx import Presentation
    out = []
    for sld in Presentation(str(pptx)).slides:
        for sh in sld.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if sh.has_table:
                out += [c.text for r in sh.table.rows for c in r.cells]
    return "\n".join(out)


def test_build_pptx_syuka_marks_no_footnote_no_appendix(desk, tmp_path):
    from pptx import Presentation
    sp, cl = fabricated_spec(desk)
    out = tmp_path / "o" / "d.pptx"
    info = B.build_pptx(sp, cl, card_doc(), out)
    assert info["appendix"] == [] and info["total"] == len(sp["slides"]) and info["links"] == 3
    prs = Presentation(str(out))
    names = {sh.name for s in prs.slides for sh in s.shapes}
    assert "출처 각주" not in names and "원문 캡처 출처" not in names
    assert "출처:" not in _all_text(out)
    assert B.screen_link_numbers(out) == {1, 2, 3}
    # 위첨자 조각: 작은 회색, baseline 이 있다
    sups = [r for s in prs.slides for sh in s.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs for r in p.runs
            if r._r.find(B.qn("a:rPr")) is not None and r._r.find(B.qn("a:rPr")).get("baseline")]
    assert sups and all(r.font.size.pt == B.sup_size(26) for r in sups if r.text in ("1", "2"))
    assert K.PASSAGE_NOTE == "원문의 글을 옮겨 그린 것 · 화면 모양은 원문과 다름"   # 빌드 동안만 비우고 되돌린다


def test_old_style_keeps_footnote_and_appendix(desk, tmp_path):
    sp, cl = fabricated_spec(desk)
    del sp["style"]
    out = tmp_path / "o" / "old.pptx"
    info = B.build_pptx(sp, cl, card_doc(), out)
    assert info["appendix"] and "links" not in info
    txt = _all_text(out)
    assert "출처: 가상 섬 농업청" in txt and "원문: stats.example.org" in txt
    assert B.screen_link_numbers(out) == set()


def test_capture_passage_has_no_note_in_syuka(desk, tmp_path):
    """원문을 옮겨 그린 그림 맨 아래 꼬리표는 새 규칙에서 찍지 않는다 — 그림 아래쪽 띠가 옛 규칙보다 비어 있다."""
    from PIL import Image
    sp, cl = fabricated_spec(desk)
    vs = B.render_visuals(sp, cl, tmp_path / "new")
    old = copy.deepcopy(sp)
    del old["style"]
    vo = B.render_visuals(old, cl, tmp_path / "old")
    new_png, old_png = vs[(5, -1)][0], vo[(5, -1)][0]
    assert vs[(5, -1)][1] == "" and vo[(5, -1)][1].startswith("원문: ")

    def ink_rows(p):
        with Image.open(p) as g:
            im = g.convert("L")
        W, H = im.size
        px = im.load()
        return [y for y in range(H) if any(px[x, y] < 245 for x in range(0, W, 2))]
    assert len(ink_rows(new_png)) < len(ink_rows(old_png))


def test_full_build_writes_links_and_pairs(desk, tmp_path, monkeypatch):
    sp, cl = fabricated_spec(desk)
    C.save_yaml(C.claim_path(OLD), cl[OLD])
    C.save_yaml(C.claim_path(TWIN), cl[TWIN])
    C.save_yaml(C.card_path(CARD), card_doc())
    monkeypatch.setattr(B, "DRAFTS", tmp_path / "drafts")
    B.DRAFTS.mkdir()
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(sp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    info = B.build(p, export=False)
    rows = list(csv.DictReader(pathlib.Path(info["links_csv"]).read_text(encoding="utf-8-sig").splitlines()))
    assert [r["번호"] for r in rows] == ["1", "2", "3"]
    assert {int(r["번호"]) for r in rows} == B.screen_link_numbers(pathlib.Path(info["pptx"]))
    r1 = rows[0]
    assert r1["기록 번호"] == OLD and r1["원본 링크"] == "https://example.org/carrot.pdf" and r1["등급"] == C.GRADE_HUMAN
    assert r1["쪽"] == "3, 6, 7" and r1["문서 위치"] == "표 2" and r1["기준 시점"] == "2098년"
    assert rows[1]["받은 시각"] and rows[2]["같은 표기가 있는 다른 기록"] == ""
    assert "사양이 지정한 기록" in pathlib.Path(info["links"]).read_text(encoding="utf-8")   # 목록 머리말이 지금 규칙을 적는다
    md = pathlib.Path(info["links"]).read_text(encoding="utf-8")
    assert "## 숫자 없이 인용한 보도" in md and "가상 일보" in md and "## 그림 출처" in md
    sheet = pathlib.Path(info["md"]).read_text(encoding="utf-8")
    assert "근거(링크 번호)" in sheet and "| [1] |" in sheet and "| [1] [3] |" in sheet


def test_build_stops_when_pairing_breaks(desk, tmp_path, monkeypatch):
    sp, cl = fabricated_spec(desk)
    for c in (OLD, TWIN):
        C.save_yaml(C.claim_path(c), cl[c])
    C.save_yaml(C.card_path(CARD), card_doc())
    monkeypatch.setattr(B, "DRAFTS", tmp_path / "drafts")
    B.DRAFTS.mkdir()
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(sp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(B, "screen_link_numbers", lambda pptx: {1, 2})
    with pytest.raises(SystemExit, match="양쪽 대응 실패"):
        B.build(p, export=False)


def test_build_refuses_an_ambiguous_spec(desk, tmp_path, monkeypatch):
    """build 명령 길: 검사가 먼저 실패하므로 폴더가 생기지 않는다."""
    cl = claims_all(desk)
    for c in (OLD, TWIN):
        C.save_yaml(C.claim_path(c), cl[c])
    C.save_yaml(C.card_path(CARD), card_doc())
    monkeypatch.setattr(B, "DRAFTS", tmp_path / "drafts")
    B.DRAFTS.mkdir()
    p = tmp_path / "spec.yaml"
    sp = syuka([text_slide(claim_ids=[OLD, TWIN], body=["1월에는 7.5였다"])])
    p.write_text(yaml.safe_dump(sp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="받치는 기록이 둘 이상이다"):
        B.build(p, export=False)
    assert list(B.DRAFTS.iterdir()) == []


def test_bundle_shows_number_claims_to_the_reviewer(desk):
    """검토 묶음의 쪽 줄에 사양이 자리마다 지정한 기록이 찍힌다 — 지정이 맞는지는 문장 대조가 본다."""
    from ozl.render import bundle as BU
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[OLD, TWIN], body=["당근은 7.5였고 무도 7.5였다"],
                    number_claims=[{"shown": "7.5", "at": "body[0]", "nth": 1, "claim_id": OLD}, {"shown": "7.5", "at": "body[0]", "nth": 2, "claim_id": TWIN}])
    lines = BU.slide_block(3, sl, cl, card_doc(), {})
    assert "수치의 기록 지정: 7.5(body[0] 1번째) → c2 / 7.5(body[0] 2번째) → c3" in lines
    assert not any(x.startswith("수치의 기록 지정") for x in BU.slide_block(3, text_slide(), cl, card_doc(), {}))


def test_claim_cited_twice_is_one_candidate(desk):
    """claim_ids 에 같은 기록이 두 번 적혀도 받치는 기록은 하나다 — '받치는 기록이 둘 이상'으로 실패하지 않는다(재확인 지적 5)."""
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[OLD, OLD])
    src = S.number_sources(sl, cl)
    assert src["errors"] == [], src["errors"]
    assert {shown: got for _, _, shown, got in src["inline"]} == {"7.5": [OLD], "9.25": [OLD]}
    lp = S.link_plan(syuka([sl]), cl)
    assert lp.errors == [] and lp.numbers == {OLD: 1}
    twice = text_slide(claim_ids=[OLD, TWIN, OLD], body=["1월에는 7.5였다", "12월에는 9.25다"])   # 서로 다른 두 기록이면 여전히 정하지 못한다
    errs = S.number_sources(twice, cl)["errors"]
    assert len(errs) == 1 and f"({OLD}, {TWIN})" in errs[0]
    conv = text_slide(claim_ids=[OLD], body=["1월에는 7.5였다", "어림 9천이다"],
                      conversions=[{"shown": "9천", "claim_id": OLD}, {"shown": "9천", "claim_id": OLD}])   # 환산을 두 번 적어도 같다
    assert not any("둘 이상" in e or "서로 다른 기록" in e for e in S.number_sources(conv, cl)["errors"])


# ── 링크 번호를 붙이지 않는 표기(분모 꼴 · 차례 꼴)와 되풀이 ─────────────────────
BREAD = f"{CARD}-c5"    # 지어낸 빵집 기록 — 분모 꼴과 차례 꼴이 든 문장
OVEN = f"{CARD}-c6"     # BREAD 와 같은 표기(1 · 2)를 가진 다른 지어낸 기록


def bread_claim():
    return {"claim_id": BREAD, "card_id": CARD, "human_verified": True, "status": "verified",
            "text": "가상의 빵집은 가게 1곳당 빵 3개를 굽고 손님 100명당 매출이 12% 는다. 제2 공장은 3번째 가게 옆에 있고 동네 1위다.",
            "observed": "가게 1곳당 빵 3개 · 손님 100명당 매출 12% · 제2 공장 · 3번째 가게 · 1위",
            "source": {"url": "https://example.org/bread.html", "publisher": "가상 빵집 조합", "tier": "T1"},
            "checks": {"base_period": "2098", "primary_doc_locator": "첫 문단"}}


def oven_claim():
    return {"claim_id": OVEN, "card_id": CARD, "human_verified": True, "status": "verified",
            "text": "가상의 화덕 가게는 직원 1인당 화덕이 하나이고 2차 조사에서도 같았다.", "observed": "직원 1인당 화덕 하나 · 2차 조사",
            "source": {"url": "https://example.org/oven.html", "publisher": "가상 화덕 조합", "tier": "T1"},
            "checks": {"base_period": "2098", "primary_doc_locator": "둘째 문단"}}


@pytest.mark.parametrize("text,want", [
    # 붙는 것 — 잰 값
    ("빵 3개", {"3": ""}), ("매출 12%", {"12%": ""}), ("1위", {"1": ""}), ("3차례 올랐다", {"3": ""}), ("2차전지 공장", {"2": ""}),
    ("3개 당연히 팔렸다", {"3": ""}), ("2명 당선", {"2": ""}), ("3당 체제", {"3": ""}), ("문제 2개", {"2": ""}), ("10차선 도로", {"10": ""}),
    # 붙지 않는 것 — 분모 꼴(수 뒤에 단위와 '당')
    ("가게 1곳당", {"1": S.SKIP_PER}), ("손님 100명당", {"100": S.SKIP_PER}), ("주민 1인당의 몫", {"1": S.SKIP_PER}), ("5만 명당 가게", {"5만": S.SKIP_PER}),
    # 붙지 않는 것 — 차례 꼴
    ("제2 공장", {"2": S.SKIP_ORDINAL}), ("3번째 가게", {"3": S.SKIP_ORDINAL}), ("2차 조사", {"2": S.SKIP_ORDINAL}), ("2차는 다르다", {"2": S.SKIP_ORDINAL}),
    # 한 문장에 섞인 것 — 분모의 수만 건너뛴다
    ("가게 1곳당 빵 3개", {"1": S.SKIP_PER, "3": ""}), ("손님 100명당 매출 12%", {"100": S.SKIP_PER, "12%": ""}),
])
def test_link_skip_table(text, want):
    """지어낸 문장의 표 — 분모 꼴과 차례 꼴만 건너뛰고, 닮은 꼴('3차례', '2명 당선', '3당')은 번호를 붙인다."""
    got = {text[t.start:t.end]: S.link_skip(text, t.start, t.end) for t in N.source_spans(text) if t.needs_claim}
    assert got == want


def test_denominator_and_ordinal_get_no_number_but_still_need_a_record():
    cl = {BREAD: bread_claim()}
    sl = text_slide(title="가게 1곳당 빵 3개", claim_ids=[BREAD],
                    body=["손님 100명당 매출 12%", "제2 공장은 3번째 가게 옆", "동네 1위"])
    src = S.number_sources(sl, cl)
    assert src["errors"] == []
    assert [(S.field_name(k), shown) for k, _, shown, _ in src["inline"]] == [("title", "3"), ("body[0]", "12%"), ("body[2]", "1")]
    lp = S.link_plan(syuka([sl]), cl)
    assert lp.numbers == {BREAD: 1}
    assert [sh for _, sh in lp.uses[1]] == ["3", "12%", "1"]          # 링크 목록의 화면 표기에 분모의 수와 차례의 수가 없다
    marks = lp.slides[2]["inline"]
    assert set(marks) == {("title",), ("body", 0), ("body", 2)}        # '제2 공장은 3번째 가게 옆' 줄에는 번호가 없다
    title = sl["title"]
    assert list(marks[("title",)]) == [title.index("3개") + 1]          # '1곳당' 뒤가 아니라 '3개' 뒤
    # 숫자 대조는 그대로다: 분모의 수도 근거가 있어야 한다
    bare = text_slide(title="가게 9곳당 빵 3개", claim_ids=[BREAD], body=["동네 1위"])
    errs = S.number_errors(bare, cl)
    assert any("'9'" in e and "observed·text 에 없다" in e for e in errs), errs
    rep = S.check(syuka([sl]), cl, V.TEMPLATE, layout_fn=B.layout_problems)
    assert not [e for e in rep.errors if e.startswith("3쪽")], rep.errors


def test_skipped_position_is_not_ambiguous_and_goes_unnumbered():
    """분모의 수(1)와 차례의 수(2)가 두 기록에 다 있어도 '받치는 기록이 둘 이상'으로 실패하지 않는다 — 이을 번호가 없다.
    그 표기만 받치던 기록은 번호 없이 「화면 수치 없이 인용한 기록」으로 간다."""
    cl = {BREAD: bread_claim(), OVEN: oven_claim()}
    sl = text_slide(title="직원 1인당 화덕", claim_ids=[BREAD, OVEN], body=["2차 조사에서도 같았다", "빵은 3개"])
    src = S.number_sources(sl, cl)
    assert src["errors"] == [], src["errors"]
    assert [(shown, got) for _, _, shown, got in src["inline"]] == [("3", [BREAD])]
    lp = S.link_plan(syuka([sl]), cl)
    assert lp.errors == [] and lp.numbers == {BREAD: 1} and lp.unnumbered == {OVEN: [3]}
    # 같은 수가 잰 값으로 쓰이면(1위) 예전처럼 정하지 못한다고 알린다
    amb = text_slide(title="동네 1위", claim_ids=[BREAD, OVEN], body=["빵은 3개"])
    errs = S.number_sources(amb, cl)["errors"]
    assert len(errs) == 1 and "'1'" in errs[0] and "둘 이상" in errs[0]
    # 건너뛰는 자리를 가리킨 지정은 실패가 아니다(쓰인 것으로 친다)
    kept = text_slide(title="직원 1인당 화덕", claim_ids=[BREAD, OVEN], body=["빵은 3개"], number_claims=[{"shown": "1", "at": "title", "claim_id": OVEN}])
    assert S.number_sources(kept, cl)["errors"] == []


def test_repeated_notation_with_same_number_is_marked_once_per_slide():
    cl = {BREAD: bread_claim()}
    sl = {"stage": "근거 수치", "kind": "number", "title": "하루에 빵 3개", "number": {"value": "3개", "label": "가게마다 굽는 빵"},
          "body": ["빵 3개를 굽는다", "매출은 12% 는다", "다시 12%"], "claim_ids": [BREAD], "seconds": 20}
    nxt = text_slide(title="다음 장도 빵 3개", claim_ids=[BREAD], body=["매출 12%"])
    lp = S.link_plan(syuka([sl, nxt]), cl)
    marks = lp.slides[2]["inline"]
    assert set(marks) == {("title",), ("body", 1)}                     # 큰 숫자 칸과 본문의 되풀이에는 붙이지 않는다
    assert set(lp.slides[3]["inline"]) == {("title",), ("body", 0)}    # 다음 쪽에서는 다시 처음 자리에 붙는다
    assert lp.uses[1] == [("3", "3"), ("3", "12%"), ("4", "3"), ("4", "12%")]


def test_same_notation_with_different_numbers_keeps_both_marks(desk):
    """같은 표기라도 자리마다 다른 기록(다른 번호)으로 이어지면 둘 다 붙는다."""
    cl = claims_all(desk)
    sl = text_slide(claim_ids=[OLD, TWIN], body=["당근은 1월에 7.5였다", "무도 1월에 7.5였다"],
                    number_claims=[{"shown": "7.5", "at": "body[0]", "claim_id": OLD}, {"shown": "7.5", "at": "body[1]", "claim_id": TWIN}])
    lp = S.link_plan(syuka([sl]), cl)
    marks = lp.slides[2]["inline"]
    assert list(marks[("body", 0)].values()) == ["1"] and list(marks[("body", 1)].values()) == ["2"]


def test_built_deck_has_no_superscript_after_denominator(tmp_path):
    """만든 pptx 에서: '1곳당' 어절 뒤에는 위첨자 조각이 없고 '3개' 뒤에는 있다. 화면 번호 집합과 링크 목록(csv)의 번호 집합이 같다."""
    from pptx import Presentation
    cl = {BREAD: bread_claim()}
    sl = text_slide(title="가게 1곳당 빵 3개", claim_ids=[BREAD], body=["손님 100명당 매출 12%", "제2 공장은 3번째 가게 옆"])
    sp = syuka([sl])
    out = tmp_path / "o" / "d.pptx"
    B.build_pptx(sp, cl, card_doc(), out)
    lp = S.link_plan(sp, cl)
    listed = {int(r["번호"]) for r in csv.DictReader(B.links_csv(sp, cl, card_doc(), lp).splitlines())}
    assert B.screen_link_numbers(out) == listed == {1}
    runs = []   # (조각 글, 위첨자인가) — 3쪽
    for sh in Presentation(str(out)).slides[2].shapes:
        if sh.has_text_frame:
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    rpr = r._r.find(B.qn("a:rPr"))
                    runs.append((r.text, rpr is not None and rpr.get("baseline") not in (None, "0")))
    before_sup = [runs[k - 1][0] for k, (_, sup) in enumerate(runs) if sup]
    assert before_sup and all(not t.rstrip().endswith("당") for t in before_sup), before_sup
    assert any(t.endswith("3개") for t in before_sup) and any(t.endswith("12%") for t in before_sup)
    assert not any(sup for t, sup in runs if "번째" in t)
    row = next(csv.DictReader(B.links_csv(sp, cl, card_doc(), lp).splitlines()))
    assert row["화면 표기"] == "3 / 12%"
