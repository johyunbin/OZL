"""덱·손 템플릿·.potx 가 모두 거치는 deck.new_deck() 의 테마 글꼴은 맑은 고딕이다(2026-11-21 사용자 지적: 새 글상자가 Calibri 로 나왔다)."""
import io
import re
import zipfile

import pytest
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from ozl.render import deck

THEME = re.compile(r'<a:(major|minor)Font>\s*<a:latin typeface="([^"]*)"/>\s*<a:ea typeface="([^"]*)"/>')
FOUR = re.compile(r'(<a:(?:major|minor)Font>\s*<a:latin typeface=")[^"]*("/>\s*<a:ea typeface=")[^"]*(")')


def _theme_xml(prs) -> str:
    b = io.BytesIO()
    prs.save(b)
    with zipfile.ZipFile(b) as z:
        return z.read("ppt/theme/theme1.xml").decode("utf-8")


def test_new_deck_theme_fonts_are_malgun_gothic_and_nothing_else_changes():
    x = _theme_xml(deck.new_deck())
    assert THEME.findall(x) == [("major", "맑은 고딕", "맑은 고딕"), ("minor", "맑은 고딕", "맑은 고딕")]
    base = Presentation().slide_masters[0].part.part_related_by(RT.THEME).blob.decode("utf-8")
    blank = lambda s: FOUR.sub(r"\1\2\3", s)        # 네 속성값만 지우고 나머지(cs, 스크립트별 글꼴 목록)는 기본 테마와 같아야 한다
    assert blank(x) == blank(base)


def test_set_theme_font_is_idempotent_escapes_and_refuses_odd_themes():
    prs = deck.new_deck()
    deck.set_theme_font(prs)                          # 두 번 불러도 같다
    assert THEME.findall(_theme_xml(prs)) == [("major", "맑은 고딕", "맑은 고딕"), ("minor", "맑은 고딕", "맑은 고딕")]
    deck.set_theme_font(prs, 'A&B"C')                 # 속성값으로 이스케이프된다 — 저장본이 XML 로 읽힌다
    assert THEME.findall(_theme_xml(prs))[0][1] == "A&amp;B&quot;C"
    part = prs.slide_masters[0].part.part_related_by(RT.THEME)
    xml = part.blob.decode("utf-8")
    for bad in (b"<a:theme/>", xml.replace("minorFont", "majorFont").encode("utf-8")):   # 글꼴 자리가 없거나 제목만 두 번인 테마
        part._blob = bad
        with pytest.raises(ValueError):
            deck.set_theme_font(prs)


def _xml(prs, name: str) -> str:
    b = io.BytesIO()
    prs.save(b)
    with zipfile.ZipFile(b) as z:
        return z.read(name).decode("utf-8")


def test_slide_size_has_no_4x3_label():
    x = _xml(deck.new_deck(), "ppt/presentation.xml")
    assert re.findall(r"<p:sldSz[^>]*>", x) == ['<p:sldSz cx="12191695" cy="6858000"/>']


A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _assert_defaults(st_xml: str, body_like: bool) -> None:
    """기본 글 서식 덩어리(defaultTextStyle·otherStyle)를 레벨마다 본다."""
    from lxml import etree
    st = etree.fromstring(st_xml)
    levels = [c for c in st if etree.QName(c).localname.startswith("lvl")]
    assert len(levels) == 9
    for lvl in levels:
        rpr = lvl.find(A + "defRPr")
        if body_like:
            lns = lvl.findall(A + "lnSpc")
            assert len(lns) == 1 and lvl[0] is lns[0]                         # 맨 앞에 정확히 하나(두 번 불러도 겹치지 않음)
            assert [(etree.QName(c).localname, c.get("val")) for c in lns[0]] == [("spcPct", "150000")]   # 비율 150%(고정 pt 아님)
            assert rpr.get("sz") == "2600" and rpr.get("lang") == "ko-KR"
        else:
            assert lvl.find(A + "lnSpc") is None and rpr.get("sz") == "1800"
    d = st.find(A + "defPPr/" + A + "defRPr")
    assert d.get("lang") == ("ko-KR" if body_like else "en-US")


def _styles(pptx_path) -> list[str]:
    with zipfile.ZipFile(pptx_path) as z:
        x, m = z.read("ppt/presentation.xml").decode("utf-8"), z.read("ppt/slideMasters/slideMaster1.xml").decode("utf-8")
    ns = ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    cut = lambda s, tag: s[s.index(f"<{tag}"):s.index(f"</{tag}>") + len(tag) + 3].replace(f"<{tag}", f"<{tag}{ns}", 1)
    return [cut(x, "p:defaultTextStyle"), cut(m, "p:otherStyle")]


def test_template_text_defaults_are_body_like_and_idempotent(tmp_path):
    prs = deck.new_deck()
    deck.set_template_text_defaults(prs)
    deck.set_template_text_defaults(prs)              # 두 번 불러도 lnSpc 가 겹치지 않는다
    prs.save(tmp_path / "a.pptx")
    for st in _styles(tmp_path / "a.pptx"):
        _assert_defaults(st, True)
    m = _xml(prs, "ppt/slideMasters/slideMaster1.xml")       # 제목·본문 자리표시자 서식은 건드리지 않는다
    base = _xml(deck.new_deck(), "ppt/slideMasters/slideMaster1.xml")
    assert m[m.index("<p:titleStyle"):m.index("</p:bodyStyle>")] == base[base.index("<p:titleStyle"):base.index("</p:bodyStyle>")]


def test_defaults_reach_templates_but_not_decks(tmp_path):
    """손 템플릿·.potx 를 만드는 경로는 기본값을 바꾸고, 일반 덱 생성은 그대로 둔다(이미 만든 덱의 렌더가 바뀌지 않게)."""
    from ozl.render import build as B
    from ozl.render import potx, template
    h = template.build(tmp_path / "hand", export=False, version="v2")
    t = potx.build(tmp_path / "potx", export=False, version="v2")
    for f in (h["pptx"], t["potx"], t["pptx"]):
        for st in _styles(f):
            _assert_defaults(st, True)
    B.build_pptx(template.template_spec("v2"), {}, {}, tmp_path / "deck.pptx", appendix=False)
    for st in _styles(tmp_path / "deck.pptx"):
        _assert_defaults(st, False)


def test_table_cells_end_runs_carry_the_font(tmp_path):
    from ozl.render import build as B
    from ozl.render import template
    out = tmp_path / "t.pptx"
    B.build_pptx(template.template_spec("v2"), {}, {}, out, appendix=False)
    prs = Presentation(str(out))
    paras = [p for s in prs.slides for sh in s.shapes if sh.has_table for p in sh._element.iter(A + "p")]
    assert paras, "템플릿 사양에 비교표가 있어야 한다"
    for p in paras:                                    # 칸의 문단마다 끝 서식이 있고 두 글꼴이 있다
        e = p.find(A + "endParaRPr")
        assert e is not None
        assert [c.get("typeface") for c in e if c.tag.split("}")[1] in ("latin", "ea")] == ["맑은 고딕", "맑은 고딕"]


def test_set_end_font_keeps_schema_order():
    from lxml import etree
    from pptx.oxml.ns import qn
    r = etree.Element(qn("a:endParaRPr"))
    for tag in ("a:solidFill", "a:cs", "a:ea", "a:extLst"):
        etree.SubElement(r, qn(tag))
    deck.set_end_font(r)
    assert [c.tag.split("}")[1] for c in r] == ["solidFill", "latin", "ea", "cs", "extLst"]
    assert [c.get("typeface") for c in r if c.tag.split("}")[1] in ("latin", "ea")] == ["맑은 고딕", "맑은 고딕"]


def test_template_defaults_put_new_defrpr_before_extlst():
    from lxml import etree
    from pptx.oxml.ns import qn
    prs = deck.new_deck()
    lvl = prs.part._element.find(qn("p:defaultTextStyle")).find(qn("a:lvl1pPr"))
    lvl.remove(lvl.find(qn("a:defRPr")))
    etree.SubElement(lvl, qn("a:extLst"))
    deck.set_template_text_defaults(prs)
    assert [etree.QName(c).localname for c in lvl] == ["lnSpc", "defRPr", "extLst"]
