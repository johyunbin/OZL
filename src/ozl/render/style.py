"""슈카월드 스타일 덱 규칙(사양 맨 위 `style: syuka`) — 기준값, 검사, 장 배분, 견본집.

    python -m ozl.render outline --minutes <분>          # 목표 장수와 종류별 장수
    python -m ozl.render samples [--out <폴더>] [--no-export]   # 종류별 견본집(pptx · PDF · 쪽 PNG)

기준값은 `python -m ozl.render norms`(원본 방송 슬라이드 집계, norms.py)가 낸 수만 옮겨 둔다. 다시 세면 이 파일의 상수만 바뀐다.
옛 사양(style 칸 없음)은 이 검사를 받지 않는다 — spec.check 가 style == "syuka" 일 때만 style_check 를 부른다.

검사(style_check — 실패)
  - 장마다 seconds 가 있어야 한다.
  - 본편 장당 평균 초가 원본 편별 범위(SEC_PER_SLIDE_RANGE) 안이어야 한다.
  - 한 장의 seconds 가 원본 한 장에 머문 초의 95% 분위(DWELL_MAX)를 넘지 않는다.
  - 본문 줄 수(어절 단위로 나눈 결과)가 원본 본문 글줄 수의 95% 분위(BODY_LINES_MAX)를 넘지 않는다.
검사(경고)
  - 말로 할 문장(spoken · transition)의 글자 수(공백 제외)가 그 장 seconds 로 말할 수 있는 양(분당 SPEAK_CHARS_PER_MIN자)의 SPEAK_SLACK 배를 넘는다.
  - 글만 있는 장이 본편의 TEXT_ONLY_MAX 를 넘는다(원본은 TEXT_ONLY_SRC).
  - compare_table 이 본편의 COMPARE_TABLE_MAX 를 넘는다(원본은 표를 그림으로 붙인다).
  - 장 모양 분포가 원본 비율에서 LAYOUT_TOL 보다 크게 벗어난다(본편 LAYOUT_MIN_SLIDES 장 이상일 때).
검사(경고 — 제목 말투와 여는 장 · title_warnings. 말투는 사람이 쓰는 몫이라 실패로 두지 않는다)
  - 제목 글자 수(공백 제외)가 원본 사분위 상단(TITLE_LEN_MAX)보다 길다.
  - '~다'로 끝나는 보고서체 제목이 제목 있는 장의 TITLE_DA_MAX(원본 비율의 두 배)를 넘는다(제목 있는 장 TITLE_SHARE_MIN 장 이상일 때).
  - 본편 QUESTION_MIN_SLIDES 장 이상인데 물음형 제목이 하나도 없다.
  - 첫 장이 full_picture 가 아니다.
  - 첫 다섯 장(OPEN_QUESTION_WITHIN)의 제목 · 부제 · caption 가운데 물음형이 없다(평가 기준 나1).
  끝맺음 갈래는 원본 집계와 같은 함수(norms.title_ending)로 나눈다. 코드는 제목을 짓거나 고치지 않고, 유머를 판정하지 않는다.
장수 상한(옛 45장)은 두지 않는다. 장수는 말할 시간이 정한다(outline).

못 하는 것: 장 모양은 종류(와 그림 자리가 찼는지)로만 정한다(KIND_LAYOUT). 그림 안의 배치는 보지 않는다. 제목 말투는 끝맺음 갈래와 글자 수만 센다(뜻과 재미는 보지 않는다).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import pathlib
import re
import sys
from collections import Counter
from statistics import mean, median

import yaml

from ozl.render import norms as NM
from ozl.render import spec as S

ROOT = S.ROOT

# ── 기준값(원본 집계 private/decks/규칙/원본_집계_20261115_013559.json · 영상 110편, 장 7,721장, 반짝 장 제외) ──────────
NORMS_FILE = "private/decks/규칙/원본_집계_20261115_013559.json"
NORMS_VIDEOS = 110
SEC_PER_SLIDE_MEDIAN = 26.2          # 편별 장당 초(편 길이 ÷ 장수)의 중앙값
SEC_PER_SLIDE_RANGE = (18.0, 37.9)   # 편별 장당 초의 최소~최대 — 우리 덱 본편 평균이 이 밖이면 실패
DWELL_MAX = 57                       # 한 장에 머문 초의 95% 분위 — 이보다 긴 장은 실패(쪼갠다)
BODY_LINES_MAX = 10                  # 본문 크기 글줄 수의 95% 분위(중앙값 6)
TITLE_LEN_Q = (16, 21, 25)           # 제목 글자 수(공백 제외) 사분위 — 제목 있는 장 7,115장
TITLE_ENDING_SHARE = {"명사 등": 0.690, "~다": 0.132, "말투 어미": 0.058, "물음": 0.094, "느낌": 0.025}
OPEN_FIRST_MEDIA = (85, 110)         # 첫 장(반짝 장 제외)이 제목 없는 화면인 편 / 편수
OPEN_TWO_MEDIA_WITH_FLASH = (106, 110)   # 반짝 장까지 셀 때 첫 두 장이 모두 제목 없는 화면인 편 / 편수
LAYOUT_SHARE = {                     # 장 모양 비율(대표 프레임 7,720장을 slide_layout.classify 로 다시 판정)
    "image_left": 0.670, "image_stack": 0.135, "text_only": 0.060, "image_full": 0.050,
    "media": 0.038, "image_pair": 0.027, "image_right": 0.019,
}
TARGET_SEC_PER_SLIDE = 25            # outline 의 목표 장수 = 분 × 60 / 25 (계획에서 정한 값 · 원본 중앙값 26.2 보다 조금 촘촘하게)

# ── 검사의 폭(정한 값 — 집계가 아니다) ────────────────────────────────────
SPEAK_CHARS_PER_MIN = 300            # build.SPEAK_CHARS_PER_MIN 과 같다
SPEAK_SLACK = 1.3
TEXT_ONLY_SRC = LAYOUT_SHARE["text_only"]
TEXT_ONLY_MAX = 0.20
# NORMS_FILE에는 편별 장 모양이 없다. 10%는 원본 비교표의 글만 장 4.7%의 약 두 배이며, 확인 덱 반려 판정에서 정한 상한이다.
V1_TEXT_ONLY_MAX = 0.10
V1_PICTURE_MIN = 0.90
V1_COUNT_TOL = 0.15
V1_TIME_TOL = 0.10
V1_FULL_OR_PAIR_FROM = 30
V1_RIGHT_FROM = 40
COMPARE_TABLE_MAX = 0.05
LAYOUT_TOL = {"image_left": 0.30}    # 그 밖의 모양은 LAYOUT_TOL_DEFAULT
LAYOUT_TOL_DEFAULT = 0.15
LAYOUT_MIN_SLIDES = 10
TITLE_LEN_MAX = TITLE_LEN_Q[2]       # 제목 글자 수 경고선 = 원본 사분위 상단
TITLE_DA_MAX = 2 * TITLE_ENDING_SHARE["~다"]   # '~다' 제목 비율 경고선 = 원본 비율의 두 배
TITLE_SHARE_MIN = 5                  # 끝맺음 비율은 제목 있는 장이 이만큼 있을 때만 본다(장이 적으면 한 장이 비율을 크게 흔든다)
QUESTION_MIN_SLIDES = 20             # 이 장수 이상이면 물음형 제목이 하나는 있어야 한다(원본 9.4%)
OPEN_KIND = "full_picture"           # 첫 장의 종류
OPEN_QUESTION_WITHIN = 5             # 이 장수 안에 물음이 선다(평가 기준 나1)

# ── 그림 자리의 읽힘과 채움(정한 값 — 집계가 아니다. pictures.placement_warnings 가 쓴다) ──────────────
SCREEN_WEB_BODY_PX = 14      # 웹 화면 갈무리의 본문 글자 크기 가정(CSS 픽셀). 정부·기관 누리집 본문은 대개 14~16px 이다 — 작은 쪽으로 잡아 경고가 먼저 나게 한다
SCREEN_DOC_BODY_PT = 10      # PDF 문서 갈무리의 본문 글자 크기 가정(pt). 보도자료와 통계 보고서 본문은 대개 10~12pt 이고 표 안은 더 작다
SCREEN_MIN_PT = 7.0          # 갈무리 글자가 슬라이드에서 이보다 작게 찍히면 경고. 우리 화면에서 가장 작은 글(그림 밑 표기 10pt, 링크 번호 8pt)보다
#                              조금 작은 값이다 — 방송 화면(1080p 의 왼쪽 60%)에 놓이면 7pt 글자는 높이 약 7px 이라 그 아래는 읽지 못한다
PICTURE_FILL_MIN = 0.5       # 그림이 자리 넓이의 이 비율을 채우지 못하면 경고(쪽 판정의 '빈칸' — 확인 기준 2절 5번). 가로세로 비가 자리와 크게 다른 그림이 걸린다

LAYOUT_NAME = {
    "image_left": "좌 그림 + 우 글", "image_stack": "그림 위아래 + 글", "text_only": "글만", "image_full": "그림 위주",
    "media": "제목 없는 화면", "image_pair": "그림 2장", "image_right": "우 그림 + 좌 글",
}
# 우리 종류 → 원본 장 모양. 그림 자리가 있는 종류는 자리가 비면 '글만'으로 센다.
KIND_LAYOUT = {
    "image_text": "image_left", "number": "image_left", "quote_translation": "image_left",
    "capture_full": "image_full", "photo_caption": "image_full",
    "full_picture": "media", "image_stack": "image_stack", "image_pair": "image_pair",
    "closing": "text_only", "quote_line": "text_only", "compare_table": "text_only", "title_hook": "text_only",
}
SLOT_OPTIONAL = S.SIDE_KINDS   # 그림 자리를 비울 수 있는 종류
BODY_BOXES = ("본문", "원문·번역", "표 아래 글", "숫자 설명")    # 본문 줄 수를 세는 글상자(build.plan_slide 의 이름)


def layout_of(sl: dict) -> str:
    k = sl.get("kind")
    if k in SLOT_OPTIONAL:
        if not S.visual_of(sl):
            return "text_only"
        if sl.get("side") == "right":
            return "image_right"
    return KIND_LAYOUT.get(k, "text_only")


def body_lines(sl: dict) -> int:
    """본문 글상자들의 줄 수(어절 단위로 나눈 결과 — 넘침 검사와 같은 계산)."""
    from ozl.render import build as B
    try:
        pl = B.plan_slide(sl)
    except Exception:  # noqa: BLE001 — 배치가 안 되는 쪽은 layout 검사가 실패시킨다
        return 0
    return sum(b.layout() for b in pl.boxes if b.name in BODY_BOXES)


def speak_chars(sl: dict) -> int:
    return sum(len(re.sub(r"\s+", "", t)) for t in S.spoken_text(sl))


def _title(sl: dict) -> str:
    t = sl.get("title")
    return t.strip() if isinstance(t, str) else ""


def _asks(sl: dict) -> bool:
    """그 장의 제목 · 부제 · caption 가운데 물음형(norms.title_ending == '물음')이 있는가."""
    return any(isinstance(sl.get(k), str) and sl[k].strip() and NM.title_ending(sl[k]) == "물음" for k in ("title", "sub", "caption"))


def title_warnings(slides: list[dict]) -> list[str]:
    """제목 말투와 여는 장의 경고. 끝맺음은 원본 집계와 같은 갈래(norms.title_ending)로 센다."""
    warns: list[str] = []
    if not slides:
        return warns
    titled = [(i, _title(sl)) for i, sl in enumerate(slides, 1) if _title(sl)]
    for i, t in titled:
        n = NM.title_len(t)
        if n > TITLE_LEN_MAX:
            warns.append(f"{i}쪽: 제목 {n}자(공백 제외) — 원본 제목 글자 수 사분위 상단 {TITLE_LEN_MAX}자보다 길다(원본 중앙값 {TITLE_LEN_Q[1]}자)")
    ends = [NM.title_ending(t) for _, t in titled]
    if len(titled) >= TITLE_SHARE_MIN:
        da = ends.count("~다")
        if da / len(titled) > TITLE_DA_MAX:
            pages = ", ".join(str(i) for (i, _), e in zip(titled, ends) if e == "~다")
            warns.append(f"'~다'로 끝나는 제목 {da}장({da / len(titled) * 100:.0f}%) — 원본 {TITLE_ENDING_SHARE['~다'] * 100:.1f}%의 두 배"
                         f"({TITLE_DA_MAX * 100:.1f}%)를 넘는다(보고서체): {pages}쪽")
    if len(slides) >= QUESTION_MIN_SLIDES and "물음" not in ends:
        warns.append(f"본편 {len(slides)}장에 물음형 제목이 없다 — 원본 제목의 {TITLE_ENDING_SHARE['물음'] * 100:.1f}%가 물음으로 끝난다")
    first = slides[0].get("kind")
    if first != OPEN_KIND:
        warns.append(f"1쪽: 첫 장이 {first} 다 — 원본은 제목 없는 화면으로 연다(첫 장 {OPEN_FIRST_MEDIA[0]}/{OPEN_FIRST_MEDIA[1]}편, "
                     f"반짝 장까지 세면 첫 두 장 {OPEN_TWO_MEDIA_WITH_FLASH[0]}/{OPEN_TWO_MEDIA_WITH_FLASH[1]}편). {OPEN_KIND} 로 연다")
    head = slides[:OPEN_QUESTION_WITHIN]
    if not any(_asks(sl) for sl in head):
        warns.append(f"첫 {len(head)}장의 제목 · 부제 · caption 에 물음형이 없다 — 첫 {OPEN_QUESTION_WITHIN}장 안에 질문이 서야 한다(평가 기준 나1)")
    return warns


def _positive_time(value) -> bool:
    # math.isfinite 는 float 로 옮길 수 없는 큰 정수에서 예외를 낸다.
    return type(value) in (int, float) and 0 < value <= sys.float_info.max


def style_check(spec: dict) -> tuple[list[str], list[str]]:
    """style: syuka 사양의 장수·장당 초·장 모양 검사 — (실패, 경고)."""
    errs: list[str] = []
    warns: list[str] = []
    slides = [sl for sl in spec.get("slides") or [] if isinstance(sl, dict)]
    if not slides:
        return errs, warns
    secs = []
    for i, sl in enumerate(slides, 1):
        sec = sl.get("seconds")
        if sec is None:
            errs.append(f"{i}쪽: seconds(이 장에서 말할 초)가 없다 — style: syuka 는 장마다 적는다")
            continue
        if not _positive_time(sec):
            errs.append(f"{i}쪽: seconds '{sec}' 는 양수여야 한다")
            continue
        secs.append(sec)
        if sec > DWELL_MAX:
            errs.append(f"{i}쪽: {sec:g}초 — 원본 한 장에 머문 초의 95% 분위 {DWELL_MAX}초를 넘는다(한 장에 한 마디로 쪼갠다)")
        n = body_lines(sl)
        if n > BODY_LINES_MAX:
            errs.append(f"{i}쪽: 본문 {n}줄 — 원본 본문 글줄 수의 95% 분위 {BODY_LINES_MAX}줄을 넘는다")
        ch = speak_chars(sl)
        cap = sec / 60 * SPEAK_CHARS_PER_MIN * SPEAK_SLACK
        if ch > cap:
            warns.append(f"{i}쪽: 말로 할 문장 {ch}자 — {sec:g}초에 말할 수 있는 양({sec / 60 * SPEAK_CHARS_PER_MIN:.0f}자)의 {SPEAK_SLACK}배를 넘는다")
    if secs and len(secs) == len(slides):
        avg = mean(secs) if spec.get("template") == "v1" else sum(secs) / len(secs)
        lo, hi = SEC_PER_SLIDE_RANGE
        if not lo <= avg <= hi:
            errs.append(f"본편 장당 평균 {avg:.1f}초 — 원본 편별 범위 {lo}~{hi}초 밖이다(원본 {NORMS_VIDEOS}편 중앙값 {SEC_PER_SLIDE_MEDIAN}초)")
    n = len(slides)
    lays = [layout_of(sl) for sl in slides]
    text_only = lays.count("text_only") / n
    if text_only > TEXT_ONLY_MAX:
        warns.append(f"글만 있는 장 {lays.count('text_only')}장({text_only * 100:.0f}%) — 원본은 {TEXT_ONLY_SRC * 100:.1f}%, 허용 {TEXT_ONLY_MAX * 100:.0f}%까지")
    tables = sum(1 for sl in slides if sl.get("kind") == "compare_table")
    if tables / n > COMPARE_TABLE_MAX:
        warns.append(f"compare_table {tables}장({tables / n * 100:.0f}%) — 본편의 {COMPARE_TABLE_MAX * 100:.0f}%까지(원본은 표를 그림으로 붙인다)")
    if n >= LAYOUT_MIN_SLIDES:
        for k, src in LAYOUT_SHARE.items():
            ours = lays.count(k) / n
            tol = LAYOUT_TOL.get(k, LAYOUT_TOL_DEFAULT)
            if abs(ours - src) > tol:
                warns.append(f"장 모양 '{LAYOUT_NAME[k]}' {ours * 100:.0f}% — 원본 {src * 100:.1f}%에서 ±{tol * 100:.0f}% 밖이다")
    warns += title_warnings(slides)
    return errs, warns


def template_v1_check(spec: dict, draft: bool = False, *, sponsor: dict | None = None) -> tuple[list[str], list[str], list[str]]:
    """판 하나의 검사. 본편 장수와 본편에 필요한 모양만 광고를 빼고, 시간·비율·그림 수는 비교표처럼 전체 장에서 잰다."""
    from ozl.render import pictures as PIC

    errs, warns = [], []
    if spec.get("style") != "syuka":
        errs.append("template: v1 에는 style: syuka 가 필요하다")
    slides = []
    counts = Counter()
    main_layouts = []
    # 단독 호출도 check와 같은 광고 판정을 쓴다.
    if sponsor is None:
        sponsor = S.sponsor_info(spec) or {}
    ad_pages = set(sponsor.get("pages", []))
    pages = spec.get("slides") or []
    for page, sl in enumerate(pages, 1):
        if not isinstance(sl, dict):
            continue
        slides.append(sl)
        layout = layout_of(sl)
        if layout == "image_pair":
            slots = [v for _, v in S.slot_views(sl) if S.visual_of(v)]
            if len(slots) != 2:
                layout = "image_pair_partial" if slots else "text_only"
        counts[layout] += 1
        if page not in ad_pages:
            main_layouts.append(layout)
    main_count = len(main_layouts)
    n = len(slides)
    secs = [sl.get("seconds") for sl in slides]
    timed = bool(secs) and all(_positive_time(s) for s in secs)
    elapsed = None
    if timed:
        try:
            elapsed = math.fsum(secs)
        except OverflowError:
            timed = False
            errs.append("전체 seconds 합을 유한한 초로 나타낼 수 없다")
    whole_ad = sponsor.get("whole")
    count_for_target = n if whole_ad else main_count
    count_label = "전체" if whole_ad else "본편"
    target = None
    minutes = spec.get("minutes")
    planned = float(minutes) * 60 if _positive_time(minutes) else 0
    if not planned or not math.isfinite(planned):
        errs.append("minutes(발표 시간, 분)는 초로 나타낼 수 있는 유한한 양수여야 한다")
    else:
        target = max(1, round(planned / TARGET_SEC_PER_SLIDE))
        if abs(count_for_target - target) > target * V1_COUNT_TOL:
            errs.append(f"{count_label} {count_for_target}장 — 목표 {target}장의 ±{V1_COUNT_TOL:.0%} 밖이다")
        if elapsed is not None:
            # 분 → 초에서 생긴 부동소수점 한 자리 차이로 ±10% 경계값을 거부하지 않는다.
            low = math.nextafter(planned * (1 - V1_TIME_TOL), -math.inf)
            high = math.nextafter(planned * (1 + V1_TIME_TOL), math.inf)
            if not low <= elapsed <= high:
                errs.append(f"전체 seconds 합 {elapsed:g}초 — 발표 시간 {planned:g}초의 ±{V1_TIME_TOL:.0%} 밖이다")

    text = counts["text_only"]
    if n and text / n > V1_TEXT_ONLY_MAX:
        errs.append(f"글만 있는 장 {text}/{n}장 — 상한 {V1_TEXT_ONLY_MAX:.0%}를 넘는다")
    if n and (n - text) / n < V1_PICTURE_MIN:
        errs.append(f"그림 든 장 {n - text}/{n}장 — 하한 {V1_PICTURE_MIN:.0%}에 못 미친다")
    if main_count >= V1_FULL_OR_PAIR_FROM and not ("image_full" in main_layouts or "image_pair" in main_layouts):
        errs.append(f"본편 {main_count}장에 그림 위주(image_full) 또는 그림 2장(image_pair)이 한 장도 없다")
    if main_count >= V1_RIGHT_FROM and "image_right" not in main_layouts:
        warns.append(f"본편 {main_count}장에 우 그림 + 좌 글(image_right)이 없다")

    pics, _ = PIC.ledger(spec)
    screen_kinds = {PIC.SCREEN, "보도자료 첨부(유형 표시 없음)"}
    screen_kinds.update(k for k in PIC.KIND_RULES if k.startswith("공공누리 "))
    captures = screens = 0
    for i, sl in enumerate(slides, 1):
        slots = [v for _, v in S.slot_views(sl)]
        if any(v.get("image") for v in slots):
            (warns if draft else errs).append(f"{i}쪽: 회색 그림 자리(image)가 남아 있다")
        captures += any(S.visual_of(v) == "capture" for v in slots)
        page_kinds = (pics.get(str(v["picture"]).strip(), {}).get("kind") for v in slots if S.visual_of(v) == "picture")
        screens += any(str(k).strip() in screen_kinds for k in page_kinds)
    if captures > screens:
        warns.append(f"옮겨 그린 상자 {captures}장 > 화면 갈무리 {screens}장 — 원문 화면 갈무리를 먼저 쓴다")

    def share(count: int) -> str:
        return f"{round(count / n, 4):.1%}" if n else "모름"  # compare._share와 같은 표시 정밀도. 판정은 반올림하지 않는다.

    layouts = list(LAYOUT_SHARE)
    if counts["image_pair_partial"]:
        layouts.append("image_pair_partial")
    metrics = [
        f"전체 {len(pages)}장 · 본편 {len(pages) if whole_ad else main_count}장 · "
        + ("회차 전체가 광고 · 전체 목표 " if whole_ad else "목표 ") + f"{target if target is not None else '미정'}장",
        f"그림 든 장 {share(n - text)} · 글만 장 {share(text)}",
        f"장당 초: 평균 {mean(secs):.1f}초 · 중앙값 {median(secs):.1f}초" if timed else "장당 초: 산출 불가",
        "장 모양: " + ", ".join(f"{k} {counts[k]}장({share(counts[k])})" for k in layouts),
        f"옮겨 그린 상자 {captures}장 · 화면 갈무리 {screens}장",
    ]
    return errs, warns, metrics


# ── 장 배분 ──────────────────────────────────────────────────────────────
OUTLINE_KINDS = [   # (원본 장 모양, 쓸 종류) — 배분표에서는 좌우 배치를 한 종류로 합친다
    ("media", "full_picture"),
    ("image_left", "image_text · number · quote_translation"),
    ("image_stack", "image_stack"),
    ("image_full", "photo_caption · capture_full"),
    ("image_pair", "image_pair"),
    ("text_only", "closing · quote_line · compare_table"),
]


def outline(minutes: float) -> dict:
    """목표 장수(분 × 60 / 25)와 원본 비율 × 장수의 종류별 배분. 큰 나머지 순으로 반올림해 합을 맞추고, 여는 장 한 장(full_picture)을 둔다."""
    target = max(1, round(minutes * 60 / TARGET_SEC_PER_SLIDE))
    share = dict(LAYOUT_SHARE)
    share["image_left"] += share.pop("image_right")
    raw = {k: share[k] * target for k, _ in OUTLINE_KINDS}
    cnt = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - cnt[k], reverse=True)[: target - sum(cnt.values())]:
        cnt[k] += 1
    if cnt["media"] < 1 and target >= 2:   # 여는 장은 제목 없는 그림 한 장(원본 110편 가운데 85편)
        big = max(cnt, key=cnt.get)
        cnt[big] -= 1
        cnt["media"] += 1
    return {"minutes": minutes, "target": target, "sec_per_slide": TARGET_SEC_PER_SLIDE,
            "rows": [(k, kinds, cnt[k], share[k]) for k, kinds in OUTLINE_KINDS],
            "table_max": math.floor(target * COMPARE_TABLE_MAX)}


def outline_text(o: dict) -> str:
    L = [f"목표 장수 {o['target']}장 = {o['minutes']:g}분 × 60 ÷ {o['sec_per_slide']}초 (원본 {NORMS_VIDEOS}편의 장당 초 중앙값 {SEC_PER_SLIDE_MEDIAN}초)", "",
         "| 원본 장 모양 | 원본 비율 | 쓸 종류 | 장수 |", "|---|---|---|---|"]
    for k, kinds, n, sh in o["rows"]:
        L.append(f"| {LAYOUT_NAME[k]} | {sh * 100:.1f}% | {kinds} | {n} |")
    L += ["", f"- 첫 장은 full_picture(제목 없는 그림 한 장)로 연다(원본 {OPEN_FIRST_MEDIA[1]}편 가운데 {OPEN_FIRST_MEDIA[0]}편).",
          f"- compare_table 은 {o['table_max']}장까지(본편의 {COMPARE_TABLE_MAX * 100:.0f}%). 표는 그림으로 붙이는 쪽을 먼저 본다.",
          f"- 한 장에 한 마디. 한 장의 seconds 는 {DWELL_MAX}초를 넘지 않는다.",
          "- 이 표는 배분의 출발점이다. 코드는 문장을 짓지 않는다 — 사양을 쓰는 세션이 내용에 맞게 고친다."]
    return "\n".join(L)


# ── 견본집 ──────────────────────────────────────────────────────────────
SAMPLES = ROOT / "private" / "decks" / "samples"
SAMPLES_LINK = ROOT / "private" / "결과물" / "04_덱" / "견본집"
SAMPLE_CARD = "견본"
# 견본집의 광고 칸 — 지어낸 광고주와 지어낸 자료 이름이다(실제 회사가 아니다)
SAMPLE_SPONSOR = {"kind": "유료 광고", "sponsor": "가상제분", "label": "유료 광고 포함", "whole": False, "materials": ["가상제분 소개 자료(지어낸 자료)"]}


def _draw(path: pathlib.Path, shape: str, size=(1600, 900)) -> None:
    """직접 그린 단순 도형 그림(글자와 숫자 없음)."""
    from PIL import Image, ImageDraw
    w, h = size
    g = Image.new("RGB", size, (246, 244, 238))
    d = ImageDraw.Draw(g)
    red, grey, dark, blue = (192, 0, 0), (170, 170, 170), (60, 60, 60), (70, 110, 160)
    if shape == "sun":
        d.rectangle([0, int(h * 0.62), w, h], fill=(200, 214, 190))
        d.ellipse([int(w * 0.40), int(h * 0.18), int(w * 0.60), int(h * 0.18) + int(w * 0.20)], fill=(232, 160, 60))
        for k in range(5):
            x = int(w * (0.08 + 0.18 * k))
            d.polygon([(x, int(h * 0.62)), (x + int(w * 0.07), int(h * 0.40)), (x + int(w * 0.14), int(h * 0.62))], fill=(110, 140, 100))
    elif shape == "bars":
        d.line([int(w * 0.1), int(h * 0.85), int(w * 0.9), int(h * 0.85)], fill=dark, width=6)
        for k, r in enumerate((0.35, 0.5, 0.42, 0.68, 0.8)):
            x = int(w * (0.16 + 0.15 * k))
            d.rectangle([x, int(h * (0.85 - r * 0.8)), x + int(w * 0.09), int(h * 0.85)], fill=red if k == 4 else grey)
    elif shape == "circles":
        for k, (c, r) in enumerate(((blue, 0.26), (red, 0.18), (grey, 0.12))):
            cx, cy = int(w * (0.3 + 0.2 * k)), int(h * 0.5)
            d.ellipse([cx - int(h * r), cy - int(h * r), cx + int(h * r), cy + int(h * r)], fill=c)
    elif shape == "steps":
        for k in range(4):
            x0, y0 = int(w * (0.1 + 0.2 * k)), int(h * (0.75 - 0.15 * k))
            d.rectangle([x0, y0, x0 + int(w * 0.2), int(h * 0.85)], fill=blue if k % 2 else grey)
        d.ellipse([int(w * 0.78), int(h * 0.14), int(w * 0.86), int(h * 0.14) + int(w * 0.08)], fill=red)
    elif shape == "house":
        d.rectangle([int(w * 0.3), int(h * 0.45), int(w * 0.7), int(h * 0.85)], fill=grey)
        d.polygon([(int(w * 0.25), int(h * 0.47)), (int(w * 0.5), int(h * 0.15)), (int(w * 0.75), int(h * 0.47))], fill=red)
        d.rectangle([int(w * 0.46), int(h * 0.62), int(w * 0.54), int(h * 0.85)], fill=dark)
    else:   # wave
        pts = [(x, int(h * 0.5 + h * 0.2 * math.sin(x / w * 6.28 * 2))) for x in range(0, w, 8)]
        d.line(pts, fill=blue, width=14)
        d.line([(x, y + 90) for x, y in pts], fill=red, width=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    g.save(path)


def _pic(pid: str, path: pathlib.Path, at: str) -> dict:
    return {"id": pid, "path": str(path), "kind": "직접 그린 도표", "source_url": "견본집 생성 명령이 그린 도형(style.samples)",
            "origin": "직접 그림", "rights_holder": "OZL", "license": "직접 제작", "commercial_ok": True, "modify_ok": True,
            "attribution": "OZL 견본 그림", "reverse_search": {"did": "직접 그린 도형이라 하지 않음", "result": "해당 없음"},
            "synthetic_check": "직접 그린 도형", "content_check": "인물, 로고 없음", "checked_at": at, "as_is": True, "map": False,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def sample_spec(pic_dir: pathlib.Path) -> dict:
    """종류마다 한 장 이상 — 지어낸 문장, 직접 그린 도형, 숫자 없음, 기록 인용 없음.
    capture_full 은 받아들여진 기록의 원문 사본에서만 그려지므로 넣지 않는다(기록을 지어내지 않는다).
    광고 구간 두 장(구간의 첫 장과 끝 장 — 지어낸 광고주)이 들어 있다: 오른쪽 위 띠와, 첫 장 · 끝 장의 화면 글과 말에 든 표시 문구를 보인다.
    그림은 들어갈 자리의 가로세로 비에 맞춰 그린다(자리 넓이의 절반을 못 채우면 빈칸 경고 — PICTURE_FILL_MIN)."""
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    shapes = {"p1": "sun", "p2": "bars", "p3": "circles", "p4": "steps", "p5": "house", "p6": "wave", "p7": "circles"}
    sizes = {"p1": (1600, 900), "p6": (1600, 900), "p7": (1600, 900),   # full_picture — 쪽을 채우는 자리
             "p4": (2000, 520),                                        # image_stack — 넓고 낮은 자리(11.41 × 2.85in)
             "p5": (1850, 600)}                                        # photo_caption — 넓은 자리(11.41 × 3.70in)
    pics = []
    for pid, sh in shapes.items():
        f = pic_dir / f"{pid}_{sh}.png"
        _draw(f, sh, sizes.get(pid, (1200, 1000)))   # 그 밖은 왼쪽 그림 자리와 두 장 비교 자리
        pics.append(_pic(pid, f, at))
    sl = [
        {"kind": "full_picture", "stage": "여는 장", "picture": "p1", "seconds": 12, "spoken": "오늘은 동네 빵집 이야기로 시작합니다."},
        {"kind": "full_picture", "stage": "여는 장", "picture": "p6", "caption": "아침마다 줄이 생기는 가게", "seconds": 14, "spoken": "이 줄이 어디서 시작됐는지 따라가 봅니다."},
        {"kind": "title_hook", "stage": "우회 도입", "title": "빵값은 누가 정할까?", "sub": "가게 주인의 고민에서 출발", "seconds": 20},
        {"kind": "image_text", "stage": "배경", "title": "밀가루가 오면 가게가 바빠진다", "picture": "p2",
         "body": ["새벽에 반죽을 시작한다", {"text": "가장 바쁜 때는 아침", "red": True}, "점심 전에 진열대가 빈다"], "seconds": 26},
        {"kind": "number", "stage": "근거 수치", "title": "가게 주인이 꼽은 가장 큰 부담", "picture": "p3",
         "number": {"value": "재료비", "label": "날씨보다 먼저 꼽혔다"}, "seconds": 24},
        {"kind": "quote_translation", "stage": "전개", "title": "손님이 남긴 말", "en": "Fresh bread every morning.", "ko": "매일 아침 갓 구운 빵", "seconds": 22},
        {"kind": "image_stack", "stage": "전개", "title": "단팥빵은 왜 마지막까지 남을까?", "picture": "p4",
         "body": ["식빵이 먼저 나가고", {"text": "단팥빵은 늘 마지막까지 남는다", "red": True}], "seconds": 25},
        {"kind": "photo_caption", "stage": "전개", "title": "가게 앞 풍경", "picture": "p5", "caption": "골목 끝에서 보이는 빨간 지붕", "seconds": 20},
        {"kind": "full_picture", "stage": "여담", "picture": "p7", "caption": "지붕 색은 주인의 고집이었다", "seconds": 12,
         "spoken": "잠깐 딴 길로 새면, 저 지붕 색에도 사연이 있습니다."},
        # 광고 구간(지어낸 광고주) — 첫 장과 끝 장: 화면 글에 표시 문구와 광고주 이름, 말로 할 문장에 표시 문구. 장마다 오른쪽 위 띠는 빌드가 그린다
        {"kind": "image_text", "stage": S.SPONSOR_STAGE, "title": f"{SAMPLE_SPONSOR['label']}: {SAMPLE_SPONSOR['sponsor']}의 밀가루 이야기", "picture": "p2",
         "body": [f"이 구간은 {SAMPLE_SPONSOR['sponsor']}의 유료 광고다", {"text": "밀가루는 빵집의 새벽을 연다", "red": True}], "seconds": 20,
         "spoken": f"여기서부터는 {SAMPLE_SPONSOR['label']} 구간입니다. {SAMPLE_SPONSOR['sponsor']}이 보낸 이야기를 전합니다."},
        {"kind": "photo_caption", "stage": S.SPONSOR_STAGE, "title": "광고 구간을 마치며", "picture": "p5",
         "caption": f"{SAMPLE_SPONSOR['label']} · {SAMPLE_SPONSOR['sponsor']}의 광고 구간은 여기까지", "seconds": 16,
         "spoken": f"{SAMPLE_SPONSOR['label']} 구간은 여기까지입니다. 다시 빵집 이야기로 돌아갑니다."},
        {"kind": "image_pair", "stage": "비교", "title": "봄과 가을의 진열대",
         "pair": [{"picture": "p2", "caption": "봄에는 가벼운 빵"}, {"picture": "p3", "caption": "가을에는 묵직한 빵"}], "seconds": 25},
        {"kind": "compare_table", "stage": "비교", "title": "두 가게의 하루",
         "table": {"header": ["", "골목 빵집", "역 앞 빵집"], "rows": [["여는 때", "새벽", "아침"], ["손님", "동네 주민", "출근길 손님"]]}, "seconds": 26},
        {"kind": "quote_line", "stage": "반전", "title": "주인의 한마디", "quote": {"text": "빵은 결국 시간이 만든다", "by": "골목 빵집 주인(지어낸 인물)"}, "seconds": 18},
        {"kind": "closing", "stage": "닫는 장", "title": "오늘의 정리", "body": ["줄은 맛보다 시간에서 생긴다", "가게마다 바쁜 때가 다르다", "다음에는 우유 가게로 간다"], "seconds": 22},
    ]
    return {"card_id": SAMPLE_CARD, "style": "syuka", S.SPONSOR: dict(SAMPLE_SPONSOR), "pictures": pics, "slides": sl}


HUMOR_KINDS = ("full_picture", "photo_caption")   # caption 한마디를 둘 수 있는 종류(image_stack 은 아래 본문 한 줄)


def _note_extra(sl: dict) -> str:
    """견본 노트에 붙이는 자리 설명 — 여는 장, 물음형 제목, 유머 자리."""
    out = []
    if sl.get("stage") == "여는 장":
        out.append("여는 장: 제목 없는 그림으로 연다")
    if _asks(sl):
        out.append("물음형 제목(또는 caption)")
    if sl.get("stage") == S.SPONSOR_STAGE:
        out.append("광고 구간: 장마다 오른쪽 위 띠(표시 문구와 광고주), 첫 장과 끝 장은 화면 글과 말로 할 문장에도 표시 문구(광고주는 지어낸 이름)")
    elif sl.get("stage") == "여담" or (sl.get("kind") in HUMOR_KINDS and sl.get("caption")):
        out.append("유머 자리: caption 한마디 · 여담 단계(원본 문구를 옮기지 않고 사람·집단을 조롱하지 않는다)")
    return (" " + " · ".join(out) + ".") if out else ""


def sample_problems(spec: dict) -> list[str]:
    """견본 사양의 배치 넘침(광고 띠 포함)과 그림 검사(엄격 모드), 광고 칸 검사 — 카드 검사는 하지 않는다(card_id 가 견본).
    그림 경고(자리 넓이의 절반을 못 채운 그림 등)도 견본에서는 실패로 본다: 견본집에 빈 그림 자리를 두지 않는다."""
    from ozl.render import build as B
    from ozl.render import pictures as PIC
    pics, perrs = PIC.ledger(spec)
    out = list(perrs)
    sponsor = S.sponsor_info(spec)
    for i, sl in enumerate(spec["slides"], 1):
        out += [f"{i}쪽: {e}" for e in B.layout_problems(S.sponsor_view(sl, sponsor, i))]
        ve, waits, vw = S.visual_errors(sl, {}, False, pics)
        out += [f"{i}쪽: {e}" for e in ve] + [f"{i}쪽: 그림 대기 {w}" for w in waits] + [f"{i}쪽: {w}" for w in vw]
        out += [f"{i}쪽: 숫자를 쓰지 않는다 — '{t}'" for t in S.visible_text(sl) + S.spoken_text(sl) if re.search(r"\d", t)]
    errs, _ = style_check(spec)
    return out + errs + S.sponsorship_errors(spec, pics)


def samples(out_root: pathlib.Path = SAMPLES, export: bool = True, link: pathlib.Path | None = SAMPLES_LINK) -> dict:
    from pptx import Presentation

    from ozl.render import build as B
    from ozl.render import deck
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = out_root / f"견본집_{ts}"
    if outdir.exists():
        raise SystemExit(f"{outdir} 가 이미 있다 — 덮어쓰지 않는다")
    outdir.mkdir(parents=True)
    spec = sample_spec(outdir / "그림")
    probs = sample_problems(spec)
    if probs:
        raise SystemExit("견본 사양 검사 실패:\n" + "\n".join(probs))
    (outdir / f"견본_사양_{ts}.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    pptx = outdir / f"견본집_{ts}.pptx"
    B.build_pptx(spec, {}, {}, pptx, appendix=False)
    prs = Presentation(str(pptx))
    for sld, sl in zip(prs.slides, spec["slides"]):
        lay = layout_of(sl)
        sld.notes_slide.notes_text_frame.text = (f"[견본 · {sl['kind']}] 원본 장 모양 '{LAYOUT_NAME[lay]}' — 원본 {LAYOUT_SHARE.get(lay, 0) * 100:.1f}% "
                                                 f"(영상 {NORMS_VIDEOS}편 집계). 문장과 그림은 지어낸 것이다."
                                                 + _note_extra(sl))
    deck.finish_package(prs)   # 노트를 고쳐 다시 저장하므로 문서 통계(낱말 수)를 다시 쓴다
    prs.save(str(pptx))
    _, warns = style_check(spec)
    info = {"dir": str(outdir), "pptx": str(pptx), "slides": len(spec["slides"]), "style_warnings": len(warns)}
    for w in warns:
        print(f"[경고] {w}", file=sys.stderr)
    if export:
        pdf, pngs = deck.to_pdf_png(pptx)
        info.update(pdf=str(pdf) if pdf else None, pngs=len(pngs))
    if link is not None:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or not link.exists():
            if link.is_symlink():
                link.unlink()
            link.symlink_to(pathlib.Path("..") / ".." / "decks" / "samples")
        info["link"] = str(link)
    return info


def main(argv: list[str]) -> int:
    cmd, rest = argv[0], argv[1:]
    if any(a in ("-h", "--help") for a in rest):
        print(__doc__)
        return 0
    if cmd == "outline":
        if len(rest) != 2 or rest[0] != "--minutes":
            print("python -m ozl.render outline --minutes <분>", file=sys.stderr)
            return 2
        try:
            m = float(rest[1])
        except ValueError:
            print(f"--minutes '{rest[1]}' 는 수가 아니다", file=sys.stderr)
            return 2
        if not (math.isfinite(m) and m > 0):
            print("--minutes 는 양수다", file=sys.stderr)
            return 2
        print(outline_text(outline(m)))
        return 0
    out, export = SAMPLES, True
    it = iter(rest)
    for a in it:
        if a == "--out":
            v = next(it, None)
            if not v:
                print("--out 뒤에 폴더가 있어야 한다", file=sys.stderr)
                return 2
            out = pathlib.Path(v)
        elif a == "--no-export":
            export = False
        else:
            print(f"모르는 인자 {a}", file=sys.stderr)
            return 2
    info = samples(out, export, SAMPLES_LINK if out == SAMPLES else None)
    for k, v in info.items():
        print(f"{k}: {v}")
    return 0
