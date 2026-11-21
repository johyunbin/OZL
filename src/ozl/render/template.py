"""손 작업용 템플릿 — v1은 종류마다 한 장, v2는 우 그림·좌 글을 더한 13장. 노트에는 쓰는 때와 분량 기준을 적는다.

python -m ozl.render.template [--template v1|v2] [--out <폴더>] [--no-export]

- 견본집(style.samples)과 같은 그리기 경로(build.build_pptx, style: syuka)를 쓴다. 글꼴, 색, 크기, 좌표는 렌더러의 값 그대로다
  (맑은 고딕 26pt, 줄 간격 1.5, 제목 #C00000, 좌 그림 4.20×4.12in — private/data/derived/style/style-guide.md).
- 화면 글은 자리 안내뿐이다. 숫자를 쓰지 않는다(숫자는 검증 기록과 이어져야 하는 화면 수치로 읽힌다). 분량 숫자는 노트에 적는다.
- 사용자는 파워포인트에서 장을 복제해 글을 바꾸고 회색 자리를 그림으로 바꿔 쓴다. 산출물은 private/결과물/ 아래 v1은 12_템플릿/, v2는 20_템플릿v2/에 둔다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
from copy import deepcopy

from ozl import paths as ozlpaths
from ozl.render import design_v2 as V2
from ozl.render import spec as S
from ozl.render import style as ST

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = ozlpaths.at("templates", "12_템플릿")
OUT_V2 = OUT.parent / "20_템플릿v2"

TITLE = "여기에 제목: 한 문장으로"
IMG = {"what": "여기에 그림", "source": "사진, 차트, 원문 캡처 가운데 하나"}
WIDE = {"what": "여기에 넓은 그림", "source": "차트, 지도, 흐름도처럼 가로로 긴 것"}
NEEDS_SLOT = ("full_picture", "image_text", "number", "quote_translation", "image_stack", "photo_caption", "capture_full", "image_pair")

# (사양의 장, 노트 — 쓰는 때 / 분량 기준)
SLIDES: list[tuple[dict, str]] = [
    ({"kind": "full_picture", "stage": "여는 장", "image": {"what": "여기에 쪽을 채우는 그림", "source": "제목 없이 그림만 둔다"},
      "caption": "여기에 한마디(빼도 된다)", "seconds": 12},
     "쓰는 때: 편의 첫 장(원본 110편 가운데 85편이 제목 없는 화면으로 연다), 여담의 한마디 장.\n"
     "분량: 그림 한 장이 쪽을 채운다. 제목과 본문을 두지 않는다. 한마디는 그림 안 아래 한 줄(빼도 된다). 10~15초."),
    ({"kind": "title_hook", "stage": "우회 도입", "title": "여기에 물음: 이 편은 무엇을 묻나?", "sub": "여기에 부제 한 줄", "seconds": 18},
     "쓰는 때: 여는 장 다음, 이 편의 중심 질문을 세울 때. 첫 다섯 장의 제목, 부제, 한마디 가운데 하나는 물음형이어야 한다.\n"
     "분량: 제목은 물음표로 끝나는 한 문장, 공백 빼고 16~25자. 부제 한 줄. 15~20초."),
    ({"kind": "image_text", "stage": "배경", "title": TITLE, "image": IMG,
      "body": ["여기에 본문 첫 줄", "어절 단위로 줄을 바꾼다", {"text": "핵심 구절은 빨강 굵게", "red": True, "bold": True}, "한 장에 한 마디만 한다", "본문은 다섯 줄 안팎"],
      "seconds": 26},
     "쓰는 때: 기본 장. 원본 장의 67%가 이 모양(좌 그림 + 우 글)이다. 배경, 전개, 근거 수치 어디에나 쓴다.\n"
     "분량: 제목 한 문장 16~25자(원본 중앙값 21자). 본문 5~6줄이 중앙값이고, 이 글상자에는 7줄까지 들어간다(원본 전체의 상한 10줄은 그림 없는 장까지 센 값). 한 줄 한글 15~17자, 어절 단위로 수동 줄바꿈.\n"
     "그림 자리 4.20×4.12in(왼쪽 0.96in, 위 1.93in). 강조는 빨강(#C00000), 핵심 구절만 굵게. 20~30초, 한 장 57초를 넘기지 않는다."),
    ({"kind": "number", "stage": "근거 수치", "title": TITLE, "image": IMG,
      "number": {"value": "여기에 수치", "label": "여기에 수치의 뜻 한 줄"}, "seconds": 24},
     "쓰는 때: 규모를 한 수치로 보일 때(근거 수치 단계). 모양은 좌 그림 + 우 글과 같다.\n"
     "분량: 큰 수치 하나와 뜻 한 줄. 수치는 인용한 검증 기록의 표기 그대로 쓰고 단위와 기준 시점을 붙인다. 20~30초."),
    ({"kind": "quote_translation", "stage": "전개", "title": TITLE, "image": IMG,
      "en": "Original sentence from the source goes here.", "ko": "여기에 한글 번역(빨강)", "seconds": 22},
     "쓰는 때: 외신이나 원문을 인용할 때. 원본 장의 46%에 영문 원문 줄이 있다(외신이 자료의 45%).\n"
     "분량: 영문 원문 한두 줄(검정) 바로 아래 한글 번역(빨강), 핵심 구절만 굵게. 원문은 대조한 대목 그대로. 20~30초."),
    ({"kind": "image_stack", "stage": "전개", "title": TITLE, "image": WIDE,
      "body": ["여기에 본문 한 줄", {"text": "세 줄까지 쓴다", "red": True}], "seconds": 25},
     "쓰는 때: 가로로 긴 그림(추세 차트, 지도, 연표)을 보일 때. 원본 장의 13.5%(그림 위아래 + 글).\n"
     "분량: 위 넓은 그림 11.41×2.85in, 아래 본문 1~3줄. 20~30초."),
    ({"kind": "photo_caption", "stage": "전개", "title": TITLE, "image": WIDE, "caption": "여기에 그림 설명(두 줄까지)", "seconds": 20},
     "쓰는 때: 사진이나 장면 한 장을 크게 보일 때. 원본 장의 5.0%(그림 위주).\n"
     "분량: 넓은 그림 11.41×3.70in, 아래 설명 두 줄까지. 15~25초."),
    ({"kind": "capture_full", "stage": "전개", "title": TITLE,
      "image": {"what": "여기에 원문 화면 한 장", "source": "대조한 문구가 다 보이게 자른다"}, "seconds": 22},
     "쓰는 때: 기사, 보고서, 공시의 원문 화면을 그대로 보일 때(인용 장). 그림 위주 모양.\n"
     "분량: 제목 한 줄과 원문 캡처 한 장뿐, 본문을 두지 않는다. 대조한 문구가 자리 안에 다 들어가야 하고, 글자가 7pt 아래로 작아지면 안 된다. 15~30초."),
    ({"kind": "image_pair", "stage": "비교", "title": TITLE,
      "pair": [{"image": {"what": "여기에 왼쪽 그림", "source": "비교의 한쪽"}, "caption": "여기에 왼쪽 설명"},
               {"image": {"what": "여기에 오른쪽 그림", "source": "비교의 다른 쪽"}, "caption": "여기에 오른쪽 설명"}], "seconds": 25},
     "쓰는 때: 두 나라, 두 시기, 두 회사를 나란히 견줄 때(비교 단계). 원본 장의 2.7%.\n"
     "분량: 그림 두 장과 각 설명 한두 줄. 20~30초."),
    ({"kind": "compare_table", "stage": "비교", "title": TITLE,
      "table": {"header": ["", "여기에 갑", "여기에 을"], "rows": [["여기에 항목", "값", "값"], ["여기에 항목", "값", "값"]]}, "seconds": 26},
     "쓰는 때: 여러 항목을 칸으로 견줄 때. 원본은 표를 그림으로 붙이는 일이 많아, 본편의 5%(30분에 3장)를 넘기지 않는다.\n"
     "분량: 열 셋, 행 두세 개. 칸의 수치는 검증 기록의 표기 그대로. 20~30초."),
    ({"kind": "quote_line", "stage": "반전", "title": TITLE,
      "quote": {"text": "여기에 인용 한 문장", "by": "여기에 말한 사람과 자리"}, "seconds": 18},
     "쓰는 때: 한 사람의 한마디로 흐름을 뒤집거나 정리할 때(반전, 시사점). 글만 있는 모양.\n"
     "분량: 인용 한 문장과 말한 사람. 원문 대조가 된 문장만 쓴다. 15~20초."),
    ({"kind": "closing", "stage": "닫는 장", "title": TITLE,
      "body": ["여기에 전망이나 열린 질문", "요약을 되풀이하지 않는다", "두세 줄로 닫는다"], "seconds": 22},
     "쓰는 때: 편의 끝 한두 장. 원본은 요약 없이 전망이나 열린 질문으로 닫는다.\n"
     "분량: 두세 줄. 글만 있는 장은 본편의 20%를 넘기지 않는다(원본 6.0%). 15~25초."),
]

COMMON_NOTE = ("\n\n공통: 제목만 이어 읽어도 줄거리가 되게 쓴다. 구성 분석 25편의 제목에서 접속어(그런데, 그러나, 결국)로 여는 제목이 17%, 물음형이 11%였다"
               "(110편 집계에서는 물음형 9.4%). "
               "말로만 할 것은 화면에 쓰지 않고 이 노트(러닝시트)에 적는다. 장을 복제해 쓰고, 회색 자리는 그림으로 바꾼다.")


# 손으로 복제할 때 모양을 고르는 기준. 수치는 모두 검사와 같은 원본 집계에서 꺼낸다.
_V2_USAGE = {
    "full_picture": ("hook", "제목 없는 그림 한 장으로 연다. 여담의 한마디 장에도 쓴다."),
    "title_hook": ("hook", "그림 없는 표지 장에 이 편의 질문을 둔다. 첫 다섯 장 안에 물음 하나."),
    "image_text": ("background", "배경을 설명하는 그림 옆에 독자가 알아야 할 사실을 쓴다."),
    "number": ("data", "규모를 보여 줄 수치에 단위와 시점을 붙인다. 그림 자리는 도표에 쓴다."),
    "quote_translation": ("development", "원문과 대조한 번역을 짝지어 놓고 번역 문단을 빨강으로 구분한다."),
    "image_stack": ("data", "가로로 긴 도표는 위에 놓고 그 아래에 읽는 법을 적는다."),
    "photo_caption": ("development", "장면을 크게 보이고 그림 아래에 짧은 설명을 단다."),
    "capture_full": ("development", "기사, 보고서, 공시의 원문 화면을 글자가 읽히는 크기로 그대로 보인다."),
    "image_pair": ("comparison", "비교할 두 대상을 나란히 놓고 서로 다른 점을 같은 기준으로 짚는다."),
    "compare_table": ("comparison", "여러 대상을 같은 항목으로 견줄 때 쓴다. 단위와 기준 시점을 맞춘다."),
    "quote_line": ("turn", "흐름이 달라지는 지점에서 한 사람의 말과 출처를 보인다."),
    "closing": ("closing", "요약을 되풀이하지 않고 전망이나 질문으로 닫는다."),
}


def _v2_note(sl):
    key, usage = _V2_USAGE[sl["kind"]]
    stage = V2.STAGE_MIX[key]
    if sl.get("side") == "right":
        usage = "배경 설명을 왼쪽에 놓고 그 설명이 가리키는 그림을 오른쪽에 둔다."
    if key == "hook":
        usage += f" 원본 여는 장의 {stage.pictures['none']:.1%}는 그림 없는 장이다."
    if key == "closing":
        usage += f" 원본 닫는 장의 {stage.pictures['drawing']:.1%}는 그린 그림 엔딩 화면이다."
    return (f"쓰는 때: {V2.STAGE_NAME[key]} 단계. {usage}\n"
            f"원본 장 모양 상위: {V2.top_text(stage.layouts, V2.LAYOUT_NAME)}.\n"
            f"원본 그림 종류 상위: {V2.top_text(stage.pictures, V2.PICTURE_NAME)}.\n"
            f"원본 빨강 본문 줄: 이 단계 {stage.red:.1%}(전체 {V2.OVERALL_RED:.1%}).")


def _amount(v1_note: str) -> str:
    """v1 노트의 분량 안내(둘째 줄부터 — 글자 수, 줄 수, 그림 자리 크기, 초)를 그대로 잇는다."""
    amount = v1_note.split("\n", 1)[1] if "\n" in v1_note else ""
    # v1 노트의 옛 경고선(글만 장 20%)은 템플릿 v1·v2 의 실패선 10%(style.V1_TEXT_ONLY_MAX)로 바꿔 적는다
    return amount.replace("글만 있는 장은 본편의 20%를 넘기지 않는다(원본 6.0%)",
                          f"글만 있는 장은 전체의 {ST.V1_TEXT_ONLY_MAX:.0%}를 넘기지 않는다(템플릿 실패선)")


def _slides_v2():
    slides = []
    for sl, v1_note in SLIDES:
        sl = {**sl, "stage": V2.STAGE_NAME[_V2_USAGE[sl["kind"]][0]]}   # 사양의 단계를 노트가 설명하는 단계와 맞춘다
        slides.append((sl, _v2_note(sl) + "\n" + _amount(v1_note)))
        if sl["kind"] == "image_text":
            right = {**sl, "side": "right"}
            slides.append((right, _v2_note(right) + "\n" + _amount(v1_note).replace("(왼쪽 0.96in, 위 1.93in)", "(좌우 거울 자리)")))
    return slides


SLIDES_V2 = _slides_v2()


def _common_v2():
    front, middle, back = V2.RED_BY_THIRD
    lengths = []
    for minutes in (30, 40):
        target, _ = V2.v2_expected(minutes)
        lengths.append(f"{minutes}분 약 {round(target / 5) * 5}장")
    return (f"\n\n공통: 원본 본문 줄의 {V2.OVERALL_RED:.1%}가 빨강이다. "
            f"근거 수치({V2.STAGE_MIX['data'].red:.1%})와 해법({V2.STAGE_MIX['solution'].red:.1%})은 낮게 둔다. "
            f"빨강은 줄의 뒤쪽에 더 자주 쓴다(앞 삼분의 일 {front:.1%}, 가운데 {middle:.1%}, 뒤 {back:.1%}).\n"
            f"장수: 전체 직선은 1분 약 {V2.SLIDES_PER_MINUTE:.2f}장. 길이별 기준은 {', '.join(lengths)}.\n"
            + "\n".join(f"{branch}: {V2.skeleton_order(branch)}" for branch in V2.SKELETONS))


def _slides(version):
    if version not in ("v1", "v2"):
        raise ValueError(f"모르는 손 템플릿: {version}")
    return SLIDES_V2 if version == "v2" else SLIDES


def template_spec(version="v1") -> dict:
    sp = {"card_id": "템플릿", "style": "syuka", "slides": [deepcopy(s) for s, _ in _slides(version)]}
    if version == "v2":
        sp["template"] = version
    return sp


def problems(spec: dict) -> list[str]:
    from ozl.render import build as B
    out = []
    for i, sl in enumerate(spec["slides"], 1):
        out += [f"{i}쪽: {e}" for e in B.layout_problems(sl)]
        # 화면 글과 말에 숫자를 두지 않는다(숫자는 검증 기록과 이어져야 하는 화면 수치로 읽힌다)
        out += [f"{i}쪽: 숫자를 쓰지 않는다 — '{t}'" for t in S.visible_text(sl) + S.spoken_text(sl) if re.search(r"\d", t)]
        # 그림 자리가 있어야 하는 종류는 자리마다 회색 자리(image)가 있어야 한다
        if sl["kind"] in NEEDS_SLOT:
            views = S.slot_views(sl)
            want = 2 if sl["kind"] == "image_pair" else 1
            if len(views) != want or any(S.visual_of(v) != "image" for _, v in views):
                out.append(f"{i}쪽: {sl['kind']} 의 그림 자리 {want}개가 회색 자리(image)로 있어야 한다")
    kinds = [s["kind"] for s in spec["slides"]]
    expected = list(S.KINDS)
    if spec.get("template") == "v2":
        expected.append("image_text")
        sides = [sl.get("side", "left") for sl in spec["slides"] if sl["kind"] == "image_text"]
        if sides != ["left", "right"]:
            out.append("image_text 는 좌 그림과 우 그림이 한 장씩 차례로 있어야 한다")
    if sorted(kinds) != sorted(expected):
        out.append(f"종류가 KINDS 와 다르다: {sorted(set(S.KINDS) ^ set(kinds))}")
    return out


def build(out_root: pathlib.Path | None = None, export: bool = True, version: str = "v2") -> dict:
    from pptx import Presentation

    from ozl.render import build as B
    from ozl.render import deck
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    spec = template_spec(version)
    out_root = out_root or (OUT_V2 if version == "v2" else OUT)
    out_root.mkdir(parents=True, exist_ok=True)
    stem = "손템플릿_v2" if version == "v2" else "손템플릿"
    pptx = out_root / f"{stem}_{ts}.pptx"
    if pptx.exists():
        raise SystemExit(f"{pptx} 가 이미 있다 — 덮어쓰지 않는다")
    probs = problems(spec)
    if probs:
        raise SystemExit("템플릿 사양 검사 실패:\n" + "\n".join(probs))
    B.build_pptx(spec, {}, {}, pptx, appendix=False)
    prs = Presentation(str(pptx))
    shares = V2.LAYOUT_SHARE if version == "v2" else ST.LAYOUT_SHARE
    common = _common_v2() if version == "v2" else COMMON_NOTE
    for sld, (sl, note) in zip(prs.slides, _slides(version), strict=True):
        lay = ST.layout_of(sl)
        head = f"[{sl['kind']} · 원본 장 모양 '{ST.LAYOUT_NAME[lay]}' {shares.get(lay, 0) * 100:.1f}%]\n"
        tf = sld.notes_slide.notes_text_frame   # notes_slide 는 없으면 만들어 준다(python-pptx)
        if tf is None:
            raise SystemExit("노트 글상자를 찾지 못했다")
        tf.text = head + note + common
    prs.core_properties.title = "슈카 덱 손 템플릿"
    deck.set_template_text_defaults(prs)
    deck.finish_package(prs)
    prs.save(str(pptx))
    info = {"pptx": str(pptx), "slides": len(spec["slides"])}
    if export:
        pdf, pngs = deck.to_pdf_png(pptx)
        info.update(pdf=str(pdf) if pdf else None, pngs=len(pngs))
    return info


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", choices=("v1", "v2"), default="v2", help="손 템플릿 버전")
    parser.add_argument("--out", type=pathlib.Path, help="출력 폴더")
    parser.add_argument("--no-export", action="store_true", help="PDF와 PNG는 만들지 않는다")
    args = parser.parse_args(argv)
    print(build(args.out, not args.no_export, args.template))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
