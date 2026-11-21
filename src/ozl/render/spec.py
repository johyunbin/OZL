#!/usr/bin/env python3
"""덱 사양(YAML) 읽기와 검사 — 슬라이드 초안의 결정적 앞단.

사양은 사람이(또는 대화 세션의 모델이) 카드와 클레임을 읽고 직접 쓴다. 이 모듈은 문장을 짓지 않고 검사만 한다.

검사 항목
  ① 숫자 규칙: 슬라이드에 보이는 숫자는 그 슬라이드가 인용한 클레임(사람 대조 `human_verified: true` 또는 기계 대조 「원문 일치」)의 `observed`·`text` 에 같은 표기로 있어야 한다.
     - 숫자가 있는데 `claim_ids` 가 없으면 실패
     - 인용한 클레임이 없거나, 사람 대조 전이면서 「원문 일치」도 아니면 실패
     - 표기가 원문에 없으면 실패. 단위를 바꿔 적었으면 `conversions`(보이는 표기 · 원문 표기 · 클레임 · 환산 근거)를 적어야 통과
     - 숫자 판독(토큰 종류·부호·범위·면제·못 잡는 것)은 numbers.py 머리말이 정본이다. 달력·식별자는 대조하지 않고, 수량·기간·수량 낱말은 대조한다
     - 환산 원문(source)은 기록 안의 완전한 숫자 토큰이어야 한다(복합 수량의 조각·숫자 없는 말은 안 된다)
  ② 단계 순서: 구성 템플릿(tracks/syuka/style/composition_template_v0.json)의 단계 위치 중앙값 순서를 거꾸로 가면 실패.
     전개·반전·여담은 한 편에 여러 번 나오는 단계라 중간 어디에나 둘 수 있다. 첫 단계는 여는 장(또는 우회 도입), 마지막은 닫는 장이나 시사점.
  ③ 글 배치: 어절 단위로 줄을 나눈 결과가 글상자 줄 수를 넘거나, 제목이 한 줄을 넘으면 실패.
  ④ 그림(chart · capture): 그림 자리가 있는 종류(VISUAL_KINDS)에서 image·chart·capture 가운데 하나만 쓴다.
     - chart: charts.validate_chart 오류 · chart.claims 는 그 쪽 claim_ids 안 · 그림에 찍히는 수량(chart_quantities)은 ①과 같은 규칙
       · 그려지는 모든 점의 값(꼬리표가 없는 점 포함)은 chart.claims 가운데 한 기록의 원문 사본 글에 그 표기로 있어야 한다
         (capture.find_value — 공백으로 나뉜 낱말 하나와 글자 그대로 같아야 한다. '-0.8%' 안의 '0.8%', '3%~5%' 안의 '5%', '4명이다.' 안의 '4명'은
         찾은 것이 아니다. 바로 앞 낱말이 부호·범위 이음만이거나 바로 뒤 낱말이 범위 이음만이면 세지 않는다). 사본이 없는 기록(사람이 대조한 옛 기록)은
         observed·text 에서 같은 함수로 찾는다.
       · 못 하는 것: 값이 사본에 있는지만 프로그램이 봤다. 칸(어느 달·어느 항목)과 값의 짝은 문장 대조에서 본다.
         세로축 눈금 숫자는 대조하지 않는다(자료가 아니라 축척이다). y_from_zero: false 는 러닝시트에 적힌다.
     - capture: <claim_id> — 그 기록의 원문 캡처. 빌드 때 해시가 확인된 사본에서 대조한 자리(match.target)의 그림을 새로 그린다
       (verification.image 는 미리 보기일 뿐 쓰지 않는다). claim_ids 안이어야 하고, 엄격 모드는 받는 기록(acceptance_error 빈 문자열)이며
       사본이 그림을 그릴 수 있고(copy_source 통과) 대조한 자리가 하나로 정해져야 하며, 사본 글의 대목 그림이면 대조한 문구 전체가 그림 자리에
       들어가야 한다(글자 크기를 최소까지 줄여도 안 들어가면 실패). 초안 모드는 기록이 아직 받아들여지지 않으면
       그 쪽을 '그림 대기'로 표시한다(pending 에 '그림:<claim_id>').
     - 엄격 모드에서 image_text 쪽에 그림이 하나도 없으면 경고(글만 있는 장이 의도일 수 있어 실패는 아니다).
     - picture: <그림 번호> — 사양 맨 위 pictures(그림 검수 대장 · pictures.py)에 오른 그림 파일. 칸이 비었거나 판정이 '쓰지 않는다'거나 파일이 없으면
       엄격 모드 실패, 초안 모드는 그림 대기('그림:<그림 번호>'). 밈은 엄격 모드에서 빠진다(pictures.drop_memes — check·build 명령이 먼저 뺀다).
       판정 '비공개 판에서만'(보도 사진 등)은 두 모드 모두 통과하지만 덱이 공개 불가가 된다(pictures.public_status). 원문 화면 갈무리는
       그 쪽 claim_ids 기록의 원문과 같은 기관 호스트여야 한다(pictures.screen_host_errors).
  ⑤ 새 종류(2026-11-14):
     - capture_full(인용 장): title + capture(+capture_focus). 본문 글이 없고 원문 캡처가 쪽 대부분을 차지한다. 캡처 규칙은 ④와 같고,
       '다 들어가는가'는 큰 자리의 크기(capture_geom)로 계산한다.
     - photo_caption(사진과 설명): title + caption(한두 줄) + image 또는 picture 하나. caption 의 수량은 ①을 받는다.
     - image_pair(그림 두 장 비교): title + pair(자리 둘 — 각각 image·chart·capture·picture 가운데 하나와 짧은 caption). 자리마다 ④를 그대로 본다
       (chart.claims · capture 는 쪽의 claim_ids 안). 그림 칸은 쪽에 두지 않고 pair 의 각 자리에 둔다.
  ⑥ 2026-11-15 새 종류와 style 칸:
     - full_picture(제목 없는 꽉 찬 그림): 그림 자리 하나(+ 그림 안 아래 한마디 caption 한 줄). title·body 를 두면 실패.
     - image_stack(그림 위 글 아래): title + 넓은 그림 자리 + body 1~3줄.
     - 사양 맨 위 style: syuka 면 style.style_check(장당 초 · 장 체류 · 본문 줄 · 장 모양 비율)를 더한다. 없으면 옛 규칙 그대로(seconds 가 비면 경고만).
     - style: syuka 는 쪽 아래 출처 줄과 부록 쪽을 두지 않는다. 화면 수치마다 받치는 기록(number_sources)에 덱 전체 링크 번호(link_plan)를 주고,
       넘침 검사는 번호 위첨자까지 넣은 쪽으로 본다. 인용한 기록에 원본 링크(source.url)가 없으면 실패(link_errors).
     - 수치 자리마다 기록 하나로 이어져야 한다. 같은 표기가 그 쪽이 인용한 기록 둘 이상에 있으면 코드가 고르지 않는다(claim_ids 의 앞 기록으로
       잇지 않는다): 환산(conversions)이 그 표기의 기록을 지정했으면 그 기록, 장의 number_claims 칸이 자리를 지정했으면 그 기록을 따르고,
       어느 쪽도 없으면 '정할 수 없다'로 실패한다. number_claims: [{shown: 화면 표기, claim_id: 기록, at: 칸 이름(생략하면 그 쪽의 그 표기 전부),
       nth: 그 칸에서 몇 번째 그 표기인가(생략하면 그 칸의 그 표기 전부 — at 과 함께만 쓴다)}]. 칸 이름은 field_name 이 정한다
       (title · sub · en · ko · caption · number.value · number.label · quote.text · quote.by · body[0] · pair[0].caption · table · image · pair[0].image).
     - 링크 번호를 붙이지 않는 표기(link_skip): 분모 꼴(「1인당」「100명당」「1곳당」 — 수 뒤에 단위와 '당')과 차례 꼴(「제2」「3번째」「2차」).
       숫자 대조(number_errors)는 그대로 받고 번호만 붙이지 않는다. 그 자리에서는 '받치는 기록이 둘 이상' 실패도 내지 않는다(이을 번호가 없다).
       한 쪽에서 같은 표기와 같은 번호가 되풀이되면 처음 자리에만 붙인다(link_plan).
  ⑦ 두 판(2026-11-15): 막는 그림(pictures.edition_block — 판정 '비공개 판에서만' 또는 권리 확인 대기)이 든 사양은 장마다 swap 칸을 두고
     check_editions 가 비공개판(swap 을 뗀 사양)과 바꾼판(swap 을 적용한 사양)을 따로 검사한다. check 는 판 하나의 사양만 받는다 —
     swap 칸이 남은 사양이 직접 들어오면 실패로 알린다. 규칙은 pictures.py 머리말(두 판과 공개 차단)에 있다.

  ⑧ 광고 칸(2026-11-15 — sponsorship_errors): 사양 맨 위 sponsorship{kind, sponsor, label, whole, materials} 와 장의 stage: 광고.
     - 실패: stage: 광고 장이 있는데 칸이 없거나 그 반대(whole 이 참이면 광고 장이 없어도 된다 — 회차 전체가 구간이다). kind 가 SPONSOR_KINDS 밖.
       sponsor · label 이 빔. label 에 한글이 없거나 '광고' · '협찬' 낱말이 없거나 그것을 부정하는 말(없음, 아님 등)이 있음. 구간이 한 덩어리가 아님(whole 제외).
       구간 첫 장과 끝 장의 화면 글에 label 과 sponsor 가 없음, 말로 할 문장에 label 이 없음. 구간 장수가 광고 아닌 장수의 20% 를 넘음(whole 제외).
       구간이 여는 장보다 앞에 옴(whole 제외). 권리자 칸에 sponsor 이름이 든 그림의 종류가 기업 뉴스룸이나 로고가 아님.
     - 단계 순서(stage_errors)는 광고 장을 뺀 순서로 본다(cards.STAGES 와 구성 템플릿 JSON 은 그대로다).
     - 구간의 장마다 빌드가 오른쪽 위에 띠(label · sponsor)를 그린다. 띠도 넘침 검사를 받는다(SPONSOR_KEY 를 넣은 쪽 사본으로 본다).
     - 코드가 보지 않는 것: 광고주 자료에만 있는 주장이 문장에 들어갔는가, 금지 문장(경쟁사 깎아내리기, 원문 없는 최상급, 효과 보장). 문장 대조가 본다.
  ⑨ capture_full 은 capture 대신 원문 화면 갈무리 종류의 picture 도 받는다(제목 한 줄과 큰 화면 한 장). 그림 파일은 자리 넓이의 절반을 채우지 못하면 경고,
     원문 화면 갈무리는 shot_log 로 어림한 글자 크기가 기준보다 작으면 경고(pictures.placement_warnings — 기준은 style.py).

    python -m ozl.render check <사양.yaml>
"""
from __future__ import annotations

import json
import math
import pathlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from ozl.research import cards as C

ROOT = pathlib.Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "tracks" / "syuka" / "style" / "composition_template_v0.json"
SPECS = ROOT / "private" / "decks" / "specs"

KINDS = ("title_hook", "image_text", "quote_translation", "number", "compare_table", "quote_line", "closing",
         "capture_full", "photo_caption", "image_pair", "full_picture", "image_stack")
STYLES = ("syuka",)   # 사양 맨 위 style — 있으면 그 규칙의 검사를 더한다(style.style_check). 없으면 2026-11-14 까지의 규칙 그대로
SIDE_KINDS = ("image_text", "number", "quote_translation")

# 카드 어휘(cards.STAGES) → 구성 템플릿 JSON 의 단계 키
STAGE_KEY = {
    "여는 장": "hook", "우회 도입": "lead_in", "배경": "background", "근거 수치": "data", "전개": "development",
    "반전": "turn", "비교": "comparison", "시사점": "implication", "해법": "solution", "여담": "digression", "닫는 장": "closing",
}
REPEATABLE = {"development", "turn", "digression"}  # 템플릿 v0: 전개 편당 3.4번 · 반전 지점 편당 5곳 · 여담은 끼어드는 단계
OPENERS, ENDERS = {"hook", "lead_in"}, {"closing", "implication"}


# ── 숫자 ────────────────────────────────────────────────────────────────
# 판독은 numbers.py 한 곳에서 한다(토큰 종류를 먼저 가르고 직접 대조와 환산 경계 검사가 같은 결과를 쓴다).
from ozl.render import numbers as N  # noqa: E402

SEP = "\n¶\n"  # 칸과 칸 사이 — 한 칸 끝의 수량이 다음 칸 첫 숫자와 이어 읽히지 않게


def numeric_tokens(text, exempt: bool = True, identifiers=()) -> list[str]:
    """대조할 숫자 표기의 정규형 목록. exempt=False 면 달력·식별자까지 숫자가 든 토큰을 모두 낸다."""
    toks = N.scan(text, identifiers)
    if exempt:
        return [t.canon for t in toks if t.needs_claim]
    return [t.canon for t in toks if any(c.isdigit() for c in t.canon)]


def basis_texts(claim: dict) -> list[str]:
    """숫자 근거가 되는 글. 사람이 대조한 기록과 옛 기록은 observed·text 둘 다(사람이 문장까지 보았다).
    기계 대조 기록(`verification` 묶음이 있고 사람 대조는 아닌 것)은 사본과 대조한 observed 만 —
    text 는 쓴 쪽의 문장이고 프로그램이 원문과 견준 적이 없다."""
    if claim.get("human_verified") is not True and isinstance(claim.get("verification"), dict):
        return [_s(claim.get("observed"))]
    return [_s(claim.get("observed")), _s(claim.get("text"))]


def source_tokens(claim: dict) -> set[str]:
    return N.pool(*basis_texts(claim))


def _s(v) -> str:
    return "" if v is None else str(v)  # 0 · False 도 글자로 남긴다


def visible_text(sl: dict) -> list[str]:
    """슬라이드(와 그 그림 자리·시각물 부록)에 실제로 찍히는 글. 발표자 노트(notes)는 뺀다."""
    out = [_s(sl.get("title"))]
    out += [_s(x.get("text") if isinstance(x, dict) else x) for x in sl.get("body") or []]
    for k in ("en", "ko", "sub"):
        out.append(_s(sl.get(k)))
    num = sl.get("number")
    if isinstance(num, dict):
        out += [_s(num.get("value")), _s(num.get("label"))]
    tbl = sl.get("table")
    if isinstance(tbl, dict):
        out += [_s(x) for x in tbl.get("header") or []]
        for row in tbl.get("rows") or []:
            out += [_s(x) for x in (row if isinstance(row, list) else [row])]
    q = sl.get("quote")
    if isinstance(q, dict):
        out += [_s(q.get("text")), _s(q.get("by"))]
    out.append(_s(sl.get("caption")))   # photo_caption 의 설명
    img = sl.get("image")
    if isinstance(img, dict):
        out += [_s(img.get("caption")), _s(img.get("what")), _s(img.get("source"))]
    if sl.get("kind") == "image_pair":   # 두 자리의 설명과 회색 자리 글
        for _, v in slot_views(sl):
            out.append(_s(v.get("caption")))
            im = v.get("image")
            if isinstance(im, dict):
                out += [_s(im.get("caption")), _s(im.get("what")), _s(im.get("source"))]
    return [t for t in out if t != ""]


def spoken_text(sl: dict) -> list[str]:
    """방송에서 소리 내어 말할 글 — 화면 글과 같은 숫자 규칙을 받는다."""
    return [_s(sl.get(k)) for k in ("spoken", "transition") if _s(sl.get(k))]


def acceptance_error(c: dict) -> str:
    """엄격 모드가 이 기록을 받지 않는 까닭. 빈 문자열이면 받는다.
    받는 기록 = 사람이 대조해 verified 가 됐거나('확인'), 기계 대조로 「원문 일치」가 됐고 **지금 다시 검사해도** 증거가 맞는 것.
    사람이 대조했어도 상태가 verified 가 아니면(단독·추정 — 보도 등) 숫자 근거로 받지 않는다(2026-11-13 문서·코드 대조).
    기록 파일에 verified 라고 적혀 있다는 것만으로는 받지 않는다 — 사본 해시, 문구, 재대조 대목을 쓸 때마다 다시 본다."""
    if c.get("human_verified") is True:
        if c.get("status") != "verified":
            return f"사람이 대조했지만 상태가 '{C.BADGE_KO.get(c.get('status'), c.get('status'))}' 다(verified 아님) — 숫자 근거로 쓰지 않는다"
        return ""
    if C.grade_label(c) != C.GRADE_MACHINE:
        return f"사람 대조 전이다(human_verified 아님 · 「{C.GRADE_MACHINE}」도 아님)"
    errs = C.machine_check(c, fresh=False)[0] or C.validate_claim(c, deep=True)   # 등급을 올릴 때 본 것을 쓸 때도 전부 다시 본다
    return f"「{C.GRADE_MACHINE}」 기록인데 지금 다시 검사하니 증거가 맞지 않는다 — {errs[0]}" if errs else ""


def accepted(c: dict) -> bool:
    return not acceptance_error(c)


def claim_state_errors(ids: list[str], claims: dict[str, dict], draft: bool = False, staged: set[str] | None = None) -> tuple[list[str], list[str]]:
    """(실패, 검증 대기 claim_id). 엄격 모드: 없거나 사람 대조 전(「원문 일치」도 아님)이거나 대기 폴더(--claims-dir) 기록이면 실패.
    초안 모드: 기록이 있기만 하면 되고, 사람 대조 전·대기 폴더 기록은 '검증 대기'로 돌려준다."""
    errs, pending = [], []
    staged = staged or set()
    for cid in ids:
        c = claims.get(cid)
        if c is None:
            errs.append(f"클레임 {cid} 를 찾지 못했다")
            continue
        why = acceptance_error(c)
        unverified = bool(why)
        if not draft:
            if cid in staged:
                errs.append(f"클레임 {cid} 는 대기 폴더(--claims-dir)의 기록이다 — 초안 모드(--draft)에서만 쓸 수 있다")
            elif unverified:
                errs.append(f"클레임 {cid} 는 {why}")
        elif unverified or cid in staged:
            pending.append(cid)
    return errs, pending


def number_errors(sl: dict, claims: dict[str, dict], draft: bool = False, staged: set[str] | None = None, extra_screen: list[str] | None = None,
                  identifiers=()) -> list[str]:
    """숫자 규칙 세 가지 + 인용 클레임 상태. 화면 글(각주에 찍히는 source_labels·refs 포함)과 말로 할 문장(spoken·transition)을 같은 규칙으로 본다."""
    ids = [str(x) for x in sl.get("claim_ids") or []]
    errs, _ = claim_state_errors(ids, claims, draft, staged)
    screen = SEP.join(visible_text(sl) + list(extra_screen or []))
    said = SEP.join(spoken_text(sl))
    both = screen + SEP + said
    covered: set[str] = set()
    for i, cv in enumerate(sl.get("conversions") or []):
        shown, src, cid, basis = (_s(cv.get(k)).strip() for k in ("shown", "source", "claim_id", "basis"))
        where = f"conversions[{i}]"
        if not (shown and src and cid and basis):
            errs.append(f"{where}: shown·source·claim_id·basis 넷 다 있어야 한다")
            continue
        own = N.complete_in(shown, both, need_digits=False, identifiers=identifiers)
        if own is None:
            errs.append(f"{where}: 보이는 표기 '{shown}' 가 슬라이드 글·말에 완전한 수량으로 없다")
            continue
        if cid not in ids:
            errs.append(f"{where}: {cid} 가 이 슬라이드의 claim_ids 에 없다")
            continue
        c = claims.get(cid) or {}
        if all(N.complete_in(src, b, True) is None for b in basis_texts(c)):
            errs.append(f"{where}: 원문 표기 '{src}' 가 {cid} 의 observed·text 에 완전한 수량 토큰으로 없다(숫자가 든 토큰 전체여야 한다)")
            continue
        covered |= {t.canon for t in own if t.needs_claim}
    pl: set[str] = set()
    for cid in ids:
        if cid in claims:
            pl |= source_tokens(claims[cid])
    for label, text in (("화면", screen), ("말로 할 문장(spoken·transition)", said)):
        toks = list(dict.fromkeys(t.canon for t in N.claim_tokens(text, identifiers)))
        if not toks:
            continue
        frag = [t[1:] for t in toks if t.startswith("?")]
        if frag:  # 판독부가 통째로 읽지 못한 표기 — 근거가 있어도 맞춰 볼 수 없다
            errs.append(f"{label}의 숫자 표기 {frag} 를 온전한 수량으로 읽지 못했다 — 앞뒤에 숫자 이음이 남았다. 표기를 한 덩어리로 고쳐 쓰거나 나눠 쓴다")
        toks = [t for t in toks if not t.startswith("?")]
        if not toks:
            continue
        if not ids:
            errs.append(f"{label}에 숫자·수량({', '.join(toks)})이 있는데 claim_ids 가 없다")
            continue
        missing = [t for t in toks if t not in pl and t not in covered]
        if missing:
            errs.append(f"{label}의 숫자·수량 {missing} 가 인용한 클레임({', '.join(ids)})의 observed·text 에 없다 — 같은 표기로 쓰거나 conversions 에 환산 근거를 적는다")
    return errs


# ── 그림(차트 · 원문 캡처) ───────────────────────────────────────────────
VISUAL_KEYS = ("image", "chart", "capture", "picture")
# 종류마다 그림 자리에 쓸 수 있는 칸(build.plan_slide 가 자리를 둔다). image_pair 는 pair 의 두 자리 각각에 적용한다.
#   image_text · number = 왼쪽 그림 자리(deck.IMG_W × IMG_H) · photo_caption = 큰 그림 하나 · capture_full = 쪽 대부분을 차지하는 원문 캡처
SLOT_KEYS = {
    "image_text": VISUAL_KEYS, "number": VISUAL_KEYS, "image_pair": VISUAL_KEYS,
    "photo_caption": ("image", "picture"), "capture_full": ("capture", "picture"),   # picture 는 원문 화면 갈무리 종류만(picture_errors)
    "full_picture": VISUAL_KEYS, "image_stack": VISUAL_KEYS,   # 2026-11-15 — 제목 없는 꽉 찬 그림 · 그림 위 글 아래
}
PICTURE_FIRST = ("photo_caption", "image_pair", "full_picture", "image_stack")   # 그림이 주인공인 종류 — 그림 자리가 비면 실패, 엄격 모드는 회색 자리도 실패
VISUAL_KINDS = tuple(SLOT_KEYS)
WAIT_IMAGE = "그림:"  # 초안 모드 pending 항목 머리 — '그림:<claim_id>' = 원문 화면 그림 대기 · '그림:<그림 번호>' = 검수 기록이 다 차지 않은 그림 파일


def visual_of(sl: dict) -> str:
    """이 쪽(또는 image_pair 의 한 자리) 그림 자리에 들어갈 것: 'chart' · 'capture' · 'picture'(검수 대장의 그림 파일) · 'image'(종전 회색 자리) · ''(없음).
    둘 이상이면 앞의 것(검사가 실패시킨다)."""
    for k in ("chart", "capture", "picture", "image"):
        if sl.get(k) not in (None, "", {}, []):
            return k
    return ""


def slot_views(sl: dict) -> list[tuple[int, dict]]:
    """그림 자리마다 (자리 번호, 검사·빌드가 쪽처럼 다룰 사전). image_pair 는 (0, 왼쪽) · (1, 오른쪽) — 쪽의 kind 와 claim_ids 를 물려받는다.
    밈을 뺀 자리(pictures.DROPPED)와 사전이 아닌 자리는 건너뛴다. 그 밖의 종류는 [(-1, 쪽 자체)]."""
    from ozl.render import pictures as PIC
    if sl.get("kind") != "image_pair":
        return [(-1, sl)]
    out = []
    pair = sl.get("pair")
    for j, slot in enumerate(pair if isinstance(pair, list) else []):
        if isinstance(slot, dict) and PIC.DROPPED not in slot:
            out.append((j, {**slot, "kind": "image_pair", "claim_ids": sl.get("claim_ids") or []}))
    return out


SLOT_NAME = {-1: "", 0: "왼쪽 자리", 1: "오른쪽 자리"}


def copy_text(c: dict) -> tuple[bool, str | None, str]:
    """기록의 원문 사본 글. (사본 묶음이 있는가, 글 | None, 못 읽은 사유). cards.copy_text 그대로 —
    machine_check 와 같은 한 길(경로 규칙 · 재해시 · 종류 재판별 · 추출 캐시)로 읽는다."""
    return C.copy_text(c)


def point_notation(pt) -> str:
    """대조할 점 값의 표기: 표시 문자열(셋째 칸)이 있으면 그것, 없으면 입력 값의 표기(문자열은 그대로, 수는 str)."""
    if len(pt) >= 3 and isinstance(pt[2], str) and pt[2].strip():
        return pt[2].strip()
    v = pt[1]
    return v.strip() if isinstance(v, str) else str(v)


def chart_screen_text(sl: dict) -> list[str]:
    """차트 그림에 글자로 찍히는 수량(charts.chart_quantities) — number_errors 의 화면 글에 더한다. 사양 오류면 빈 목록(오류는 chart_errors 가 낸다)."""
    from ozl.render import charts as G
    out: list[str] = []
    for _, v in slot_views(sl):
        ch = v.get("chart")
        if isinstance(ch, dict) and not G.validate_chart(ch):
            out += list(G.chart_quantities(ch))
    return out


def chart_errors(sl: dict, claims: dict[str, dict]) -> list[str]:
    from ozl.research import capture as K
    from ozl.render import charts as G
    ch = sl.get("chart")
    errs = [f"chart: {e}" for e in G.validate_chart(ch)]
    if errs:
        return errs
    ids = [str(x) for x in sl.get("claim_ids") or []]
    used = [str(x) for x in ch["claims"]]
    out_ids = [c for c in used if c not in ids]
    if out_ids:
        errs.append(f"chart.claims {out_ids} 가 이 쪽의 claim_ids 에 없다 — 차트가 쓴 기록은 그 쪽이 인용한 기록이어야 한다")
    texts: list[tuple[str, str]] = []   # (claim_id, 대조할 글) — 사본이 있으면 사본 글, 없으면 observed·text
    for cid in used:
        c = claims.get(cid)
        if c is None:
            if cid in ids:
                continue  # claim_state_errors 가 '찾지 못했다'를 낸다
            errs.append(f"chart.claims {cid} 를 찾지 못했다")
            continue
        has, text, why = copy_text(c)
        if has:
            if text is None:
                errs.append(f"chart.claims {cid} 의 원문 사본 글을 읽지 못했다 — {why}")
            else:
                texts.append((cid, text))
        else:
            texts += [(cid, _s(c.get("observed"))), (cid, _s(c.get("text")))]
    if not texts:
        return errs
    where = "원문 사본 글(사본이 없는 기록은 observed·text)"
    for s in ch["series"]:
        for pt in s["points"]:
            nota = point_notation(pt)
            hits = [K.find_value(t, nota) for _, t in texts]
            if any(h["found"] for h in hits):
                continue
            skipped = sum(h["skipped"] for h in hits)
            errs.append(f"chart 계열 '{s['name']}' 점 {pt[0]}: 값 '{nota}' 이 chart.claims({', '.join(used)})의 {where}에 "
                        "공백으로 나뉜 낱말 하나로 그 표기 그대로 없다(표의 칸 값이어야 한다 — 부호·범위·조사가 붙은 낱말이나 더 긴 수의 조각은 찾은 것이 아니다)"
                        + (f" — 바로 앞이 부호·범위 이음이거나 바로 뒤가 범위 이음인 자리 {skipped}곳은 세지 않았다" if skipped else ""))
    return errs


def capture_errors(sl: dict, claims: dict[str, dict], draft: bool, geom: tuple | None = None) -> tuple[list[str], str | None]:
    """(실패, 그림 대기 claim_id | None). 원문 캡처 그림은 빌드 때 해시가 확인된 사본에서 새로 그린다(기록의 verification.image 는 쓰지 않는다).
    그래서 여기서는 그림 파일이 아니라 '기록이 받아들여지는가(acceptance_error 빈 문자열)'와 '사본에서 그림을 그릴 수 있는가'를 본다.
    초안 모드의 그림 대기 = 기록이 아직 받아들여지지 않을 때.
    geom = (픽셀 크기, 자리 폭 in) — image_pair 의 한 자리처럼 sl 이 쪽 자체가 아닐 때 그 자리의 크기(capture_geom). 없으면 sl 의 계획에서 구한다."""
    cid = _s(sl.get("capture")).strip()
    ids = [str(x) for x in sl.get("claim_ids") or []]
    ferr = focus_error(sl)
    if ferr:
        return [ferr], None
    if not C.CLAIM_ID.match(cid):
        return [f"capture '{cid}' 는 claim_id 하나여야 한다"], None
    if cid not in ids:
        return [f"capture {cid} 가 이 쪽의 claim_ids 에 없다 — 원문 캡처는 그 쪽이 인용한 기록의 것이어야 한다"], None
    c = claims.get(cid)
    if c is None:
        return [], None  # claim_state_errors 가 '찾지 못했다'를 낸다
    from ozl.research import capture as K
    try:
        K.focus_spans(_s(c.get("observed")), sl.get("capture_focus"))
    except ValueError as e:
        return [f"capture {cid}: {e} — 형광으로 칠할 구절은 대조한 대목(observed) 안에서 글자 그대로 따온다"], None
    why = acceptance_error(c)
    if why:
        return ([], cid) if draft else ([f"capture {cid} 는 {why}"], None)
    src = C.copy_source(c)
    if not src["ok"]:
        return [f"capture {cid} 의 원문 사본으로 그림을 그릴 수 없다 — {src['reason']}"], None
    from ozl.research import capture as K
    target = capture_target(c)
    if not target:
        return [f"capture {cid} 의 대조한 자리를 정하지 못했다 — observed 가 사본에 한 번만 나오거나 재대조 기록이 자리를 정해야 한다"], None
    size_px, slot_in = geom or capture_geom(sl)
    fit = K.evidence_image(cid, src["path"], src["kind"], src["text"], _s(c.get("observed")), target["offset"], capture_meta(src["cap"]),
                           "", size_px=size_px, check_only=True, focus=sl.get("capture_focus"), slot_width_in=slot_in)
    if fit.get("reason"):
        return [f"capture {cid} 의 원문 캡처를 그릴 수 없다 — {fit['reason']}"], None
    return [], None


def focus_error(sl: dict) -> str:
    """capture_focus 의 모양과 자리. 구절(문자열) 또는 구절 목록이고, 각 구절이 대조한 대목(observed) 안에 글자 그대로(공백만 정리) 있어야 한다.
    대목 안의 자리는 그림을 그릴 때(capture.focus_spans) 같은 규칙으로 다시 본다."""
    f = sl.get("capture_focus")
    if f is None:
        return ""
    if not (isinstance(f, str) or (isinstance(f, list) and f and all(isinstance(x, str) for x in f))) or not all(x.strip() for x in ([f] if isinstance(f, str) else f)):
        return "capture_focus 는 비지 않은 구절(문자열) 또는 구절 목록이어야 한다"
    return ""


def capture_meta(cap: dict) -> dict:
    """원문 캡처 그림 머리에 적는 사본 정보 — 검사와 빌드가 같은 것을 쓴다(머리 글 줄 수가 대목 자리에 영향을 준다)."""
    return {"url": cap.get("final_url") or cap.get("url"), "fetched_at": cap.get("fetched_at"), "sha256": cap.get("sha256")}


def capture_size(sl: dict) -> tuple[int, int]:
    """이 쪽 원문 캡처 그림의 픽셀 크기 — 빌드(render_visuals)와 같은 계산."""
    return capture_geom(sl)[0]


def capture_geom(sl: dict, slot: int = -1) -> tuple[tuple[int, int], float]:
    """이 쪽(slot = image_pair 의 자리 번호) 원문 캡처 그림의 (픽셀 크기, 자리 폭 in) — 빌드(render_visuals)와 같은 계산.
    자리 폭은 그림 글자를 슬라이드 위 pt 로 맞추는 기준이다. 자리가 커지면(capture_full) 같은 글자 크기로 더 많은 글이 들어간다."""
    from ozl.render import build as B
    from ozl.render import charts as G
    from ozl.research import capture as K
    try:
        ims = [im for im in B.plan_slide(sl).imgs if im.kind == "capture" and im.slot == slot]
    except Exception:  # noqa: BLE001 — 쪽 배치가 안 되는 사양은 다른 검사가 실패시킨다. 여기서는 기본 크기로 본다
        ims = []
    if not ims:
        return G.DEFAULT_SIZE_PX, K.SLOT_W_IN
    return B.chart_png_size(ims[0]), B.capture_slot_in(ims[0])


def capture_target(c: dict) -> dict | None:
    """원문 캡처를 그릴 자리 — machine_check 가 정한 유일한 자리(match.target). 사람이 대조한 기록은 observed 가 사본에 한 번만 나올 때 그 자리."""
    from ozl.research import capture as K
    _, match = C.machine_check(c, fresh=False)
    if match.get("target"):
        return match["target"]
    if c.get("human_verified") is True:
        src = C.copy_source(c)
        if src["ok"]:
            f = K.find_phrase(src["text"], _s(c.get("observed")))
            if f["count"] == 1:
                m = f["matches"][0]
                return {"offset": m["offset"], "end": m["end"], "page": m["page"]}
    return None


def pair_shape_ok(sl: dict) -> bool:
    """image_pair 의 pair 가 그림 자리 두 개(사전 둘)의 목록인가. 아니면 배치(layout)를 부르지 않는다."""
    pair = sl.get("pair")
    return isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, dict) for x in pair)


def visual_errors(sl: dict, claims: dict[str, dict], draft: bool, pics: dict | None = None, *, template_v1: bool = False) -> tuple[list[str], list[str], list[str]]:
    """그림 칸 검사 (실패, 그림 대기 id 목록, 경고). 그림 자리마다(slot_views) 본다.
    그림 대기 id = 원문 캡처의 claim_id 또는 검수 대장의 그림 번호."""
    from ozl.render import pictures as PIC
    kind = sl.get("kind")
    errs: list[str] = []
    waits: list[str] = []
    warns: list[str] = []
    if kind == "image_pair":
        pair = sl.get("pair")
        if pair is not None and not pair_shape_ok(sl):
            return ["image_pair 의 pair 는 그림 자리 두 개(사전 둘)의 목록이어야 한다"], [], []
        if pair and all(PIC.DROPPED in slot for slot in pair):
            # drop_memes 가 비울 수는 있지만 안전망으로 남긴다 — 두 자리가 다 빈 장은 완성본에 남기지 않는다
            errs.append("image_pair 의 두 자리가 다 비었다(밈을 뺐다) — 그림 없는 두 칸짜리 장은 쓰지 않는다")
        for k in VISUAL_KEYS + ("capture_focus",):
            if sl.get(k) not in (None, "", {}, []):
                errs.append(f"image_pair 는 '{k}' 를 쪽에 두지 않고 pair 의 각 자리에 둔다")
        for j, slot in enumerate(pair or []):
            if PIC.DROPPED in slot:
                continue
            if not _present(slot.get("caption")):
                errs.append(f"{SLOT_NAME[j]}: 짧은 설명(caption)이 있어야 한다")
            im = slot.get("image")
            if im is not None and not (isinstance(im, dict) and all(_present(im.get(x)) for x in ("what", "source"))):
                errs.append(f"{SLOT_NAME[j]}: 'image' 는 what·source 가 있는 사전이어야 한다")
            if isinstance(im, dict) and im.get("caption"):
                errs.append(f"{SLOT_NAME[j]}: image.caption 은 쓰지 않는다 — 자리의 caption 에 쓴다")
    elif kind == "photo_caption" and isinstance(sl.get("image"), dict) and sl["image"].get("caption"):
        errs.append("photo_caption 은 image.caption 을 쓰지 않는다 — 쪽의 caption 에 쓴다")
    if kind == "full_picture":
        if _present(sl.get("title")):
            errs.append("full_picture 에는 제목(title)을 두지 않는다 — 그림 한 장이 쪽을 채우고, 한마디는 caption 한 줄에 쓴다")
        if _present(sl.get("body")):
            errs.append("full_picture 에는 본문 글(body)을 두지 않는다 — 한마디는 caption 한 줄에 쓴다")
    if kind == "image_stack" and isinstance(sl.get("body"), list) and len(sl["body"]) > 3:
        errs.append(f"image_stack 의 본문은 1~3줄이다(지금 {len(sl['body'])}줄) — 글이 많으면 image_text 로 쓴다")
    if kind in ("full_picture", "image_stack") and isinstance(sl.get("image"), dict) and sl["image"].get("caption"):
        errs.append(f"{kind} 는 image.caption 을 쓰지 않는다" + (" — 쪽의 caption 에 쓴다" if kind == "full_picture" else ""))
    if kind == "capture_full" and _present(sl.get("body")):
        errs.append("capture_full 에는 본문 글(body)을 두지 않는다 — 원문 캡처 한 장과 한 줄 제목뿐이다")
    for j, v in slot_views(sl):
        tag = (SLOT_NAME[j] + ": ") if j >= 0 else ""
        have = [k for k in VISUAL_KEYS if v.get(k) not in (None, "", {}, [])]
        e: list[str] = []
        if len(have) > 1:
            e.append(f"그림 자리는 하나다 — {' · '.join(have)} 가운데 하나만 쓴다")
        if v.get("capture_focus") is not None and "capture" not in have:
            e.append("capture_focus 는 capture 를 쓴 쪽에서만 쓴다")
        allowed = SLOT_KEYS.get("image_text" if template_v1 and kind == "quote_translation" else kind)
        for k in have:
            if allowed is not None and k not in allowed:
                e.append(f"'{k}' 는 {kind} 의 그림 자리에 쓰지 않는다({' · '.join(allowed)} 가운데 하나)")
            elif allowed is None and k != "image":
                e.append(f"'{k}' 는 그림 자리가 있는 종류({', '.join(VISUAL_KINDS)})에서만 쓴다(지금 {kind})")
        if kind in PICTURE_FIRST and not have:
            e.append(f"그림 자리에 {' · '.join(SLOT_KEYS[kind])} 가운데 하나가 있어야 한다")
        if kind == "capture_full" and not have:
            e.append("capture_full 에는 'capture' 가 있어야 한다 — 원문 캡처 대신 원문 화면 갈무리 종류의 그림(picture)을 써도 된다")
        if e:
            errs += [tag + x for x in e]
            continue
        if have == ["image"] and kind in PICTURE_FIRST and not draft:
            # 회색 자리는 그림이 아니다 — 그림이 주인공인 종류에서 회색 상자와 '그림 자리' 글이 완성본에 찍히지 않게 엄격 모드는 실패시킨다
            errs.append(tag + "그림 자리가 회색 자리(image)다 — 그림이 주인공인 장이라 엄격 모드(완성본)에서는 쓰지 않는다. "
                        "검수 대장에 오른 그림(picture)이나 차트·원문 캡처로 바꾸거나, 그림이 없으면 다른 종류의 장으로 바꾼다(초안 모드는 통과)")
        if "chart" in have:
            errs += [tag + x for x in chart_errors(v, claims)]
        elif "capture" in have:
            ce, wait = capture_errors(v, claims, draft, capture_geom(sl, j) if j >= 0 else None)
            errs += [tag + x for x in ce]
            if wait:
                waits.append(wait)
        elif "picture" in have:
            pe, wait, pw = picture_errors(sl, v, j, pics or {}, draft, claims)
            errs += [tag + x for x in pe]
            warns += [tag + x for x in pw]
            if wait:
                waits.append(wait)
    return errs, waits, warns


def picture_errors(sl: dict, v: dict, slot: int, pics: dict, draft: bool, claims: dict | None = None) -> tuple[list[str], str | None, list[str]]:
    """그림 파일(picture: <그림 번호>) 검사 — (실패, 그림 대기 그림 번호 | None, 경고).
    대장(pictures)에 없으면 두 모드 모두 실패. 칸이 비었거나 판정이 '쓰지 않는다'이거나 파일이 없으면 엄격 모드 실패, 초안 모드는 그림 대기.
    밈은 엄격 모드 검사에 오면 실패다(build · check 명령은 미리 drop_memes 로 뺀다).
    개념도가 아닌 생성 그림과 종류를 바꿔 적은 생성 그림(pictures.hard_block)은 초안 모드에서도 실패다(그림 대기로 미루지 않는다)."""
    from ozl.render import pictures as PIC
    pid = _s(v.get("picture")).strip()
    if pid not in pics:
        return [f"picture {pid} 가 그림 검수 대장(pictures)에 없다"], None, []
    e = pics[pid]
    if sl.get("kind") == "capture_full" and not (PIC.rule_of(e) is not None and PIC.rule_of(e).screen):
        return [f"picture {pid}({_s(e.get('kind'))}): capture_full 에는 원문 화면 갈무리 종류의 그림만 쓴다 — 다른 그림은 photo_caption · full_picture 로 쓴다"], None, []
    if not draft and PIC.is_meme(e):
        return [f"picture {pid} 는 밈이다 — 엄격 모드(완성본·공개용)에는 넣지 않는다. check·build 명령은 밈을 빼고(drop_memes) 검사한다"], None, []
    verdict, why, warns = PIC.judge(e, draft)
    hard = PIC.hard_block(e) if draft else []   # 엄격 모드는 judge 의 까닭에 이미 들어 있다
    if hard:
        return [f"picture {pid}({_s(e.get('kind'))}): {w} — 초안 모드에서도 실패다" for w in hard], None, [f"picture {pid}: {w}" for w in warns]
    ferr = PIC.file_error(e)
    if ferr:
        if _s(e.get("kind")) == PIC.AI_KIND and not PIC.resolve_path(e).is_file():
            ferr = ("생성 그림 파일이 아직 없다 — 그림을 만든 세션이 파일을 두고 path · sha256 · generator · prompt · generated_at 과 "
                    "concept · concept_check 를 채운다: " + ferr)
        why.append(ferr)
    rule = PIC.rule_of(e)
    if rule is not None and rule.screen:   # 원문 화면 갈무리: 그 쪽이 인용한 기록의 원문과 같은 기관 호스트
        cited = [(claims or {}).get(str(c)) for c in sl.get("claim_ids") or []]
        why += PIC.screen_host_errors(e, [c for c in cited if isinstance(c, dict)])
    warns = [f"picture {pid}: {w}" for w in warns]
    if why:
        if draft:
            return [], pid, warns + [f"picture {pid} 그림 대기({verdict}): {w}" for w in why]
        return [f"picture {pid}({_s(e.get('kind'))} · 판정 {verdict}): {w}" for w in why], None, warns
    from ozl.render import build as B
    try:
        ims = [im for im in B.plan_slide(sl).imgs if im.kind == "picture" and im.slot == slot]
    except Exception:  # noqa: BLE001 — 배치가 안 되는 사양은 layout 검사가 실패시킨다
        ims = []
    if ims:
        for p in B.picture_credit_box(ims[0], e, 0.0).problems():
            why.append(f"그림 밑 표기 {p}")
    if why:
        return [f"picture {pid}: {w}" for w in why], None, warns
    if ims:   # 자리에 놓인 크기로 보는 경고 — 자리 넓이의 절반을 못 채운 그림, 글자가 작게 찍히는 화면 갈무리
        warns += [f"picture {pid}: {w}" for w in PIC.placement_warnings(e, ims[0].width, ims[0].height)]
    return [], None, warns


# ── 각주(화면에 찍히는 글 — 생성과 검사가 같은 함수를 쓴다) ─────────────────
def base_period_text(base) -> str:
    """기록의 base_period 를 화면 표기로: 2023 → 2023년 · 2026-07 → 2026년 7월 · 2026-Q3 → 2026년 3분기 · 2026-01~2026-09 → 2026년 1월 ~ 2026년 9월 · 날짜는 그대로."""
    b = _s(base).strip()
    if not b or b == "n/a":
        return ""
    if "~" in b:   # 범위(2026-01~2026-09)는 양끝을 따로 풀고 사이를 띄운다 — 한 덩어리로 두면 부록 칸에서 줄을 바꾸지 못한다
        lo, hi = (x.strip() for x in b.split("~", 1))
        return f"{base_period_text(lo)} ~ {base_period_text(hi)}"
    if re.fullmatch(r"\d{4}", b):
        return f"{b}년"
    m = re.fullmatch(r"(\d{4})-(\d{2})", b)
    if m:
        return f"{m.group(1)}년 {int(m.group(2))}월"
    m = re.fullmatch(r"(\d{4})-Q([1-4])", b)
    if m:
        return f"{m.group(1)}년 {m.group(2)}분기"
    return b


def short_source(cid: str, claim: dict, card: dict | None, labels: dict | None = None) -> str:
    if labels and labels.get(cid):
        return str(labels[cid])
    for d in (card or {}).get("data") or []:
        if d.get("claim_id") == cid and d.get("source_name"):
            return str(d["source_name"])
    return str((claim.get("source") or {}).get("publisher") or "")


def footnote_text(sl: dict, claims: dict, card: dict | None, labels: dict | None = None) -> str:
    # 같은 출처는 한 번만 적고 기준 시점을 모은다(같은 문서가 꼬리 줄에 두 번 찍히지 않게 — 2026-11-13 덱 검토)
    bases: dict[str, list[str]] = {}
    for cid in sl.get("claim_ids") or []:
        c = claims.get(str(cid)) or {}
        base = base_period_text((c.get("checks") or {}).get("base_period"))
        got = bases.setdefault(short_source(str(cid), c, card, labels), [])
        if base and base not in got:
            got.append(base)
    parts = [src + (f" · 기준 {', '.join(b)}" if b else "") for src, b in bases.items()]
    refs = [str(x) for x in sl.get("refs") or []]
    # 카드 sources 의 등급이 T1·T2(기업·기관이 낸 문서)인 refs 는 '자료', 그 밖(보도·등급 모름)은 '보도'로 부른다
    # — 회사 문서를 보도로 읽히게 하지 않는다(2026-11-13 덱 검토). 숫자 근거가 아닌 것은 둘 다 같다.
    doc_names = {str(s.get("name")) for s in (card or {}).get("sources") or [] if isinstance(s, dict) and s.get("tier") in DOC_TIERS}
    docs = [x for x in refs if x in doc_names]
    press = [x for x in refs if x not in doc_names]
    out = ("출처: " + " / ".join(parts)) if parts else ""
    if docs:
        out += ("  ·  " if out else "") + "자료: " + " / ".join(docs)
    if press:
        out += ("  ·  " if out else "") + "보도: " + " / ".join(press)
    return out


DOC_TIERS = ("T1", "T2")   # refs 각주·부록에서 '자료'로 부르는 출처 등급


# ── 링크 번호(style: syuka — 쪽 아래 출처 줄 대신 수치 뒤 작은 번호와 덱 밖 링크 목록) ──────────────
# 숫자 대조가 이미 "이 수치가 어느 기록의 observed·text 에 있는가"를 본다. 그 결과를 돌려주는 것이 number_sources 이고,
# link_plan 이 기록마다 덱 전체에서 번호 하나(처음 나온 순서)를 준다. 번호는 빌드가 붙이는 표시라 사양의 글이 아니다 —
# visible_text 에 들어가지 않으므로 숫자 대조를 받지 않는다. 화면 글의 수치 뒤에는 작은 회색 위첨자, 차트·원문 캡처·표·회색 그림 자리는
# 그 자리 오른쪽 아래 귀퉁이에 번호 하나(여러 기록이면 '2,3').
LINKS_KEY = "_links"    # 검사·빌드가 쪽 사본에 넣는 칸 — {"inline": {칸: {글자 자리: 번호}}, "corner": {자리: 번호}}. 사양 파일에는 쓰지 않는다
_MARK_TAIL = ".,;:!?)]」』\"'”’…"   # 어절 끝의 문장부호 — 번호는 그 앞에 붙인다
_MARK_UNITS = tuple(sorted(("퍼센트포인트", "퍼센트", "포인트", "달러", "가구", "개월", "시간", "배럴", "위안", "유로", "파운드", "명", "원", "개", "회",
                            "건", "곳", "배", "톤", "엔", "대", "척", "세", "살", "층", "장", "편", "상자", "마리", "평"), key=len, reverse=True))
# 띄어 쓴 단위 낱말 — '5조 원이' 의 번호는 '원이' 끝에 붙인다(숫자 판독의 단위 목록과 별개 · 번호 자리에만 쓴다)


def inline_fields(sl: dict) -> list[tuple[tuple, str]]:
    """수치 뒤에 위첨자 번호를 붙이는 화면 글 칸(build.plan_slide 가 글상자로 그리는 칸) — (칸 이름, 글). 화면에 보이는 순서."""
    out: list[tuple[tuple, str]] = [(("title",), _s(sl.get("title")))]
    for k in ("sub", "en", "ko"):
        out.append(((k,), _s(sl.get(k))))
    num = sl.get("number")
    if isinstance(num, dict):
        out += [(("number", "value"), _s(num.get("value"))), (("number", "label"), _s(num.get("label")))]
    q = sl.get("quote")
    if isinstance(q, dict):
        out += [(("quote", "text"), _s(q.get("text"))), (("quote", "by"), _s(q.get("by")))]
    for k, x in enumerate(sl.get("body") or []):
        out.append((("body", k), _s(x.get("text") if isinstance(x, dict) else x)))
    out.append((("caption",), _s(sl.get("caption"))))
    if sl.get("kind") == "image_pair":
        for j, v in slot_views(sl):
            out.append((("pair", j, "caption"), _s(v.get("caption"))))
    return [(k, t) for k, t in out if t]


# ── 링크 번호를 붙이지 않는 표기 ──
# 숫자 대조(number_errors)는 그대로다 — 근거는 지금처럼 요구하고 번호만 붙이지 않는다.
#   분모 꼴: 수 뒤에 단위와 '당'이 오는 표기(「1인당」「100명당」「가게 1곳당」). 그 수는 잰 값이 아니라 나누는 기준이다.
#   차례 꼴: 「제2」「3번째」「2차」. 그 수는 차례다.
# 좁게 잡는다(모르면 번호를 붙인다): 단위는 아래 목록만, 단위와 '당' 사이는 붙여 쓴 것만, '당' 뒤는 낱말 끝이나 조사만 받는다
# (「3개 당연히」「2명 당선」「3당 체제」는 분모 꼴이 아니다). 「3차례」「2차전지」「10차선」은 차례 꼴이 아니다(번호를 붙인다).
_PER_UNITS = tuple(sorted(("킬로미터", "킬로그램", "제곱미터", "가구", "세대", "사람", "시간", "개월", "점포", "매장", "상자", "마리", "리터", "미터", "그램",
                           "인", "명", "곳", "개", "건", "회", "대", "주", "평", "채", "호", "권", "병", "잔", "끼", "번", "장", "편", "척", "톤", "원", "달러",
                           "일", "월", "년", "분", "초", "km", "kg", "㎡", "㎞", "㎏", "m", "g", "t", "L", "l", "%"), key=len, reverse=True))
_WORD_END = r"(?=$|[^가-힣A-Za-z]|(?:으로|로|의|은|는|이|가|을|를|에|도|만)(?:$|[^가-힣A-Za-z]))"
_PER_TAIL = re.compile(r"\s?(?P<unit>" + "|".join(map(re.escape, _PER_UNITS)) + r")?당" + _WORD_END)
_ORD_HEAD = re.compile(r"(?:^|[^가-힣A-Za-z0-9])제\s?$")
_ORD_TAIL = re.compile(r"(?:\s?번째|차(?=$|[^가-힣A-Za-z]|(?:의|는|은|가|를|을|에|에서|까지|부터|도|와|과)(?:$|[^가-힣A-Za-z])))")
SKIP_PER, SKIP_ORDINAL = "분모 꼴", "차례 꼴"


def link_skip(text: str, start: int, end: int) -> str:
    """수치 표기 text[start:end] 에 링크 번호를 붙이지 않는 까닭 — SKIP_PER · SKIP_ORDINAL. 빈 문자열이면 붙인다."""
    tok, rest = text[start:end], text[end:]
    m = _PER_TAIL.match(rest)
    if m and (m.group("unit") or (not m.group(0)[:1].isspace() and not tok[-1:].isdigit())):
        return SKIP_PER   # 단위가 수치 표기 안에 든 꼴('7일당')은 바로 뒤의 '당'으로 본다
    if _ORD_HEAD.search(text[:start]) or _ORD_TAIL.match(rest):
        return SKIP_ORDINAL
    return ""


NUMBER_CLAIMS = "number_claims"   # 장의 칸 — 화면 수치 자리마다 받치는 기록을 지정한다(같은 표기가 인용한 기록 둘 이상에 있을 때)


def field_name(key) -> str:
    """수치 자리의 칸 이름 — number_claims 의 at 과 오류 글에 쓴다. ('body', 1) → body[1] · ('number', 'value') → number.value ·
    ('pair', 0, 'caption') → pair[0].caption · ('image',) → image(회색 그림 자리) · ('table',) → table."""
    key = tuple(key)
    if key[0] in ("body", "pair") and len(key) >= 2:
        return f"{key[0]}[{key[1]}]" + "".join(f".{x}" for x in key[2:])
    return ".".join(str(x) for x in key)


def _token_claims(canon: str, ids: list[str], pools: dict[str, set[str]], conv: dict[str, list[str]]) -> list[str]:
    """이 수치 표기를 받칠 수 있는 기록(claim_ids 순서). 환산(conversions)으로 받친 표기는 그 환산의 기록도 든다.
    후보일 뿐이다 — 자리마다 어느 기록인지는 _resolve 가 정한다. claim_ids 에 같은 기록이 두 번 적혀도 후보는 하나다(순서를 지키며 중복 제거)."""
    return [c for c in dict.fromkeys(ids) if canon in pools.get(c, set()) or c in conv.get(canon, [])]


def _occurrences(sl: dict, identifiers=()) -> list[dict]:
    """이 쪽 화면의 수치 자리(링크 번호를 붙일 수 있는 자리) — 화면 글 칸, 회색 그림 자리, 표. 나온 순서대로.
    한 자리 = {key: 칸, kind: 'inline' | 'image' | 'table', slot, at: 글자 자리(inline), shown: 화면 표기, canon, nth: 그 칸에서 몇 번째 그 표기인가,
    skip: 번호를 붙이지 않는 까닭(link_skip — 분모 꼴 · 차례 꼴. 빈 문자열이면 붙인다)}. nth 는 건너뛰는 자리까지 센다(사양의 지정과 같은 셈)."""
    out: list[dict] = []
    seen: dict[tuple, int] = {}

    def add(key: tuple, kind: str, slot, at: int, shown: str, canon: str, skip: str = ""):
        seen[(key, canon)] = seen.get((key, canon), 0) + 1
        out.append({"key": key, "kind": kind, "slot": slot, "at": at, "shown": shown, "canon": canon, "nth": seen[(key, canon)], "skip": skip})

    def spans(text: str):
        return [(t, text[t.start:t.end], link_skip(text, t.start, t.end)) for t in N.source_spans(text, identifiers) if t.needs_claim and not t.fragment]

    for key, text in inline_fields(sl):
        for t, shown, skip in spans(text):
            add(key, "inline", None, _mark_at(text, t.end), shown, t.canon, skip)
    for j, v in slot_views(sl):
        if visual_of(v) == "image" and isinstance(v.get("image"), dict):
            key = ("image",) if j == -1 else ("pair", j, "image")
            for k in ("what", "source", "caption"):
                for t, shown, skip in spans(_s(v["image"].get(k))):
                    add(key, "image", j, -1, shown, t.canon, skip)
    tbl = sl.get("table")
    if isinstance(tbl, dict):
        cells = [_s(x) for x in tbl.get("header") or []] + [_s(x) for row in tbl.get("rows") or [] for x in (row if isinstance(row, list) else [row])]
        for cell in cells:
            for t, shown, skip in spans(cell):
                add(("table",), "table", "table", -1, shown, t.canon, skip)
    return out


def _designations(sl: dict, ids: list[str], occ: list[dict], identifiers=()) -> tuple[list[dict], list[str]]:
    """장의 number_claims 를 읽는다 — ([{i, canon, shown, claim, at, nth}], 모양 오류). 모양이 틀린 줄은 지정으로 쓰지 않는다."""
    raw = sl.get(NUMBER_CLAIMS)
    if raw in (None, []):
        return [], []
    if not isinstance(raw, list):
        return [], [f"{NUMBER_CLAIMS} 는 {{shown, claim_id, at, nth}} 의 목록이어야 한다"]
    fields = {field_name(o["key"]) for o in occ}
    out, errs = [], []
    for i, d in enumerate(raw):
        where = f"{NUMBER_CLAIMS}[{i}]"
        if not isinstance(d, dict) or not (_s(d.get("shown")).strip() and _s(d.get("claim_id")).strip()):
            errs.append(f"{where}: shown · claim_id 둘 다 있어야 한다")
            continue
        shown, cid = _s(d.get("shown")).strip(), _s(d.get("claim_id")).strip()
        toks = [t for t in N.claim_tokens(shown, identifiers) if not t.fragment]
        if len(toks) != 1:
            errs.append(f"{where}: shown '{shown}' 는 화면 수치 표기 하나여야 한다")
            continue
        if cid not in ids:
            errs.append(f"{where}: {cid} 가 이 슬라이드의 claim_ids 에 없다")
            continue
        at, nth = d.get("at"), d.get("nth")
        if at is not None and _s(at).strip() not in fields:
            errs.append(f"{where}: 칸 '{at}' 가 이 쪽에 없다(수치가 있는 칸: {', '.join(sorted(fields)) or '없음'})")
            continue
        if nth is not None:
            if at is None:
                errs.append(f"{where}: nth 는 at 과 함께 쓴다(그 칸에서 몇 번째 그 표기인가)")
                continue
            if isinstance(nth, bool) or not isinstance(nth, int) or nth < 1:
                errs.append(f"{where}: nth 는 1 이상의 정수여야 한다({nth})")
                continue
        out.append({"i": i, "canon": toks[0].canon, "shown": shown, "claim": cid, "at": None if at is None else _s(at).strip(), "nth": nth})
    return out, errs


def _resolve(sl: dict, claims: dict[str, dict], identifiers=()) -> tuple[list[tuple[dict, list[str]]], list[str]]:
    """수치 자리마다 받치는 기록을 정한다 — ([(자리, [정한 기록, 같은 표기가 있는 다른 기록…])], 실패).
    후보 = 그 표기가 observed·text 에 있는 기록과 환산(conversions)이 그 표기에 지정한 기록(이 쪽 claim_ids 안에서).
      1. number_claims 가 그 자리를 지정했으면 그 기록(가장 좁게 적은 지정이 이긴다: at+nth > at > 쪽 전체). 지정한 기록이 후보가 아니면 실패.
      2. 환산이 그 표기에 기록 하나를 지정했으면 그 기록 — 같은 표기가 다른 기록에 글자 그대로 있어도 지정을 따른다.
      3. 후보가 하나면 그 기록.
      4. 그 밖(후보가 둘 이상인데 지정이 없다, 환산 둘이 서로 다른 기록을 가리킨다)은 정할 수 없다 — 실패로 알리고 그 자리에는 번호를 주지 않는다.
    후보가 없는 수치는 넣지 않는다(숫자 대조가 실패시킨다).
    번호를 붙이지 않는 표기(자리의 skip — 분모 꼴 · 차례 꼴)는 넣지 않고, 기록을 정하지 못해도 실패로 알리지 않는다(이을 번호가 없다).
    그 자리를 가리킨 number_claims 지정은 쓰인 것으로 친다(지워도 된다 — 실패는 아니다)."""
    ids = [str(x) for x in sl.get("claim_ids") or []]
    pools = {c: source_tokens(claims[c]) for c in ids if c in claims}
    conv: dict[str, list[str]] = {}
    for cv in sl.get("conversions") or []:
        if not isinstance(cv, dict):
            continue
        shown, cid = _s(cv.get("shown")).strip(), _s(cv.get("claim_id")).strip()
        for t in N.claim_tokens(shown, identifiers):
            conv.setdefault(t.canon, []).append(cid)
    occ = _occurrences(sl, identifiers)
    des, errs = _designations(sl, ids, occ, identifiers)
    hit: set[int] = set()
    per_field: dict[tuple, int] = {}
    for o in occ:
        per_field[(o["key"], o["canon"])] = max(per_field.get((o["key"], o["canon"]), 0), o["nth"])
    out: list[tuple[dict, list[str]]] = []
    for o in occ:
        name = field_name(o["key"])
        match = [d for d in des if d["canon"] == o["canon"] and d["at"] in (None, name) and d["nth"] in (None, o["nth"])]
        hit |= {d["i"] for d in match}
        if o["skip"]:
            continue
        cands = _token_claims(o["canon"], ids, pools, conv)
        if not cands:
            continue
        via = [c for c in dict.fromkeys(conv.get(o["canon"], [])) if c in cands]
        spot = f"'{o['shown']}'({name}" + (f" {o['nth']}번째" if per_field[(o["key"], o["canon"])] > 1 else "") + ")"
        hint = f"{{shown: '{o['shown']}', at: {name}" + (f", nth: {o['nth']}" if per_field[(o["key"], o["canon"])] > 1 else "") + ", claim_id: …}"
        if match:
            rank = max((d["at"] is not None) + (d["nth"] is not None) for d in match)
            best = [d for d in match if (d["at"] is not None) + (d["nth"] is not None) == rank]
            picks = list(dict.fromkeys(d["claim"] for d in best))
            lines = ", ".join(f"{NUMBER_CLAIMS}[{d['i']}]" for d in best)
            if len(picks) > 1:
                errs.append(f"{lines}: 화면 수치 {spot} 의 지정이 겹친다({', '.join(picks)}) — 자리마다 기록 하나만 지정한다")
                continue
            if picks[0] not in cands:
                errs.append(f"{lines}: {picks[0]} 의 observed·text(또는 그 기록을 지정한 conversions)에 '{o['shown']}' 표기가 없다 — 그 수치를 받치는 기록이 아니다")
                continue
            pick = picks[0]
        elif len(via) == 1:
            pick = via[0]
        elif len(via) > 1:
            errs.append(f"화면 수치 {spot} 를 conversions 가 서로 다른 기록({', '.join(via)})으로 지정했다 — 링크 번호를 어느 기록에 이을지 정할 수 없다. "
                        f"{NUMBER_CLAIMS} 에 {hint} 를 적는다")
            continue
        elif len(cands) == 1:
            pick = cands[0]
        else:
            errs.append(f"화면 수치 {spot} 를 받치는 기록이 둘 이상이다({', '.join(cands)}) — 링크 번호를 어느 기록에 이을지 정할 수 없다. "
                        f"{NUMBER_CLAIMS} 에 {hint} 를 적는다")
            continue
        out.append((o, [pick] + [c for c in cands if c != pick]))
    for d in des:
        if d["i"] not in hit:
            where = ("화면에 " if d["at"] is None else f"칸 {d['at']} 에 ") + (f"{d['nth']}번째 " if d["nth"] is not None else "")
            errs.append(f"{NUMBER_CLAIMS}[{d['i']}]: {where}'{d['shown']}' 표기가 없다 — 쓰이지 않는 지정이다")
    return out, errs


def _mark_at(text: str, end: int) -> int:
    """번호를 붙일 글자 자리(그 글자 뒤에 붙인다): 수치가 든 어절의 끝 — 띄어 쓴 단위 낱말('5조 원')이면 그 낱말 끝, 끝의 문장부호는 뺀다."""
    n = len(text)
    k = end
    while k < n and not text[k].isspace():
        k += 1
    if k == end and k < n:   # 수치 바로 뒤가 공백 — 다음 어절이 단위 낱말이면 그 어절까지
        j = k
        while j < n and text[j].isspace():
            j += 1
        if any(text.startswith(u, j) for u in _MARK_UNITS):
            k = j
            while k < n and not text[k].isspace():
                k += 1
    while k - 1 > end - 1 and text[k - 1] in _MARK_TAIL:
        k -= 1
    return max(k, end) - 1


def number_sources(sl: dict, claims: dict[str, dict], identifiers=()) -> dict:
    """이 쪽 화면 수치마다 받치는 기록. 돌려주는 값:
    {"inline": [(칸 이름, 글자 자리, 화면 표기, [받치는 기록])], "corner": [(자리, 무엇, [기록])], "errors": [실패]}.
    자리마다 기록 하나로 정한다(_resolve — number_claims 지정 > conversions 지정 > 후보가 하나뿐). inline 의 기록 목록은 [정한 기록, 같은 표기가 있는
    다른 기록…] — 앞의 것이 번호를 받는다. 정할 수 없는 자리(같은 표기가 인용한 기록 둘 이상에 있는데 지정이 없다)는 넣지 않고 errors 에 적는다.
    차트와 원문 캡처는 사양이 기록을 직접 적는다(chart.claims · capture). 받치는 기록이 없는 수치는 넣지 않는다(숫자 대조가 실패시킨다).
    분모 꼴과 차례 꼴(link_skip)의 자리는 넣지 않는다 — 번호를 붙이지 않는 표기다."""
    ids = [str(x) for x in sl.get("claim_ids") or []]
    resolved, errors = _resolve(sl, claims, identifiers)
    inline = [(o["key"], o["at"], o["shown"], got) for o, got in resolved if o["kind"] == "inline"]

    def picked(kind: str, slot) -> list[str]:
        return list(dict.fromkeys(got[0] for o, got in resolved if o["kind"] == kind and o["slot"] == slot))

    corner = []
    for j, v in slot_views(sl):
        what = visual_of(v)
        got: list[str] = []
        if what == "chart" and isinstance(v.get("chart"), dict):
            got = [str(c) for c in v["chart"].get("claims") or [] if str(c) in ids]
        elif what == "capture":
            got = [_s(v.get("capture")).strip()] if _s(v.get("capture")).strip() in ids else []
        elif what == "image" and isinstance(v.get("image"), dict):
            got = picked("image", j)
        if got:
            corner.append((j, {"chart": "차트", "capture": "원문 캡처", "image": "그림 자리"}[what], got))
    if isinstance(sl.get("table"), dict):
        got = picked("table", "table")
        if got:
            corner.append(("table", "표", got))
    return {"inline": inline, "corner": corner, "errors": errors}


@dataclass
class LinkPlan:
    numbers: dict[str, int] = field(default_factory=dict)            # claim_id → 링크 번호(덱 전체에서 처음 나온 순서)
    slides: list[dict] = field(default_factory=list)                 # 쪽마다 LINKS_KEY 에 넣을 값
    uses: dict[int, list[tuple[str, str]]] = field(default_factory=dict)   # 번호 → [(쪽, 화면 표기)]
    also: dict[int, list[str]] = field(default_factory=dict)         # 번호 → 같은 표기가 있는 다른 기록
    unnumbered: dict[str, list[int]] = field(default_factory=dict)   # 인용했지만 화면 수치를 받치지 않은 기록 → 쪽(말로 할 문장 · 글의 근거)
    errors: list[str] = field(default_factory=list)                  # 받치는 기록을 정할 수 없는 수치 자리와 number_claims 의 모양 오류('N쪽: …')


def _page(i: int, slot) -> str:
    return str(i) if slot in (-1, "table") else f"{i} {'왼' if slot == 0 else '오른'}"


def link_plan(spec: dict, claims: dict[str, dict]) -> LinkPlan:
    """덱 전체의 링크 번호. 쪽 순서로, 한 쪽 안에서는 제목 → 그림 자리·표 귀퉁이 → 나머지 글 칸 순서로 번호를 준다.
    받치는 기록을 정할 수 없는 자리는 번호를 주지 않고 errors 에 적는다(check 가 실패로 알리고, build_pptx 는 만들지 않는다).
    한 쪽의 글에서 같은 표기와 같은 번호가 되풀이되면 처음 자리에만 붙인다(제목의 수치를 본문이 다시 쓰는 장에서 번호가 줄줄이 붙지 않게)."""
    lp = LinkPlan()
    idents = [x for x in spec.get("identifiers") or [] if isinstance(x, str)]

    def num(cid: str, page: str, shown: str, others: list[str]) -> int:
        n = lp.numbers.setdefault(cid, len(lp.numbers) + 1)
        u = lp.uses.setdefault(n, [])
        if (page, shown) not in u:
            u.append((page, shown))
        for o in others:
            if o not in lp.also.setdefault(n, []):
                lp.also[n].append(o)
        return n

    for i, sl in enumerate(spec.get("slides") or [], 1):
        if not isinstance(sl, dict):
            lp.slides.append({"inline": {}, "corner": {}})
            continue
        src = number_sources(sl, claims, idents)
        lp.errors += [f"{i}쪽: {e}" for e in src["errors"]]
        inline: dict[tuple, dict[int, str]] = {}
        corner: dict = {}
        order = [x for x in src["inline"] if x[0] == ("title",)]
        rest = [x for x in src["inline"] if x[0] != ("title",)]
        marked: set[tuple[str, int]] = set()   # 이 쪽에서 이미 번호를 붙인 (화면 표기, 번호)

        def mark(key, at, shown, got, page):
            n = num(got[0], page, shown, got[1:])
            if (shown, n) in marked:
                return
            marked.add((shown, n))
            labels = inline.setdefault(key, {})
            labels[at] = ",".join(dict.fromkeys((labels[at].split(",") if at in labels else []) + [str(n)]))

        for key, at, shown, got in order:
            mark(key, at, shown, got, _page(i, -1))
        for slot, what, got in src["corner"]:
            corner[slot] = ",".join(str(num(c, _page(i, slot), what, [])) for c in got)
        for key, at, shown, got in rest:
            mark(key, at, shown, got, _page(i, key[1] if key[0] == "pair" else -1))
        lp.slides.append({"inline": inline, "corner": corner})
    for i, sl in enumerate(spec.get("slides") or [], 1):
        for cid in (sl.get("claim_ids") or []) if isinstance(sl, dict) else []:
            if str(cid) not in lp.numbers:
                pg = lp.unnumbered.setdefault(str(cid), [])
                if i not in pg:
                    pg.append(i)
    return lp


def with_links(sl: dict, links: dict) -> dict:
    """쪽 사본에 링크 번호 표시를 넣는다(build.plan_slide 가 읽는다). 원래 쪽은 건드리지 않는다."""
    return {**sl, LINKS_KEY: links}


def link_errors(spec: dict, claims: dict[str, dict]) -> list[str]:
    """style: syuka — 인용한 기록마다 원본 링크(source.url)가 있어야 한다. 링크 목록이 출처 줄을 대신하므로 링크 없는 기록은 받지 않는다."""
    out = []
    seen: set[str] = set()
    for i, sl in enumerate(spec.get("slides") or [], 1):
        for cid in (sl.get("claim_ids") or []) if isinstance(sl, dict) else []:
            cid = str(cid)
            if cid in seen or cid not in claims:
                continue
            seen.add(cid)
            url = _s((claims[cid].get("source") or {}).get("url")).strip()
            if not url.startswith(("https://", "http://")):
                out.append(f"{i}쪽: 기록 {cid} 에 원본 링크(source.url)가 없다 — style: syuka 덱은 쪽 아래 출처 줄 대신 링크 목록으로 출처를 밝힌다")
    return out


# ── 단계 순서 ────────────────────────────────────────────────────────────
def load_template(path: pathlib.Path = TEMPLATE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _runs(stages: list[str]) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for i, s in enumerate(stages):
        if out and out[-1][0] == s:
            out[-1] = (s, out[-1][1], i)
        else:
            out.append((s, i, i))
    return out


def stage_errors(stages: list[str], template: dict, pages: list[int] | None = None) -> tuple[list[str], list[str]]:
    """(실패, 경고). 실패 = 순서가 템플릿을 거스름. 경고 = 템플릿 규칙(적중률 기반)에서 벗어남.
    pages = stages 의 원래 쪽 번호(광고 장을 뺀 순서로 볼 때 — check 가 준다). 없으면 1부터 차례로. 비율(앞 35% · 15%)은 받은 목록 안에서 센다."""
    errs, warns = [], []
    pos = {s["stage"]: s["position_median"] for s in template.get("stages", [])}
    keys = []

    def pg(a: int) -> int:   # 목록의 자리(0부터) → 알릴 쪽 번호
        return pages[a] if pages else a + 1

    for i, s in ((pg(a), s) for a, s in enumerate(stages)):
        k = STAGE_KEY.get(s)
        if k is None or s not in C.STAGES:
            errs.append(f"{i}쪽: 단계 '{s}' 는 구성 템플릿 어휘가 아니다({' · '.join(C.STAGES)})")
        elif k not in pos:
            errs.append(f"{i}쪽: 단계 '{s}'({k}) 가 구성 템플릿 JSON 에 없다")
        keys.append(k)
    if errs or not keys:
        return errs or ["슬라이드가 없다"], warns
    runs = _runs(keys)
    if runs[0][0] not in OPENERS:
        errs.append(f"첫 단계는 여는 장 또는 우회 도입이어야 한다(지금 '{stages[0]}')")
    if runs[-1][0] not in ENDERS:
        errs.append(f"마지막 단계는 닫는 장 또는 시사점이어야 한다(지금 '{stages[-1]}')")
    for k, a, b in runs[1:]:
        if k == "hook":
            errs.append(f"{pg(a)}쪽: 여는 장은 맨 앞에만 둔다")
    for k, a, b in runs[:-1]:
        if k == "closing":
            errs.append(f"{pg(a)}쪽: 닫는 장은 맨 끝에만 둔다")
    last_k, last_p = None, -1.0
    for k, a, b in runs:
        if k in REPEATABLE:
            continue
        if pos[k] < last_p:
            ko = {v: kk for kk, v in STAGE_KEY.items()}
            errs.append(f"{pg(a)}쪽: '{ko[k]}' 가 '{ko[last_k]}' 뒤에 왔다 — 템플릿 순서(위치 중앙값 {pos[k]:.2f} < {last_p:.2f})를 거스른다")
        else:
            last_k, last_p = k, pos[k]
    n = len(keys)
    turns = [r for r in runs if r[0] == "turn"]
    if not turns:
        warns.append("반전 단계가 없다(템플릿: 편당 반전 지점 3~6곳)")
    else:
        if turns[0][1] / n > 0.35:
            warns.append(f"첫 반전이 {pg(turns[0][1])}쪽({turns[0][1] / n:.0%} 지점) — 템플릿 규칙은 앞 35% 안")
        if not 3 <= len(turns) <= 6:
            warns.append(f"반전 묶음 {len(turns)}곳 — 템플릿 규칙은 3~6곳")
    if (runs[0][2] + 1) / n > 0.15:
        warns.append(f"여는 단계가 {runs[0][2] + 1}장 — 템플릿 규칙은 전체의 15% 이하")
    if sum(1 for r in runs if r[0] == "development") < 2:
        warns.append("전개가 2번 미만(템플릿: 21/25편에서 2번 이상)")
    return errs, warns


# ── 광고 칸(사양 맨 위 sponsorship 과 장의 stage: 광고) ─────────────────────────
# 기준은 private/decks/규칙/광고_협업_절차_<타임코드>.md 2절(광고 표시)과 4절(덱 구성의 차이)이다. 20% 는 우리가 정한 값이다.
SPONSOR = "sponsorship"
SPONSOR_STAGE = "광고"                       # 광고 구간의 장 — cards.STAGES 밖이다(단계 순서 검사는 이 장을 빼고 본다)
SPONSOR_KINDS = ("유료 광고", "협찬", "협업")
SPONSOR_WORDS = ("광고", "협찬")             # 표시 문구(label)에 이 낱말 가운데 하나가 있어야 한다(경제적 이해관계가 드러나게)
# 표시 문구에 있으면 안 되는 말 — 광고나 협찬임을 부정하는 꼴("광고 없음", "협찬 아님")이 낱말 검사를 지나가지 않게 한다
SPONSOR_DENY = ("없음", "없는", "없습니다", "없이", "아님", "아닌", "아닙니다", "아니다", "무관", "미포함", "불포함", "제외", "않")
SPONSOR_MAX_SHARE = 0.20                     # 광고 구간 장수 ≤ 광고 아닌 장수 × 이 값
SPONSOR_PIC_KINDS = ("기업 뉴스룸", "로고")   # 권리자 칸에 광고주 이름이 든 그림의 종류
SPONSOR_KEY = "_sponsor"                     # 검사·빌드가 구간의 쪽 사본에 넣는 칸 — 띠에 찍을 글. 사양 파일에는 쓰지 않는다
SPONSOR_FIELDS = ("kind", "sponsor", "label", "whole", "materials")
_HANGUL = re.compile(r"[가-힣]")


def _squash(t: str) -> str:
    return re.sub(r"\s+", "", _s(t))


def sponsor_info(spec: dict) -> dict | None:
    """사양의 광고 칸을 읽은 것 — {kind, sponsor, label, whole, materials, pages: 구간의 쪽(1부터), band: 띠에 찍을 글}.
    칸도 없고 stage: 광고 장도 없으면 None(광고 회차가 아니다). 모양이 틀려도 읽을 수 있는 만큼 돌려준다(오류는 sponsorship_errors 가 낸다)."""
    raw = spec.get(SPONSOR)
    slides = spec.get("slides") or []
    ad = [i for i, sl in enumerate(slides, 1) if isinstance(sl, dict) and _s(sl.get("stage")).strip() == SPONSOR_STAGE]
    if raw is None and not ad:
        return None
    d = raw if isinstance(raw, dict) else {}
    whole = d.get("whole") is True
    label, sponsor = _s(d.get("label")).strip(), _s(d.get("sponsor")).strip()
    mats = d.get("materials")
    return {"kind": _s(d.get("kind")).strip(), "sponsor": sponsor, "label": label, "whole": whole,
            "materials": [_s(m).strip() for m in mats if _s(m).strip()] if isinstance(mats, list) else [],
            "pages": list(range(1, len(slides) + 1)) if whole else ad, "ad_pages": ad,
            "band": " · ".join(x for x in (label, sponsor) if x)}


def sponsor_view(sl: dict, info: dict | None, page: int) -> dict:
    """구간의 쪽이면 띠 글(SPONSOR_KEY)을 넣은 쪽 사본, 아니면 그 쪽 그대로. 검사(넘침)와 빌드가 같은 사본을 쓴다."""
    if info and info["band"] and page in info["pages"]:
        return {**sl, SPONSOR_KEY: info["band"]}
    return sl


def sponsorship_errors(spec: dict, pics: dict | None = None, *, info: dict | None = None) -> list[str]:
    """광고 칸 검사(실패 목록). 광고 회차가 아니면(칸도 광고 장도 없다) 빈 목록."""
    if info is None:
        info = sponsor_info(spec)
    if info is None:
        return []
    raw = spec.get(SPONSOR)
    slides = spec.get("slides") or []
    ad = info["ad_pages"]
    if raw is None:
        return [f"{', '.join(map(str, ad))}쪽: stage '{SPONSOR_STAGE}' 장이 있는데 사양 맨 위 {SPONSOR} 칸이 없다 — "
                f"{{kind: {' | '.join(SPONSOR_KINDS)}, sponsor: 광고주 이름, label: 표시 문구, whole: 참/거짓, materials: [광고주 제공 자료 이름]}} 을 적는다"]
    if not isinstance(raw, dict):
        return [f"{SPONSOR} 는 {{kind, sponsor, label, whole, materials}} 의 사전이어야 한다"]
    errs: list[str] = []
    extra = [k for k in raw if k not in SPONSOR_FIELDS]
    if extra:
        errs.append(f"{SPONSOR} 에 모르는 칸 {extra} 가 있다({', '.join(SPONSOR_FIELDS)})")
    if info["kind"] not in SPONSOR_KINDS:
        errs.append(f"{SPONSOR}.kind '{info['kind']}' 는 {' · '.join(SPONSOR_KINDS)} 가운데 하나여야 한다")
    if not info["sponsor"]:
        errs.append(f"{SPONSOR}.sponsor(광고주 이름)가 비었다")
    label = info["label"]
    if not label:
        errs.append(f"{SPONSOR}.label(표시 문구)이 비었다")
    else:
        if not _HANGUL.search(label):
            errs.append(f"{SPONSOR}.label '{label}' 에 한글이 없다 — 표시 문구는 한글로 쓴다(영문 약어만 쓰지 않는다)")
        deny = [w for w in SPONSOR_DENY if w in label]
        if deny:
            errs.append(f"{SPONSOR}.label '{label}' 에 광고나 협찬임을 부정하는 말({' · '.join(repr(w) for w in deny)})이 있다 — "
                        "표시 문구는 광고나 협찬이라는 사실을 밝히는 글이다(예: 유료 광고 포함, 협찬 포함)")
        if not any(w in label for w in SPONSOR_WORDS):
            errs.append(f"{SPONSOR}.label '{label}' 에 {' · '.join(repr(w) for w in SPONSOR_WORDS)} 낱말이 없다 — 경제적 이해관계가 드러나게 쓴다(예: 유료 광고 포함, 협찬 포함)")
    if "whole" in raw and not isinstance(raw.get("whole"), bool):
        errs.append(f"{SPONSOR}.whole 은 참/거짓이어야 한다(회차 전체가 광고인가)")
    mats = raw.get("materials")
    if mats is not None and not (isinstance(mats, list) and all(isinstance(m, str) and m.strip() for m in mats)):
        errs.append(f"{SPONSOR}.materials 는 광고주 제공 자료 이름(문자열)의 목록이어야 한다")
    pages = info["pages"]
    n_all = sum(1 for sl in slides if isinstance(sl, dict))
    if not info["whole"]:
        if not ad:
            errs.append(f"{SPONSOR} 칸이 있는데 stage: {SPONSOR_STAGE} 장이 없다 — 광고 구간의 장에 stage: {SPONSOR_STAGE} 를 적는다(회차 전체가 광고면 whole: true)")
        else:
            if ad != list(range(ad[0], ad[-1] + 1)):
                errs.append(f"광고 구간이 한 덩어리가 아니다({', '.join(map(str, ad))}쪽) — 본편 사이에 광고 장을 흩어 두지 않는다")
            if ad[0] == 1:
                errs.append("광고 구간이 여는 장보다 앞에 왔다(1쪽) — 본편을 연 뒤에 둔다")
            rest = n_all - len(ad)
            if len(ad) > rest * SPONSOR_MAX_SHARE:
                errs.append(f"광고 구간 {len(ad)}장 — 광고 아닌 장 {rest}장의 {SPONSOR_MAX_SHARE * 100:.0f}%({rest * SPONSOR_MAX_SHARE:.1f}장)를 넘는다")
    if pages and label and info["sponsor"]:
        for where, i in [("첫 장", pages[0])] + ([("끝 장", pages[-1])] if pages[-1] != pages[0] else []):   # 한 장짜리 구간은 그 장이 첫 장이자 끝 장이다
            sl = slides[i - 1] if isinstance(slides[i - 1], dict) else {}
            screen, said = _squash(" ".join(visible_text(sl))), _squash(" ".join(spoken_text(sl)))
            miss = [name for name, v in (("표시 문구", label), ("광고주 이름", info["sponsor"])) if _squash(v) not in screen]
            if miss:
                errs.append(f"{i}쪽: 광고 구간 {where}의 화면 글에 {' · '.join(miss)}('{label}' · '{info['sponsor']}')이 없다 — 띠와 별개로 그 장의 글에 적는다")
            if _squash(label) not in said:
                errs.append(f"{i}쪽: 광고 구간 {where}의 말로 할 문장(spoken · transition)에 표시 문구 '{label}' 이 없다")
    if info["sponsor"]:
        from ozl.render import pictures as PIC
        for pid, e in (pics or {}).items():
            if PIC.name_in(info["sponsor"], _s(e.get("rights_holder"))) and _s(e.get("kind")).strip() not in SPONSOR_PIC_KINDS:
                errs.append(f"picture {pid}: 권리자 칸에 광고주 이름('{info['sponsor']}')이 든 그림의 종류가 '{_s(e.get('kind')).strip()}' 다 — "
                            f"광고주가 준 그림은 {' · '.join(SPONSOR_PIC_KINDS)} 종류로 올린다(기업 뉴스룸은 사용 허락 기록)")
    return errs


# ── 글 배치(어절 줄바꿈) ─────────────────────────────────────────────────
_FONT_DIRS = [pathlib.Path("/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts"),
              pathlib.Path.home() / "Library/Fonts", pathlib.Path("/Library/Fonts")]


@lru_cache(maxsize=None)
def _font(bold: bool):
    try:
        from PIL import ImageFont
    except ImportError:  # pragma: no cover
        return None
    name = "malgunbd.ttf" if bold else "malgun.ttf"
    for d in _FONT_DIRS:
        p = d / name
        if p.exists():
            return ImageFont.truetype(str(p), 100)
    return None


def measure(text: str, size: float, bold: bool = False) -> float:
    """맑은 고딕으로 잰 글 폭(pt). 폰트 파일이 없으면 어림(한글 1em · 그 밖 0.55em)."""
    f = _font(bold)
    if f is not None:
        return f.getlength(text) * size / 100.0
    return sum(size if ord(ch) > 0x2E80 else size * 0.55 for ch in text) * (1.04 if bold else 1.0)


# 수량 덩어리(줄 사이에서 가르지 않는 낱말 묶음) — 판독(numbers.py)과 별개인 단순 규칙이다. 줄 배치에만 쓰고 숫자 검사에는 쓰지 않는다.
#   '약' + 숫자로 시작하는 낱말 · 숫자(+크기 단위 십·백·천·만·억·조)만인 낱말 + 숫자로 시작하는 낱말이나 단위 낱말 · '2022년'·'11월' + '11월'·'3분기'·'5일'
QTY_UNITS = ("퍼센트포인트", "제곱피트", "제곱미터", "퍼센트", "포인트", "달러", "가구", "개월", "시간", "배럴", "위안", "유로", "파운드", "분기",
             "%p", "명", "원", "개", "회", "건", "곳", "배", "톤", "%", "년", "월", "일", "엔", "대", "척", "주", "세", "살", "층", "분", "초", "장", "편",
             "million", "billion", "trillion", "thousand", "percent", "dollars", "miles", "mile", "feet", "tonnes", "tons", "people", "kg", "km", "bp")
_PARTICLE = (r"(?=$|[^가-힣A-Za-z]|(?:으로|로|에서|에|은|는|이|가|을|를|의|와|과|도|만|씩|까지|부터|이다|였다|이었다|이며|이고|입니다|"
             r"정도|가량|쯤|어치|짜리|당|째|간|이나|나|보다|다|인|씩))")
_UNIT_WORD = re.compile(r"^(?:" + "|".join(map(re.escape, QTY_UNITS)) + r")" + _PARTICLE, re.I)
_NUM_WORD = re.compile(r"^[(\[“\"'‘]?[-+−△▲▽▼]?[$€£¥₩]?\d")
_NUM_OPEN = re.compile(r"^[(\[“\"'‘]?[-+−△▲▽▼]?[$€£¥₩]?\d[\d,.]*[십백천만억조경]*$")
_DATE_OPEN = re.compile(r"^\d{1,4}(?:년|월)$")
_DATE_NEXT = re.compile(r"^\d{1,2}(?:월|일|분기)" + _PARTICLE)


def _qty_joined(prev: str, nxt: str) -> bool:
    if prev == "약":
        return bool(_NUM_WORD.match(nxt))
    if _DATE_OPEN.match(prev):
        return bool(_DATE_NEXT.match(nxt))
    if _NUM_OPEN.match(prev):
        return bool(_NUM_WORD.match(nxt) or _UNIT_WORD.match(nxt))
    return False


def qty_groups(text: str, words: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """어절들을 수량 덩어리로 묶는다(덩어리 밖 어절은 홀로 한 묶음)."""
    groups: list[list[tuple[int, int]]] = []
    for s, e in words:
        if groups and _qty_joined(text[groups[-1][-1][0]:groups[-1][-1][1]], text[s:e]):
            groups[-1].append((s, e))
        else:
            groups.append([(s, e)])
    return groups


def wrap(text: str, width_pt: float, size: float, bold_mask: list[bool] | None = None, measure_fn=measure) -> list[tuple[int, int]]:
    """어절(공백으로 나뉜 덩어리) 단위로 줄을 나눈다. 반환 = 각 줄의 [시작, 끝) 글자 위치(줄 끝 공백 제외).
    수량 덩어리(qty_groups — '약 4억 1,000만 달러', '5만 명', '2022년 11월')는 한 줄에 둔다. 덩어리가 들어갈 자리가 없으면 덩어리 앞에서 줄을 바꾸고,
    덩어리 하나가 줄 폭보다 길면 그때만 덩어리 안에서 어절 단위로 나눈다.
    한 어절이 줄 폭보다 길어도 자르지 않고 그 줄에 홀로 둔다(검사에서 넘침으로 잡는다)."""
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if not words:
        return []
    mask = bold_mask or [False] * len(text)

    def w(a: int, b: int) -> float:
        tot, i = 0.0, a
        while i < b:
            j = i
            while j < b and mask[j] == mask[i]:
                j += 1
            tot += measure_fn(text[i:j], size, mask[i])
            i = j
        return tot

    lines: list[tuple[int, int]] = []
    cur: list[int] = []   # [a, b] 지금 줄

    def put(s: int, e: int):
        if not cur:
            cur[:] = [s, e]
        elif w(cur[0], e) <= width_pt:
            cur[1] = e
        else:
            lines.append((cur[0], cur[1]))
            cur[:] = [s, e]

    for g in qty_groups(text, words):
        gs, ge = g[0][0], g[-1][1]
        if len(g) == 1 or w(gs, ge) <= width_pt:
            put(gs, ge)   # 덩어리째 — 지금 줄에 안 들어가면 덩어리 앞에서 바꾼다
            continue
        if cur:          # 줄 폭보다 긴 덩어리: 덩어리 앞에서 줄을 바꾸고 그 안은 어절 단위
            lines.append((cur[0], cur[1]))
            cur.clear()
        for s, e in g:
            put(s, e)
    lines.append((cur[0], cur[1]))
    return lines


def emphasis_mask(text: str, phrases: list[str]) -> list[bool]:
    m = [False] * len(text)
    for ph in phrases or []:
        if not ph:
            continue
        for x in re.finditer(re.escape(ph), text):
            for i in range(x.start(), x.end()):
                m[i] = True
    return m


# ── 사양 ────────────────────────────────────────────────────────────────
@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pending: dict[int, list[str]] = field(default_factory=dict)  # 초안 모드: 쪽 번호 → 검증 대기 claim_id
    exempt_idents: list[str] = field(default_factory=list)  # 대조에서 면제한 식별자(검토자가 볼 수 있게 출력한다)
    metrics: list[str] = field(default_factory=list)  # v1 지표. 경고나 실패 건수에 포함하지 않는다.

    @property
    def ok(self) -> bool:
        return not self.errors


def load_spec(path: pathlib.Path) -> dict:
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}


def load_claims(ids, claims_dirs=()) -> tuple[dict[str, dict], set[str]]:
    """사양이 인용한 클레임을 읽는다(읽기만). 정본(private/desk/claims)에 없으면 claims_dirs(대기 폴더)에서 `<claim_id>.yaml` 을 찾는다.
    반환 = (클레임, 대기 폴더에서 온 claim_id). 대기 폴더 기록은 초안 모드에서만 쓸 수 있다(check 가 가른다)."""
    out: dict[str, dict] = {}
    staged: set[str] = set()
    dirs = [pathlib.Path(d) for d in claims_dirs or ()]
    for cid in ids:
        if not C.CLAIM_ID.match(cid):
            continue
        p = C.claim_path(cid)
        if p.exists() or p.is_symlink():
            real = p.resolve()
            canon = C.CLAIMS.resolve()
            out[cid] = C.load_yaml(real) if real.exists() else {}
            if p.is_symlink() or canon not in real.parents:
                staged.add(cid)  # 정본 자리에 놓인 링크 — 실제로 읽은 파일이 정본 폴더 밖이면 대기 기록과 같게 다룬다(엄격 모드 실패)
            if not out[cid]:
                del out[cid]
            continue
        for d in dirs:
            hits = sorted(d.rglob(f"{cid}.yaml")) if d.is_dir() else []
            if hits:
                c = C.load_yaml(hits[0])
                if c.get("claim_id") == cid:
                    out[cid] = c
                    staged.add(cid)
                break
    return out, staged


def cited_ids(spec: dict, *, all_refs: bool = False) -> list[str]:
    """검사가 읽을 기록을 모은다. all_refs는 지문용으로 장의 차트·캡처와 숫자 지정까지 따로 모은다."""
    seen: dict[str, None] = {}
    slides = spec.get("slides")
    for sl in slides if isinstance(slides, list) else []:
        if not isinstance(sl, dict):
            continue
        seen.update(dict.fromkeys(_part_cited(sl, visuals=all_refs, number_claims=all_refs)))
        swap = sl.get("swap")
        if isinstance(swap, dict):
            for part in (swap.get("set"), swap.get("slide")):
                seen.update(dict.fromkeys(_part_cited(part, visuals=True, number_claims=all_refs)))
    return list(seen)


def _part_cited(part, *, visuals: bool, number_claims: bool) -> list[str]:
    """장 또는 swap 한 덩어리에서 읽는다. 칸 모양 오류는 사양 검사가 낸다."""
    if not isinstance(part, dict):
        return []
    out: list[str] = []
    ids = part.get("claim_ids")
    if isinstance(ids, (list, dict)):
        out.extend(str(c) for c in ids)
    for key in (("conversions", NUMBER_CLAIMS) if number_claims else ("conversions",)):
        rows = part.get(key)
        if isinstance(rows, list):
            out.extend(str(row["claim_id"]) for row in rows if isinstance(row, dict) and row.get("claim_id"))
    if not visuals:
        return out
    pair = part.get("pair")
    for v in [part] + [x for x in (pair if isinstance(pair, list) else []) if isinstance(x, dict)]:
        ch = v.get("chart")
        if isinstance(ch, dict) and isinstance(ch.get("claims"), list):
            out += [str(c) for c in ch["claims"]]
        if isinstance(v.get("capture"), str) and v["capture"].strip():
            out.append(v["capture"].strip())
    return out


_REQUIRED = {
    "title_hook": ("title",),
    "image_text": ("title", "body"),
    "quote_translation": ("title", "en", "ko"),
    "number": ("title", "number"),
    "compare_table": ("title", "table"),
    "quote_line": ("title", "quote"),
    "closing": ("title", "body"),
    "capture_full": ("title",),   # 그림 자리는 capture 또는 picture(원문 화면 갈무리) 가운데 하나 — visual_errors 가 본다
    "photo_caption": ("title", "caption"),
    "image_pair": ("title", "pair"),
    "full_picture": (),
    "image_stack": ("title", "body"),
}
_NESTED = {"number": ("value",), "quote": ("text",), "table": ("header", "rows"), "image": ("what", "source")}


def _present(v) -> bool:
    return v is not None and (not isinstance(v, (str, list, dict)) or len(v) > 0) and _s(v).strip() != ""


def check(spec: dict, claims: dict[str, dict], template: dict, card: dict | None = None, layout_fn=None,
          draft: bool = False, staged: set[str] | None = None, appendix_fn=None, also_used=()) -> Report:
    """사양 전체 검사. layout_fn(slide) → 넘침 메시지 목록 (build.layout_problems — 글상자 크기를 아는 쪽이 준다).
    draft=True: 사람 대조 전·대기 폴더 기록을 인용해도 실패하지 않고 r.pending 에 쪽별로 모은다(기록은 실제로 있어야 하고 숫자 대조는 그대로).
    판 하나의 사양을 받는다(swap 칸이 남아 있으면 실패 — 두 판은 check_editions 가 가른다).
    also_used = 다른 판에서 쓰는 그림 번호 — '쓰지 않은 그림' 경고에서 뺀다."""
    r = Report()
    slides = spec.get("slides") or []
    cid = spec.get("card_id")
    if not cid:
        r.errors.append("card_id 가 없다")
    elif not C.CARD_ID.match(str(cid)):
        r.errors.append(f"card_id '{cid}' 가 카드 ID 형식(YYYY-MM-DD-am|pm|wk-NN)이 아니다")
    idents = spec.get("identifiers") or []
    if not isinstance(idents, list) or not all(isinstance(x, str) and x.strip() for x in idents):
        r.errors.append("identifiers 는 식별자 표기(문자열)의 목록이어야 한다")
        idents = []
    for k, v in (spec.get("source_labels") or {}).items():
        if not C.CLAIM_ID.match(str(k)) or not _present(v):
            r.errors.append(f"source_labels: '{k}' 는 claim_id 와 짧은 출처 이름의 짝이어야 한다")
    style = spec.get("style")
    if style is not None and style not in STYLES:
        r.errors.append(f"style '{style}' 를 모른다({', '.join(STYLES)} — 옛 규칙이면 style 칸을 두지 않는다)")
        style = None
    sponsor = sponsor_info(spec)
    if spec.get("template") == "v1":
        from ozl.render import style as ST
        errs, warns, r.metrics = ST.template_v1_check(spec, draft=draft, sponsor=sponsor or {})
        r.errors += errs
        r.warnings += warns
    elif "template" in spec:
        r.errors.append(f"template '{spec['template']}' 를 모른다(v1 만 허용)")
    if not slides:
        r.errors.append("slides 가 비었다")
        return r
    card_sources = {s.get("name") for s in (card or {}).get("sources") or []}
    # 사양에 직접 적은 보도 출처(카드 sources 에 아직 반영되지 않은 것) — 초안 모드에서만 refs 로 쓸 수 있다
    press = {}
    for k, ps in enumerate(spec.get("press_sources") or []):
        if not isinstance(ps, dict) or not all(_present(ps.get(x)) for x in ("name", "tier", "url")):
            r.errors.append(f"press_sources[{k}]: name·tier·url 셋 다 있어야 한다")
            continue
        if str(ps["tier"]) not in C.TIERS:
            r.errors.append(f"press_sources[{k}]: tier '{ps['tier']}' 는 {C.TIERS} 가 아니다")
        if not str(ps["url"]).startswith(("https://", "http://")):
            r.errors.append(f"press_sources[{k}]: url 이 주소가 아니다")
        press[str(ps["name"])] = ps
    from ozl.render import pictures as PIC
    pics, perrs = PIC.ledger(spec)
    r.errors += perrs
    used_pics: set[str] = set()
    links = link_plan(spec, claims) if style == "syuka" else None
    if links is not None:
        r.errors += link_errors(spec, claims) + links.errors   # 링크 없는 기록 · 받치는 기록을 정할 수 없는 수치 자리
    bare: list[int] = []  # 엄격 모드: 그림이 하나도 없는 image_text 쪽(경고 한 줄로 모은다)
    for i, sl in enumerate(slides, 1):
        tag = f"{i}쪽"
        if not isinstance(sl, dict):
            r.errors.append(f"{tag}: 슬라이드가 사전(mapping)이 아니다")
            continue
        kind = sl.get("kind")
        if "side" in sl:
            if sl["side"] not in ("left", "right"):
                r.errors.append(f"{tag}: side 는 left 또는 right 여야 한다")
            elif kind not in SIDE_KINDS:
                r.errors.append(f"{tag}: side 는 {', '.join(SIDE_KINDS)} 에서만 쓴다")
        if PIC.SWAP in sl:
            r.errors.append(f"{tag}: swap 칸이 남아 있다 — 판을 가른 사양(pictures.strip_swaps · apply_swaps)을 검사한다. "
                            "check · build 명령과 check_editions 가 가른다")
        if kind not in KINDS:
            r.errors.append(f"{tag}: 슬라이드 종류 '{kind}' 를 모른다({', '.join(KINDS)})")
            continue
        for k in _REQUIRED[kind]:
            if not _present(sl.get(k)):
                r.errors.append(f"{tag}: {kind} 에는 '{k}' 가 있어야 한다")
        for k, subs in _NESTED.items():
            v = sl.get(k)
            if v is None:
                continue
            if not isinstance(v, dict):
                r.errors.append(f"{tag}: '{k}' 는 사전(mapping)이어야 한다")
                continue
            for sub in subs:
                if not _present(v.get(sub)):
                    r.errors.append(f"{tag}: '{k}.{sub}' 가 있어야 한다")
        tbl = sl.get("table") if isinstance(sl.get("table"), dict) else {}
        for j, row in enumerate(tbl.get("rows") or []):
            if not isinstance(row, list) or len(row) != len(tbl.get("header") or []):
                n = len(row) if isinstance(row, list) else 1
                r.errors.append(f"{tag}: 표 {j + 1}행의 칸 수 {n} ≠ 머리글 {len(tbl.get('header') or [])}칸(YAML 쉼표에 칸이 쪼개졌는지 본다)")
        if tbl.get("widths") is not None:
            ws = tbl["widths"]
            if not isinstance(ws, list) or len(ws) != len(tbl.get("header") or []):
                r.errors.append(f"{tag}: 표 widths 칸 수가 머리글과 다르다")
            elif not all(isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w) and w > 0 for w in ws):
                r.errors.append(f"{tag}: 표 widths 는 양의 유한수여야 한다({ws})")
        # style: syuka 덱은 쪽 아래 출처 줄을 찍지 않는다(링크 목록이 맡는다) — 화면에 없는 글이라 숫자 대조에도 넣지 않는다
        foot = "" if style == "syuka" else footnote_text(sl, claims, card, spec.get("source_labels") or {})
        for t in visible_text(sl) + spoken_text(sl) + [foot]:
            for x in N.exempt_identifiers(t, idents):
                if x not in r.exempt_idents:
                    r.exempt_idents.append(x)
        for e in number_errors(sl, claims, draft, staged, [foot] + chart_screen_text(sl), idents):
            r.errors.append(f"{tag}: {e}")
        if draft:
            _, pend = claim_state_errors([str(x) for x in sl.get("claim_ids") or []], claims, True, staged)
            if pend:
                r.pending[i] = pend
        for c_id in sl.get("claim_ids") or []:
            c = claims.get(str(c_id)) or {}
            if card and c.get("card_id") and c.get("card_id") != spec.get("card_id"):
                r.warnings.append(f"{tag}: {c_id} 는 다른 카드의 클레임이다")
        for ref in sl.get("refs") or []:
            if card is not None and ref in card_sources:
                continue
            if ref in press:
                if draft:
                    r.pending.setdefault(i, []).append(f"보도:{ref}")
                else:
                    r.errors.append(f"{tag}: refs '{ref}' 는 사양 press_sources 에만 있다 — 카드 sources 에 반영되기 전에는 초안 모드(--draft)에서만 쓸 수 있다")
            elif card is not None or press:
                r.errors.append(f"{tag}: refs '{ref}' 가 카드 sources 와 사양 press_sources 의 name 에 없다")
        verrs, waits, vwarns = visual_errors(sl, claims, draft, pics, template_v1=spec.get("template") == "v1")
        r.errors += [f"{tag}: {e}" for e in verrs]
        r.warnings += [f"{tag}: {w}" for w in vwarns]
        for wait in waits:
            r.pending.setdefault(i, []).append(WAIT_IMAGE + wait)
        used_pics |= {_s(v.get("picture")).strip() for _, v in slot_views(sl) if _s(v.get("picture")).strip()}
        if not draft and kind == "image_text" and not visual_of(sl):
            bare.append(i)
        if sl.get("seconds") is None and style is None:   # style: syuka 는 style_check 가 실패로 본다
            r.warnings.append(f"{tag}: 예상 발화 시간(seconds)이 없다")
        if layout_fn is not None and not (kind == "image_pair" and not pair_shape_ok(sl)):
            # pair 의 모양이 틀리면 형식 실패 한 줄로 끝낸다(배치를 부르면 KeyError 같은 잡음이 한 줄 더 붙는다)
            # style: syuka 는 링크 번호(위첨자)까지 넣은 쪽으로 넘침을 본다 — 빌드와 같은 글상자
            # 광고 구간의 쪽은 오른쪽 위 띠까지 넣은 쪽으로 본다
            for e in layout_fn(sponsor_view(with_links(sl, links.slides[i - 1]) if links is not None else sl, sponsor, i)):
                r.errors.append(f"{tag}: {e}")
    unused = [p for p in pics if p not in used_pics and p not in set(also_used or ())]
    if unused:
        r.warnings.append(f"그림 검수 대장에 있지만 어느 쪽에서도 쓰지 않은 그림: {', '.join(unused)}")
    if bare:
        r.warnings.append(f"그림 자리가 비었다(image_text 인데 chart·capture·picture·image 가 없다): {', '.join(map(str, bare))}쪽 — 글만 있는 장이 의도면 그대로 둔다")
    stages = [str(sl.get("stage")) if isinstance(sl, dict) else "" for sl in slides]
    if sponsor is None:
        errs, warns = stage_errors(stages, template)
    else:   # 광고 장을 뺀 순서로 본다(알리는 쪽 번호는 원래 번호)
        keep = [(i, s) for i, s in enumerate(stages, 1) if s.strip() != SPONSOR_STAGE]
        errs, warns = stage_errors([s for _, s in keep], template, [i for i, _ in keep])
        errs += sponsorship_errors(spec, pics, info=sponsor)
    r.errors += errs
    r.warnings += warns
    if style == "syuka":
        from ozl.render import style as ST
        errs, warns = ST.style_check(spec)
        r.errors += errs
        r.warnings += warns
    if appendix_fn is not None and not r.errors and style != "syuka":   # style: syuka 덱은 부록 쪽을 두지 않는다(링크 목록·그림 검수 대장이 덱 밖 파일로 나온다)
        r.errors += list(appendix_fn(spec, claims, card, r.pending))
    return r


@dataclass
class EditionCheck:
    name: str | None                # 판 이름(pictures.EDITION_PRIVATE · EDITION_SWAP). None = 판을 가르지 않는 한 판
    spec: dict                      # 그 판의 사양(swap 을 떼거나 적용한 뒤)
    report: Report
    swaps: list[dict] = field(default_factory=list)   # 바꾼 장 목록(pictures.apply_swaps) — 두 판이 같은 목록을 쓴다


def check_editions(spec: dict, claims: dict[str, dict], template: dict, card: dict | None = None, layout_fn=None,
                   draft: bool = False, staged: set[str] | None = None, appendix_fn=None, edition: str | None = None) -> list[EditionCheck]:
    """판마다 check 를 돌린다(pictures.plan_editions 가 판을 정한다). 막는 그림도 swap 도 없는 사양은 한 판 — check 를 그대로 부른 것과 같다.
    판 가르기 규칙의 실패(pictures.swap_errors)는 바꾼판의 실패로 적는다(바꾼판이 없으면 다루는 그 판에).
    claims 는 cited_ids(spec) 로 읽은 것 — swap 안에서 인용한 기록까지 들어 있어야 한다."""
    from ozl.render import pictures as PIC
    errs, plan = PIC.plan_editions(spec, draft, edition)
    if not plan:   # --edition 을 줄 수 없는 사양(막는 그림도 swap 도 없다) 또는 모르는 판 이름
        r = Report()
        r.errors += errs
        return [EditionCheck(edition, spec, r, [])]
    also = PIC.used_in_any_edition(spec) if PIC.has_swaps(spec) else set()
    out = [EditionCheck(name, sp, check(sp, claims, template, card, layout_fn, draft=draft, staged=staged, appendix_fn=appendix_fn, also_used=also), rows)
           for name, sp, rows in plan]
    if errs:
        target = next((x for x in out if x.name == PIC.EDITION_SWAP), out[-1])
        target.report.errors[:0] = errs
    return out
