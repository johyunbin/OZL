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
