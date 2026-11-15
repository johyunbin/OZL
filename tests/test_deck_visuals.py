"""덱 그림 자리의 차트(chart)·원문 캡처(capture) 검사와 빌드 회귀 테스트(src/ozl/render/spec.py · build.py).
네트워크 없이 돈다(임시 폴더의 html 사본과 주입한 응답). 예시 문장과 숫자는 전부 지어낸 것이다."""
from __future__ import annotations

import copy
import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.render import build as B  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.research import cards as C  # noqa: E402
from ozl.research import capture as K  # noqa: E402

TEMPLATE = S.load_template()
CARD = "2099-01-02-am-01"
CID = f"{CARD}-c1"          # 기계 대조 기록(원문 사본이 있다)
OLD = f"{CARD}-c2"          # 사람이 대조한 옛 기록(사본 없음)
URL = "https://stats.example.org/potato.html"
PAD = "가상의 섬 통계청은 해마다 감자 값을 집계해 알린다. 이 문서의 수치는 전부 지어낸 것이다. " * 3
SENTENCE = "2098년 12월 감자 값은 18,250이다."   # observed·located 는 통째 대목(문장·줄·칸)이어야 한다
HTML = ("<!doctype html><html><head><title>가상 섬 통계</title></head><body>"
        f"<p>{SENTENCE}</p>"
        "<table><tr><th>월</th><th>감자 값</th></tr><tr><td>2098-01</td><td>12.5</td></tr><tr><td>2098-06</td><td>20.40</td></tr>"
        "<tr><td>2098-12</td><td>18,250</td></tr></table>"   # 차트 점 값은 표의 칸(공백으로 나뉜 낱말 하나)에서 찾는다
        "<p>같은 해 출하는 11,234상자였다.</p><table><tr><td>출하(상자)</td><td>11,234</td></tr></table>"
        f"<p>{PAD}</p></body></html>").encode("utf-8")


class Resp:
    def __init__(self, body: bytes):
        self.status, self._b, self.headers = 200, io.BytesIO(body), {"Content-Type": "text/html; charset=utf-8"}

    def geturl(self):
        return URL

    def read(self, n=-1):
        return self._b.read(n)

    def close(self):
        pass


def base_claim():
    return {"claim_id": CID, "card_id": CARD, "text": "가상의 섬 2098년 12월 감자 값은 18,250이다.", "observed": SENTENCE,
            "source": {"url": URL, "tier": "T1", "publisher": "가상 섬 통계청", "accessed": "2099-01-02", "archived": ""},
            "cross_check": [], "status": "pending",
            "checks": {"unit_ok": True, "base_period": "2098", "real_vs_nominal": "n/a", "seasonally_adjusted": "n/a", "methodology_match": "n/a",
                       "revision_status": "final", "primary_doc_locator": "본문 첫 문단", "recalculated": "n/a", "translation_checked": True},
            "counter": {"core_claim": "가상", "strongest_counter": "가상", "denominator_check": "가상", "residual_uncertainty": "가상"},
            "human_verified": False, "revision": 1}


def old_claim():
    return {"claim_id": OLD, "card_id": CARD, "text": "가상의 섬 당근 값은 1월 7.5, 12월 9.25다.", "observed": "carrot 7.5 → 9.25",
            "human_verified": True, "status": "verified",
            "source": {"url": "https://example.org/carrot.pdf", "publisher": "가상 섬 농업청", "tier": "T1"},
            "checks": {"base_period": "2098", "primary_doc_locator": "표 2"}}


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DESK", tmp_path / "desk")
    monkeypatch.setattr(C, "CARDS", tmp_path / "desk" / "cards")
    monkeypatch.setattr(C, "CLAIMS", tmp_path / "desk" / "claims")
    monkeypatch.setattr(C, "PUB_CLAIMS", tmp_path / "claims")
    return tmp_path


def pending_claim(tmp, body: bytes = HTML, observed: str = "", author_located: str = "", recheck_located: str = SENTENCE) -> dict:
    """사본을 받고(주입한 응답) 재대조 기록까지 붙였지만 아직 machine_verify 전(pending)인 기록 — 정본 위치(임시)에 저장한다."""
    c = base_claim()
    if observed:
        c["observed"] = observed
    got = K.capture_claim(c, tmp / "captures", C.ROOT, fetcher=lambda u, d: K.fetch(u, d, opener=lambda req, timeout: Resp(body)), shot=False)
    c["verification"] = {"method": "machine", **got, "author": {"by": "agent-a", "located": author_located},
                         "recheck": {"by": "agent-b", "located": recheck_located,
                                     "checks": {"unit": "원", "as_of": "2098년", "status": "확정", "population": "가상", "speaker": "가상 섬 통계청"},
                                     "at": "2099-01-02T10:00:00+09:00"},
                         "verified_at": ""}
    C.save_yaml(C.claim_path(CID), c)
    return c


def machine_claim(tmp, image=True, **kw) -> dict:
    """pending_claim 을 machine_verify 로 「원문 일치」까지 올린 기록. image=True 면 기록의 verification.image 에 가짜 PNG 를 적는다
    (덱은 이것을 쓰지 않는다 — 빌드가 사본에서 새로 그린다)."""
    pending_claim(tmp, **kw)
    r = C.machine_verify(CID)
    assert r["ok"], r["reasons"]
    c = C.load_yaml(C.claim_path(CID))
    if image:
        from PIL import Image
        png = tmp / "captures" / f"{CID}.png"
        Image.new("RGB", (900, 1400), "white").save(png)   # 세로로 긴 그림 — 자리 안쪽 맞춤을 본다
        c["verification"]["image"] = {"path": str(png), "reason": "", "view": "text"}
    assert S.accepted(c)
    return c


def line_chart(**kw):
    ch = {"kind": "line", "title": "가상의 섬 감자 값", "unit": "원", "period": "2098-01 ~ 2098-12",
          "series": [{"name": "감자", "points": [["2098-01", "12.5"], ["2098-06", "20.40"], ["2098-12", "18,250"]]}],
          "source": "가상 섬 통계청", "claims": [CID], "highlight": ["2098-12"]}
    ch.update(kw)
    return ch


def slide(**kw):
    base = {"stage": "근거 수치", "kind": "image_text", "title": "감자 값", "body": ["감자 값이 올랐다"], "claim_ids": [CID], "seconds": 20}
    base.update(kw)
    return base


def spec_of(slides):
    stages = ["여는 장", "배경", "반전", "전개", "반전", "근거 수치", "비교", "반전", "전개", "닫는 장"]
    out = [{"stage": s, "kind": "closing" if s == "닫는 장" else "image_text", "title": "감자 이야기", "body": ["감자는 땅속에서 자란다"],
            "seconds": 20, "image": {"what": "감자밭 사진", "source": "가상 섬 농업청"}} for s in stages]
    for o in out:
        if o["kind"] == "closing":
            del o["image"]
    return {"card_id": CARD, "slides": out[:2] + slides + out[2:]}


def errors(sl, claims, draft=False):
    return S.check(spec_of([sl]), claims, TEMPLATE, draft=draft, layout_fn=B.layout_problems).errors


# ── 차트 ────────────────────────────────────────────────────────────────
def test_chart_happy_path_passes(desk):
    c = machine_claim(desk)
    rep = S.check(spec_of([slide(chart=line_chart())]), {CID: c}, TEMPLATE, layout_fn=B.layout_problems)
    assert rep.ok, rep.errors
    assert not any("그림 자리가 비었다" in w for w in rep.warnings)


def test_chart_point_value_missing_from_copy_fails(desk):
    c = machine_claim(desk)
    ch = line_chart()
    ch["series"][0]["points"][1] = ["2098-06", "20.45"]       # 꼬리표가 없는 점도 본다
    errs = errors(slide(chart=ch), {CID: c})
    assert any("2098-06" in e and "'20.45'" in e and "원문 사본 글" in e for e in errs), errs


def test_chart_point_that_is_a_piece_of_a_longer_number_fails(desk):
    c = machine_claim(desk)
    ch = line_chart(highlight=[])
    ch["series"][0]["points"][1] = ["2098-06", "1,234"]       # 사본에는 11,234 만 있다
    errs = errors(slide(chart=ch), {CID: c})
    assert any("'1,234'" in e and "조각" in e for e in errs), errs
    ch["series"][0]["points"][1] = ["2098-06", "11,234"]
    assert errors(slide(chart=ch), {CID: c}) == []


def test_chart_display_string_is_the_notation_checked(desk):
    c = machine_claim(desk)
    ch = line_chart(highlight=[])
    ch["series"][0]["points"][1] = ["2098-06", 20.4, "20.40"]  # 표시 문자열 '20.40' 으로 대조한다(값 20.4 의 표기 '20.4' 는 20.40 의 조각)
    assert errors(slide(chart=ch), {CID: c}) == []
    ch["series"][0]["points"][1] = ["2098-06", 20.4]
    assert any("'20.4'" in e for e in errors(slide(chart=ch), {CID: c}))


def test_chart_claims_outside_slide_claim_ids_fails(desk):
    c = machine_claim(desk)
    errs = errors(slide(chart=line_chart(claims=[CID, OLD])), {CID: c, OLD: old_claim()})
    assert any("chart.claims" in e and OLD in e and "claim_ids 에 없다" in e for e in errs), errs


def test_chart_label_quantity_follows_number_rule(desk):
    c = machine_claim(desk)
    ch = line_chart(highlight=["2098-06"])                    # 꼬리표 '20.40' 은 기록 observed·text 에 없다(사본에는 있다)
    errs = errors(slide(chart=ch), {CID: c})
    assert any("화면의 숫자·수량" in e and "20.40" in e for e in errs), errs
    ch = line_chart(title="가상의 섬 감자 값 3배")             # 그림 제목의 수량도 같은 규칙
    assert any("화면의 숫자·수량" in e and "'3'" in e for e in errors(slide(chart=ch), {CID: c}))


def test_chart_validate_errors_pass_through_and_kind_must_have_slot(desk):
    c = machine_claim(desk)
    errs = errors(slide(chart=line_chart(kind="pie")), {CID: c})
    assert any(e.endswith("kind 는 line 또는 bar 여야 한다(받은 값: 'pie')") for e in errs), errs
    sl = {"stage": "근거 수치", "kind": "closing", "title": "끝", "body": ["끝"], "claim_ids": [CID], "chart": line_chart(), "seconds": 5}
    assert any("그림 자리가 있는 종류" in e for e in errors(sl, {CID: c}))


def test_chart_with_only_human_verified_old_claim_uses_observed_and_text():
    ch = line_chart(claims=[OLD], highlight=[], series=[{"name": "당근", "points": [["2098-01", "7.5"], ["2098-12", "9.25"]]}])
    assert errors(slide(claim_ids=[OLD], chart=ch), {OLD: old_claim()}) == []
    ch["series"][0]["points"][1] = ["2098-12", "9.2"]
    assert any("'9.2'" in e for e in errors(slide(claim_ids=[OLD], chart=ch), {OLD: old_claim()}))


def test_chart_and_capture_together_fails(desk):
    c = machine_claim(desk)
    errs = errors(slide(chart=line_chart(), capture=CID), {CID: c})
    assert any("그림 자리는 하나다" in e for e in errs), errs


# ── 원문 캡처 ────────────────────────────────────────────────────────────
def test_capture_not_yet_accepted_fails_strict_and_waits_in_draft(desk):
    c = pending_claim(desk)                                       # 사본은 있지만 아직 「원문 일치」가 아니다
    errs = errors(slide(capture=CID), {CID: c})
    assert any(e.startswith("3쪽: capture ") and "사람 대조 전" in e for e in errs), errs
    rep = S.check(spec_of([slide(capture=CID)]), {CID: c}, TEMPLATE, draft=True, layout_fn=B.layout_problems)
    assert rep.ok, rep.errors
    assert rep.pending[3] == [CID, S.WAIT_IMAGE + CID]
    # 받아들여지는 기록이면 그림 파일 없이도(빌드가 사본에서 그린다) 엄격 모드가 통과한다
    c = machine_claim(desk, image=False)
    assert errors(slide(capture=CID), {CID: c}) == []


def test_capture_needs_drawable_copy_for_human_record_without_copy():
    errs = errors(slide(claim_ids=[OLD], capture=OLD), {OLD: old_claim()})
    assert any("원문 사본으로 그림을 그릴 수 없다" in e for e in errs), errs


def test_capture_must_be_cited_and_accepted(desk):
    c = machine_claim(desk)
    assert any("claim_ids 에 없다" in e for e in errors(slide(claim_ids=[OLD], capture=CID), {CID: c, OLD: old_claim()}))
    bad = copy.deepcopy(c)
    bad["verification"]["recheck"]["by"] = "agent-a"           # 쓴 쪽과 재대조한 쪽이 같다 → 받지 않는 기록
    assert any(e.startswith("3쪽: capture ") for e in errors(slide(capture=CID), {CID: bad}))
    assert errors(slide(capture=CID), {CID: c}) == []


def test_bare_image_text_warns_in_strict_only(desk):
    rep = S.check(spec_of([slide(claim_ids=[], body=["글만"])]), {}, TEMPLATE, layout_fn=B.layout_problems)
    assert rep.ok and any("그림 자리가 비었다" in w and "3쪽" in w for w in rep.warnings)
    rep = S.check(spec_of([slide(claim_ids=[], body=["글만"])]), {}, TEMPLATE, draft=True, layout_fn=B.layout_problems)
    assert not any("그림 자리가 비었다" in w for w in rep.warnings)


# ── 빌드 ────────────────────────────────────────────────────────────────
def _pictures(s):
    return [sh for sh in s.shapes if sh.shape_type == 13]  # MSO_SHAPE_TYPE.PICTURE


def test_build_puts_chart_and_capture_pictures_in_pptx(desk):
    from pptx import Presentation
    c = machine_claim(desk)
    bar = {"kind": "bar", "title": "가상의 섬 감자 값 비교", "unit": "원", "period": "2098년",
           "series": [{"name": "감자", "points": [["1월", "12.5"], ["12월", "18,250"]]}], "source": "가상 섬 통계청", "claims": [CID]}
    sp = spec_of([slide(chart=line_chart(y_from_zero=False)), slide(kind="number", number={"value": "18,250"}, chart=bar), slide(capture=CID)])
    rep = S.check(sp, {CID: c}, TEMPLATE, layout_fn=B.layout_problems)
    assert rep.ok, rep.errors
    out = desk / "out" / "d.pptx"
    B.build_pptx(sp, {CID: c}, {"card_id": CARD}, out)
    assert sorted(p.name for p in (out.parent / B.VISUALS_DIR).iterdir()) == ["03_chart.png", "04_chart.png", "05_capture.png"]
    prs = Presentation(str(out))
    slides = list(prs.slides)
    for k in (2, 3):
        pics = _pictures(slides[k])
        assert len(pics) == 1 and pics[0].name == "차트"
        assert abs(pics[0].width / pics[0].height - (B.deck.IMG_W / B.deck.IMG_H)) < 0.01   # 그림 자리와 같은 비(찌그러지지 않는다)
    pics = _pictures(slides[4])
    assert len(pics) == 1 and pics[0].name == "원문 캡처"
    from PIL import Image
    with Image.open(out.parent / B.VISUALS_DIR / "05_capture.png") as g:
        gw, gh = g.size
    assert abs(pics[0].width / pics[0].height - gw / gh) < 0.01                             # 새로 그린 그림의 비율을 지켰다
    assert pics[0].height <= B.deck.IMG_H + 1 and pics[0].width <= B.deck.IMG_W + 1          # 자리 안쪽
    texts = [sh.text_frame.text for sh in slides[4].shapes if sh.has_text_frame]
    assert "원문: stats.example.org" in texts and not any("받은 날" in t for t in texts), texts
    assert all(not sh.name == "그림 자리" for sh in slides[2].shapes)
    md = B.running_sheet(sp, {"card_id": CARD}, {CID: c}, "20990102_000000")
    assert "| 근거 | 그림 |" in md and "| 차트(선) |" in md and "| 차트(막대) |" in md and "| 원문 캡처 c1 |" in md and "| 그림 자리(회색) |" in md
    assert "3쪽 차트(선) · 쓴 기록 c1: 값이 사본에 있는지만 프로그램이 봤다. 칸과 값의 짝은 문장 대조에서 본다. 세로축이 0에서 시작하지 않는다" in md
    assert "4쪽 차트(막대)" in md and md.count("세로축이 0에서") == 1


def test_draft_build_marks_waiting_capture(desk):
    from pptx import Presentation
    c = pending_claim(desk)
    sp = spec_of([slide(capture=CID)])
    rep = S.check(sp, {CID: c}, TEMPLATE, draft=True, layout_fn=B.layout_problems)
    out = desk / "out" / "w.pptx"
    B.build_pptx(sp, {CID: c}, {"card_id": CARD}, out, pending=rep.pending)
    s3 = Presentation(str(out)).slides[2]
    texts = [sh.text_frame.text for sh in s3.shapes if sh.has_text_frame]
    assert any(t == "[검증 대기] c1 · [그림 대기] c1" for t in texts), texts      # 아직 받아들여지지 않은 기록 = 검증 대기이자 그림 대기
    assert any("그림 대기 — c1" in t for t in texts) and not _pictures(s3)
    assert "[그림 대기]" in s3.notes_slide.notes_text_frame.text
    md = B.running_sheet(sp, {"card_id": CARD}, {CID: c}, "x", rep.pending)
    assert "| 원문 캡처 c1 [그림 대기] |" in md


def _build_capture_png(desk, c, name):
    sp = spec_of([slide(capture=CID)])
    out = desk / name / "d.pptx"
    B.build_pptx(sp, {CID: c}, {"card_id": CARD}, out)
    return (out.parent / B.VISUALS_DIR / "03_capture.png").read_bytes()


def test_capture_ignores_recorded_image_path(desk):
    """기록의 verification.image.path 를 무관한 PNG 로 바꿔도 덱의 원문 캡처는 달라지지 않는다(빌드가 사본에서 새로 그린다)."""
    from PIL import Image
    c = machine_claim(desk)
    a = _build_capture_png(desk, c, "o1")
    junk = desk / "captures" / "junk.png"
    Image.new("RGB", (50, 50), "red").save(junk)
    c2 = copy.deepcopy(c)
    c2["verification"]["image"] = {"path": str(junk), "reason": ""}
    assert _build_capture_png(desk, c2, "o2") == a
    c3 = copy.deepcopy(c)
    c3["verification"]["image"] = {"path": "", "reason": "없음"}
    assert _build_capture_png(desk, c3, "o3") == a


def test_capture_uses_the_matched_place_not_the_first(desk, monkeypatch):
    """observed 가 사본에 두 번 나오고 둘째 자리를 대조했으면 문맥과 그림은 둘째 자리의 것이다."""
    body = ("<!doctype html><html><body><p>가상 1분기 감자 집계다. 값은 18,250이다.</p><p>가상 4분기 당근 집계다. 값은 18,250이다.</p>"
            f"<p>{PAD}</p></body></html>").encode("utf-8")
    c = machine_claim(desk, image=False, body=body, observed="값은 18,250이다.", author_located="가상 4분기 당근 집계다. 값은 18,250이다.",
                      recheck_located="가상 4분기 당근 집계다. 값은 18,250이다.")
    m = c["verification"]["match"]
    assert m["count"] == 2 and m["target"]["nth"] == 1 and "당근" in m["context"] and "감자 집계다. 【" not in m["context"]
    text = C.copy_text(c)[1]
    second = K.find_phrase(text, "값은 18,250이다.")["matches"][1]["offset"]
    seen = []
    real = K.evidence_image
    monkeypatch.setattr(K, "evidence_image", lambda *a, **k: seen.append(a[5]) or real(*a, **k))
    _build_capture_png(desk, c, "o4")
    assert seen == [second]


def test_capture_passage_that_does_not_fit_fails_strict(desk):
    """대조한 문구가 글자 크기를 최소로 줄여도 그림 자리에 다 들어가지 않으면 엄격 모드가 실패시킨다(잘린 그림으로 성공하지 않는다)."""
    long = "가상의 섬 감자 값은 " + "해마다 조금씩 다르게 집계되어 왔고 " * 90 + "18,250이다."
    body = f"<!doctype html><html><body><p>{long}</p><p>{PAD}</p></body></html>".encode("utf-8")
    c = machine_claim(desk, image=False, body=body, observed=long, recheck_located=long)
    errs = errors(slide(capture=CID), {CID: c})
    assert any("원문 캡처를 그릴 수 없다" in e and "다 들어가지 않는다" in e for e in errs), errs


# ── 차트 그림 안의 출처 줄(style: syuka 는 끈다) ─────────────────────────────
def _ink_rows_from_bottom(png, band: float = 0.045) -> int:
    """그림 아래 띠(높이의 band)에서 잉크가 있는 줄 수. 출처 줄은 아래 끝에서 높이의 약 3~6% 자리에 찍히고,
    출처 줄을 끈 그림의 가장 아래 글(가로축 눈금)은 약 5.4% 위에서 시작한다(기본 크기 1200×1175 에서 잰 값)."""
    from PIL import Image
    with Image.open(png) as g:
        im = g.convert("L")
    W, H = im.size
    px = im.load()
    return sum(1 for y in range(int(H * (1 - band)), H) if any(px[x, y] < 200 for x in range(0, W, 2)))


def test_chart_source_line_can_be_turned_off(tmp_path):
    from ozl.render import charts as G
    ch = line_chart()
    assert "출처: 가상 섬 통계청" in G._drawn_texts(ch)
    assert not any(t.startswith("출처") for t in G._drawn_texts(ch, False))
    conv = line_chart(transform="천 원을 원으로")
    assert "환산: 천 원을 원으로" in G._drawn_texts(conv, False) and "출처: 가상 섬 통계청 · 환산: 천 원을 원으로" in G._drawn_texts(conv)
    assert G.chart_quantities(ch) == G.chart_quantities(dict(ch))            # 수량 대조는 인자와 상관없다(그대로)
    on = G.render_chart(ch, tmp_path / "on.png")
    off = G.render_chart(ch, tmp_path / "off.png", source_line=False)
    kept = G.render_chart(conv, tmp_path / "conv.png", source_line=False)
    assert _ink_rows_from_bottom(on) > 0                                    # 옛 그림: 아래 띠에 출처 줄
    assert _ink_rows_from_bottom(off) == 0                                  # 끄면 아래 띠에 글이 없다
    assert _ink_rows_from_bottom(kept) > 0                                  # 환산식이 있으면 그 줄은 남는다


def test_syuka_build_draws_charts_without_source_line(desk):
    c = machine_claim(desk)
    old = spec_of([slide(chart=line_chart())])
    new = {**spec_of([slide(chart=line_chart())]), "style": "syuka"}
    a = B.render_visuals(old, {CID: c}, desk / "va")[(3, -1)][0]
    b = B.render_visuals(new, {CID: c}, desk / "vb")[(3, -1)][0]
    assert _ink_rows_from_bottom(a) > 0 and _ink_rows_from_bottom(b) == 0    # 옛 사양의 차트는 그대로, 새 규칙은 출처 줄 없음
    rep = S.check(new | {"slides": [dict(sl, seconds=20) for sl in new["slides"]]}, {CID: c}, TEMPLATE, layout_fn=B.layout_problems)
    assert not any("chart" in e for e in rep.errors), rep.errors              # 검사(수량 대조)는 달라지지 않는다


# ── capture_full 의 화면 갈무리 그림, 읽힘과 채움 경고 ────────────────────────
def _shot(tmp, name, size, **kw):
    """지어낸 원문 화면 갈무리 대장 줄(그림은 PIL 로 그린 것). 출처 호스트는 CID 기록의 원문과 같은 기관이다."""
    from test_deck_pictures_policy import _art, screen
    return screen(_art(tmp / name, size), **kw)


def _full_pic(**kw):
    base = {"stage": "근거 수치", "kind": "capture_full", "title": "통계청 화면", "picture": "p1", "claim_ids": [CID], "seconds": 20}
    base.update(kw)
    return base


def _chk_pics(sl, claims, pics, draft=False):
    sp = spec_of([sl])
    sp["pictures"] = pics
    return S.check(sp, claims, TEMPLATE, draft=draft, layout_fn=B.layout_problems)


def test_capture_full_takes_a_screen_shot_picture(desk):
    from pptx import Presentation
    from test_deck_kinds import entry
    from ozl.render import style as ST
    c = machine_claim(desk, image=False)
    shot = _shot(desk, "wide.png", (1500, 640))
    rep = _chk_pics(_full_pic(), {CID: c}, [shot])
    assert rep.ok, rep.errors
    assert not any("picture p1" in w for w in rep.warnings), rep.warnings   # 자리(11.41 × 4.95in)를 절반 넘게 채운다. shot_log 가 없어 읽힘은 어림하지 않는다
    assert ST.layout_of(_full_pic()) == "image_full"
    # capture 를 쓴 꼴은 그대로다(같은 종류, 같은 자리)
    assert _chk_pics({"stage": "근거 수치", "kind": "capture_full", "title": "통계청 원문", "capture": CID, "claim_ids": [CID], "seconds": 20}, {CID: c}, []).ok
    # 원문 화면 갈무리가 아닌 그림은 받지 않는다
    other = _chk_pics(_full_pic(), {CID: c}, [entry(desk / "wide.png")])
    assert any("capture_full 에는 원문 화면 갈무리 종류의 그림만 쓴다" in e for e in other.errors), other.errors
    both = _chk_pics(_full_pic(capture=CID), {CID: c}, [shot])
    assert any("그림 자리는 하나다" in e for e in both.errors)
    none = _chk_pics({k: v for k, v in _full_pic().items() if k != "picture"}, {CID: c}, [shot])
    assert any("capture_full 에는 'capture' 가 있어야 한다" in e and "picture" in e for e in none.errors), none.errors
    grey = _chk_pics({**{k: v for k, v in _full_pic().items() if k != "picture"}, "image": {"what": "감자", "source": "가상 섬 농업청"}}, {CID: c}, [shot])
    assert any("'image' 는 capture_full 의 그림 자리에 쓰지 않는다" in e for e in grey.errors), grey.errors
    # 인용 기록의 원문과 기관 호스트가 다르면 지금 규칙대로 실패한다
    far = _chk_pics(_full_pic(), {CID: c}, [_shot(desk, "far.png", (1500, 640), source_url="https://other.example.net/view")])
    assert any("기관 호스트" in e for e in far.errors), far.errors
    # 빌드: 큰 자리 안쪽에 비율을 지켜 놓이고 그림 밑에 호스트 표기가 붙는다
    sp = spec_of([_full_pic()])
    sp["pictures"] = [shot]
    out = desk / "o" / "full.pptx"
    B.build_pptx(sp, {CID: c}, {"card_id": CARD}, out)
    s3 = Presentation(str(out)).slides[2]
    pics = _pictures(s3)
    assert len(pics) == 1 and pics[0].name == "그림 파일"
    assert abs(pics[0].width / pics[0].height - 1500 / 640) < 0.01
    assert pics[0].top >= B.Inches(B.FULL_TOP) - 1 and pics[0].top + pics[0].height <= B.Inches(B.FULL_BOTTOM) + 1
    assert "원문: www.stats.example.org" in [sh.text_frame.text for sh in s3.shapes if sh.has_text_frame]
    assert "| 그림 파일 p1 |" in B.running_sheet(sp, {"card_id": CARD}, {CID: c}, "x")


def test_screen_readable_pt_from_shot_log(desk):
    from test_deck_kinds import entry
    from ozl.render import pictures as PIC
    from ozl.render import style as ST
    web = _shot(desk, "web.png", (900, 1000), shot_log={"window": "900x1000", "image": "900x1000"})
    assert PIC.screen_readable_pt(web, 2.56) == pytest.approx(ST.SCREEN_WEB_BODY_PX * 2.56 / 900 * 72)        # 창 폭 900px 이 2.56in 로 줄면 약 2.9pt
    clip = _shot(desk, "clip.png", (450, 300), shot_log={"window": "900x1000", "clip": [100, 200, 450, 300], "image": "450x300"})
    assert PIC.screen_readable_pt(clip, 7.4) == pytest.approx(ST.SCREEN_WEB_BODY_PX * 7.4 / 450 * 72)         # 범위를 좁히면 그 폭(450px)이 기준
    pdf = _shot(desk, "pdf.png", (1241, 1755), shot_log={"dpi": 150, "page_px": "1241x1755", "image": "1241x1755"})
    assert PIC.screen_readable_pt(pdf, 2.91) == pytest.approx(ST.SCREEN_DOC_BODY_PT * 150 * 2.91 / 1241)      # 약 3.5pt
    band = _shot(desk, "band.png", (1241, 527), shot_log={"dpi": 150, "page_px": "1241x1755", "band": [0.2, 0.5], "image": "1241x527"})
    assert PIC.screen_readable_pt(band, 11.41) == pytest.approx(ST.SCREEN_DOC_BODY_PT * 150 * 11.41 / 1241)   # 구간은 높이만 자른다 — 넓은 자리면 약 13.8pt
    old = _shot(desk, "old.png", (1241, 1755), shot_log={"dpi": 150})                                         # 그림 크기 칸이 없는 옛 줄은 파일에서 읽는다
    assert PIC.screen_readable_pt(old, 2.91) == pytest.approx(PIC.screen_readable_pt(pdf, 2.91))
    assert PIC.screen_readable_pt(_shot(desk, "none.png", (900, 1000)), 2.56) is None                         # shot_log 가 없으면 어림하지 않는다
    assert PIC.screen_readable_pt(entry(desk / "web.png", shot_log={"window": "900x1000"}), 2.56) is None     # 원문 화면 갈무리가 아니면 어림하지 않는다
    assert PIC.screen_readable_pt(_shot(desk, "bad.png", (900, 1000), shot_log={"window": "넓다"}), 2.56) is None


def test_small_screen_shot_and_half_empty_slot_warn(desk):
    from test_deck_kinds import entry
    from test_deck_pictures_policy import _art
    c = machine_claim(desk, image=False)
    web = _shot(desk, "web.png", (900, 1000), shot_log={"window": "900x1000", "image": "900x1000"})
    stack = {"stage": "근거 수치", "kind": "image_stack", "title": "통계청 화면", "picture": "p1", "claim_ids": [CID], "body": ["감자 값이 올랐다"], "seconds": 20}
    rep = _chk_pics(stack, {CID: c}, [web])
    assert rep.ok, rep.errors                                                # 경고일 뿐이다
    mine = [w for w in rep.warnings if w.startswith("3쪽: picture p1")]
    assert any("갈무리 글자가 약 2.9pt 로 찍힌다" in w and "찍는 범위를 좁히거나 넓은 자리를 쓴다" in w for w in mine), mine
    assert any("자리 넓이의 22% 만 채운다" in w and "빈칸" in w for w in mine), mine
    pdf = _shot(desk, "pdf.png", (1241, 1755), shot_log={"dpi": 150, "page_px": "1241x1755"})
    left = _chk_pics(slide(picture="p1"), {CID: c}, [pdf])
    got = [w for w in left.warnings if "picture p1" in w]
    assert len(got) == 1 and "약 3.5pt" in got[0], got                         # 왼쪽 자리는 71% 를 채워 채움 경고는 없다
    wide = _shot(desk, "band.png", (1241, 527), shot_log={"dpi": 150, "page_px": "1241x1755", "band": [0.2, 0.5], "image": "1241x527"})
    assert not [w for w in _chk_pics(_full_pic(), {CID: c}, [wide]).warnings if "picture p1" in w]           # 구간만 큰 자리에 놓으면 경고가 없다
    # 채움 경고는 그림 종류와 상관없다. 읽힘은 원문 화면 갈무리만 어림한다
    tall = entry(_art(desk / "tall.png", (500, 1000)))
    cap = _chk_pics({"stage": "배경", "kind": "photo_caption", "title": "감자밭", "picture": "p1", "caption": "가상의 섬 풍경이다", "seconds": 20}, {}, [tall])
    got = [w for w in cap.warnings if "picture p1" in w]
    assert len(got) == 1 and "만 채운다" in got[0] and "갈무리" not in got[0], got
