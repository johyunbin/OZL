"""광고 칸 검사(spec.sponsorship_errors) — 사양 맨 위 sponsorship{kind, sponsor, label, whole, materials} 와 장의 stage: 광고.
실패 조건, 광고 장을 뺀 단계 순서, 구간 장마다 오른쪽 위 띠(넘침 검사 포함), 러닝시트 머리와 링크 목록의 「광고주 제공 자료」 절, 견본집의 광고 장.
네트워크 없이 돈다. 광고주 이름, 표시 문구, 자료 이름, 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import copy
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from test_deck_kinds import entry  # noqa: E402
from test_deck_pictures_policy import _art  # noqa: E402
from ozl.render import build as B  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.render import style as ST  # noqa: E402

TEMPLATE, CARD = V.TEMPLATE, V.CARD
LABEL, SPONSOR = "유료 광고 포함", "가상상사"
AD = S.SPONSOR_STAGE


def sponsorship(**kw) -> dict:
    d = {"kind": "유료 광고", "sponsor": SPONSOR, "label": LABEL, "whole": False, "materials": ["가상상사 소개 자료(지어낸 자료)"]}
    d.update(kw)
    return d


def ad(first: bool = False, last: bool = False, **kw) -> dict:
    """광고 구간의 장. first · last 면 화면 글과 말로 할 문장에 표시 문구와 광고주 이름을 넣는다."""
    edge = first or last
    sl = {"stage": AD, "kind": "image_text", "seconds": 20,
          "title": f"{LABEL}: {SPONSOR}의 감자 이야기" if edge else "감자를 고르는 법",
          "body": ["감자는 단단한 것을 고른다"],
          "spoken": (f"여기부터 {LABEL} 구간입니다." if first else f"{LABEL} 구간은 여기까지입니다.") if edge else "감자는 단단한 것을 고릅니다."}
    sl.update(kw)
    return sl


def spec_with(ads: list[dict], at: int = 5, sp: dict | None = None, style: str | None = "syuka", **top) -> dict:
    """V.spec_of 의 본편 열 장(여는 장 … 닫는 장) 가운데 at 쪽 뒤에 광고 장들을 끼운 사양."""
    out = V.spec_of([])
    out["slides"] = out["slides"][:at] + ads + out["slides"][at:]
    if style:
        out["style"] = style
    if sp is not None:
        out[S.SPONSOR] = sp
    out.update(top)
    return out


def errs(sp: dict) -> list[str]:
    return S.check(sp, {}, TEMPLATE, layout_fn=B.layout_problems).errors


def good() -> dict:
    return spec_with([ad(first=True), ad(last=True)], sp=sponsorship())


# ── 통과하는 꼴과 단계 순서 ────────────────────────────────────────────────

def test_ad_block_passes_and_stage_order_ignores_it():
    sp = good()
    rep = S.check(sp, {}, TEMPLATE, layout_fn=B.layout_problems)
    assert rep.ok, rep.errors
    info = S.sponsor_info(sp)
    assert info["pages"] == [6, 7] and info["band"] == f"{LABEL} · {SPONSOR}" and not info["whole"]
    assert S.sponsorship_errors(sp) == []
    # 광고 장을 뺀 순서로 본다 — 단계 어휘 밖의 '광고'가 순서 실패를 내지 않고, 경고의 비율도 광고 아닌 장에서 센다
    plain = S.check(spec_with([], style="syuka"), {}, TEMPLATE, layout_fn=B.layout_problems)
    stage_w = [w for w in rep.warnings if "반전" in w or "여는 단계" in w or "전개" in w]
    assert stage_w == [w for w in plain.warnings if "반전" in w or "여는 단계" in w or "전개" in w]


def test_stage_errors_report_original_page_numbers():
    """광고 장을 빼고 본 순서의 실패는 원래 쪽 번호로 알린다."""
    sp = good()
    sp["slides"][8]["stage"] = "여는 장"          # 광고 두 장(6·7쪽) 뒤의 9쪽
    assert any(e.startswith("9쪽: 여는 장은 맨 앞에만 둔다") for e in errs(sp)), errs(sp)
    assert "9쪽: 여는 장은 맨 앞에만 둔다" in S.stage_errors(["여는 장", "전개", "여는 장"], TEMPLATE, pages=[1, 2, 9])[0]
    assert "3쪽: 여는 장은 맨 앞에만 둔다" in S.stage_errors(["여는 장", "전개", "여는 장"], TEMPLATE)[0]        # 쪽 번호를 주지 않으면 예전 그대로


def test_plain_spec_is_untouched():
    """광고 칸도 광고 장도 없는 사양은 검사 결과가 예전과 같다(sponsor_info 가 None)."""
    sp = spec_with([], style=None)
    assert S.sponsor_info(sp) is None and S.sponsorship_errors(sp) == []
    assert S.sponsor_view(sp["slides"][0], None, 1) is sp["slides"][0]
    assert B.sponsor_line(sp) == ""
    assert S.check(sp, {}, TEMPLATE, layout_fn=B.layout_problems).errors == S.check(V.spec_of([]), {}, TEMPLATE, layout_fn=B.layout_problems).errors


# ── 실패 조건 ─────────────────────────────────────────────────────────────

def test_block_and_field_must_come_together():
    no_field = spec_with([ad(first=True), ad(last=True)])
    got = errs(no_field)
    assert any("6, 7쪽: stage '광고' 장이 있는데 사양 맨 위 sponsorship 칸이 없다" in e for e in got), got
    assert not any("구성 템플릿 어휘가 아니다" in e for e in got)              # 단계 어휘 오류로 한 줄 더 알리지 않는다
    no_block = spec_with([], sp=sponsorship())
    assert any("sponsorship 칸이 있는데 stage: 광고 장이 없다" in e for e in errs(no_block))
    assert any("사전이어야 한다" in e for e in errs(spec_with([ad(first=True, last=True)], sp="유료 광고")))


@pytest.mark.parametrize("change,frag", [
    ({"kind": "광고"}, "sponsorship.kind '광고' 는 유료 광고 · 협찬 · 협업 가운데 하나여야 한다"),
    ({"kind": None}, "sponsorship.kind"),
    ({"sponsor": ""}, "sponsorship.sponsor(광고주 이름)가 비었다"),
    ({"label": ""}, "sponsorship.label(표시 문구)이 비었다"),
    ({"label": "AD"}, "에 한글이 없다"),
    ({"label": "Sponsored 광고"}, None),                                    # 한글과 낱말이 있으면 이 두 검사는 통과한다(아래에서 따로 본다)
    ({"label": "가상상사와 함께"}, "'광고' · '협찬' 낱말이 없다"),
    ({"label": "광고 없음"}, "부정하는 말"),                                 # 낱말은 있지만 광고임을 부정한다
    ({"label": "협찬 아님"}, "부정하는 말"),
    ({"label": "유료 광고 미포함"}, "부정하는 말"),
    ({"whole": "아니오"}, "sponsorship.whole 은 참/거짓이어야 한다"),
    ({"materials": "소개 자료"}, "sponsorship.materials 는 광고주 제공 자료 이름(문자열)의 목록이어야 한다"),
    ({"materials": ["소개 자료", ""]}, "sponsorship.materials"),
    ({"slides": [6, 7]}, "모르는 칸 ['slides']"),
])
def test_field_shape_errors(change, frag):
    sp = good()
    sp[S.SPONSOR].update(change)
    got = S.sponsorship_errors(sp)
    if frag is None:
        assert not any("한글이 없다" in e or "낱말이 없다" in e for e in got), got
    else:
        assert any(frag in e for e in got), got
        assert any(frag in e for e in errs(sp))                                # check 에도 그대로 올라온다


def test_kinds_and_label_words():
    for kind, label in (("유료 광고", "유료 광고 포함"), ("협찬", "협찬 포함"), ("협업", "가상군청 협찬 포함")):
        sp = spec_with([ad(first=True, last=True, title=f"{label}: {SPONSOR}의 감자 이야기", spoken=f"{label} 구간입니다.")], sp=sponsorship(kind=kind, label=label))
        assert S.sponsorship_errors(sp) == [], (kind, S.sponsorship_errors(sp))


def test_block_must_be_one_run_after_the_opening_and_within_the_share():
    split = spec_with([ad(first=True, last=True)], at=4, sp=sponsorship())
    split["slides"].insert(8, ad(first=True, last=True))
    got = S.sponsorship_errors(split)
    assert any("광고 구간이 한 덩어리가 아니다(5, 9쪽)" in e for e in got), got
    front = spec_with([ad(first=True, last=True)], at=0, sp=sponsorship())
    assert any("광고 구간이 여는 장보다 앞에 왔다(1쪽)" in e for e in S.sponsorship_errors(front))
    # 광고 아닌 장 10장의 20% = 2장까지. 3장이면 넘는다
    assert S.sponsorship_errors(spec_with([ad(first=True), ad(last=True)], sp=sponsorship())) == []
    three = spec_with([ad(first=True), ad(), ad(last=True)], sp=sponsorship())
    assert any("광고 구간 3장 — 광고 아닌 장 10장의 20%(2.0장)를 넘는다" in e for e in S.sponsorship_errors(three))
    assert S.SPONSOR_MAX_SHARE == 0.20


def test_first_and_last_slides_carry_the_label_on_screen_and_in_speech():
    sp = spec_with([ad(), ad()], sp=sponsorship())                              # 첫 장과 끝 장에 표시가 없다(띠는 빌드가 그리지만 그것으로 갈음하지 않는다)
    got = S.sponsorship_errors(sp)
    assert any(e.startswith("6쪽: 광고 구간 첫 장의 화면 글에 표시 문구 · 광고주 이름") for e in got), got
    assert any(e.startswith("6쪽: 광고 구간 첫 장의 말로 할 문장") for e in got)
    assert any(e.startswith("7쪽: 광고 구간 끝 장의 화면 글에") for e in got) and any(e.startswith("7쪽: 광고 구간 끝 장의 말로 할 문장") for e in got)
    only_label = spec_with([ad(first=True, title=f"{LABEL}: 감자 이야기"), ad(last=True)], sp=sponsorship())
    got = S.sponsorship_errors(only_label)
    assert any(e.startswith("6쪽: 광고 구간 첫 장의 화면 글에 광고주 이름") for e in got) and not any(e.startswith("7쪽") for e in got), got
    # 가운데 장은 띠만 있으면 된다. 한 장짜리 구간은 그 장이 첫 장이자 끝 장이다(같은 줄을 두 번 내지 않는다)
    assert S.sponsorship_errors(spec_with([ad(first=True, last=True)], sp=sponsorship())) == []
    one = S.sponsorship_errors(spec_with([ad()], sp=sponsorship()))
    assert len(one) == 2 and all(e.startswith("6쪽: 광고 구간 첫 장") for e in one), one
    spaced = spec_with([ad(first=True, last=True, title="유료  광고 포함: 가상상사 이야기")], sp=sponsorship())   # 띄어쓰기 차이는 가리지 않는다
    assert S.sponsorship_errors(spaced) == []


def test_whole_episode_needs_no_ad_stage_and_marks_first_and_last_slides():
    sp = spec_with([], sp=sponsorship(whole=True))
    got = S.sponsorship_errors(sp)
    assert not any("장이 없다" in e or "20%" in e or "한 덩어리" in e or "여는 장보다" in e for e in got), got
    assert any(e.startswith("1쪽: 광고 구간 첫 장") for e in got) and any(e.startswith("10쪽: 광고 구간 끝 장") for e in got)
    assert S.sponsor_info(sp)["pages"] == list(range(1, 11))                    # 모든 장에 띠
    for i in (0, 9):
        sp["slides"][i]["title"] = f"{LABEL} · {SPONSOR}"
        sp["slides"][i]["spoken"] = f"이 회차는 {LABEL} 회차입니다."
    assert S.sponsorship_errors(sp) == []
    assert "회차 전체" in B.sponsor_line(sp) and "1쪽~10쪽(10장" in B.sponsor_line(sp)


def test_sponsor_pictures_must_be_newsroom_or_logo(tmp_path):
    art = _art(tmp_path / "a.png")
    sp = good()
    sp["pictures"] = [entry(art, pid="p1", rights_holder=f"{SPONSOR} 홍보팀"), entry(art, pid="p2"),
                      entry(art, pid="p3", kind="기업 뉴스룸", rights_holder=SPONSOR, permission="가상상사 뉴스룸 이용 조건(지어낸 기록)"),
                      entry(art, pid="p4", kind="로고", rights_holder=f"주식회사 {SPONSOR.upper()}")]
    from ozl.render import pictures as PIC
    got = S.sponsorship_errors(sp, PIC.ledger(sp)[0])
    assert len(got) == 1 and got[0].startswith("picture p1: 권리자 칸에 광고주 이름('가상상사')이 든 그림의 종류가 'CC BY' 다"), got
    assert any("picture p1: 권리자 칸에 광고주 이름" in e for e in errs(sp))


# ── 띠 ───────────────────────────────────────────────────────────────────

def test_band_is_planned_on_every_slide_of_the_block_and_checked_for_overflow():
    sp = good()
    info = S.sponsor_info(sp)
    views = [S.sponsor_view(sl, info, i) for i, sl in enumerate(sp["slides"], 1)]
    assert [i for i, v in enumerate(views, 1) if S.SPONSOR_KEY in v] == [6, 7]
    assert S.SPONSOR_KEY not in sp["slides"][5]                                  # 사양은 고치지 않는다(사본에만 넣는다)
    pl = B.plan_slide(views[5])
    band = [b for b in pl.boxes if b.name == B.BAND_NAME]
    assert len(band) == 1 and band[0].paras[0].text == f"{LABEL} · {SPONSOR}"
    b = band[0]
    assert abs(b.left + b.width - (B.SW - B.ML)) < 1e-6 and b.top + b.height < B._in(B.deck.TITLE_TOP)   # 오른쪽 위, 제목 줄 위
    assert b.problems() == [] and b.fill == B.BAND_FILL
    assert not [x for x in B.plan_slide(views[0]).boxes if x.name == B.BAND_NAME]
    # 띠가 넘치면 검사가 실패한다(표시 문구나 광고주 이름이 너무 길다)
    long = good()
    long[S.SPONSOR]["sponsor"] = "가상의 섬 감자 농사 협동조합 연합회 중앙 사무국 홍보 담당 부서"
    for k in (5, 6):
        long["slides"][k]["title"] = "감자 이야기"
        long["slides"][k]["body"] = [f"{LABEL} · {long[S.SPONSOR]['sponsor']}"]
    got = errs(long)
    assert any(e.startswith("6쪽: 광고 띠:") and "줄 넘침" in e for e in got), got


def test_built_deck_draws_the_band_and_writes_the_sheet_and_links(tmp_path):
    from pptx import Presentation
    sp = good()
    out = tmp_path / "o" / "ad.pptx"
    B.build_pptx(sp, {}, {"card_id": CARD}, out)
    prs = Presentation(str(out))
    bands = [(i, sh) for i, s in enumerate(prs.slides, 1) for sh in s.shapes if sh.name == B.BAND_NAME]
    assert [i for i, _ in bands] == [6, 7]
    sh = bands[0][1]
    assert sh.text_frame.text == f"{LABEL} · {SPONSOR}" and sh.fill.fore_color.rgb == B.BAND_FILL
    run = sh.text_frame.paragraphs[0].runs[0]
    assert run.font.color.rgb == B.BAND_TEXT and run.font.bold
    assert sh.left + sh.width <= prs.slide_width and sh.top >= 0
    assert "[광고 · image_text]" in prs.slides[5].notes_slide.notes_text_frame.text
    sheet = B.running_sheet(sp, {"card_id": CARD}, {}, "20990102_000000")
    assert f"**광고 구간: 6쪽~7쪽(2장)** · 광고주: {SPONSOR} · 종류: 유료 광고 · 표시 문구: {LABEL}." in sheet
    assert "광고주 제공 자료 1건: 가상상사 소개 자료(지어낸 자료)" in sheet and "| 광고 | 2 | 40 |" in sheet
    md = B.links_md(sp, {}, {"card_id": CARD}, S.link_plan(sp, {}), "20990102_000000")
    assert "## 광고주 제공 자료" in md and "- 가상상사 소개 자료(지어낸 자료)" in md and "숫자의 근거가 아니다" in md
    assert md.index("## 광고주 제공 자료") < md.index("## 그림 출처")
    none = copy.deepcopy(sp)
    none[S.SPONSOR]["materials"] = []
    assert "없음(광고주가 준 자료를 쓰지 않았다)." in B.links_md(none, {}, {"card_id": CARD}, S.link_plan(none, {}), "x")
    plain = spec_with([])
    assert "광고주 제공 자료" not in B.links_md(plain, {}, {"card_id": CARD}, S.link_plan(plain, {}), "x")
    assert "광고 구간" not in B.running_sheet(plain, {"card_id": CARD}, {}, "x")


def test_pending_tag_moves_left_of_the_band_in_draft(tmp_path):
    """초안 모드의 [검증 대기] 딱지는 광고 띠와 겹치지 않게 띠의 왼쪽에 놓인다."""
    from pptx import Presentation
    sp = good()
    out = tmp_path / "o" / "draft.pptx"
    B.build_pptx(sp, {}, {"card_id": CARD}, out, pending={6: [f"{CARD}-c9"], 3: [f"{CARD}-c9"]})
    prs = Presentation(str(out))
    by = {sh.name: sh for sh in prs.slides[5].shapes}
    assert by["검증 대기"].left + by["검증 대기"].width <= by[B.BAND_NAME].left
    plain = {sh.name: sh for sh in prs.slides[2].shapes}["검증 대기"]
    assert abs((plain.left + plain.width) - B.Inches(B.SW - B.ML)) < 2          # 띠가 없는 쪽은 예전 자리


# ── 견본집 ────────────────────────────────────────────────────────────────

def test_samples_carry_an_ad_block_with_a_made_up_sponsor(tmp_path):
    from pptx import Presentation
    sp = ST.sample_spec(tmp_path / "그림")
    info = S.sponsor_info(sp)
    assert len(info["pages"]) == 2 and info["sponsor"] == ST.SAMPLE_SPONSOR["sponsor"] and "지어낸" in info["materials"][0]
    assert ST.sample_problems(sp) == []
    first, last = (sp["slides"][i - 1] for i in info["pages"])
    assert info["label"] in first["title"] and info["label"] in last["caption"] and info["label"] in first["spoken"] and info["label"] in last["spoken"]
    built = ST.samples(tmp_path / "out", export=False, link=None)
    prs = Presentation(built["pptx"])
    assert [i for i, s in enumerate(prs.slides, 1) if any(sh.name == B.BAND_NAME for sh in s.shapes)] == info["pages"]
    assert "광고 구간" in prs.slides[info["pages"][0] - 1].notes_slide.notes_text_frame.text
    # 견본에서는 그림 경고도 실패다 — 자리 넓이의 절반을 못 채우는 그림으로 바꾸면 견본집을 만들지 않는다
    bad = ST.sample_spec(tmp_path / "그림2")
    tall = _art(tmp_path / "tall.png", (500, 1000))
    from ozl.render import pictures as PIC
    bad["pictures"][4].update(path=str(tall), sha256=PIC.file_sha256(tall))      # p5 — photo_caption 의 넓은 자리
    assert any("만 채운다" in e for e in ST.sample_problems(bad)), ST.sample_problems(bad)
