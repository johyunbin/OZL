"""손 템플릿 사양을 다시 그린 결과와 임시 폴더의 실제 PowerPoint 패키지를 대조한다."""

import re
from zipfile import ZipFile

import pytest
from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER as PH
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.opc.constants import CONTENT_TYPE as CT
from pptx.oxml.ns import qn
from pptx.package import Package

from ozl.render import build as renderer
from ozl.render import deck, spec, style, template
from ozl.render.__main__ import main

KINDS = {
    "full_picture": (PH.PICTURE, PH.BODY),
    "title_hook": (PH.TITLE, PH.BODY),
    "image_text": (PH.PICTURE, PH.TITLE, PH.BODY),
    "number": (PH.PICTURE, PH.TITLE, PH.BODY, PH.BODY),
    "quote_translation": (PH.PICTURE, PH.TITLE, PH.BODY),
    "image_stack": (PH.PICTURE, PH.TITLE, PH.BODY),
    "photo_caption": (PH.PICTURE, PH.TITLE, PH.BODY),
    "capture_full": (PH.PICTURE, PH.TITLE),
    "image_pair": (PH.PICTURE, PH.PICTURE, PH.TITLE, PH.BODY, PH.BODY),
    "compare_table": (PH.TITLE, PH.TABLE),
    "quote_line": (PH.TITLE, PH.BODY, PH.BODY),
    "closing": (PH.TITLE, PH.BODY),
}


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    root = tmp_path_factory.mktemp("potx")
    assert main(["potx", "--out", str(root), "--no-export"]) == 0
    potx, = root.glob("*.potx")
    preview, = root.glob("*.pptx")
    assert sorted(root.iterdir()) == sorted([potx, preview])
    ref = root / "reference.pptx"
    renderer.build_pptx(template.template_spec(), {}, {}, ref, appendix=False)
    return potx, preview, ref


def _geometry(shape):
    return shape.left, shape.top, shape.width, shape.height


def test_packages(files):
    potx, preview, ref = files
    for path, main_type in ((potx, CT.PML_TEMPLATE_MAIN), (preview, CT.PML_PRESENTATION_MAIN)):
        with ZipFile(path) as z:
            types = etree.fromstring(z.read("[Content_Types].xml"))
            assert types.find("{*}Override[@PartName='/ppt/presentation.xml']").get("ContentType") == main_type
            assert not any("thumbnail" in n or "printerSettings" in n for n in z.namelist())
            if path == potx:
                assert not any(n.startswith("ppt/slides/") for n in z.namelist())
        part = Package.open(path).main_document_part  # Presentation(path)는 정식 POTX MIME을 받지 않는다.
        assert part.content_type == main_type
        prs = part.presentation
        assert len(prs.slides) == (0 if path == potx else len(spec.KINDS))
        assert len(prs.slide_masters) == 1
        assert (prs.slide_width, prs.slide_height) == (deck.W, deck.H)
    with ZipFile(potx) as a, ZipFile(preview) as b, ZipFile(ref) as c:
        for name in a.namelist():
            if name.startswith(("ppt/slideMasters/", "ppt/slideLayouts/", "ppt/theme/")):
                assert a.read(name) == b.read(name)
        assert a.read("ppt/theme/theme1.xml") == c.read("ppt/theme/theme1.xml")


def test_layouts_and_new_slide(files):
    prs = Package.open(files[0]).main_document_part.presentation
    slides = template.template_spec()["slides"]
    assert set(KINDS) == set(spec.KINDS)
    assert len(prs.slide_layouts) == len(KINDS)
    for layout, sl in zip(prs.slide_layouts, slides, strict=True):
        kind = sl["kind"]
        assert layout.name == f"OZL {kind} · {style.LAYOUT_NAME[style.layout_of(sl)]}"
        inserted = prs.slides.add_slide(layout)
        for shapes in (layout.shapes, inserted.shapes):
            assert all(sh.is_placeholder for sh in shapes)
            assert tuple(sh.placeholder_format.type for sh in shapes) == KINDS[kind]
            assert len({sh.placeholder_format.idx for sh in shapes}) == len(shapes)
        for ph in layout.shapes:
            assert ph._element.ph.get("hasCustomPrompt") == "1"
            assert ph.text and not re.search(r"\d", ph.text)
            assert _geometry(inserted.placeholders[ph.placeholder_format.idx]) == _geometry(ph)


def test_rendered_geometry_and_text_style(files):
    potx, preview, ref = files
    layouts = Package.open(potx).main_document_part.presentation.slide_layouts
    for layout, slide, rendered in zip(layouts, Presentation(preview).slides, Presentation(ref).slides, strict=True):
        assert slide.slide_layout.name == layout.name
        labels = [sh for sh in slide.shapes if not sh.is_placeholder]
        assert len(labels) == sum(sh.placeholder_format.type == PH.PICTURE for sh in layout.shapes)
        for ph, original in zip(layout.shapes, rendered.shapes, strict=True):
            sample = slide.placeholders[ph.placeholder_format.idx]
            assert ph.name == original.name
            assert sample.placeholder_format.idx == ph.placeholder_format.idx
            for sh in (ph, sample):
                assert max(abs(a - b) for a, b in zip(_geometry(sh), _geometry(original))) <= 1
            if original.has_table:
                assert [c.text for c in sample.table.iter_cells()] == [c.text for c in original.table.iter_cells()]
                continue
            src, dst = original.text_frame, ph.text_frame
            if ph.placeholder_format.type == PH.PICTURE:
                assert sample.image.content_type == "image/png"
                sample, = [sh for sh in labels if _geometry(sh) == _geometry(ph)]
            assert sample.text == ph.text == original.text
            assert dst.auto_size == MSO_AUTO_SIZE.NONE
            assert dst.word_wrap == src.word_wrap
            assert (dst.margin_left, dst.margin_right, dst.margin_top, dst.margin_bottom) == (
                src.margin_left, src.margin_right, src.margin_top, src.margin_bottom)
            level, = dst._txBody.xpath("./a:lstStyle/a:lvl1pPr")
            para = src.paragraphs[0]
            assert level.get("algn") == para._p.pPr.get("algn")
            assert level.find(qn("a:buNone")) is not None
            pct = level.find(qn("a:lnSpc")).find(qn("a:spcPct"))
            assert int(pct.get("val")) == round(100000 * (para.line_spacing or 1))
            default = level.find(qn("a:defRPr"))
            actual = para.runs[0]._r.rPr
            assert default.get("sz") == actual.get("sz") and default.get("b") == actual.get("b")
            assert default.xpath("./a:solidFill/a:srgbClr/@val") == actual.xpath("./a:solidFill/a:srgbClr/@val")
            for script in ("latin", "ea", "cs"):
                tag = qn(f"a:{script}")
                assert default.find(tag).get("typeface") == actual.find(tag).get("typeface") == deck.FONT


def test_master_style(files):
    master = Package.open(files[0]).main_document_part.presentation.slide_master
    for tag, rgb in (("titleStyle", deck.TITLE_RGB), ("bodyStyle", deck.BODY_RGB)):
        levels = master._element.xpath(f"./p:txStyles/p:{tag}/*")
        assert levels
        for level in levels:
            font = level.find(qn("a:defRPr"))
            assert font.xpath("./a:solidFill/a:srgbClr/@val") == [str(rgb)]
            for script in ("latin", "ea", "cs"):
                assert font.find(qn(f"a:{script}")).get("typeface") == deck.FONT
