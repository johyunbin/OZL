"""[새 슬라이드]에서 고르는 OZL 템플릿과 같은 마스터의 확인용 프레젠테이션.

손 템플릿 사양을 실제로 그린 뒤 도형의 EMU 좌표, 글꼴(동아시아 포함), 크기, 색,
굵기, 정렬, 줄 간격, 여백을 레이아웃으로 옮긴다. 안내 글과 확인본에는 개별 줄의
강조도 남지만 새로 입력하는 본문의 기본값은 첫 글자 서식이다. 특정 구절의 빨강·굵게,
어절별 수동 줄바꿈은 새 글에 자동 적용되지 않는다. 원래 글상자의 크기 자동 조절은
고정 좌표를 위해 끈다. 표의 칸 서식은 확인본에만 있고, 새 표의 행·열은 삽입할 때 정한다.
빈 그림 자리의 안내는 인쇄되지 않으므로 확인본만 회색 그림 위에 같은 안내 글을 얹는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import tempfile
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER as PH
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.opc.constants import CONTENT_TYPE as CT, RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.parts.slide import SlideLayoutPart

from ozl.render import build as renderer
from ozl.render import deck, style, template

OUT = template.ROOT / "private" / "결과물" / "16_템플릿v1"


def _placeholder_type(shape):
    if shape.has_table:
        return PH.TABLE
    if shape.name == "그림 자리":
        return PH.PICTURE
    if shape.name in ("제목", "여는 제목"):
        return PH.TITLE
    return PH.BODY


def _level_style(paragraph):
    """실제 문단/첫 글자에서 새로 입력할 글의 기본값을 만든다."""
    level = deepcopy(paragraph._p.get_or_add_pPr())
    level.tag = qn("a:lvl1pPr")
    level.set("marL", "0")
    level.set("indent", "0")
    if level.find(qn("a:lnSpc")) is None:  # 줄 간격 미지정인 그림 안내: 보통 한 줄
        spacing = etree.SubElement(level, qn("a:lnSpc"))
        etree.SubElement(spacing, qn("a:spcPct"), val="100000")
    etree.SubElement(level, qn("a:buNone"))
    font = deepcopy(paragraph.runs[0]._r.rPr)
    font.tag = qn("a:defRPr")
    level.append(font)
    return level


def _add_placeholder(layout, shape, order):
    kind = _placeholder_type(shape)
    idx = 0 if kind == PH.TITLE else order
    sp = layout.shapes._spTree.add_placeholder(order + 1, shape.name, kind, "horz", "full", idx)
    sp.ph.set("hasCustomPrompt", "1")
    if kind == PH.TABLE:
        # 표 자체가 아닌 삽입 가능한 표 자리. 안내는 견본의 첫 번째 비지 않은 머리칸.
        sp.x, sp.y, sp.cx, sp.cy = shape.left, shape.top, shape.width, shape.height
        source = next(cell.text_frame for cell in shape.table.rows[0].cells if cell.text)
    else:
        sp.replace(sp.spPr, deepcopy(shape._element.spPr))
        source = shape.text_frame

    body = deepcopy(source._txBody)
    body.tag = qn("p:txBody")  # 표의 셀은 a:txBody
    if sp.txBody is not None:
        sp.remove(sp.txBody)
    sp.append(body)
    props = body.bodyPr
    props.autofit = MSO_AUTO_SIZE.NONE
    props.set("anchor", props.get("anchor", "t"))
    for key, margin in (("lIns", source.margin_left), ("tIns", source.margin_top),
                        ("rIns", source.margin_right), ("bIns", source.margin_bottom)):
        props.set(key, str(margin))
    level = _level_style(source.paragraphs[0])
    body.find(qn("a:lstStyle")).append(level)
    return level


def _layout_skeleton(prs):
    blank = prs.slide_layouts.get_by_name("Blank")
    root = deepcopy(blank._element)
    for shape in list(root.cSld.spTree.iter_shape_elms()):
        root.cSld.spTree.remove(shape)
    for ext in root.cSld.xpath("./p:extLst"):  # 기본 레이아웃의 creationId를 복제하지 않는다
        root.cSld.remove(ext)
    root.set("type", "cust")
    for layout in list(prs.slide_layouts):
        prs.slide_layouts.remove(layout)
    return root


def _add_layout(prs, skeleton, name, number):
    master = prs.slide_master
    package = prs.part.package
    root = deepcopy(skeleton)
    root.cSld.set("name", name)
    part = SlideLayoutPart(package.next_partname("/ppt/slideLayouts/slideLayout%d.xml"),
                           CT.PML_SLIDE_LAYOUT, package, root)
    part.relate_to(master.part, RT.SLIDE_MASTER)
    rid = master.part.relate_to(part, RT.SLIDE_LAYOUT)
    master_id = int(prs._element.sldMasterIdLst[0].get("id"))
    entry = etree.SubElement(master._element.sldLayoutIdLst, qn("p:sldLayoutId"), id=str(master_id + number))
    entry.set(qn("r:id"), rid)
    return part.slide_layout


def _make_layouts(prs, slides, source):
    skeleton = _layout_skeleton(prs)
    defaults = {}
    for number, (spec, slide) in enumerate(zip(slides, source.slides, strict=True), 1):
        name = f"OZL {spec['kind']} · {style.LAYOUT_NAME[style.layout_of(spec)]}"
        layout = _add_layout(prs, skeleton, name, number)
        for order, shape in enumerate(slide.shapes, 1):
            level = _add_placeholder(layout, shape, order)
            if shape.name in ("제목", "본문"):
                defaults.setdefault(shape.name, level)

    for tag, name in (("titleStyle", "제목"), ("bodyStyle", "본문")):
        parent = prs.slide_master._element.xpath(f"./p:txStyles/p:{tag}")[0]
        for old in list(parent):
            level = deepcopy(defaults[name])
            level.tag = old.tag
            parent.replace(old, level)


def _fill_picture(slide, target, guide, rendered):
    image = BytesIO()
    Image.new("RGB", (1, 1), tuple(rendered.fill.fore_color.rgb)).save(image, format="PNG")
    picture = target.insert_picture(image)
    picture.line.color.rgb = rendered.line.color.rgb
    label = slide.shapes.add_textbox(guide.left, guide.top, guide.width, guide.height)
    label.name = guide.name + " 안내"
    label._element.replace(label._element.txBody, deepcopy(guide._element.txBody))
    picture._element.addnext(label._element)  # 쪽을 채우는 그림의 캡션보다 뒤에 둔다


def _fill_preview(prs, source):
    for layout, original in zip(prs.slide_layouts, source.slides, strict=True):
        slide = prs.slides.add_slide(layout)
        for guide, rendered in zip(layout.shapes, original.shapes, strict=True):
            target = slide.placeholders[guide.placeholder_format.idx]
            if rendered.has_table:
                table = deepcopy(rendered._element)
                table.nvGraphicFramePr.cNvPr.set("id", str(target.shape_id))
                target._replace_placeholder_with(table)
            elif guide.placeholder_format.type == PH.PICTURE:
                _fill_picture(slide, target, guide, rendered)
            else:
                # 위치는 레이아웃에서 상속. 안내 글은 실제 내용으로 넣어 PDF에도 보이게 한다.
                body = deepcopy(guide._element.txBody)
                if target._element.txBody is not None:
                    target._element.remove(target._element.txBody)
                target._element.append(body)


def _save_template(prs, empty, potx):
    deck.finish_package(prs)
    prs.save(empty)
    with ZipFile(empty) as src, ZipFile(potx, "x") as dst:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "[Content_Types].xml":
                types = etree.fromstring(data)
                main = types.find(f"{{*}}Override[@PartName='{prs.part.partname}']")
                main.set("ContentType", CT.PML_TEMPLATE_MAIN)
                data = etree.tostring(types, encoding="UTF-8", xml_declaration=True, standalone=True)
            dst.writestr(item, data)


def build(out_root: pathlib.Path | None = None, export: bool = True, version: str = "v2") -> dict:
    slides = template.template_spec(version)
    out_root = out_root or (template.OUT_V2 if version == "v2" else OUT)
    problems = template.problems(slides)
    if problems:
        raise ValueError("\n".join(problems))
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y%m%d_%H%M%S")
    prefix = "OZL_덱템플릿_v2" if version == "v2" else "OZL_덱템플릿"
    stem = f"{prefix}_{stamp}"
    out_root.mkdir(parents=True, exist_ok=True)
    potx = out_root / (stem + ".potx")
    preview = out_root / (stem + "_확인.pptx")
    for target in (potx, preview, preview.with_suffix(".pdf"), out_root / (preview.stem + "_png")):
        if os.path.lexists(target):
            raise FileExistsError(f"이미 있다 — 덮어쓰지 않는다: {target}")

    with tempfile.TemporaryDirectory(dir=out_root) as tmp:
        work = pathlib.Path(tmp)
        renderer.build_pptx(slides, {}, {}, work / "render.pptx", appendix=False)
        source = Presentation(work / "render.pptx")
        prs = deck.new_deck()
        _make_layouts(prs, slides["slides"], source)
        deck.clear_template_props(prs)
        prs.core_properties.title = "OZL 덱 템플릿"
        _save_template(prs, work / "empty.pptx", work / potx.name)
        _fill_preview(prs, source)
        deck.finish_package(prs)
        prs.save(work / preview.name)
        # 같은 초의 다른 실행과 경합해도 기존 파일을 대체하지 않는다.
        os.link(work / potx.name, potx)
        os.link(work / preview.name, preview)

    info = {"potx": str(potx), "pptx": str(preview)}
    if export:
        pdf, pngs = deck.to_pdf_png(preview)
        if not pdf or len(pngs) != len(prs.slides):
            raise RuntimeError(f"내보내기 미완료: PDF {pdf}, PNG {len(pngs)}/{len(prs.slides)}장")
        info.update(pdf=str(pdf), pngs=len(pngs))
    return info


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ozl.render potx", description=__doc__)
    parser.add_argument("--template", choices=("v1", "v2"), default="v2", help="레이아웃 템플릿 버전")
    parser.add_argument("--out", type=pathlib.Path, help="출력 폴더")
    parser.add_argument("--no-export", action="store_true", help="확인본의 PDF와 PNG는 만들지 않는다")
    args = parser.parse_args(argv)
    print(build(args.out, not args.no_export, args.template))
    return 0
