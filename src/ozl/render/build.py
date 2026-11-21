#!/usr/bin/env python3
"""덱 사양 → 초안 pptx(+ 출처 부록 · 시각물 출처·검증표 · 발표자 노트) → 파워포인트 PDF → 쪽별 PNG → 러닝시트 md+PDF.

결정적 코드다. 문장은 사양에 있는 것만 옮기고 새로 짓지 않는다. 숫자 검사는 spec.check 가 맡고, 통과하지 못한 사양은 만들지 않는다.
글은 어절 단위로 미리 줄을 나눠 줄바꿈을 넣고 글상자의 자동 줄바꿈은 끈다(파워포인트가 한글 낱말 가운데서 끊지 않게).
그림은 내려받지 않는다 — 회색 자리에 '무엇을 · 어느 공식 출처에서'만 적거나, 검수 대장(사양 pictures)에 오른 로컬 그림 파일을 넣는다.
엄격 모드 빌드는 밈 그림을 빼고(pictures.drop_memes) 뺀 것을 빌드 출력과 러닝시트 머리에 적는다.
막는 그림(판정 '비공개 판에서만' 또는 권리 확인 대기)이 든 사양은 엄격 모드에서 두 판을 같은 타임코드로 함께 낸다(pictures.py 머리말의 「두 판과 공개 차단」):
  private/outputs/decks/drafts/<card_id>_<ts>_비공개판/ 과 <card_id>_<ts>_바꾼판/ — 판마다 pptx · PDF · 쪽 PNG · 러닝시트 · 링크 목록(style: syuka) ·
  그림 검수 대장(「바꾼 장」 표) · 공개_가부.json(edition · pair · swaps) · 그 판의 사양 사본(spec_<ts>_<판>.yaml).
  한 판이라도 검사에 실패하면 어느 폴더도 만들지 않는다. 끝에 public_check 가 비공개판 1 · 바꾼판 0 이 아니면 멈춘다.
  비공개판을 만들면 막는 그림 파일과 그 판의 pptx · PDF · 막는 그림이 든 쪽의 PNG 의 sha256 을 비공개 등록 대장(registry_file)에 덧붙인다
  (막는 그림이 든 초안 모드의 연습용 판도 같다). pptx 를 쓰기 시작한 뒤로는 빌드가 예외로 멈춰도(내보내기 시간 초과, 도구 없음 등)
  그때까지 만든 파일을 등록한다.
막는 그림도 swap 도 없는 사양은 지금까지와 같은 폴더 하나, 같은 파일이 나온다.
pptx 는 저장 직전에 deck.finish_package 를 거친다(문서 통계를 실제 값으로, 틀의 축소 그림과 인쇄 설정 파일을 뗀다). 그 뒤로는 pptx 를 다시 쓰지 않는다.
style: syuka 빌드는 차트 그림 안의 '출처:' 줄을 그리지 않는다(환산식이 있으면 '환산: …' 줄만 — charts.render_chart 의 source_line).
광고 회차(사양 맨 위 sponsorship)는 구간의 장마다 오른쪽 위에 띠(표시 문구 · 광고주)를 그리고, 러닝시트 머리에 광고 구간 줄을,
링크 목록에 「광고주 제공 자료」 절을 둔다(검사는 spec.sponsorship_errors).

    python -m ozl.render build <사양.yaml> [--edition 비공개판|바꾼판]   # private/outputs/decks/drafts/<card_id>_<ts>[_<판>]/
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import pathlib
import subprocess
import tempfile
import sys
from dataclasses import dataclass, field
from functools import cache

import yaml
from lxml import etree
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from ozl import paths as ozlpaths
from ozl.render import deck
from ozl.render import spec as S
from ozl.render.pictures import file_sha256
from ozl.research import cards as C

ROOT = S.ROOT
DRAFTS = ozlpaths.at("decks", "drafts")
MD2PDF = pathlib.Path.home() / "Claude" / "tools" / "md2pdf.py"

EMU_IN = 914400
GREY = RGBColor(0x66, 0x66, 0x66)
LIGHT = RGBColor(0x88, 0x88, 0x88)
SW, SH = deck.W / EMU_IN, deck.H / EMU_IN           # 13.333 × 7.5 in
ML = deck.M / EMU_IN                               # 좌우 여백 0.96in
FOOT_TOP = 6.92                                    # 출처 각주 줄 윗변(in)
BODY_BOTTOM = 6.85                                 # 본문 글상자가 내려갈 수 있는 끝(in)
PAD = 0.05                                         # 글상자 안쪽 좌우 여백(in · deck._text 와 같다)
TABLE_SIZE = 22                                    # 비교표 글자 크기(pt) — 표 양식은 미확정(토큰 '미확정' 항목)
APPX_SIZE = 10                                     # 부록 표 글자 크기(pt)
NO_GRID_STYLE = "{5940675A-B579-460E-94D1-54222C63F5DA}"  # 파워포인트 '스타일 없음, 표 눈금' — 기본 파랑 표 스타일을 쓰지 않는다


def _in(emu) -> float:
    return emu / EMU_IN


# ── 배치 계획(검사와 생성이 같은 계획을 쓴다) ─────────────────────────────
@dataclass
class Para:
    text: str
    color: RGBColor = deck.BODY_RGB
    bold: bool = False
    emph: list[str] = field(default_factory=list)  # 이 낱말들은 빨강 굵게
    lines: list[tuple[int, int]] = field(default_factory=list)
    marks: dict = field(default_factory=dict)      # 글자 자리 → 그 글자 뒤에 붙일 링크 번호(작은 회색 위첨자 · style: syuka). 비면 종전 그대로


SUP_RATIO = 0.6      # 링크 번호 위첨자 크기 = 글자 크기 × 0.6(8~16pt). 파워포인트는 위첨자를 이 크기보다 크게 그리지 않는다 — 폭 계산이 넉넉한 쪽이다
SUP_BASELINE = "30000"


def sup_size(size: float) -> float:
    return min(16.0, max(8.0, round(size * SUP_RATIO)))


def para_mask(p: Para):
    """(줄 나눔 마스크, 폭 함수). 링크 번호가 없으면 종전 그대로(굵기 마스크와 S.measure). 있으면 번호가 붙는 글자의 폭에 위첨자 폭을 더한다
    — 줄 나눔과 넘침 검사가 번호까지 본다."""
    base = [m or p.bold for m in S.emphasis_mask(p.text, p.emph)]
    if not p.marks:
        return base, S.measure
    mask = [(b, p.marks.get(i), i if i in p.marks else -1) for i, b in enumerate(base)]

    def fn(t: str, size: float, m) -> float:
        return S.measure(t, size, m[0]) + (S.measure(m[1], sup_size(size)) if m[1] else 0.0)
    return mask, fn


@dataclass
class Box:
    name: str
    left: float
    top: float
    width: float
    height: float
    paras: list[Para]
    size: float = deck.SIZE
    spacing: float = deck.LINE
    align: object = PP_ALIGN.LEFT
    max_lines: int | None = None
    fill: RGBColor | None = None   # 글상자 바탕(full_picture 의 그림 위 한마디). None 이면 바탕 없음

    @property
    def line_h(self) -> float:  # pt — 파워포인트 배수 줄 간격의 기준은 글자 크기의 1.2배
        return self.size * 1.2 * self.spacing

    def capacity(self) -> int:
        if self.max_lines is not None:
            return self.max_lines
        return max(1, int((self.height * 72 - 0.1 * 72) / self.line_h + 0.15))

    def layout(self) -> int:
        width_pt = (self.width - 2 * PAD) * 72 * 0.98  # 2% 여유 — 폰트 힌팅 차이로 줄 끝이 넘지 않게
        n = 0
        for p in self.paras:
            mask, fn = para_mask(p)
            p.lines = S.wrap(p.text, width_pt, self.size, mask, fn) or [(0, 0)]
            n += len(p.lines)
        return n

    def problems(self) -> list[str]:
        out = []
        n = self.layout()
        width_pt = (self.width - 2 * PAD) * 72
        for p in self.paras:
            mask, fn = para_mask(p)
            for a, b in p.lines:
                wpt = sum(fn(p.text[i], self.size, mask[i]) for i in range(a, b))
                if wpt > width_pt:
                    out.append(f"{self.name}: 어절 '{p.text[a:b]}' 이 줄 폭보다 길다")
        if n > self.capacity():
            out.append(f"{self.name}: {n}줄 — 글상자에 {self.capacity()}줄까지 들어간다(줄 넘침)")
        return out


@dataclass
class Img:
    left: float
    top: float
    width: float
    height: float
    what: str
    source: str
    caption: str = ""
    kind: str = "slot"  # slot = 종전 회색 자리(image) · chart = charts.render_chart PNG · capture = 기록의 원문 화면 그림 · picture = 검수 대장의 그림 파일
    ref: str = ""       # capture 의 claim_id · picture 의 그림 번호
    slot: int = -1      # image_pair 의 자리 번호(0 왼쪽 · 1 오른쪽). 그 밖의 종류는 -1


@dataclass
class Table:
    left: float
    top: float
    width: float
    widths: list[float]
    header: list[str]
    rows: list[list[str]]
    size: float = TABLE_SIZE
    emph: list[str] = field(default_factory=list)
    max_bottom: float = BODY_BOTTOM
    words_whole: bool = False  # 어절이 칸 폭을 넘으면 실패시키고, 수동 어절 줄바꿈 뒤 자동 줄바꿈을 끈다
    free_cols: frozenset = frozenset()  # 예외 칸(주소): 파워포인트가 글자 단위로 접게 둔다

    def whole(self, j: int) -> bool:
        return self.words_whole and j not in self.free_cols

    def cell_width_pt(self, w: float) -> float:
        return (w - 0.3) * 72  # 칸 안쪽 여백 0.16in + 파워포인트 줄바꿈 여유

    def row_heights(self) -> list[float]:
        """행 높이(in) 어림 — 파워포인트는 글이 넘치면 행을 늘리므로 미리 세어 쪽을 넘는지 본다."""
        out = []
        for row in [self.header] + self.rows:
            n = 1
            for j, (txt, w) in enumerate(zip(row, self.widths)):
                width_pt = self.cell_width_pt(w)
                lines = 0
                for part in str(txt).split("\n"):
                    ls = S.wrap(part, width_pt, self.size) or [(0, 0)]
                    if self.whole(j) and not _has_url(part):
                        lines += len(ls)
                        continue
                    for a, b in ls:  # 공백 없는 긴 덩어리(주소)는 파워포인트가 글자 단위로 접는다
                        lines += max(1, math.ceil(S.measure(part[a:b], self.size) / width_pt))
                n = max(n, lines)
            out.append(n * self.size * 1.2 / 72 + 0.12)
        return out

    def problems(self, name="표") -> list[str]:
        out = []
        if self.words_whole:
            for row in [self.header] + self.rows:
                for j, (txt, w) in enumerate(zip(row, self.widths)):
                    if not self.whole(j):
                        continue
                    for word in str(txt).split():
                        if _is_url(word):
                            continue  # 주소는 낱말이 아니라 파워포인트가 글자 단위로 접게 둔다(그 칸만 자동 줄바꿈을 켠다)
                        bold = row is self.header
                        if S.measure(word, self.size, bold) > self.cell_width_pt(w):
                            out.append(f"{name}: 어절 '{word}' 이 칸 폭보다 길다(낱말이 끊긴다 — 칸 너비를 넓히거나 줄여 쓴다)")
        if out:
            return out
        h = sum(self.row_heights())
        if self.top + h > self.max_bottom + 0.01:
            return [f"{name}: 표 높이 {h:.2f}in — 쪽 아래로 넘친다({self.top + h:.2f} > {self.max_bottom:.2f}in)"]
        return []


def _is_url(word: str) -> bool:
    return word.startswith(("http://", "https://")) or "://" in word


def _has_url(text: str) -> bool:
    return any(_is_url(w) for w in str(text).split())


@dataclass
class Plan:
    boxes: list[Box] = field(default_factory=list)
    imgs: list[Img] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)


def _mk(sl, *key) -> dict:
    """그 칸의 링크 번호 표시(spec.link_plan → spec.with_links). 없으면 빈 사전(옛 규칙)."""
    return dict((((sl or {}).get(S.LINKS_KEY) or {}).get("inline") or {}).get(tuple(key)) or {})


def _body_paras(items, emph, sl=None) -> list[Para]:
    out = []
    for k, it in enumerate(items or []):
        if isinstance(it, dict):
            out.append(Para(str(it.get("text", "")), deck.EMPH_RGB if it.get("red") else deck.BODY_RGB, bool(it.get("bold")), list(emph or []),
                            marks=_mk(sl, "body", k)))
        else:
            out.append(Para(str(it), emph=list(emph or []), marks=_mk(sl, "body", k)))
    return out


def _title_box(sl) -> Box:
    left = _in(deck.TITLE_LEFT)
    return Box("제목", left, _in(deck.TITLE_TOP), SW - left - ML, _in(deck.px(60)), [Para(str(sl["title"]), deck.TITLE_RGB, marks=_mk(sl, "title"))],
               spacing=1.0, max_lines=1)


def _img(sl, left, top, width, height, slot: int = -1, caption: bool = True) -> Img | None:
    """그림 자리 하나. caption=False 면 image.caption 을 그림 밑에 따로 그리지 않는다(설명 칸이 따로 있는 종류)."""
    v = S.visual_of(sl)
    if v == "chart" and isinstance(sl["chart"], dict):
        ch = sl["chart"]
        return Img(left, top, width, height, str(ch.get("title", "")), str(ch.get("source", "")), kind="chart", slot=slot)
    if v == "capture":
        return Img(left, top, width, height, "원문 화면", "", kind="capture", ref=str(sl["capture"]).strip(), slot=slot)
    if v == "picture":
        return Img(left, top, width, height, "그림 파일", "", kind="picture", ref=str(sl["picture"]).strip(), slot=slot)
    im = sl.get("image")
    if not im or not isinstance(im, dict):
        return None
    return Img(left, top, width, height, str(im.get("what", "")), str(im.get("source", "")), str(im.get("caption") or "") if caption else "", slot=slot)


# 새 종류의 자리(in) — 제목 줄 아래부터 출처 각주(FOOT_TOP) 위까지
FULL_TOP, FULL_BOTTOM = 1.45, 6.40      # capture_full: 원문 캡처 자리(아래 0.4in 는 호스트 표기 줄)
WIDE_TOP, WIDE_H = 1.50, 3.70           # photo_caption · image_pair: 그림 자리(아래 0.45in 는 그림 밑 표기 줄)
CAPTION_TOP, CAPTION_H = 5.65, 1.20     # photo_caption · image_pair: 설명 글상자(두 줄까지)
PAIR_GAP = 0.40                         # image_pair 두 자리 사이
# 2026-11-15 새 종류(style: syuka 덱에서 쓰려고 더했다 — 옛 종류의 자리는 그대로)
BLEED_L, BLEED_T, BLEED_B = 0.35, 0.30, 0.62     # full_picture: 그림 자리 왼쪽·위 띄움, 아래 띄움(그림 밑 표기 두 줄 자리)
BLEED_CAP_H, BLEED_CAP_UP = 0.62, 0.22          # full_picture: 그림 안 아래 한마디 글상자 높이, 그림 자리 아래 끝에서 띄움
STACK_TOP, STACK_H = 1.45, 2.85                 # image_stack: 넓은 그림 자리(아래 0.45in 는 그림 밑 표기 줄)
STACK_BODY_TOP = 4.80                           # image_stack: 아래 글상자 윗변 — BODY_BOTTOM 까지 26pt 1.5줄로 3줄


CORNER_SIZE = 11        # 그림 자리·표 귀퉁이 링크 번호(pt)
CORNER_W, CORNER_H = 1.6, 0.20


def _corner_box(label: str, right: float, top: float) -> Box:
    return Box("링크 번호", right - CORNER_W, top, CORNER_W, CORNER_H, [Para(label, LIGHT)], size=CORNER_SIZE, spacing=1.0, align=PP_ALIGN.RIGHT, max_lines=1)


# 광고 구간의 띠 — 구간의 장마다 오른쪽 위에 '표시 문구 · 광고주'(어두운 바탕에 흰 글씨). 제목 줄(윗변 0.68in) 위의 빈 띠에 둔다.
BAND_NAME = "광고 띠"
BAND_TOP, BAND_H = 0.14, 0.38
BAND_SIZE = 14
BAND_MAX_W = 6.0                                  # 이보다 긴 글은 두 줄이 되어 넘침 검사에 걸린다(표시 문구나 광고주 이름을 줄인다)
BAND_FILL = RGBColor(0x33, 0x33, 0x33)
BAND_TEXT = RGBColor(0xFF, 0xFF, 0xFF)


def sponsor_band_box(label: str) -> Box:
    """광고 띠 글상자. 폭은 글 폭에 맞추고(BAND_MAX_W 까지) 오른쪽 여백에 붙인다. 한 줄 — 넘치면 Box.problems 가 알린다."""
    need = S.measure(label, BAND_SIZE, True) / 72 / 0.98 + 2 * PAD + 0.24
    w = min(BAND_MAX_W, need)
    return Box(BAND_NAME, SW - ML - w, BAND_TOP, w, BAND_H, [Para(label, BAND_TEXT, True)], size=BAND_SIZE, spacing=1.0, align=PP_ALIGN.CENTER,
               max_lines=1, fill=BAND_FILL)


def plan_slide(sl: dict) -> Plan:
    """쪽의 배치 계획. 쪽 사본에 링크 번호(S.LINKS_KEY)가 있으면 차트·원문 캡처·회색 자리·표의 오른쪽 아래 귀퉁이에 번호 글상자를 더한다
    (차트·캡처·표는 자리 바로 아래, 회색 자리는 자리 안쪽 — 그 아래에 캡션 글상자가 온다).
    쪽 사본에 광고 띠 글(S.SPONSOR_KEY — 광고 구간의 쪽)이 있으면 오른쪽 위에 띠 글상자를 더한다. 검사와 빌드가 같은 계획을 쓰므로 띠도 넘침 검사를 받는다."""
    p = _plan_slide(sl)
    if sl.get("side") == "right" and sl.get("kind") in S.SIDE_KINDS and p.imgs:
        # side는 v1과 무관한 선택 칸이다. 제목은 고정하고 그림과 본문만 정수 EMU로 뒤집는다.
        for shape in [*p.imgs, *(b for b in p.boxes if b.name != "제목")]:
            shape.left = _in(deck.W - Inches(shape.left) - Inches(shape.width))
    if sl.get(S.SPONSOR_KEY):
        p.boxes.append(sponsor_band_box(str(sl[S.SPONSOR_KEY])))
    corner = ((sl.get(S.LINKS_KEY) or {}).get("corner") or {})
    if not corner:
        return p
    for im in p.imgs:
        label = corner.get(im.slot)
        if not label or im.kind == "picture":
            continue
        # 링크 번호 글상자는 거울 배치하지 않고, 옮긴 그림 자리의 오른쪽 아래 귀퉁이에 고정한다.
        top = im.top + im.height - CORNER_H - 0.04 if im.kind == "slot" else im.top + im.height + 0.02
        p.boxes.append(_corner_box(label, im.left + im.width - (0.06 if im.kind == "slot" else 0.0), top))
    if corner.get("table") and p.tables:
        t = p.tables[0]
        p.boxes.append(_corner_box(corner["table"], t.left + t.width, t.top + sum(t.row_heights()) + 0.0))
    return p


def _plan_slide(sl: dict) -> Plan:
    k = sl.get("kind")
    emph = sl.get("emphasis") or []
    p = Plan()
    img_l, img_t, img_w, img_h = ML, _in(deck.IMG_TOP), _in(deck.IMG_W), _in(deck.IMG_H)
    body_top = _in(deck.BODY_TOP)
    if k == "title_hook":
        p.boxes.append(Box("여는 제목", ML, 2.2, SW - 2 * ML, 2.0, [Para(str(sl["title"]), deck.TITLE_RGB, True, list(emph), marks=_mk(sl, "title"))], size=40, spacing=1.2, align=PP_ALIGN.CENTER))
        if sl.get("sub"):
            p.boxes.append(Box("부제", ML, 4.35, SW - 2 * ML, 1.3, [Para(str(sl["sub"]), emph=list(emph), marks=_mk(sl, "sub"))], align=PP_ALIGN.CENTER))
        return p
    if k == "full_picture":   # 제목 없이 그림 하나가 쪽을 채운다 — 한마디(caption)는 그림 안 아래 한 줄
        h = SH - BLEED_T - BLEED_B
        im = _img(sl, BLEED_L, BLEED_T, SW - 2 * BLEED_L, h, caption=False)
        if im:
            p.imgs.append(im)
        if sl.get("caption") not in (None, ""):
            cw = SW - 2 * ML
            p.boxes.append(Box("한마디", ML, BLEED_T + h - BLEED_CAP_H - BLEED_CAP_UP, cw, BLEED_CAP_H, [Para(str(sl["caption"]), emph=list(emph), marks=_mk(sl, "caption"))],
                               spacing=1.0, align=PP_ALIGN.CENTER, max_lines=1, fill=RGBColor(0xFF, 0xFF, 0xFF)))
        return p
    p.boxes.append(_title_box(sl))
    if k == "image_text":
        im = _img(sl, img_l, img_t, img_w, img_h)
        if im:
            p.imgs.append(im)
            x = img_l + img_w + _in(deck.GAP)
        else:
            x = ML
        p.boxes.append(Box("본문", x, body_top, SW - ML - x, BODY_BOTTOM - body_top, _body_paras(sl.get("body"), emph, sl)))
    elif k == "quote_translation":
        im = _img(sl, img_l, img_t, 2.6, 1.7)
        x = ML + 3.2 if im else ML
        if im:
            p.imgs.append(im)
        paras = [Para(str(sl["en"]), emph=[], marks=_mk(sl, "en"))] + [Para(str(sl["ko"]), deck.EMPH_RGB, False, list(emph), marks=_mk(sl, "ko"))] + _body_paras(sl.get("body"), emph, sl)
        p.boxes.append(Box("원문·번역", x, body_top, SW - ML - x, BODY_BOTTOM - body_top, paras))
    elif k == "number":
        im = _img(sl, img_l, img_t, img_w, img_h)
        num = sl["number"]
        if im:
            p.imgs.append(im)
            x, align, top = img_l + img_w + _in(deck.GAP), PP_ALIGN.LEFT, body_top
        else:
            x, align, top = ML, PP_ALIGN.CENTER, 2.1
        w = SW - ML - x
        size = 44 if im else 60  # 그림 옆 글 기둥은 좁아 한 단 작게
        p.boxes.append(Box("큰 숫자", x, top, w, 1.25, [Para(str(num["value"]), deck.EMPH_RGB, True, marks=_mk(sl, "number", "value"))], size=size, spacing=1.0, align=align, max_lines=1))
        y = top + 1.35
        if num.get("label"):
            p.boxes.append(Box("숫자 설명", x, y, w, 1.0, [Para(str(num["label"]), emph=list(emph), marks=_mk(sl, "number", "label"))], spacing=1.2, align=align, max_lines=2))
            y += 1.1
        if sl.get("body"):
            p.boxes.append(Box("본문", x, y, w, BODY_BOTTOM - y, _body_paras(sl.get("body"), emph, sl), align=align))
    elif k == "compare_table":
        t = sl["table"]
        header = [str(x) for x in t.get("header") or []]
        rows = [[str(x) for x in r] for r in t.get("rows") or []]
        rel = t.get("widths") or [1] * len(header)
        tw = SW - 2 * ML
        widths = [tw * r / sum(rel) for r in rel]
        tb = Table(ML, 1.75, tw, widths, header, rows, emph=list(emph), words_whole=True)
        p.tables.append(tb)
        if sl.get("body"):
            y = tb.top + sum(tb.row_heights()) + 0.2
            tb.max_bottom = BODY_BOTTOM - 0.6
            p.boxes.append(Box("표 아래 글", ML, y, tw, max(0.6, BODY_BOTTOM - y), _body_paras(sl.get("body"), emph, sl), spacing=1.2))
    elif k == "quote_line":
        q = sl["quote"]
        p.boxes.append(Box("인용", ML + 0.5, 2.3, SW - 2 * ML - 1.0, 2.4, [Para(str(q["text"]), deck.EMPH_RGB, True, [], marks=_mk(sl, "quote", "text"))], size=36, spacing=1.3, align=PP_ALIGN.CENTER))
        if q.get("by"):
            p.boxes.append(Box("인용 출처", ML + 0.5, 4.85, SW - 2 * ML - 1.0, 0.8, [Para(str(q["by"]), marks=_mk(sl, "quote", "by"))], size=20, spacing=1.2, align=PP_ALIGN.CENTER))
    elif k == "closing":
        p.boxes.append(Box("본문", ML, body_top, SW - 2 * ML, BODY_BOTTOM - body_top, _body_paras(sl.get("body"), emph, sl)))
    elif k == "capture_full":
        im = _img(sl, ML, FULL_TOP, SW - 2 * ML, FULL_BOTTOM - FULL_TOP, caption=False)
        if im:
            p.imgs.append(im)
    elif k == "photo_caption":
        im = _img(sl, ML, WIDE_TOP, SW - 2 * ML, WIDE_H, caption=False)
        if im:
            p.imgs.append(im)
        p.boxes.append(Box("설명", ML, CAPTION_TOP, SW - 2 * ML, CAPTION_H, [Para(str(sl["caption"]), emph=list(emph), marks=_mk(sl, "caption"))],
                           size=deck.CAPTION_SIZE, spacing=1.2, align=PP_ALIGN.CENTER, max_lines=2))
    elif k == "image_stack":
        im = _img(sl, ML, STACK_TOP, SW - 2 * ML, STACK_H, caption=False)
        if im:
            p.imgs.append(im)
        p.boxes.append(Box("본문", ML, STACK_BODY_TOP, SW - 2 * ML, BODY_BOTTOM - STACK_BODY_TOP, _body_paras(sl.get("body"), emph, sl), max_lines=3))
    elif k == "image_pair":
        w = (SW - 2 * ML - PAIR_GAP) / 2
        for j, v in S.slot_views(sl):
            x = ML + j * (w + PAIR_GAP)
            im = _img(v, x, WIDE_TOP, w, WIDE_H, slot=j, caption=False)
            if im:
                p.imgs.append(im)
            if v.get("caption") not in (None, ""):
                p.boxes.append(Box(f"설명({S.SLOT_NAME[j]})", x, CAPTION_TOP, w, CAPTION_H, [Para(str(v["caption"]), emph=list(emph), marks=_mk(sl, "pair", j, "caption"))],
                                   size=deck.CAPTION_SIZE, spacing=1.2, align=PP_ALIGN.CENTER, max_lines=2))
    return p


def layout_problems(sl: dict) -> list[str]:
    if sl.get("kind") not in S.KINDS:
        return []
    out = []
    try:
        pl = plan_slide(sl)
        for b in pl.boxes:
            out += b.problems()
        for t in pl.tables:
            out += t.problems()
    except (KeyError, TypeError, AttributeError, ValueError, ZeroDivisionError, OverflowError) as e:  # 삼키지 않는다 — 검사를 통과한 사양이 빌드에서 깨지면 안 된다
        return [f"배치 실패({type(e).__name__}: {e}) — 필수 칸이 빠졌거나 모양이 틀렸다"]
    if sl.get("kind") == "title_hook" and sl.get("image"):
        out.append("여는 제목 장에는 그림 자리를 두지 않는다(image_text 로 따로 둔다)")
    return out


# ── pptx 쓰기 ────────────────────────────────────────────────────────────
def _style_run(r, size, bold, color):
    f = r.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    deck.set_run_font(r, deck.FONT)


def _write_para(para, p: Para, size: float):
    mask = [m or p.bold for m in S.emphasis_mask(p.text, p.emph)]
    emph_mask = S.emphasis_mask(p.text, p.emph)
    for li, (a, b) in enumerate(p.lines):
        if li:
            para.add_line_break()
        i = a
        while i < b:
            j = i
            while j < b and emph_mask[j] == emph_mask[i] and (j == i or (j - 1) not in p.marks):
                j += 1   # 링크 번호가 붙는 글자에서 조각을 끊는다(번호 조각을 그 뒤에 넣는다)
            r = para.add_run()
            r.text = p.text[i:j]
            _style_run(r, size, mask[i], deck.EMPH_RGB if emph_mask[i] else p.color)
            if (j - 1) in p.marks:
                _sup_run(para, p.marks[j - 1], size)
            i = j


def _sup_run(para, label: str, size: float):
    """링크 번호 — 작은 회색 위첨자 조각. 사양의 글이 아니라 빌드가 붙이는 표시다(숫자 대조를 받지 않는다)."""
    r = para.add_run()
    r.text = label
    _style_run(r, sup_size(size), False, LIGHT)
    r._r.get_or_add_rPr().set("baseline", SUP_BASELINE)


def draw_box(slide, b: Box):
    b.layout()
    tb = slide.shapes.add_textbox(Inches(b.left), Inches(b.top), Inches(b.width), Inches(b.height))
    tb.name = b.name
    tf = tb.text_frame
    tf.word_wrap = False  # 줄은 어절 단위로 이미 나눴다
    tf.margin_left = tf.margin_right = Inches(PAD)
    if b.fill is not None:
        tb.fill.solid()
        tb.fill.fore_color.rgb = b.fill
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, p in enumerate(b.paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = b.align
        para.line_spacing = b.spacing
        _write_para(para, p, b.size)
    return tb


SOURCE_PREFIX = "출처: "   # 회색 그림 자리의 셋째 줄 머리. style: syuka 빌드는 비운다(화면에 '출처:' 를 찍지 않는다 — 링크 목록이 맡는다)


def draw_img(slide, im: Img, prefix: str | None = None):
    box = slide.shapes.add_shape(1, Inches(im.left), Inches(im.top), Inches(im.width), Inches(im.height))
    box.name = "그림 자리"
    box.fill.solid()
    box.fill.fore_color.rgb = deck.PLACEHOLDER_RGB
    box.line.color.rgb = RGBColor(0xBB, 0xBB, 0xBB)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, (txt, sz, bold) in enumerate([("그림 자리", 14, True), (im.what, 12, False), ((SOURCE_PREFIX if prefix is None else prefix) + im.source, 10, False)]):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = PP_ALIGN.CENTER
        r = para.add_run()
        r.text = txt
        _style_run(r, sz, bold, LIGHT if i == 0 else GREY)
    if im.caption:
        cb = Box("캡션", im.left, im.top + im.height + 0.08, im.width, 0.8, [Para(im.caption)], size=deck.CAPTION_SIZE, spacing=1.2, align=PP_ALIGN.CENTER)
        draw_box(slide, cb)


VISUALS_DIR = "visuals"   # 산출 폴더 안 — 렌더한 차트 PNG
CREDIT_SIZE = 11          # 원문 캡처 아래 출처 줄(pt)


def chart_png_size(im: Img) -> tuple[int, int]:
    """그림 자리와 같은 가로세로 비의 픽셀 크기. 왼쪽 그림 자리(charts.SLOT_W_IN × SLOT_H_IN)면 charts.DEFAULT_SIZE_PX 그대로."""
    from ozl.render import charts as G
    if abs(im.width - G.SLOT_W_IN) < 1e-6 and abs(im.height - G.SLOT_H_IN) < 1e-6:
        return G.DEFAULT_SIZE_PX
    w = G.DEFAULT_SIZE_PX[0]
    return w, round(w * im.height / im.width)


def capture_credit(c: dict) -> str:
    """원문 캡처 아래 출처 줄: 원문 주소의 호스트만(검사가 붙이는 구조 글 — 부록의 링크·기준 시점 칸처럼 숫자 대조에서 뺀다).
    받은 시각은 화면에서 읽을 일이 없어 부록 「시각물 출처·검증표」가 맡는다(2026-11-13 구성 평가)."""
    import urllib.parse
    cap = ((c.get("verification") or {}).get("capture") or {}) if isinstance(c.get("verification"), dict) else {}
    url = str(cap.get("final_url") or cap.get("url") or (c.get("source") or {}).get("url") or "")
    host = urllib.parse.urlsplit(url).hostname or url
    return "원문: " + host


def capture_slot_in(im: Img) -> float:
    """원문 캡처 그림 글자를 슬라이드 위 pt 로 맞추는 기준 폭(in). 왼쪽 그림 자리면 capture.SLOT_W_IN 그대로(종전 그림과 같게), 그 밖은 자리 폭."""
    from ozl.render import charts as G
    from ozl.research import capture as K
    if abs(im.width - G.SLOT_W_IN) < 1e-6 and abs(im.height - G.SLOT_H_IN) < 1e-6:
        return K.SLOT_W_IN
    return im.width


PIC_CREDIT_SIZE = 10      # 그림 파일 밑 표기(pt)
PIC_CREDIT_H = 0.42       # 두 줄 자리(in)


def picture_credit_box(im: Img, e: dict, y: float) -> Box:
    """그림 파일 밑 표기 글상자 — 'AI 생성 이미지, 실제 장면 아님'(AI 개념도) · '출처 표시 문구 · 라이선스'(+ 상표 고지). 두 줄까지."""
    from ozl.render import pictures as PIC
    lines = PIC.credit_lines(e)
    paras = [Para(t, GREY, t == PIC.AI_MARK) for t in lines] or [Para("", GREY)]
    return Box("그림 표기", im.left, y, im.width, PIC_CREDIT_H, paras, size=PIC_CREDIT_SIZE, spacing=1.0, align=PP_ALIGN.CENTER, max_lines=2)


def draw_picture(slide, im: Img, e: dict | None, waiting: bool, prefix: str | None = None):
    """검수 대장의 그림 파일을 자리 안쪽에 비율을 지켜 넣고 밑에 표기를 단다. 대기(초안 모드)면 회색 자리에 대기 문구."""
    from ozl.render import pictures as PIC
    if waiting or not e or PIC.file_error(e):
        draw_img(slide, Img(im.left, im.top, im.width, im.height, f"그림 대기 — {im.ref} 검수 기록이 다 차지 않았거나 쓰지 않는 그림이다", "그림 검수 대장"), prefix)
        return None
    path = PIC.resolve_path(e)
    from PIL import Image
    with Image.open(path) as g:
        pw, ph = g.size
    dx, dy, w, h = fit_inside(pw, ph, im.width, im.height)
    pic = slide.shapes.add_picture(str(path), Inches(im.left + dx), Inches(im.top + dy), Inches(w), Inches(h))
    pic.name = "그림 파일"
    draw_box(slide, picture_credit_box(im, e, im.top + dy + h + 0.04))
    return pic


def fit_inside(img_w: int, img_h: int, box_w: float, box_h: float) -> tuple[float, float, float, float]:
    """(왼쪽 띄움, 위 띄움, 폭, 높이) in — 비율을 지켜 자리 안쪽에 맞춘다(잘리지 않는다)."""
    k = min(box_w / img_w, box_h / img_h)
    w, h = img_w * k, img_h * k
    return (box_w - w) / 2, (box_h - h) / 2, w, h


def draw_visual(slide, im: Img, png: pathlib.Path | None, credit: str = "", prefix: str | None = None):
    """chart·capture 그림을 그림 자리에 넣는다. png 가 없으면(초안 모드 그림 대기) 회색 자리에 대기 문구를 적는다."""
    if png is None:
        draw_img(slide, Img(im.left, im.top, im.width, im.height, f"그림 대기 — {im.ref.rsplit('-', 1)[-1]} 원문 화면 그림이 아직 없다", credit or "원문 캡처"), prefix)
        return None
    if im.kind == "chart":
        pic = slide.shapes.add_picture(str(png), Inches(im.left), Inches(im.top), Inches(im.width), Inches(im.height))
        pic.name = "차트"
        if im.slot >= 0:
            # image_pair: 차트 그림은 위쪽에 흰 여백이 있어 옆 자리의 테두리 있는 캡처와 위 끝이 어긋나 보인다 — 같은 테두리를 둘러 두 자리의 틀을 맞춘다
            pic.line.color.rgb = RGBColor(0xBB, 0xBB, 0xBB)
        return pic
    from PIL import Image
    with Image.open(png) as g:
        pw, ph = g.size
    dx, dy, w, h = fit_inside(pw, ph, im.width, im.height)
    pic = slide.shapes.add_picture(str(png), Inches(im.left + dx), Inches(im.top + dy), Inches(w), Inches(h))
    pic.name = "원문 캡처"
    pic.line.color.rgb = RGBColor(0xBB, 0xBB, 0xBB)
    pic.line.width = Pt(0.75)
    if credit:
        size = CREDIT_SIZE
        while size > 8 and S.measure(credit, size) > (im.width - 2 * PAD) * 72:
            size -= 1
        b = Box("원문 캡처 출처", im.left, im.top + dy + h + 0.06, im.width, 0.35, [Para(credit, GREY)], size=size, spacing=1.0, align=PP_ALIGN.CENTER, max_lines=1)
        draw_box(slide, b)
    return pic


def _no_grid(tbl):
    tblPr = tbl._tbl.tblPr
    tblPr.set("firstRow", "0")
    tblPr.set("bandRow", "0")
    sid = tblPr.find(qn("a:tableStyleId"))
    if sid is None:
        sid = etree.SubElement(tblPr, qn("a:tableStyleId"))
    sid.text = NO_GRID_STYLE


def draw_table(slide, t: Table, header_rgb=deck.EMPH_RGB):
    heights = t.row_heights()
    gf = slide.shapes.add_table(len(t.rows) + 1, len(t.header), Inches(t.left), Inches(t.top), Inches(t.width), Inches(sum(heights)))
    gf.name = "표"
    tbl = gf.table
    _no_grid(tbl)
    for j, w in enumerate(t.widths):
        tbl.columns[j].width = Inches(w)
    for i, h in enumerate(heights):
        tbl.rows[i].height = Inches(h)
    for i, row in enumerate([t.header] + t.rows):
        for j, txt in enumerate(row):
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            if i == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xF2, 0xF2, 0xF2)
            tf = cell.text_frame
            tf.word_wrap = not t.whole(j) or _has_url(str(txt))  # 어절 줄바꿈을 미리 넣은 칸은 자동 줄바꿈을 끈다(주소 칸·주소가 든 칸만 예외)
            width_pt = t.cell_width_pt(t.widths[j])
            for k, part in enumerate(str(txt).split("\n")):
                para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                para.line_spacing = 1.0
                p = Para(part, header_rgb if i == 0 else deck.BODY_RGB, i == 0, [] if i == 0 else t.emph)
                mask = [m or p.bold for m in S.emphasis_mask(p.text, p.emph)]
                p.lines = S.wrap(p.text, width_pt, t.size, mask) or [(0, 0)]
                # 문단 끝 표시의 글자 크기도 표 크기로 — 비워 두면 기본 18pt 가 빈 칸의 행 높이를 키워 표가 쪽 아래로 넘친다
                para._p.get_or_add_endParaRPr().set("sz", str(int(round(t.size * 100))))
                if not part:
                    continue
                _write_para(para, p, t.size)
    return gf


def _footnote(slide, text: str):
    b = Box("출처 각주", ML, FOOT_TOP, SW - 2 * ML, 0.5, [Para(text, GREY)], size=11, spacing=1.0, max_lines=2)
    draw_box(slide, b)


footnote_text = S.footnote_text  # 각주 글을 만드는 함수는 하나 — 검사(spec.check)와 생성이 같이 쓴다


def notes_text(sl: dict, claims: dict, stage: str, pics: dict | None = None) -> str:
    from ozl.render import pictures as PIC
    lines = [f"[{stage} · {sl.get('kind')}]"]
    for j, v in S.slot_views(sl):
        where = (S.SLOT_NAME[j] + " ") if j >= 0 else ""
        if S.visual_of(v) == "chart":
            ch = v["chart"]
            lines.append(f"그림: {where}차트({ch.get('kind')}) · 쓴 기록 {', '.join(map(str, ch.get('claims') or []))} — " + chart_limit(ch, claims))
        elif S.visual_of(v) == "capture":
            lines.append(f"그림: {where}원문 캡처 {v['capture']} — {capture_credit(claims.get(str(v['capture'])) or {})}")
        elif S.visual_of(v) == "picture":
            e = (pics or {}).get(str(v["picture"]).strip()) or {}
            verdict = PIC.judge(e)[0] if e else "대장에 없음"
            lines.append(f"그림: {where}그림 파일 {v['picture']} — {e.get('kind', '')} · 권리자 {e.get('rights_holder', '')} · "
                         f"{e.get('license', '')} · 판정 {verdict} · 출처 {e.get('source_url', '')}")
    ids = [str(x) for x in sl.get("claim_ids") or []]
    if ids:
        lines.append("claim_id: " + ", ".join(ids))
        for cid in ids:
            c = claims.get(cid) or {}
            lines.append(f"- {cid}: {c.get('text', '')} (출처 {(c.get('source') or {}).get('url', '')})")
    for cv in sl.get("conversions") or []:
        lines.append(f"환산: '{cv.get('shown')}' ← {cv.get('claim_id')} '{cv.get('source')}' — {cv.get('basis')}")
    if sl.get("notes"):
        lines.append("메모: " + str(sl["notes"]).strip())
    if sl.get("spoken"):
        lines.append("말로만: " + str(sl["spoken"]).strip())
    if sl.get("transition"):
        lines.append("넘어가기: " + str(sl["transition"]).strip())
    return "\n".join(lines)


CHART_LIMIT = "값이 사본에 있는지만 프로그램이 봤다. 칸과 값의 짝은 문장 대조에서 본다."
CHART_LIMIT_NO_COPY = "값이 기록의 observed·text 에 있는지만 프로그램이 봤다(사본 없는 기록). 칸과 값의 짝은 문장 대조에서 본다."


def chart_limit(ch: dict, claims: dict) -> str:
    """러닝시트·노트의 차트 줄 — 무엇을 프로그램이 봤고 무엇을 못 봤는가."""
    has_copy = any(S.copy_text(claims.get(str(c)) or {})[0] for c in ch.get("claims") or [])
    return (CHART_LIMIT if has_copy else CHART_LIMIT_NO_COPY) + (" 세로축이 0에서 시작하지 않는다(y_from_zero: false)." if ch.get("y_from_zero") is False else "")


# ── 부록 ────────────────────────────────────────────────────────────────
_URL = re.compile(r"\(?https?://[^\s)]+\)?")


def locator_text(loc: str) -> str:
    """부록 '문서 위치' 칸 — 기록의 primary_doc_locator 에 섞인 주소는 빼고(주소는 링크 칸에만) 남은 설명만. 기록 파일은 고치지 않는다."""
    t = _URL.sub("", str(loc or ""))
    t = re.sub(r"\s*[·,]\s*(?=[·,]|$)", "", t)
    t = re.sub(r"·(?=\S)", "· ", t)  # 가운뎃점으로만 이어진 긴 덩어리를 어절로 나눈다(부록 칸의 어절 검사)
    t = re.sub(r"\s{2,}", " ", t).strip(" ·,")
    return t


def source_rows(spec: dict, claims: dict, card: dict, pending=None) -> list[list[str]]:
    """pending: 초안 모드의 {쪽: [claim_id]} (또는 claim_id 집합). 검증 대기 기록의 행과, 검증 대기 쪽에서 인용한 보도 행에 [검증 대기]를 붙인다."""
    pend_pages = set(pending) if isinstance(pending, dict) else set()
    pending_ids = {c for v in pending.values() for c in v} if isinstance(pending, dict) else set(pending or ())
    """출처 부록 행 = 인용된 클레임마다 [클레임 · 기관 · 문서 위치 · 링크 · 기준 시점 · 쓰인 쪽] + 카드 sources 중 refs 로 쓴 보도."""
    pages: dict[str, list[int]] = {}
    ref_pages: dict[str, list[int]] = {}
    for i, sl in enumerate(spec.get("slides") or [], 1):
        for cid in sl.get("claim_ids") or []:
            pages.setdefault(str(cid), []).append(i)
        for ref in sl.get("refs") or []:
            ref_pages.setdefault(str(ref), []).append(i)

    def key(cid):
        m = C.CLAIM_ID.match(cid)
        return (m.group(1), int(m.group(2))) if m else (cid, 0)

    rows = []
    for cid in sorted(pages, key=key):
        c = claims.get(cid) or {}
        src = c.get("source") or {}
        chk = c.get("checks") or {}
        short = cid.rsplit("-", 1)[-1] + (f"\n{PENDING_MARK}" if cid in (pending_ids or set()) else "")
        rows.append([short, str(src.get("publisher") or ""), locator_text(chk.get("primary_doc_locator")), str(src.get("url") or ""),
                     str(chk.get("base_period") or "").replace("~", " ~ "), ", ".join(map(str, pages[cid]))])   # 범위는 띄어 쓴다(칸에서 줄을 바꿀 수 있게)
        for x in c.get("cross_check") or []:  # 교차 출처도 부록에 — 화면에서 '다른 보도'로 인용한 문장을 거슬러 갈 수 있게
            if isinstance(x, dict) and x.get("url"):
                rows.append([short.split("\n")[0] + " 교차" + (f"\n{PENDING_MARK}" if cid in (pending_ids or set()) else ""),
                             str(x.get("publisher") or ""), "교차 출처", str(x["url"]), "", ", ".join(map(str, pages[cid]))])
    by_name = {s.get("name"): s for s in spec.get("press_sources") or [] if isinstance(s, dict)}
    by_name.update({s.get("name"): s for s in card.get("sources") or []})  # 카드 sources 가 우선
    for ref, pg in ref_pages.items():
        s = by_name.get(ref) or {}
        mark = f"\n{PENDING_MARK}" if pend_pages & set(pg) else ""
        doc = s.get("tier") in S.DOC_TIERS   # 각주(footnote_text)와 같은 기준 — 기업·기관 문서는 보도로 부르지 않는다
        rows.append([("자료" if doc else "보도") + mark, ref,
                     "검증 기록 없음 — " + ("문서 인용(숫자 근거 아님)" if doc else "보도 인용"), str(s.get("url") or ""), "", ", ".join(map(str, pg))])
    return rows


def visual_rows(spec: dict, pending: dict[int, list[str]] | None = None) -> list[list[str]]:
    """그림 자리마다 한 행. 초안 모드에서 원 슬라이드가 검증 대기면 쪽 칸에 [검증 대기]를 붙인다(부록에서도 표시가 빠지지 않게)."""
    rows = []
    for i, sl in enumerate(spec.get("slides") or [], 1):
        for j, v in S.slot_views(sl):
            im = v.get("image")
            if not im:
                continue
            rows.append([page_label(i, j) + (f"\n{PENDING_MARK}" if i in (pending or {}) else ""), str(im.get("what", "")), str(im.get("source", "")), "", "",
                         "" if im.get("map") else "해당 없음"])
    return rows


def page_label(i: int, slot: int) -> str:
    """부록 '쪽' 칸: 쪽 번호, image_pair 의 자리면 '3 왼' · '3 오른'."""
    return str(i) if slot < 0 else f"{i} {'왼' if slot == 0 else '오른'}"


def _fetched(at) -> str:
    """받은 시각 '2026-11-13T08:02:23+09:00' → '2026-11-13 08:02'(한 어절이 칸 폭을 넘지 않게)."""
    t = str(at or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", t)
    return f"{m.group(1)} {m.group(2)}" if m else t


CAPTURE_VIEW = {"text_passage": "원문의 글을 옮겨 그림", "pdf_band": "PDF 쪽에서 자름", "pdf_page": "PDF 쪽 전체"}


def visual_check_rows(spec: dict, claims: dict, pending=None, views: dict[int, str] | None = None) -> list[list[str]]:
    """차트·원문 캡처마다 한 행. 그림 안에서 뺀 내부 정보(기록 번호·주소·받은 시각·사본 해시)를 이 표가 맡는다.
    views = 빌드 때 실제로 그린 그림의 종류(쪽 → evidence_image 의 view). 없으면(검사 때) 사본 종류로 어림한다."""
    rows = []
    for i, whole in enumerate(spec.get("slides") or [], 1):
        for j, sl in S.slot_views(whole):
            v = S.visual_of(sl)
            pg = page_label(i, j) + (f"\n{PENDING_MARK}" if i in (pending or {}) else "")
            if v == "chart" and isinstance(sl["chart"], dict):
                ch = sl["chart"]
                ids = ", ".join(str(c).rsplit("-", 1)[-1] for c in ch.get("claims") or [])
                has_copy = any(S.copy_text(claims.get(str(c)) or {})[0] for c in ch.get("claims") or [])
                # '확인'은 사람이 대조한 일에만 쓴다(완성본 평가 기준 가8) — 프로그램과 에이전트가 한 일은 '대조'로 적는다.
                scope = ("값이 사본에 있는지는 프로그램이 대조" if has_copy else "값이 기록 observed·text 에 있는지는 프로그램이 대조") + \
                    " · 칸과 값의 짝은 문장 대조에서 봄" + (" · 세로축이 0에서 시작하지 않음" if ch.get("y_from_zero") is False else "")
                rows.append([pg, f"차트({'선' if ch.get('kind') == 'line' else '막대'})", f"{ch.get('title', '')} · 기록 {ids}",
                             f"단위 {ch.get('unit', '')} · 기간 {ch.get('period', '')}", "", scope])
            elif v == "capture":
                cid = str(sl["capture"]).strip()
                c = claims.get(cid) or {}
                cap = ((c.get("verification") or {}).get("capture") or {}) if isinstance(c.get("verification"), dict) else {}
                url = str(cap.get("final_url") or cap.get("url") or (c.get("source") or {}).get("url") or "")
                view = (views or {}).get(i if j < 0 else (i, j)) or ("pdf_band" if cap.get("kind") == "pdf" else "text_passage")
                label = CAPTURE_VIEW.get(view, view)
                if view == "text_passage" and cap.get("kind") == "pdf":
                    label = "PDF 의 글을 옮겨 그림"
                sha = str(cap.get("sha256") or "")[:12]
                rows.append([pg, "원문 캡처", f"기록 {cid.rsplit('-', 1)[-1]}", url, f"{_fetched(cap.get('fetched_at'))} · sha256 {sha}", label])
    return rows


PENDING_MARK = "[검증 대기]"
WAIT_MARK = "[그림 대기]"   # 초안 모드: capture 기록의 원문 화면 그림이 아직 없다
SRC_HEADER = ["클레임", "기관", "문서 위치", "링크", "기준 시점", "쪽"]
SRC_WIDTHS = [1.0, 1.9, 3.0, 3.3, 1.2, 1.01]
VIS_HEADER = ["쪽", "무엇을", "어느 공식 출처에서", "역검색", "400% 확대", "지도 표기"]
VIS_WIDTHS = [1.2, 3.3, 3.9, 1.0, 1.0, 1.01]
VC_HEADER = ["쪽", "종류", "무엇을", "원문 주소 · 단위·기간", "받은 시각 · 사본", "검증 범위 · 그림"]
VC_WIDTHS = [0.8, 1.1, 2.5, 3.3, 1.7, 2.01]
PIC_HEADER = ["그림", "쪽", "종류", "권리자", "라이선스", "출처 주소", "확인 시각"]
PIC_WIDTHS = [0.8, 0.9, 1.6, 2.0, 1.6, 3.1, 1.41]
PIC_FOOT = "그림마다 검수 기록(원출처 · 상업적 이용 · 변경 · 출처 표시 · 역검색 · 합성 여부 · 인물·로고·지도 점검)은 사양의 pictures 대장에 있다. 칸이 빈 그림과 '쓰지 않는다' 판정 그림은 엄격 모드가 받지 않고, 밈은 엄격 모드에서 뺀다."
VC_FOOT = "원문 캡처 그림에는 대목 글만 둔다 — 기록 번호·원문 주소·받은 시각·사본 sha256 은 이 표가 맡는다. 차트의 값은 사본(또는 기록)에 그 표기로 있는지만 프로그램이 봤다."


def appendix_tables(spec: dict, claims: dict, card: dict | None, pending=None, views=None) -> list[tuple]:
    """부록 표 (제목, 머리, 폭, 행) — 검사와 빌드가 같은 목록을 쓴다. 시각물 표: 회색 그림 자리(image)가 있거나 차트·캡처가 없으면 종전 표,
    차트·원문 캡처가 있으면 그 검증표."""
    out = [("부록 · 출처", SRC_HEADER, SRC_WIDTHS, source_rows(spec, claims, card or {}, pending))]
    img_rows = visual_rows(spec, pending)
    vc_rows = visual_check_rows(spec, claims, pending, views)
    if img_rows or not vc_rows:
        out.append(("부록 · 시각물 출처·검증표", VIS_HEADER, VIS_WIDTHS, img_rows))
    if vc_rows:
        out.append(("부록 · 시각물 출처·검증표(차트·원문 캡처)", VC_HEADER, VC_WIDTHS, vc_rows))
    pic_rows = picture_rows(spec, pending)
    if pic_rows:
        out.append(("부록 · 시각물 출처·검증표(그림 파일)", PIC_HEADER, PIC_WIDTHS, pic_rows))
    return out


def picture_rows(spec: dict, pending=None) -> list[list[str]]:
    """쓴 그림 파일마다 한 행(처음 쓴 쪽 순서): 번호 · 쓴 쪽 · 종류 · 권리자 · 라이선스 · 출처 주소 · 확인 시각.
    초안 모드에서 그 그림이 그림 대기면 번호 칸에 [그림 대기]를 붙인다."""
    from ozl.render import pictures as PIC
    pics, _ = PIC.ledger(spec)
    pages: dict[str, list[str]] = {}
    for i, sl in enumerate(spec.get("slides") or [], 1):
        if not isinstance(sl, dict):
            continue
        for j, v in S.slot_views(sl):
            pid = str(v.get("picture") or "").strip()
            if pid:
                pages.setdefault(pid, []).append(page_label(i, j))
    waits = {str(c)[len(S.WAIT_IMAGE):] for v in (pending or {}).values() for c in v if str(c).startswith(S.WAIT_IMAGE)} if isinstance(pending, dict) else set()
    rows = []
    for pid, pg in pages.items():
        e = pics.get(pid) or {}
        rows.append([pid + (f"\n{WAIT_MARK}" if pid in waits else ""), ", ".join(pg), str(e.get("kind") or ""), str(e.get("rights_holder") or ""),
                     str(e.get("license") or ""), str(e.get("source_url") or ""), _fetched(e.get("checked_at"))])
    return rows


def _appx_table(header, rows, widths, top, bottom) -> Table:
    free = frozenset({SRC_HEADER.index("링크")}) if header is SRC_HEADER else frozenset({VC_HEADER.index("원문 주소 · 단위·기간")}) if header is VC_HEADER \
        else frozenset({PIC_HEADER.index("출처 주소")}) if header is PIC_HEADER else frozenset()
    return Table(ML, top, sum(widths), widths, header, rows, size=APPX_SIZE, max_bottom=bottom, words_whole=True, free_cols=free)


def paginate(header, rows, widths, top=1.45, bottom=BODY_BOTTOM) -> list[Table]:
    out, cur = [], []
    for r in rows:
        t = _appx_table(header, cur + [r], widths, top, bottom)
        if cur and any("넘친다" in e for e in t.problems()):
            out.append(_appx_table(header, cur, widths, top, bottom))
            cur = [r]
        else:
            cur.append(r)
    if cur or not out:
        out.append(_appx_table(header, cur, widths, top, bottom))
    return out


# 부록 출처 표의 칸 구분 — 한곳에 모아 둔다.
#   대조 칸: 수량 주장이 실릴 수 있는 일반 글. 그 기록의 observed·text 에 같은 숫자가 있어야 한다.
#   구조 칸: 원문 안의 자리·형식을 가리키는 표기라 숫자가 기록 본문에 있을 수 없다 — 숫자 검사에서 뺀다.
#            (문서 위치 = primary_doc_locator 의 쪽·조·문단·표 번호. 쪽 = 쓰인 슬라이드 번호. 링크 = 주소. 기준 시점 = base_period.
#             클레임 = 약칭. '교차 출처(T3)'·'검증 기록 없음 — 보도 인용' 같은 생성 문구.)
#   보도 행의 이름은 본편 각주(footnote_text)에서, 시각물 표의 무엇을·출처는 본편 그림 자리(visible_text)에서 이미 검사한다.
APPX_CHECKED = ("기관", "교차 출처 기관")
APPX_STRUCTURAL = ("클레임", "문서 위치", "링크", "기준 시점", "쪽", "생성 문구")


def appendix_number_errors(spec: dict, claims: dict, card: dict | None) -> list[str]:
    """부록에 찍히는 대조 칸(APPX_CHECKED)의 숫자 검사. 구조 칸(APPX_STRUCTURAL)은 보지 않는다."""
    out = []
    idents = spec.get("identifiers") or []
    cids: dict[str, None] = {}
    for sl in spec.get("slides") or []:
        for cid in sl.get("claim_ids") or []:
            cids[str(cid)] = None
    for cid in cids:
        c = claims.get(cid) or {}
        pool = S.source_tokens(c)
        cells = [("기관", (c.get("source") or {}).get("publisher"))]
        cells += [("교차 출처 기관", x.get("publisher")) for x in c.get("cross_check") or [] if isinstance(x, dict)]
        for label, txt in cells:
            assert label in APPX_CHECKED
            toks = [t.canon for t in S.N.claim_tokens(_URL.sub("", S._s(txt)), idents)]
            miss = [t for t in dict.fromkeys(toks) if t not in pool]
            if miss:
                out.append(f"부록·출처 {cid.rsplit('-', 1)[-1]} {label}: 숫자 {miss} 가 그 기록의 observed·text 에 없다 — '{S._s(txt)[:60]}'")
    return out


def appendix_problems(spec: dict, claims: dict, card: dict | None, pending=None) -> list[str]:
    """부록 표 검사 — 일반 글 칸의 숫자(appendix_number_errors) · 어절이 칸 폭을 넘으면 실패(주소만 예외) · 한 행이 한 쪽을 넘쳐도 실패."""
    out = appendix_number_errors(spec, claims, card)
    for title, header, widths, rows in appendix_tables(spec, claims, card, pending):
        title = title.replace(" · ", "·")
        for t in paginate(header, rows, widths):
            for e in t.problems(title):
                if e not in out:
                    out.append(e)
    return out


# ── 덱 ──────────────────────────────────────────────────────────────────

def draw_pending(slide, ids: list[str], right: float | None = None):
    """아직 '확인'도 「원문 일치」도 아닌 기록을 인용한 슬라이드 — 오른쪽 위에 빨간 테두리 딱지(초안 모드 전용).
    right = 딱지의 오른쪽 끝(in). 없으면 오른쪽 여백. 광고 띠가 있는 쪽은 띠의 왼쪽에 둔다(겹치지 않게)."""
    waits = [str(c)[len(S.WAIT_IMAGE):] for c in ids if str(c).startswith(S.WAIT_IMAGE)]  # 원문 화면 그림 대기(capture)
    ids = list(dict.fromkeys("보도" if str(c).startswith("보도:") else str(c).split(" ")[0] for c in ids if not str(c).startswith(S.WAIT_IMAGE)))  # 'c13 교차' → 'c13' · 사양 보도 → '보도' · 중복 제거
    parts = [PENDING_MARK + " " + ", ".join(c.rsplit("-", 1)[-1] for c in ids)] if ids else []
    if waits:
        parts.append(WAIT_MARK + " " + ", ".join(c.rsplit("-", 1)[-1] for c in dict.fromkeys(waits)))
    label = " · ".join(parts)
    w = min(SW - 2 * ML, max(3.3, S.measure(label, 14, True) / 72 + 0.4))  # 글이 딱지 밖으로 나가지 않게 폭을 맞춘다
    box = slide.shapes.add_shape(1, Inches(max(ML, (SW - ML if right is None else right) - w)), Inches(0.12), Inches(w), Inches(0.42))
    box.name = "검증 대기"
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xFF, 0xF2, 0xCC)
    box.line.color.rgb = deck.EMPH_RGB
    box.line.width = Pt(2)
    tf = box.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    r = para.add_run()
    r.text = label
    _style_run(r, 14, True, deck.EMPH_RGB)


@contextlib.contextmanager
def _no_passage_note(K):
    """style: syuka — 대목을 다시 그린 그림 맨 아래의 '옮겨 그린 것' 꼬리표를 찍지 않는다(research.capture 는 다른 작업의 소관이라 고치지 않고,
    빌드 동안에만 그 글을 비운다). 꼬리표 자리는 그대로 남아 대목 배치·'다 들어가는가' 계산은 검사와 같다. 그림 종류는 링크 목록이 적는다."""
    orig = K.PASSAGE_NOTE
    K.PASSAGE_NOTE = ""
    try:
        yield
    finally:
        K.PASSAGE_NOTE = orig


def trim_bottom_white(png: pathlib.Path, white: int = 245) -> bool:
    """마지막 잉크 줄 아래 흰 띠를 위쪽 여백만큼만 남기고 줄인다(style: syuka 의 capture_full — 꼬리표가 없어 trim_passage_gap 의 기준 줄이 없다)."""
    from PIL import Image
    with Image.open(png) as g:
        img = g.convert("RGB")
    W, H = img.size
    px = img.convert("L").load()
    rows = [y for y in range(H) if any(px[x, y] < white for x in range(0, W, 2))]
    if not rows:
        return False
    keep = max(rows[0], int(H * 0.03))
    cut = rows[-1] + 1 + keep
    if cut >= H - 4:
        return False
    img.crop((0, 0, W, cut)).save(png)
    return True


def render_visuals(spec: dict, claims: dict, vis_dir: pathlib.Path) -> dict:
    """(쪽 번호, 자리 번호) → (넣을 PNG | None, 출처 줄, 그림 종류). chart 와 capture 모두 vis_dir 에 그때 새로 그린다
    (capture 는 해시가 확인된 사본에서 — capture_png). 파일 이름: 한 자리면 '03_chart.png', image_pair 면 '03a_chart.png' · '03b_capture.png'."""
    from ozl.render import charts as G
    from ozl.research import capture as K
    syuka = spec.get("style") == "syuka"
    out: dict = {}
    for idx, whole in enumerate(spec.get("slides") or [], 1):
        views = dict(S.slot_views(whole))
        for im in plan_slide(whole).imgs:
            if im.kind not in ("chart", "capture"):
                continue
            sl = views.get(im.slot, whole)
            stem = f"{idx:02d}" + ("" if im.slot < 0 else "ab"[im.slot])
            if im.kind == "chart":
                vis_dir.mkdir(parents=True, exist_ok=True)
                # style: syuka 는 차트 그림 안에 '출처:' 줄을 그리지 않는다(귀퉁이 번호와 링크 목록이 맡는다). 환산식이 있으면 그 줄만 남는다
                png = G.render_chart(sl["chart"], vis_dir / f"{stem}_chart.png", size_px=chart_png_size(im), slot_width_in=im.width,
                                     source_line=not syuka)
                out[(idx, im.slot)] = (png, "", "chart")
            else:
                c = claims.get(im.ref) or {}
                with (_no_passage_note(K) if syuka else contextlib.nullcontext()):
                    png, view = capture_png(c, vis_dir / f"{stem}_capture.png", chart_png_size(im), sl.get("capture_focus"), capture_slot_in(im))
                if png is not None and whole.get("kind") == "capture_full" and view == "text_passage":
                    (trim_bottom_white if syuka else trim_passage_gap)(png)
                # style: syuka 는 그림 밑 호스트 줄을 찍지 않는다(원문 주소는 링크 목록이 맡는다)
                out[(idx, im.slot)] = (png, "" if syuka else capture_credit(c), view)
    return out


def trim_passage_gap(png: pathlib.Path, white: int = 245) -> bool:
    """대목을 다시 그린 그림(text_passage)에서 글과 맨 아래 표기 줄 사이의 흰 띠를 줄인다 — capture_full 의 큰 자리에서는
    대목 앞뒤 글이 정해진 길이라 그림 아래쪽이 비어 상자 안에 빈칸이 생긴다. 흰 줄만 빼고 글자·형광 픽셀은 건드리지 않는다.
    남기는 띠 = 그림 위쪽 여백(첫 글 줄까지)과 같은 높이(글 쪽 반, 표기 쪽 반). 줄였으면 True. 자리에 넣을 때는 fit_inside 가 위아래 가운데에 둔다."""
    from PIL import Image
    with Image.open(png) as g:
        img = g.convert("RGB")
    W, H = img.size
    gray = img.convert("L")
    px = gray.load()
    inked = [any(px[x, y] < white for x in range(0, W, 2)) for y in range(H)]
    rows = [y for y, k in enumerate(inked) if k]
    if not rows:
        return False
    # 잉크가 있는 줄을 덩어리로 묶는다 — 마지막 덩어리가 표기 줄이다
    groups: list[list[int]] = [[rows[0], rows[0]]]
    for y in rows[1:]:
        if y - groups[-1][1] > 1:
            groups.append([y, y])
        else:
            groups[-1][1] = y
    if len(groups) < 2:
        return False
    body_end, note_start = groups[-2][1], groups[-1][0]
    keep = max(groups[0][0], int(H * 0.03))
    gap = note_start - body_end - 1
    if gap <= keep + 4:
        return False
    cut_from, cut_to = body_end + 1 + keep // 2, note_start - (keep - keep // 2)
    out = Image.new("RGB", (W, H - (cut_to - cut_from)), "white")
    out.paste(img.crop((0, 0, W, cut_from)), (0, 0))
    out.paste(img.crop((0, cut_to, W, H)), (0, cut_from))
    out.save(png)
    return True


def capture_png(c: dict, out: pathlib.Path, size_px: tuple[int, int], focus=None, slot_width_in: float | None = None) -> tuple[pathlib.Path | None, str]:
    """원문 캡처를 빌드 때 새로 그린다 — 기록이 받아들여지고(acceptance_error 빈 문자열), 해시가 확인된 사본에서, 대조한 자리(match.target)의 그림.
    기록의 verification.image 는 쓰지 않는다(아무 PNG 로 바꿔 넣을 수 있다). 그리지 못하면 None(그림 대기 자리)."""
    from ozl.research import capture as K
    if not c or S.acceptance_error(c):
        return None, ""
    target = S.capture_target(c)
    src = C.copy_source(c)
    if not target or not src["ok"]:
        return None, ""
    cap = src["cap"]
    with _ctx_without_numbers(K):
        r = K.evidence_image(str(c.get("claim_id")), src["path"], src["kind"], src["text"], str(c.get("observed") or ""), target["offset"],
                             S.capture_meta(cap), out, size_px=size_px, focus=focus, slot_width_in=slot_width_in or K.SLOT_W_IN)
    return (pathlib.Path(r["path"]), str(r.get("view") or "")) if r.get("path") else (None, "")


_DIGIT = re.compile(r"\d")


@contextlib.contextmanager
def _ctx_without_numbers(K):
    """대목을 다시 그린 그림의 앞뒤 회색 문맥에서 수가 든 문장을 뺀다(덱 화면에 인용 기록 밖의 수량이 비치지 않게).
    문맥을 고르는 함수(research.capture._ctx_before · _ctx_after)는 다른 작업의 소관이라 고치지 않고, 덱 빌드 동안에만 감싼다.
    대목(observed) 글자는 건드리지 않는다 — 문맥 문장에 수가 있으면 그 쪽 문맥이 통째로 빈다."""
    orig_b, orig_a = K._ctx_before, K._ctx_after

    def before(t, *a, **kw):
        s = orig_b(t, *a, **kw)
        return "" if _DIGIT.search(s) else s

    def after(t, *a, **kw):
        s = orig_a(t, *a, **kw)
        return "" if _DIGIT.search(s) else s

    K._ctx_before, K._ctx_after = before, after
    try:
        yield
    finally:
        K._ctx_before, K._ctx_after = orig_b, orig_a


def visual_label(sl: dict, waiting: bool = False, waits=None) -> str:
    """러닝시트 '그림' 칸. waits = 그림 대기 id(claim_id · 그림 번호) — 주면 자리마다 그것으로 대기 표시를 가린다."""
    from ozl.render import pictures as PIC
    if sl.get("kind") == "image_pair":
        pair = sl.get("pair") if isinstance(sl.get("pair"), list) else []
        parts = []
        for j, slot in enumerate(pair):
            if isinstance(slot, dict) and PIC.DROPPED in slot:
                parts.append(f"{S.SLOT_NAME[j]} 밈을 뺐다")
            elif isinstance(slot, dict):
                parts.append(f"{S.SLOT_NAME[j]} " + visual_label({**slot, "kind": "image_pair_slot"}, waiting, waits))
        return " · ".join(parts) or "없음"
    v = S.visual_of(sl)
    ref = str(sl.get(v) or "").strip() if v in ("capture", "picture") else ""
    wait = (ref in waits) if waits is not None else waiting
    if v == "chart":
        return f"차트({'선' if sl['chart'].get('kind') == 'line' else '막대'})"
    if v == "capture":
        return ("원문 캡처(한 장) " if sl.get("kind") == "capture_full" else "원문 캡처 ") + ref.rsplit('-', 1)[-1] + (" " + WAIT_MARK if wait else "")
    if v == "picture":
        return f"그림 파일 {ref}" + (" " + WAIT_MARK if wait else "")
    if v == "image":
        return "그림 자리(회색)"
    return "없음"


def _read_build_source(path: pathlib.Path) -> tuple[dict, dict]:
    """해시를 낸 바로 그 원본 바이트로 사양을 읽는다. 두 판으로 갈라도 출처는 같다."""
    path = path.resolve()
    raw = path.read_bytes()
    return yaml.safe_load(raw) or {}, {"spec": str(path), "spec_sha256": hashlib.sha256(raw).hexdigest()}


@cache
def _warn_no_output_lock() -> None:
    print("[경고] fcntl이 없어 빌드 잠금 없이 진행한다.", file=sys.stderr)


@contextlib.contextmanager
def _output_lock(folder: pathlib.Path):
    """폴더마다 메타가 하나이므로 pptx와 메타를 바꿔 끼우는 동안 같은 폴더의 빌드를 직렬화한다."""
    try:
        import fcntl
    except ImportError:
        _warn_no_output_lock()
        yield
        return
    fd = os.open(folder, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _write_build_meta(pptx: pathlib.Path, source: dict, expected_sha: str, *, draft: bool, edition: str | None) -> None:
    meta = {**source, "draft": draft, "edition": edition, "pptx": pptx.name, "pptx_sha256": expected_sha, "built_at": C.now_kst()}
    with tempfile.TemporaryDirectory(dir=pptx.parent) as staging:
        temp = pathlib.Path(staging) / "meta.tmp"
        temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if file_sha256(pptx) != expected_sha:
            raise ValueError(f"빌드 뒤 pptx가 바뀌었다 — 메타를 저장하지 않는다: {pptx}")
        temp.replace(pptx.parent / "build_meta.json")


def build_pptx(spec: dict | pathlib.Path | str, claims: dict, card: dict, out: pathlib.Path, pending: dict[int, list[str]] | None = None, appendix: bool = True,
               edition: str | None = None) -> dict:
    """appendix=False 면 부록 쪽을 붙이지 않는다(견본집 — 기록을 인용하지 않는 지어낸 사양).
    edition = 판 이름(두 판 빌드) — 문서 속성 keywords 끝에 판 표시를 붙인다(pictures.keywords_value). 없으면 지금까지와 같다.
    style: syuka 사양은 새 규칙이다: 쪽 아래 출처 줄과 부록 쪽을 두지 않고, 화면 수치 뒤에 링크 번호(spec.link_plan)를 붙인다
    — 링크 목록 파일은 build 가 쓴다(links_<ts>.md · csv). 옛 사양은 종전 그대로."""
    from ozl.render import pictures as PIC
    # 파일을 받은 직접 빌드만 원본을 증명할 수 있다. 사전으로 만드는 견본에는 지문을 꾸며 넣지 않는다.
    source = None
    if isinstance(spec, (str, pathlib.Path)):
        spec, source = _read_build_source(pathlib.Path(spec))
    prs = deck.new_deck()
    draft = pending is not None  # 초안은 대기 항목이 없어도 빈 사전을 받는다.
    pending = pending or {}
    labels = spec.get("source_labels") or {}
    pics, _ = PIC.ledger(spec)
    syuka = spec.get("style") == "syuka"
    links = S.link_plan(spec, claims) if syuka else None
    if links is not None and links.errors:   # check 가 먼저 잡는다 — 검사를 거치지 않고 불렀을 때도 번호가 빠진 덱을 내지 않는다
        raise SystemExit("링크 번호를 정할 수 없다 — 이 덱을 만들지 않는다:\n" + "\n".join(links.errors))
    prefix = "" if syuka else None
    sponsor = S.sponsor_info(spec)   # 광고 회차면 구간의 쪽마다 오른쪽 위 띠
    visuals = render_visuals(spec, claims, out.parent / VISUALS_DIR)
    for idx, sl in enumerate(spec["slides"], 1):
        s = deck._blank(prs)
        pl = plan_slide(S.sponsor_view(S.with_links(sl, links.slides[idx - 1]) if links is not None else sl, sponsor, idx))
        waits = {str(c)[len(S.WAIT_IMAGE):] for c in pending.get(idx, []) if str(c).startswith(S.WAIT_IMAGE)}
        for im in pl.imgs:
            if im.kind in ("chart", "capture") and (idx, im.slot) in visuals:
                draw_visual(s, im, *visuals[(idx, im.slot)][:2], prefix=prefix)
            elif im.kind == "picture":
                draw_picture(s, im, pics.get(im.ref), im.ref in waits, prefix)
            else:
                draw_img(s, im, prefix)
        for b in pl.boxes:
            draw_box(s, b)
        for t in pl.tables:
            draw_table(s, t)
        ft = "" if syuka else footnote_text(sl, claims, card, labels)
        if ft:
            _footnote(s, ft)
        nt = notes_text(sl, claims, str(sl.get("stage")), pics)
        if idx in pending:
            band = [b.left for b in pl.boxes if b.name == BAND_NAME]
            draw_pending(s, pending[idx], right=band[0] - 0.12 if band else None)
            recs = [c for c in pending[idx] if not str(c).startswith(S.WAIT_IMAGE)]
            cap_waits = [c for c in waits if C.CLAIM_ID.match(c)]
            pic_waits = [c for c in waits if not C.CLAIM_ID.match(c)]
            nt = (f"{PENDING_MARK} 검증 전·대기 폴더 기록: {', '.join(recs)}\n" if recs else "") + \
                 (f"{WAIT_MARK} 원문 화면 그림이 아직 없다: {', '.join(sorted(cap_waits))}\n" if cap_waits else "") + \
                 (f"{WAIT_MARK} 그림 검수 기록이 다 차지 않았거나 쓰지 않는 그림이다: {', '.join(sorted(pic_waits))}\n" if pic_waits else "") + nt
        s.notes_slide.notes_text_frame.text = nt
    n_main = len(spec["slides"])
    appx = []
    views = {(i if j < 0 else (i, j)): v[2] for (i, j), v in visuals.items() if v[2] and v[2] != "chart"}
    for title, header, widths, rows in (appendix_tables(spec, claims, card, pending, views) if appendix and not syuka else []):
        pages = paginate(header, rows, widths)
        for k, t in enumerate(pages, 1):
            s = deck._blank(prs)
            marked = [r[0].split("\n")[0] for r in t.rows if PENDING_MARK in r[0]]
            if marked:  # 이 쪽 표에 검증 대기 행이 있으면 쪽 딱지도 붙인다(출처 표 = 클레임 약칭 · 시각물 표 = 원 슬라이드 번호)
                draw_pending(s, marked if header is SRC_HEADER else [f"{m}쪽" for m in marked])
            ttl = title + (f" ({k}/{len(pages)})" if len(pages) > 1 else "")
            draw_box(s, _title_box({"title": ttl}))
            draw_table(s, t, header_rgb=deck.BODY_RGB)
            if header is VC_HEADER:
                _footnote(s, VC_FOOT)
            if header is PIC_HEADER:
                _footnote(s, PIC_FOOT)
            if header is VIS_HEADER:
                _footnote(s, "역검색(Google Lens·TinEye) · 400% 확대 검수 · 지도 동해·독도·국경 표기는 사람이 확인하고 칸을 채운다. 공식 보도자료실·프레스킷·기관 CI·라이선스 스톡만 쓴다(방법론 5절).")
            s.notes_slide.notes_text_frame.text = f"[부록] {title} — 검증 기록(claims)과 사양의 그림 자리에서 자동으로 만들었다."
            appx.append(ttl)
    status = PIC.public_status(spec)
    kw = PIC.keywords_value(status, edition)
    if kw:   # 비공개 판 전용 그림이 든 덱 — 문서 속성에 표시를 남긴다(public-check 가 읽는다). 막는 그림이 없으면 속성을 건드리지 않는다
        prs.core_properties.keywords = kw
    deck.clear_template_props(prs)
    deck.finish_package(prs)   # 문서 통계를 실제 값으로, 틀의 축소 그림과 인쇄 설정 파일을 뗀다 — 이 뒤로는 pptx 를 다시 쓰지 않는다(등록 대장의 해시)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as staging:
        saved = pathlib.Path(staging) / out.name
        prs.save(str(saved))
        pptx_sha = file_sha256(saved)
        with _output_lock(out.parent):
            saved.replace(out)
            if source is None:
                (out.parent / "build_meta.json").unlink(missing_ok=True)
            else:
                _write_build_meta(out, source, pptx_sha, draft=draft, edition=edition)
    private = PIC.PRIVATE_KEYWORD in kw.split()
    return {"main": n_main, "appendix": appx, "total": n_main + len(appx), "pptx_sha256": pptx_sha} | ({"public_ok": False} if private else {}) | \
        ({"links": len(links.numbers)} if links is not None else {})


SPEAK_CHARS_PER_MIN = 300  # 발표 시간 어림 기준: 말로 할 문장(spoken·transition)의 공백을 뺀 글자 수 ÷ 분당 300자. 실측이 아니라 어림이다


def speech_estimate(slides: list) -> tuple[int, float]:
    """(말로 할 문장의 글자 수 — 공백 제외, 어림 발표 시간 분)."""
    n = sum(len(re.sub(r"\s+", "", t)) for sl in slides if isinstance(sl, dict) for t in S.spoken_text(sl))
    return n, n / SPEAK_CHARS_PER_MIN


def sponsor_line(spec: dict) -> str:
    """러닝시트 머리의 광고 구간 줄 — 구간의 쪽, 광고주, 종류, 표시 문구, 광고주 제공 자료. 광고 회차가 아니면 빈 문자열."""
    info = S.sponsor_info(spec)
    if info is None:
        return ""
    pg = info["pages"]
    span = "없음" if not pg else (f"{pg[0]}쪽" if len(pg) == 1 else f"{pg[0]}쪽~{pg[-1]}쪽") + f"({len(pg)}장" + (", 회차 전체" if info["whole"] else "") + ")"
    mats = info["materials"]
    return (f"**광고 구간: {span}** · 광고주: {info['sponsor']} · 종류: {info['kind']} · 표시 문구: {info['label']}. "
            f"구간의 장마다 오른쪽 위에 띠({info['band']})가 찍히고, 첫 장과 끝 장은 화면 글과 말로 할 문장에 표시 문구가 있다. "
            + (f"광고주 제공 자료 {len(mats)}건: {' / '.join(mats)}(링크 목록의 「광고주 제공 자료」 절 — 숫자의 근거가 아니다)." if mats else "광고주 제공 자료: 없음."))


def edition_line(spec: dict, edition: str, swaps: list[dict] | None, pair: str = "") -> str:
    """러닝시트 머리의 판 이름 한 줄."""
    from ozl.render import pictures as PIC
    pages = ", ".join(str(s["page"]) for s in swaps or [])
    mate = f" 짝 폴더: `{pair}`." if pair else ""
    if edition == PIC.EDITION_PRIVATE:
        ids = ", ".join(b["id"] for b in PIC.public_status(spec)["blocking"]) or "없음"
        return f"**판: {edition}** — 막는 그림({ids})이 든 판이다. 공개하지 않는다." + (f" 바꾼 판에서는 {pages}쪽이 바뀐다." if pages else "") + mate
    return f"**판: {edition}** — 비공개 판의 {pages or '(없음)'}쪽을 바꾼 판이다. 바꾼 장과 까닭은 그림 검수 대장의 「바꾼 장」 표에 있다." + mate


def running_sheet(spec: dict, card: dict, claims: dict, ts: str, pending: dict[int, list[str]] | None = None,
                  dropped: list[str] | None = None, edition: str | None = None, swaps: list[dict] | None = None, pair: str = "") -> str:
    """dropped = 엄격 모드에서 뺀 밈(pictures.drop_memes 의 글) — 머리에 적는다(조용히 빼지 않는다).
    edition = 판 이름(두 판 빌드) — 머리에 판 이름 한 줄을 적는다. 없으면 지금까지와 같은 글이다."""
    from ozl.render import pictures as PIC
    pending = pending or {}
    slides = spec["slides"]
    links = S.link_plan(spec, claims) if spec.get("style") == "syuka" else None   # 새 규칙: 근거 칸을 링크 번호로
    total = sum(int(sl.get("seconds") or 0) for sl in slides)
    why = str(spec.get("why_this") or "").strip()
    cited = {str(c) for sl in slides for c in sl.get("claim_ids") or []}
    machine = sorted(c for c in cited if C.grade_label(claims.get(c) or {}) == C.GRADE_MACHINE)
    basis = ("숫자는 전부 사람이 대조한 검증 기록(claim_id)에서만" if not machine else
             f"숫자는 전부 검증 기록(claim_id)에서만 — 사람 대조 '{C.GRADE_HUMAN}' {len(cited) - len(machine)}건 · 기계 대조 「{C.GRADE_MACHINE}」 {len(machine)}건"
             f"({', '.join(c.rsplit('-', 1)[-1] for c in machine)} · 사람이 원문을 본 것은 아니다)")
    lines = [
        f"# 러닝시트 — {card.get('card_id', spec.get('card_id'))}",
        "",
        f"왜 이 소재를 골랐는가: {why if why else '＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿ (지원자가 한 줄로 쓴다)'}",
        "",
        f"초안 {ts} · 본편 {len(slides)}장 · 예상 발화 {total // 60}분 {total % 60}초 · " + (basis if not pending else f"**초안 모드 — [검증 대기] 기록을 인용한 쪽 {len(pending)}장({', '.join(map(str, pending))}쪽). 엄격 모드를 통과하기 전에는 제출·발행하지 않는다**") + " · 말은 진행자 말투로 바꿔 읽어도 된다(수치·인용·단서는 그대로).",
        "",
        f"발표 시간 어림 {speech_estimate(slides)[1]:.1f}분(말로 할 문장 {speech_estimate(slides)[0]}자 · 기준 분당 {SPEAK_CHARS_PER_MIN}자, 공백 제외) · "
        f"인용한 검증 기록 {len(cited)}건",
        "",
    ] + ([edition_line(spec, edition, swaps, pair), ""] if edition else []) + ([sponsor_line(spec), ""] if sponsor_line(spec) else []) + \
        ([f"**{PIC.dropped_summary(dropped)}**", ""] if dropped else []) + [
        "## 장별 진행",
        "",
        "| 쪽 | 단계 | 제목과 말로만 할 핵심 문장 | 넘어가는 멘트 | 초 | " + ("근거(링크 번호)" if links is not None else "근거") + " | 그림 |",   # 제목 칸을 따로 두면 PDF 에서 글자 단위로 세로로 끊긴다
        "|---|---|---|---|---|---|---|",
    ]

    def cell(x):
        return str(x or "").replace("|", "／").replace("\n", " ").strip()

    t = 0
    for i, sl in enumerate(slides, 1):
        sec = int(sl.get("seconds") or 0)
        t += sec
        ids = (link_cell(sl, links) if links is not None else
               ", ".join(str(c).rsplit("-", 1)[-1] + (f"「{C.GRADE_MACHINE}」" if str(c) in machine else "") for c in sl.get("claim_ids") or [])) + \
            (" [검증 대기]" if any(not str(c).startswith(S.WAIT_IMAGE) for c in pending.get(i, [])) else "")
        waits = {str(c)[len(S.WAIT_IMAGE):] for c in pending.get(i, []) if str(c).startswith(S.WAIT_IMAGE)}
        head = f"**{cell(sl.get('title'))}** " if cell(sl.get('title')) else ""
        lines.append(f"| {i} | {cell(sl.get('stage'))} | {head}{cell(sl.get('spoken'))} | {cell(sl.get('transition'))} | {sec} | {ids} | {cell(visual_label(sl, waits=waits))} |")
    charts_ = [(page_label(i, j), v["chart"]) for i, sl in enumerate(slides, 1) for j, v in S.slot_views(sl) if S.visual_of(v) == "chart"]
    if charts_:
        lines += ["", "## 차트", ""]
        for i, ch in charts_:
            lines.append(f"- {i}쪽 차트({'선' if ch.get('kind') == 'line' else '막대'}) · 쓴 기록 "
                         f"{', '.join(str(c).rsplit('-', 1)[-1] for c in ch.get('claims') or [])}: {chart_limit(ch, claims)}")
    lines += ["", "## 단계별 시간", "", "| 단계 | 장수 | 초 |", "|---|---|---|"]
    agg: dict[str, list[int]] = {}
    order: list[str] = []
    for sl in slides:
        st = str(sl.get("stage"))
        if st not in agg:
            agg[st] = [0, 0]
            order.append(st)
        agg[st][0] += 1
        agg[st][1] += int(sl.get("seconds") or 0)
    for st in order:
        lines.append(f"| {st} | {agg[st][0]} | {agg[st][1]} |")
    if spec.get("qa"):
        lines += ["", "## 예상 돌발 질문", ""]
        for q in spec["qa"]:
            lines.append(f"- **{cell(q.get('q'))}** — {cell(q.get('a'))}")
    lines += ["", "## 쓰지 않는 말(카드 리스크에서)", ""]
    for r in card.get("risks") or []:
        lines.append(f"- {cell(r)}")
    return "\n".join(lines) + "\n"


def link_cell(sl: dict, links) -> str:
    """러닝시트 근거 칸(style: syuka): 이 쪽이 인용한 기록의 링크 번호 '[1] [3]'. 화면 수치를 받치지 않은 기록은 '기록 c5'(링크 목록의 따로 적은 절)."""
    out = []
    for c in sl.get("claim_ids") or []:
        n = links.numbers.get(str(c))
        out.append(f"[{n}]" if n else f"기록 {str(c).rsplit('-', 1)[-1]}")
    return " ".join(dict.fromkeys(out))


# ── 링크 목록(style: syuka — 쪽 아래 출처 줄과 부록 쪽 대신 덱 밖 파일) ─────────────────────
LINK_HEADER = ["번호", "쪽", "화면 표기", "기관·문서", "원본 링크", "문서 위치", "기준 시점", "기록 번호", "등급", "받은 시각", "같은 표기가 있는 다른 기록"]
LINK_MD_HEADER = ["번호", "쪽", "화면 표기", "기관·문서", "원본 링크", "문서 위치 · 기준 시점", "기록 · 등급", "받은 시각", "같은 표기 다른 기록"]


def _claim_row(cid: str, c: dict, card: dict | None, labels: dict) -> dict:
    src = c.get("source") or {}
    chk = c.get("checks") or {}
    ver = c.get("verification") if isinstance(c.get("verification"), dict) else {}
    cap = ver.get("capture") or {}
    name = S.short_source(cid, c, card, labels)
    pub = str(src.get("publisher") or "")
    return {"기관·문서": " · ".join(dict.fromkeys(x for x in (pub, name) if x)), "원본 링크": str(src.get("url") or ""),
            "문서 위치": locator_text(chk.get("primary_doc_locator")), "기준 시점": S.base_period_text(chk.get("base_period")),
            "기록 번호": cid, "등급": C.grade_label(c), "받은 시각": _fetched(cap.get("fetched_at")) or str(src.get("accessed") or "")}


def link_rows(spec: dict, claims: dict, card: dict | None, links) -> list[dict]:
    """링크 목록의 줄 — 번호마다 한 줄(번호 순서)."""
    labels = spec.get("source_labels") or {}
    rows = []
    for cid, n in sorted(links.numbers.items(), key=lambda kv: kv[1]):
        uses = links.uses.get(n, [])
        row = {"번호": str(n), "쪽": ", ".join(dict.fromkeys(pg for pg, _ in uses)), "화면 표기": " / ".join(dict.fromkeys(sh for _, sh in uses))}
        row.update(_claim_row(cid, claims.get(cid) or {}, card, labels))
        row["같은 표기가 있는 다른 기록"] = ", ".join(links.also.get(n, []))
        rows.append(row)
    return rows


def ref_rows(spec: dict, card: dict | None) -> list[dict]:
    """숫자 없이 인용한 보도와 자료(사양 refs) — 이름, 등급, 주소, 쪽."""
    by_name = {s.get("name"): s for s in spec.get("press_sources") or [] if isinstance(s, dict)}
    by_name.update({s.get("name"): s for s in (card or {}).get("sources") or [] if isinstance(s, dict)})
    pages: dict[str, list[str]] = {}
    for i, sl in enumerate(spec.get("slides") or [], 1):
        for ref in (sl.get("refs") or []) if isinstance(sl, dict) else []:
            pages.setdefault(str(ref), []).append(str(i))
    out = []
    for ref, pg in pages.items():
        x = by_name.get(ref) or {}
        out.append({"이름": ref, "구분": "자료" if x.get("tier") in S.DOC_TIERS else "보도", "등급": str(x.get("tier") or ""),
                    "주소": str(x.get("url") or ""), "쪽": ", ".join(dict.fromkeys(pg))})
    return out


def _md_cell(x) -> str:
    return str(x or "").replace("|", "／").replace("\n", " ").strip()


def links_md(spec: dict, claims: dict, card: dict | None, links, ts: str, ledger_name: str = "") -> str:
    rows = link_rows(spec, claims, card, links)
    cid = str(spec.get("card_id", ""))
    out = ["---", "kicker: 덱 링크 목록", f"date: {ts[:4]}-{ts[4:6]}-{ts[6:8]}", "theme: doc", "---", "",
           f"# 링크 목록 — {cid}", "",
           f"덱 {ts} 판의 화면 수치 뒤 작은 번호(차트·원문 캡처·표는 그 자리 오른쪽 아래 번호)가 아래 줄의 번호다. 번호는 기록마다 하나이고 덱에서 처음 나온 순서로 매겼다. "
           "같은 표기가 그 쪽의 다른 기록에도 있으면 사양이 지정한 기록(number_claims · conversions)이 번호를 받고, 나머지는 끝 칸에 적었다.", "",
           "| " + " | ".join(LINK_MD_HEADER) + " |", "|" + "---|" * len(LINK_MD_HEADER)]
    for r in rows:   # 읽는 판은 칸을 묶어 줄인다(기록 번호는 끝 번호만) — 칸마다 따로 쓰는 판은 csv
        short = r["기록 번호"].rsplit("-", 1)[-1]
        cells = [r["번호"], r["쪽"], r["화면 표기"], r["기관·문서"], r["원본 링크"], " · ".join(x for x in (r["문서 위치"], r["기준 시점"]) if x),
                 f"{short} · {r['등급']}", r["받은 시각"], ", ".join(x.rsplit("-", 1)[-1] for x in r["같은 표기가 있는 다른 기록"].split(", ") if x)]
        out.append("| " + " | ".join(_md_cell(x) for x in cells) + " |")
    if not rows:
        out.append("| " + " | ".join(["—"] + [""] * (len(LINK_MD_HEADER) - 1)) + " |")
    if links.unnumbered:
        out += ["", "## 화면 수치 없이 인용한 기록", "", "말로 할 문장이나 글의 근거로 인용했지만 화면에 그 기록의 수치가 없어 번호를 붙이지 않았다.", "",
                "| 기록 번호 | 쪽 | 기관·문서 | 원본 링크 | 등급 |", "|---|---|---|---|---|"]
        labels = spec.get("source_labels") or {}
        for c, pg in links.unnumbered.items():
            r = _claim_row(c, claims.get(c) or {}, card, labels)
            out.append(f"| {_md_cell(c)} | {', '.join(map(str, pg))} | {_md_cell(r['기관·문서'])} | {_md_cell(r['원본 링크'])} | {_md_cell(r['등급'])} |")
    refs = ref_rows(spec, card)
    out += ["", "## 숫자 없이 인용한 보도", ""]
    if refs:
        out += ["보도와 자료는 숫자의 근거가 아니다(기계 대조는 T1·T2 원문만). 화면에는 번호를 붙이지 않았다.", "",
                "| 이름 | 구분 | 등급 | 주소 | 쪽 |", "|---|---|---|---|---|"]
        out += [f"| {_md_cell(r['이름'])} | {r['구분']} | {_md_cell(r['등급'])} | {_md_cell(r['주소'])} | {r['쪽']} |" for r in refs]
    else:
        out.append("없음.")
    sponsor = S.sponsor_info(spec)
    if sponsor is not None:   # 광고 회차 — 광고주가 준 자료는 번호 줄과 섞지 않고 따로 적는다
        out += ["", "## 광고주 제공 자료", "",
                f"광고주({sponsor['sponsor']})가 준 자료다. 숫자의 근거가 아니다 — 화면과 말의 수치는 위 번호의 기록(원문)으로만 받쳤다. "
                "원문으로 받치지 못한 주장은 수치 없이 \"광고주 제공 자료에 따르면\"으로만 소개한다.", ""]
        out += [f"- {_md_cell(m)}" for m in sponsor["materials"]] or ["없음(광고주가 준 자료를 쓰지 않았다)."]
    out += ["", "## 그림 출처", ""]
    pics = picture_rows(spec)
    if pics:
        out.append("그림 파일마다 권리자, 라이선스, 원출처 대조, 맥락 점검, 공개 가부는 " + (f"`{ledger_name}`" if ledger_name else "그림 검수 대장") + " 에 있다.")
        out += ["", "| 그림 | 쪽 | 종류 | 출처 주소 |", "|---|---|---|---|"]
        out += [f"| {_md_cell(r[0])} | {_md_cell(r[1])} | {_md_cell(r[2])} | {_md_cell(r[5])} |" for r in pics]
    else:
        out.append("그림 파일 없음(차트와 원문 캡처는 위 번호의 기록에서 그렸다).")
    return "\n".join(out) + "\n"


def links_csv(spec: dict, claims: dict, card: dict | None, links) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(LINK_HEADER)
    for r in link_rows(spec, claims, card, links):
        w.writerow([r[h] for h in LINK_HEADER])
    return buf.getvalue()


def _labels(text: str) -> set[int]:
    return {int(x) for x in str(text).replace(" ", "").split(",") if x.isdigit()}


def screen_link_numbers(pptx: pathlib.Path) -> set[int]:
    """만든 pptx 에서 읽은 화면의 링크 번호 — 위첨자 조각(baseline 이 있는 글자 조각)과 '링크 번호' 글상자. 본편 쪽만 본다(노트 제외)."""
    from pptx import Presentation
    out: set[int] = set()
    for sld in Presentation(str(pptx)).slides:
        for sh in sld.shapes:
            if not sh.has_text_frame:
                continue
            if sh.name == "링크 번호":
                out |= _labels(sh.text_frame.text)
                continue
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    rpr = r._r.find(qn("a:rPr"))
                    if rpr is not None and rpr.get("baseline") not in (None, "0"):
                        out |= _labels(r.text)
    return out


def link_pair_errors(screen: set[int], listed: set[int]) -> list[str]:
    """양쪽 대응: 화면의 모든 번호가 목록에 있고, 목록의 모든 줄이 화면 어딘가에서 쓰인다."""
    out = []
    if screen - listed:
        out.append(f"화면에 있는 링크 번호 {sorted(screen - listed)} 가 링크 목록에 없다")
    if listed - screen:
        out.append(f"링크 목록의 번호 {sorted(listed - screen)} 가 화면 어느 쪽에도 없다")
    return out


def resolve_card(card_id) -> dict:
    """card_id 는 형식이 맞고 카드 정본이 실제로 있어야 한다(없는 카드를 빈 카드로 대신하지 않는다)."""
    if not card_id or not C.CARD_ID.match(str(card_id)):
        raise SystemExit(f"card_id '{card_id}' 가 카드 ID 형식(YYYY-MM-DD-am|pm|wk-NN)이 아니다")
    if not C.card_path(str(card_id)).exists():
        raise SystemExit(f"카드 {card_id} 가 없다({C.card_path(str(card_id))})")
    return C.load_card(str(card_id))


def out_paths(card_id: str, ts: str, draft: bool, edition: str | None = None) -> tuple[pathlib.Path, pathlib.Path]:
    stem = f"{card_id}_{ts}" + (f"_{edition}" if edition else "") + ("_draft" if draft else "")
    raw = DRAFTS / stem
    outdir = raw.resolve()
    if outdir.parent != DRAFTS.resolve():
        raise SystemExit(f"출력 경로 {outdir} 가 {DRAFTS} 바로 아래가 아니다")
    if raw.is_symlink() or raw.exists():
        raise SystemExit(f"출력 폴더 {raw} 가 이미 있다(링크 포함) — 덮어쓰지 않는다")
    return outdir, outdir / f"{stem}.pptx"


def safe_new_file(outdir: pathlib.Path, path: pathlib.Path) -> pathlib.Path:
    """최종 출력 파일은 새 폴더 바로 아래의 새 파일이어야 한다. 이미 있거나(링크 포함) 실제 경로가 폴더 밖이면 거부한다."""
    if path.is_symlink() or path.exists():
        raise SystemExit(f"출력 파일 {path} 가 이미 있다(링크 포함) — 덮어쓰지 않는다")
    if path.resolve().parent != outdir.resolve():
        raise SystemExit(f"출력 파일 {path} 의 실제 경로가 {outdir} 밖이다")
    return path


PIC_PUBLIC_FILE = "공개_가부.json"   # pictures.PUBLIC_FILE 과 같다


def write_picture_files(sp: dict, outdir: pathlib.Path, led_md: pathlib.Path, ts: str, draft: bool,
                        edition: str | None = None, pair: str = "", swaps: list[dict] | None = None) -> dict:
    """그림_검수대장_<ts>.md · .json 과 공개_가부.json 을 쓴다(style: syuka 빌드와 두 판 빌드). 돌려주는 값은 빌드 출력 칸.
    edition 이 있으면 대장 머리에 판 이름과 「바꾼 장」 표를, 공개_가부.json 에 edition · pair(짝 폴더 이름) · swaps(바꾼 장 목록)를 더한다.
    비공개판은 막는 그림 목록이 비어도 public_ok 를 거짓으로 적는다."""
    from ozl.render import pictures as PIC
    status = PIC.public_status(sp)
    if edition == PIC.EDITION_PRIVATE:
        status = {**status, "public_ok": False}
    rows = PIC.ledger_report(sp, draft)
    cid = str(sp.get("card_id", ""))
    ed = {} if edition is None else {"edition": edition, "pair": pair, "swaps": swaps or []}
    led_md.write_text(PIC.ledger_md(rows, status, cid, ts, edition, swaps, pair), encoding="utf-8")
    led_md.with_suffix(".json").write_text(json.dumps({"card_id": cid, "built_at": ts, "draft": draft, **ed, "pictures": rows, "public": status},
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / PIC_PUBLIC_FILE).write_text(json.dumps({"card_id": cid, "built_at": ts, "draft": draft, **status,
                                                      "keywords": PIC.keywords_value(status, edition), **ed}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"picture_ledger": str(led_md), "public_ok": status["public_ok"],
            "public_blocking": ", ".join(b["id"] for b in status["blocking"]) or "없음"}


def registry_file() -> pathlib.Path:
    """빌드가 덧붙이는 비공개 등록 대장 — 산출 폴더(DRAFTS)의 윗 폴더에 둔다. 기본 자리에서는 pictures.REGISTRY 와 같다
    (private/outputs/decks/private_only_registry.jsonl). 시험이 DRAFTS 를 임시 폴더로 바꾸면 대장도 그 옆으로 간다(실제 대장을 건드리지 않는다)."""
    from ozl.render import pictures as PIC
    return DRAFTS.parent / PIC.REGISTRY_NAME


def register_private_outputs(sp: dict, outdir: pathlib.Path, pptx: pathlib.Path, ts: str) -> int:
    """비공개판의 막는 그림 파일과 그 판의 pptx · PDF · 막는 그림이 든 쪽의 PNG 의 sha256 을 등록 대장에 덧붙인다. 돌려주는 값 = 새로 적은 줄 수.
    지금 폴더에 있는 파일만 적는다 — 빌드가 중간에 멈췄을 때도 그때까지 만든 것을 적을 수 있게(_build_one 이 예외가 나도 부른다).
    쪽 PNG 는 막는 그림이 든 쪽만 적는다 — 그 밖의 쪽은 바꾼판의 같은 쪽과 그림이 같아서(바이트까지 같다) 적으면 바꾼판이 막힌다.
    쪽과 파일은 파일 이름 끝의 쪽 번호(pdftoppm 의 slide-03.png)로 맞춘다 — 쪽 PNG 가 덜 나온 채 멈췄어도 나온 쪽은 맞출 수 있다.
    이름에서 쪽 번호를 읽지 못하면 이름 순서로 맞추되, PNG 수가 본편 장수보다 적으면(쪽과 파일을 맞출 수 없다) 쪽 PNG 는 적지 않는다."""
    from ozl.render import pictures as PIC
    pics, _ = PIC.ledger(sp)
    cid = str(sp.get("card_id", ""))
    base = {"card_id": cid, "built_at": ts, "dir": outdir.name}
    rows = []
    pages: set[int] = set()
    for b in PIC.public_status(sp)["blocking"]:
        f = PIC.resolve_path(pics.get(b["id"]) or {})
        if f.is_file():
            rows.append({"sha256": PIC.file_sha256(f), "what": "막는 그림", "name": b["id"], **base})
        pages |= {int(str(pg).split()[0]) for pg in b.get("pages") or [] if str(pg).split()[0].isdigit()}
    for f, what in ((pptx, "pptx"), (pptx.with_suffix(".pdf"), "pdf")):
        if f.is_file():
            rows.append({"sha256": PIC.file_sha256(f), "what": what, "name": f.name, **base})
    pngs = sorted((outdir / (pptx.stem + "_png")).glob("*.png"))   # pdftoppm 이 쪽 번호를 같은 자릿수로 붙인다 — 이름 순서가 쪽 순서다
    numbered = {int(m.group(1)): f for f in pngs if (m := re.search(r"(\d+)$", f.stem))}
    if len(numbered) == len(pngs):
        by_page = numbered
    else:   # 이름에 쪽 번호가 없는 파일이 섞였다 — 다 나왔을 때만 이름 순서로 맞춘다
        by_page = dict(enumerate(pngs, 1)) if len(pngs) >= len(sp.get("slides") or []) else {}
    for i in sorted(pages):
        if i in by_page:
            rows.append({"sha256": PIC.file_sha256(by_page[i]), "what": "쪽 png", "name": f"{by_page[i].name}({i}쪽)", **base})
    return PIC.register_private(rows, registry_file())


def spec_copy_text(sp: dict, source: dict, ts: str, edition: str) -> str:
    """판의 사양 사본 — swap 을 떼거나(비공개판) 적용한(바꾼판) 뒤의 사양. compare <폴더> 와 검토자가 읽는다."""
    name = pathlib.Path(source["spec"]).name
    sha = source["spec_sha256"]
    head = (f"# 판의 사양 사본 — {sp.get('card_id', '')} · {ts} · {edition}\n"
            f"# 원래 사양: {name} (sha256 {sha[:16]}). build 가 썼다 — 고칠 때는 원래 사양을 고친다.\n")
    return head + yaml.safe_dump(sp, allow_unicode=True, sort_keys=False)


def build(spec_path: pathlib.Path, export: bool = True, draft: bool = False, claims_dirs=(), edition: str | None = None) -> dict:
    """사양 하나를 검사하고 만든다. 판을 가르지 않는 사양(막는 그림도 swap 도 없다, 또는 초안 모드)은 폴더 하나 — 돌려주는 값은 그 폴더의 출력 칸.
    두 판 사양(엄격 모드)은 같은 타임코드로 폴더 둘 — 돌려주는 값은 {"editions": {판 이름: 출력 칸}, "dropped": …}. edition 을 주면 그 판 하나만."""
    from ozl.render import pictures as PIC
    sp, source = _read_build_source(pathlib.Path(spec_path))
    dropped: list[str] = []
    if not draft:   # 완성본·공개용 판에는 밈을 넣지 않는다 — 빼고, 뺀 것을 출력과 러닝시트에 적는다
        sp, dropped = PIC.drop_memes(sp)
    card = resolve_card(sp.get("card_id"))
    claims, staged = S.load_claims(S.cited_ids(sp), claims_dirs)
    eds = S.check_editions(sp, claims, S.load_template(), card, layout_problems, draft=draft, staged=staged, appendix_fn=appendix_problems,
                           edition=edition)
    if not all(e.report.ok for e in eds):   # 한 판이라도 실패하면 어느 폴더도 만들지 않는다
        lines = [(f"[{e.name}] " if e.name else "") + x for e in eds for x in e.report.errors]
        raise SystemExit("사양 검사 실패 — build 하지 않는다:\n" + "\n".join(lines))
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(eds) == 1 and eds[0].name is None:
        return _build_one(eds[0].spec, eds[0].report, card, claims, ts, export, draft, dropped, source)
    cid = str(sp["card_id"])
    dirs = {e.name: out_paths(cid, ts, draft, e.name)[0] for e in eds}   # 만들기 전에 두 폴더 자리를 다 확인한다
    infos: dict[str, dict] = {}
    for e in eds:
        mate = next((d.name for n, d in dirs.items() if n != e.name), "")
        infos[e.name] = _build_one(e.spec, e.report, card, claims, ts, export, draft, dropped, source, edition=e.name, pair=mate, swaps=e.swaps)
    bad = []
    regs = [registry_file()] + PIC.registry_paths()
    for e in eds:   # 판의 표시와 public_check 의 판정이 어긋나면 생성기 결함이다 — 덱을 쓰지 말라고 멈춘다
        want = 1 if e.name == PIC.EDITION_PRIVATE or not PIC.public_status(e.spec)["public_ok"] else 0
        code, lines = PIC.public_check(dirs[e.name], registries=regs)
        infos[e.name]["public_check"] = code
        if code != want:
            bad.append(f"{e.name}: public_check 종료 {code}(기대 {want}) — " + " / ".join(x.strip() for x in lines))
    if bad:
        raise SystemExit("공개 가부 확인이 판과 어긋난다 — 이 덱을 쓰지 않는다:\n" + "\n".join(bad))
    out: dict = {"editions": infos}
    if dropped:
        out["dropped"] = dropped
    return out


def _build_one(sp: dict, rep, card: dict, claims: dict, ts: str, export: bool, draft: bool, dropped: list[str], source: dict,
               edition: str | None = None, pair: str = "", swaps: list[dict] | None = None) -> dict:
    """검사를 통과한 판 하나를 만든다. edition 이 없으면 지금까지의 빌드와 같은 폴더, 같은 파일이다.
    막는 그림이 든 판(비공개판, 막는 그림이 남은 초안 모드의 연습용 판)은 pptx 를 쓰기 시작한 뒤로 어디서 멈추든(내보내기의 시간 초과,
    도구 없음, 링크 번호 대응 실패, 중단) 그때까지 만든 파일을 등록 대장에 남긴다 — 등록이 빠지면 남은 PDF · 쪽 PNG 와 keywords 를 지운 사본이
    public_check 를 통과한다."""
    from ozl.render import pictures as PIC
    outdir, pptx = out_paths(str(sp["card_id"]), ts, draft, edition)
    outdir.mkdir(parents=False, exist_ok=False)
    md = outdir / f"running_sheet_{ts}{'_draft' if draft else ''}.md"
    for f in (pptx, md, pptx.with_suffix(".pdf"), md.with_suffix(".pdf"), outdir / (pptx.stem + "_png"), outdir / VISUALS_DIR):
        safe_new_file(outdir, f)
    syuka = sp.get("style") == "syuka"
    with_pics = syuka or edition is not None   # 그림 검수 대장과 공개 가부: 새 규칙 빌드와 두 판 빌드
    if with_pics:
        led_md = outdir / f"그림_검수대장_{ts}.md"
        extra = (led_md, led_md.with_suffix(".json"), led_md.with_suffix(".pdf"), outdir / PIC_PUBLIC_FILE)
        for f in extra:
            safe_new_file(outdir, f)
    if syuka:   # 새 규칙: 링크 목록을 덱과 같은 폴더에 낸다
        links_path = outdir / f"links_{ts}.md"
        for f in (links_path, links_path.with_suffix(".csv"), links_path.with_suffix(".pdf")):
            safe_new_file(outdir, f)
    if edition is not None:
        spec_copy = safe_new_file(outdir, outdir / f"spec_{ts}_{edition}.yaml")
    # 막는 그림이 든 판(비공개판, 그리고 막는 그림이 남은 초안 모드의 연습용 판) — 그림과 이 판 산출물의 해시를 등록 대장에 남긴다
    private = edition == PIC.EDITION_PRIVATE or not PIC.public_status(sp)["public_ok"]
    registered = 0
    try:
        info = build_pptx(sp, claims, card, pptx, rep.pending if draft else None, edition=edition)
        md.write_text(running_sheet(sp, card, claims, ts, rep.pending if draft else None, dropped, edition, swaps, pair), encoding="utf-8")
        info.update(dir=str(outdir), pptx=str(pptx), md=str(md), warnings=rep.warnings)
        if edition is not None:
            spec_copy.write_text(spec_copy_text(sp, source, ts, edition), encoding="utf-8")
            info.update(edition=edition, pair=pair, spec=str(spec_copy), swapped=len(swaps or []))
        if with_pics:
            info.update(write_picture_files(sp, outdir, led_md, ts, draft, edition, pair, swaps))
        if syuka:
            lp = S.link_plan(sp, claims)
            links_path.write_text(links_md(sp, claims, card, lp, ts, led_md.name), encoding="utf-8")
            links_path.with_suffix(".csv").write_text(links_csv(sp, claims, card, lp), encoding="utf-8-sig")
            pair_errs = link_pair_errors(screen_link_numbers(pptx), set(lp.numbers.values()))
            if pair_errs:   # 화면과 목록이 같은 계획에서 나오므로 어긋나면 생성기 결함이다 — 덱을 쓰지 말라고 멈춘다
                raise SystemExit("링크 번호 양쪽 대응 실패 — 이 덱을 쓰지 않는다:\n" + "\n".join(pair_errs))
            info.update(links=str(links_path), links_csv=str(links_path.with_suffix(".csv")), link_count=len(lp.numbers))
        if dropped and edition is None:
            info["dropped"] = dropped
        if draft:
            info["pending_slides"] = len(rep.pending)
        if export:
            pdf, pngs = deck.to_pdf_png(pptx)
            info.update(pdf=str(pdf) if pdf else None, pngs=len(pngs))
            if MD2PDF.exists():
                r = subprocess.run(["python3", str(MD2PDF), str(md), "--theme", "doc", "--footer-title"], capture_output=True, text=True, timeout=300)
                info["sheet_pdf"] = str(md.with_suffix(".pdf")) if md.with_suffix(".pdf").exists() else f"실패: {(r.stderr or r.stdout)[-300:]}"
                if with_pics:
                    r = subprocess.run(["python3", str(MD2PDF), str(led_md), "--theme", "doc", "--footer-title"], capture_output=True, text=True, timeout=300)
                    info["picture_ledger_pdf"] = str(led_md.with_suffix(".pdf")) if led_md.with_suffix(".pdf").exists() else f"실패: {(r.stderr or r.stdout)[-300:]}"
                if syuka:
                    r = subprocess.run(["python3", str(MD2PDF), str(links_path), "--theme", "doc", "--footer-title"], capture_output=True, text=True, timeout=300)
                    info["links_pdf"] = str(links_path.with_suffix(".pdf")) if links_path.with_suffix(".pdf").exists() else f"실패: {(r.stderr or r.stdout)[-300:]}"
    finally:
        if private:   # 예외로 나가는 길에서도 — 그때까지 만든 pptx · PDF · 쪽 PNG 와 막는 그림 파일을 적는다(끝까지 갔으면 PDF 와 쪽 PNG 까지)
            registered = register_private_outputs(sp, outdir, pptx, ts)
    if private:
        info["registered"] = registered
    with _output_lock(outdir):
        _write_build_meta(pptx, source, info["pptx_sha256"], draft=draft, edition=edition)
    return info
