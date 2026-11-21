"""덱과 원본 방송의 설계 규칙 비교 — 2026-11-21 집계.

출처: private/p3/rules/{slides_by_duration,stage_mix,skeletons,labeler_compare}.json.
실행할 때 원자료를 읽지 않는다. 원본은 줄 색을 쟀으므로, 우리 덱도 넘침 검사와
같이 나눈 본문 줄 중 문단 자체가 빨강인 줄만 센다. 검정 문단의 빨강 낱말은 제외한다.
"""
from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import yaml

from ozl.render import pictures, spec as S, style


class DurationBand(NamedTuple):
    low: int
    high: float
    videos: int
    median: float
    p25: float
    p75: float
    seconds: float


DURATION_BANDS = (
    DurationBand(0, 15, 1, 19, 19, 19, 32.05),
    DurationBand(15, 20, 3, 49, 47, 50, 23.49),
    DurationBand(20, 25, 11, 57, 53.5, 68.5, 24.81),
    DurationBand(25, 30, 44, 64.5, 57.75, 71, 25.67),
    DurationBand(30, 35, 40, 70, 64, 73, 27.43),
    DurationBand(35, math.inf, 26, 80, 71.25, 85, 29.68),
)
SLIDES_PER_MINUTE = 2.1764
UNCENTERED_R2 = .974
OVERALL_RED = .294
RED_BY_THIRD = (.107, .418, .496)
LABELED_VIDEOS = 122
LABELER_RANGES = {"반전": "11~18%", "한국 연결 위치": "59~74%", "유머 장 수": "8~14장"}

# 표본이 적으면 전체 직선을 쓰고, 경고는 작은 분모나 약간의 편차에는 내지 않는다.
V2_MIN_BAND_VIDEOS = 10
V2_DATA_MIN_SLIDES = 3
V2_DATA_CHART_MIN = 1 / 3
V2_RED_MIN_LINES = 20
V2_RED_TOL = .15
V2_RED_GROUP_MIN_LINES = 5
V2_SKELETON_WARN_SHARE = 2 / 3
# 비교표의 '같은 범위' 폭(경고를 내지 않는 표시용 판단). 단계 장 비율은 ±5%p, 단계 빨강 줄은 전체와 같은 ±15%p.
V2_STAGE_SHARE_TOL = .05


class StageMix(NamedTuple):
    videos: int
    slides: int
    share: float
    layout_sample: int
    layouts: dict[str, float]
    picture_sample: int
    pictures: dict[str, float]
    red: float


STAGE_MIX = {
    "hook": StageMix(121, 479, .056, 102, dict(image_left=.333, image_full=.304, media=.127),
                     102, dict(none=.373, photo=.157, chart=.137), .157),
    "lead_in": StageMix(14, 97, .011, 37, dict(image_left=.459, image_stack=.351, image_pair=.081),
                        37, dict(person=.270, article=.135, chart=.135), .211),
    "background": StageMix(83, 728, .085, 256, dict(image_left=.770, image_stack=.129, text_only=.047),
                           256, dict(person=.312, drawing=.180, photo=.152), .283),
    "data": StageMix(73, 576, .067, 132, dict(image_left=.470, image_stack=.265, text_only=.098),
                     132, dict(chart=.545, table=.076, photo=.068), .215),
    "development": StageMix(119, 2684, .314, 763, dict(image_left=.739, image_stack=.114, text_only=.056),
                            762, dict(person=.346, photo=.126, drawing=.121), .315),
    "turn": StageMix(119, 1443, .169, 334, dict(image_left=.772, image_stack=.129, text_only=.045),
                     334, dict(person=.293, chart=.189, drawing=.156), .336),
    "comparison": StageMix(82, 905, .106, 295, dict(image_left=.675, image_stack=.156, text_only=.098),
                           295, dict(person=.285, drawing=.149, photo=.119), .304),
    "implication": StageMix(67, 498, .058, 133, dict(image_left=.744, image_stack=.098, text_only=.053),
                            133, dict(person=.241, chart=.218, drawing=.165), .271),
    "solution": StageMix(48, 441, .052, 113, dict(image_left=.451, image_stack=.230, text_only=.177),
                         113, dict(drawing=.204, none=.204, article=.186), .152),
    "digression": StageMix(27, 100, .012, 36, dict(image_left=.667, image_full=.111, image_stack=.083),
                           36, dict(person=.472, photo=.194, drawing=.083), .223),
    "closing": StageMix(118, 372, .044, 97, dict(image_left=.433, media=.330, image_full=.082),
                        97, dict(drawing=.515, person=.124, logo=.093), .265),
}

# stage_mix.json 의 전체 장 모양(모양을 잰 2,398장). 노트의 머리 줄에 쓴다.
LAYOUT_SHARE = dict(image_full=.047123, image_left=.675563, image_pair=.031693, image_right=.020017,
                    image_stack=.133445, media=.026272, text_only=.065888)
LAYOUT_NAME = {**style.LAYOUT_NAME, "image_pair_partial": "그림 두 자리 중 하나"}
PICTURE_NAME = dict(person="인물", photo="사진", drawing="그린 그림", chart="도표", table="표",
                    article="기사·문서 화면", logo="로고", map="지도", meme="밈", sns="SNS 화면",
                    none="그림 없음", unknown="종류 모름")
PICTURE_KIND = {
    "직접 그린 도표": "chart", "직접 그린 지도": "map", "원문 화면 갈무리": "article",
    "보도자료 첨부(유형 표시 없음)": "article", "기업 뉴스룸": "article", "무료 스톡 인물 사진": "person",
    "통신사·언론사 사진": "photo", "방송 화면 캡처": "photo", "로고": "logo", "AI 개념도": "drawing",
    "실존 인물 AI 그림": "drawing", "사실처럼 보이는 AI 장면": "drawing", "밈": "meme", "화제 그림": "meme",
}
STAGE_NAME = {key: name for name, key in S.STAGE_KEY.items()}
CATEGORY_BRANCH = {
    "국제·지정학": "국제", "국내 경제·정책": "국내", "사회·문화": "국내",
    "금융·증시": "시장·기업", "역사·과학·기술": "시장·기업",
}
# 편수와 위치순 단계(키, 나온 편 비율, 처음 위치 중앙값, 장 비율 중앙값).
SKELETONS = {
    "국제": (42, (
        ("hook", 1., .014, .043), ("background", .738, .082, .108), ("development", 1., .172, .356),
        ("turn", .952, .317, .206), ("comparison", .619, .520, .126), ("implication", .619, .797, .093),
        ("closing", 1., .973, .041))),
    "국내": (23, (
        ("hook", 1., .015, .052), ("background", .652, .082, .091), ("data", .696, .130, .082),
        ("development", .957, .181, .316), ("turn", 1., .342, .110), ("comparison", .696, .424, .174),
        ("solution", .783, .516, .140), ("closing", 1., .976, .039))),
    "시장·기업": (50, (
        ("hook", .98, .014, .056), ("data", .72, .096, .116), ("background", .62, .167, .115),
        ("development", .98, .217, .315), ("turn", .98, .311, .176), ("comparison", .68, .470, .115),
        ("implication", .56, .760, .088), ("closing", .92, .982, .035))),
}


def branch_of(card):
    return CATEGORY_BRANCH.get(str((card or {}).get("category", "")))


def _duration_band(minutes):
    if not style._positive_time(minutes) or not math.isfinite(float(minutes) * 60):
        raise ValueError("minutes 는 초로 나타낼 수 있는 유한한 양수여야 한다")
    return next(b for b in DURATION_BANDS if minutes < b.high)


def v2_expected(minutes) -> tuple[int, str]:
    band = _duration_band(minutes)
    if band.videos < V2_MIN_BAND_VIDEOS:
        return max(1, round(minutes * SLIDES_PER_MINUTE)), f"1분 {SLIDES_PER_MINUTE:.2f}장 직선"
    high = "∞" if math.isinf(band.high) else str(band.high)
    basis = f"구간 [{band.low},{high})분 {band.videos}편 장당 초 {band.seconds:.2f}초"
    return max(1, round(float(minutes) * 60 / band.seconds)), basis


def picture_kind(sl, pics):
    if S.visual_of(sl) == "chart":
        return "chart"
    if sl.get("kind") == "compare_table":
        return "table"
    fallback = "none"
    for _, slot in S.slot_views(sl):
        visual = S.visual_of(slot)
        if visual == "image":
            fallback = "unknown"
        elif visual == "picture":
            entry = pics.get(str(slot["picture"]).strip(), {})
            return PICTURE_KIND.get(str(entry.get("kind")).strip(), "unknown")
        elif visual == "capture":
            return "article"
        elif visual == "chart":
            return "chart"
    return fallback


def red_lines(sl) -> tuple[int, int] | None:
    """(빨강 줄, 전체 본문 줄). 렌더러와 같은 쪽 사본(링크 번호, 광고 띠를 넣은 것)을 받아야 줄 감김이 같다.
    배치하지 못한 장은 None — 본문 0줄과 구분한다(배치 실패 자체는 별도 배치 검사가 실패시킨다)."""
    from ozl.render import build, deck
    red = total = 0
    try:
        for box in build.plan_slide(sl).boxes:
            if box.name in style.BODY_BOXES:
                total += box.layout()
                red += sum(len(p.lines) for p in box.paras if p.color == deck.EMPH_RGB)
    except (AttributeError, KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, OverflowError):
        return None
    return red, total


def _within(value, center, tol):
    # 경계에 꼭 놓인 값이 부동소수점 차이로 밖이 되지 않게 한다.
    return round(center - tol, 9) <= round(value, 9) <= round(center + tol, 9)


def _pct(count, total):
    return f"{count / total:.1%}" if total else "재지 못함"


def top_text(shares, names):
    return ", ".join(f"{names[k]} {v:.1%}" for k, v in shares.items())


@dataclass
class StageCount:
    layouts: Counter = field(default_factory=Counter)
    pictures: Counter = field(default_factory=Counter)
    red: int = 0
    lines: int = 0
    ratios: list = field(default_factory=list)   # 본문이 있는 장마다 빨강 줄 비율(원본 집계는 장별 비율의 평균이다)
    unmeasured: list = field(default_factory=list)   # 배치하지 못해 빨강 줄을 재지 못한 쪽

    @property
    def slides(self):
        return self.layouts.total()


SAME, DIFFERENT, WARN, ONLY = "같은 범위", "다름(경고 없음)", "다름(경고)", "범위만"


def _verdict(measured, different, warn=False):
    if not measured:
        return ONLY
    if warn:
        return WARN
    return DIFFERENT if different else SAME


@dataclass
class Comparison:
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    target: int | None = None

    def row(self, item, source, deck, verdict, warning=None):
        self.rows.append(dict(item=item, source=source, deck=deck, verdict=verdict))
        if warning:
            self.warnings.append(f"{warning}: {deck} — {source}")


def _count_report(report, minutes, count):
    try:
        target, basis = v2_expected(minutes)
    except ValueError:
        report.metrics.append(f"본편 {count}장 · v2 기대 장수 미정(발표 시간 오류)")
        report.row("장수", "발표 시간 필요", f"{count}장", ONLY)
        return
    report.target = target
    band = _duration_band(minutes)
    source = f"v2 기대 {target}장(근거: {basis}) · 같은 길이 원본 25~75% {band.p25:g}~{band.p75:g}장({band.videos}편)"
    deck = f"이 덱 본편 {count}장"
    outside = style.outside_count(count, target)
    report.metrics.append(f"{deck} · {source}")
    report.row("장수", source, deck, WARN if outside else SAME,
               f"W-장수 · 기대 장수의 ±{style.V1_COUNT_TOL:.0%} 밖" if outside else None)


def _stage_report(report, key, stats, n):
    name, src = STAGE_NAME[key], STAGE_MIX[key]
    share = _pct(stats.slides, n)
    pages = f"{stats.slides}장({share})"
    if key == "turn":   # 반전 단계의 장 비율은 라벨러에 따라 갈린다 — 범위로만 본다(아래 '범위로만' 행)
        report.row(f"{name} 장 비율", f"{src.share:.1%}(라벨러에 따라 {LABELER_RANGES['반전']})", pages, ONLY)
    else:
        near = bool(n) and _within(stats.slides / n, src.share, V2_STAGE_SHARE_TOL)
        report.row(f"{name} 장 비율", f"{src.share:.1%}(±{V2_STAGE_SHARE_TOL * 100:g}%p)", pages, SAME if near else DIFFERENT)
    parts = [f"{name} {pages}(원본 {src.share:.1%})"]
    for item, counts, baseline, names in (
        ("장 모양", stats.layouts, src.layouts, LAYOUT_NAME),
        ("그림 종류", stats.pictures, src.pictures, PICTURE_NAME),
    ):
        top = counts.most_common(3)
        ours = top_text({k: v / stats.slides for k, v in top}, names)
        source = top_text(baseline, names)
        # 덱의 최빈 범주가 원본 상위 셋에 드는지 비교한다. 동률이면 어느 쪽도 버리지 않는다.
        matches = any(counts[k] == top[0][1] for k in baseline)
        report.row(f"{name} {item}", source, ours, SAME if matches else DIFFERENT)
        parts.append(f"{item} 상위 {ours}(원본 {source})")
    source = f"{src.red:.1%}"
    mean = sum(stats.ratios) / len(stats.ratios) if stats.ratios else None
    red = f"장별 평균 {mean:.1%}({len(stats.ratios)}장)" if mean is not None else "재지 못함"
    far = mean is not None and not _within(mean, src.red, V2_RED_TOL)
    if stats.unmeasured:   # 그 단계에 배치하지 못한 장이 있으면 평균을 단정하지 않는다
        red = f"{', '.join(map(str, stats.unmeasured))}쪽 배치 실패로 재지 못함 · 나머지 {red}"
        report.row(f"{name} 빨강 줄", f"장별 평균 {source}(±{V2_RED_TOL * 100:g}%p)", red, ONLY)
    else:
        report.row(f"{name} 빨강 줄", f"장별 평균 {source}(±{V2_RED_TOL * 100:g}%p)", red, _verdict(mean is not None, far))
    parts.append(f"빨강 줄 {red}(원본 장별 평균 {source})")
    report.metrics.append(" · ".join(parts))


def _red_report(report, totals, groups, unmeasured=(), linked=False):
    red, lines = totals
    overall = _pct(red, lines)
    source = f"원본 {OVERALL_RED:.1%} ±{V2_RED_TOL * 100:g}%p"
    note = "" if linked else " · 링크 번호 없이 잼"
    if unmeasured:   # 배치하지 못한 장이 있으면 빨강 비율을 단정하지 않는다(그 장을 뺀 비율은 틀릴 수 있다)
        miss = f"{', '.join(map(str, unmeasured))}쪽 배치 실패로 재지 못함"
        report.row("빨강 본문 줄 전체", source, f"{miss} · 나머지 {red}/{lines}줄({overall}){note}", ONLY)
        report.row("단계별 빨강 비교", "근거 수치·해법이 다른 단계보다 낮다", miss, ONLY)
        report.metrics.append(f"빨강 본문 줄 전체: {miss}{note}(원본 {OVERALL_RED:.1%})")
        return
    outside = bool(lines) and not _within(red / lines, OVERALL_RED, V2_RED_TOL)
    warn = outside and lines >= V2_RED_MIN_LINES
    verdict = _verdict(lines, outside, warn)
    report.row("빨강 본문 줄 전체", source, f"{red}/{lines}줄({overall}){note}", verdict, "W-빨강 전체" if warn else None)
    low_keys = ("data", "solution")
    low_red = sum(g.red for k, g in groups.items() if k in low_keys)
    low_n = sum(g.lines for k, g in groups.items() if k in low_keys)
    others = [g for k, g in groups.items() if k not in (*low_keys, "hook", "closing")]
    other_red, other_n = sum(g.red for g in others), sum(g.lines for g in others)
    deck = f"줄 합산 근거 수치·해법 {_pct(low_red, low_n)} · 그 밖 단계 {_pct(other_red, other_n)}"
    source = "장별 평균 " + " · ".join(f"{STAGE_NAME[k]} {STAGE_MIX[k].red:.1%}" for k in (*low_keys, "development", "turn"))
    higher = low_red * other_n > other_red * low_n
    warn = higher and min(low_n, other_n) >= V2_RED_GROUP_MIN_LINES
    verdict = _verdict(low_n and other_n, higher, warn)
    report.row("단계별 빨강 비교", source, deck, verdict, "W-빨강 단계" if warn else None)
    report.metrics.append(f"빨강 본문 줄 전체: {overall}{note}(원본 {OVERALL_RED:.1%}) · {deck}")


def skeleton_order(branch):
    return " → ".join(STAGE_NAME[k] for k, *_ in SKELETONS[branch][1])


def _skeleton_report(report, stages, card):
    branch = branch_of(card)
    category = (card or {}).get("category") or "카드 갈래 없음"
    runs = [(s, i) for i, s in enumerate(stages) if not i or s != stages[i - 1]]
    order = " → ".join(f"{s or '단계 없음'}({(i + 1) / len(stages):.1%})" for s, i in runs) or "없음"
    source = skeleton_order(branch) if branch else "갈래 없음"
    report.metrics.append(f"뼈대: {branch or '갈래 없음'}({category}) · 원본 {source} · 이 덱 {order}")
    # 표의 판단은 단계가 처음 나오는 순서로 본다(전개·반전처럼 되풀이되는 단계의 묶음 수는 뼈대에 없다).
    firsts = list(dict.fromkeys(s for s in stages if s))
    first_order = " → ".join(firsts) or "없음"
    same = False
    if branch:
        names = [STAGE_NAME[k] for k, *_ in SKELETONS[branch][1]]
        same = [s for s in firsts if s in names] == [s for s in names if s in firsts]
    report.row("뼈대 순서(처음 나오는 순서)", f"{branch or '갈래 없음'}({category}): {source}", first_order,
               (SAME if same else DIFFERENT) if branch else ONLY)
    if branch:
        videos, skeleton = SKELETONS[branch]
        for key, share, _, _ in skeleton:
            if key in ("hook", "closing") or share < V2_SKELETON_WARN_SHARE:
                continue
            stage = STAGE_NAME[key]
            missing = stage not in stages
            report.row(f"{branch} 뼈대 · {stage}", f"원본 {videos}편 중 {share:.1%}에 {stage}",
                       f"{stage} {'없음' if missing else '있음'}", WARN if missing else SAME, "W-뼈대" if missing else None)


def _render_views(spec, claims, sponsor):
    """쪽마다 렌더러(build.build_pptx)가 그리는 사본 — 링크 번호(style: syuka)와 광고 띠를 넣는다.
    기록(claims)이 없거나 번호를 정할 수 없으면 링크 번호 없이 잰다(번호 오류는 check 가 실패시킨다)."""
    slides = spec.get("slides") or []
    links = None
    if claims is not None and spec.get("style") == "syuka":
        try:
            plan = S.link_plan(spec, claims)
        except (AttributeError, KeyError, TypeError, ValueError, IndexError):
            plan = None
        # 인용한 기록을 하나라도 찾지 못했으면 번호가 빠진 계획이다 — 링크 없이 잰 것으로 표시한다
        complete = set(S.cited_ids(spec)) <= set(claims)
        if plan is not None and complete and not plan.errors and len(plan.slides) == len(slides):
            links = plan.slides
    views = []
    for page, sl in enumerate(slides, 1):
        if not isinstance(sl, dict):
            views.append(sl)
            continue
        view = S.with_links(sl, links[page - 1]) if links is not None else sl
        # 직접 호출에서 정규화하지 않은 광고 정보(band 칸 없음)가 와도 예외를 내지 않는다
        band = sponsor if sponsor and "band" in sponsor and "pages" in sponsor else None
        views.append(S.sponsor_view(view, band, page))
    return views, links is not None


def _compare(spec, card, sponsor, claims=None):
    report = Comparison()
    pics, _ = pictures.ledger(spec)
    groups = defaultdict(StageCount)
    stages = []
    red = lines = count = 0
    unmeasured = []
    ad_pages = set(sponsor.get("pages", []))
    views, linked = _render_views(spec, claims, sponsor)
    for page, (sl, view) in enumerate(zip(spec.get("slides") or [], views), 1):
        if not isinstance(sl, dict):
            continue
        count += bool(sponsor.get("whole") or page not in ad_pages)
        measured = red_lines(view)
        if measured is None:
            unmeasured.append(page)
            page_red = page_lines = 0
        else:
            page_red, page_lines = measured
        red += page_red
        lines += page_lines
        stage = str(sl.get("stage") or "")
        if stage.strip() == S.SPONSOR_STAGE:
            continue
        stages.append(stage)
        key = S.STAGE_KEY.get(stage)
        if key:
            group = groups[key]
            group.red += page_red
            group.lines += page_lines
            if measured is None:
                group.unmeasured.append(page)
            elif page_lines:
                group.ratios.append(page_red / page_lines)
            group.layouts[style.template_layout(sl)] += 1
            group.pictures[picture_kind(sl, pics)] += 1

    _count_report(report, spec.get("minutes"), count)
    for key, group in groups.items():
        _stage_report(report, key, group, len(stages))
    data = groups.get("data", StageCount())
    charts = data.pictures["chart"] + data.pictures["table"]
    src = STAGE_MIX["data"].pictures
    source = f"도표·표 {src['chart'] + src['table']:.1%} · 경고선 {V2_DATA_CHART_MIN:.1%} 미만"
    below = charts < data.slides * V2_DATA_CHART_MIN
    warn = below and data.slides >= V2_DATA_MIN_SLIDES
    report.row("근거 수치 도표", source, f"도표·표 {charts}/{data.slides}장({_pct(charts, data.slides)})",
               _verdict(data.slides, below, warn), "W-근거 수치 도표" if warn else None)
    for stage, index in (("여는 장", 0), ("닫는 장", -1)):
        actual = stages[index] if stages else "없음"
        wrong = bool(stages) and actual != stage
        videos = STAGE_MIX[S.STAGE_KEY[stage]].videos
        report.row(stage, f"{stage} {videos}/{LABELED_VIDEOS}편", actual or "단계 없음",
                   _verdict(stages, wrong, wrong), f"W-{stage}" if wrong else None)
    _red_report(report, (red, lines), groups, unmeasured, linked)
    _skeleton_report(report, stages, card)
    turn = _pct(stages.count("반전"), len(stages))
    ranges = []
    for item, span in LABELER_RANGES.items():
        deck = turn if item == "반전" else "재지 않음 — 사양에 칸이 없다"
        label = "반전 단계 장 비율" if item == "반전" else item
        report.row(label, span, deck, ONLY)
        ranges.append(f"{label} 이 덱 {deck}(원본 라벨러에 따라 {span})" if item == "반전" else f"{label} 원본 {span}({deck})")
    report.metrics.append("범위로만: " + " · ".join(ranges))
    return report


def template_v2_check(spec, draft=False, *, sponsor=None, card=None, claims=None):
    if sponsor is None:
        sponsor = S.sponsor_info(spec) or {}
    report = _compare(spec, card, sponsor, claims)
    errors, warnings, metrics = style._template_check(spec, draft, sponsor=sponsor, version="v2",
                                                      alternative_target=report.target)
    return errors, warnings + report.warnings, metrics + report.metrics


def compare_rows(spec, card=None, draft=False, claims=None) -> list[dict]:
    """검사한 판 하나의 표. 초안과 완성본의 설계 기준은 같고, 그림 제거·판 나누기는 호출자가 맡는다."""
    sponsor = S.sponsor_info(spec) or {}
    report = _compare(spec, card, sponsor, claims)
    # 상속 지표는 v1 출력 원문을 그대로 쓴다. 원본과 단위를 맞출 수 없는 값에 새 판정을 붙이지 않는다.
    _, warnings, metrics = style.template_v1_check(spec, draft=draft, sponsor=sponsor)
    references = (
        ("목표 장수", f"장당 {style.TARGET_SEC_PER_SLIDE}초, 허용 ±{style.V1_COUNT_TOL:.0%}"),
        ("그림과 글", f"원본 글만 장 {style.TEXT_ONLY_SRC:.1%}"),
        ("장당 초", f"편별 중앙값 {style.SEC_PER_SLIDE_MEDIAN}초"),
        ("전체 장 모양", top_text(style.LAYOUT_SHARE, LAYOUT_NAME)),
        ("원문 화면", "옮겨 그린 상자보다 화면 갈무리를 먼저 쓴다"),
    )
    for (item, source), measured in zip(references, metrics, strict=True):
        report.row(f"v1 {item}", source, measured, ONLY)
    for warning in warnings:
        report.row("v1 경고", "상속한 템플릿 기준", warning, WARN)
    return report.rows


def _table(editions, card, draft, claims=None):
    def cell(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")

    lines = []
    for edition in editions:
        if edition.name:
            lines.extend([f"## {edition.name}", ""])
        lines.extend(["| 항목 | 원본 | 이 덱 | 판단 |", "|---|---|---|---|"])
        for row in compare_rows(edition.spec, card, draft, claims):
            lines.append("| " + " | ".join(cell(row[k]) for k in ("item", "source", "deck", "verdict")) + " |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    from ozl.render import build

    parser = argparse.ArgumentParser(description="사양 파일을 바꾸지 않고 v2 기준으로 검사한다.")
    parser.add_argument("spec", type=Path, metavar="사양.yaml")
    parser.add_argument("--draft", action="store_true", help="초안 모드로 검사한다")
    parser.add_argument("--claims-dir", type=Path, action="append", default=[], help="기록을 찾을 폴더(여러 번 가능)")
    parser.add_argument("--table", type=Path, help="비교표를 새 마크다운 파일에 쓴다")
    args = parser.parse_args(argv)
    try:
        sp = S.load_spec(args.spec)
        if not isinstance(sp, dict):
            raise ValueError("사양은 사전(mapping)이어야 한다")
        print(f"[v2] 사양의 template '{sp.get('template')}' 을 v2 로 보고 검사한다(파일은 그대로)")
        sp["template"] = "v2"
        if not args.draft:
            sp, dropped = pictures.drop_memes(sp)
            if dropped:
                print(f"[v2] {pictures.dropped_summary(dropped)}")
        card = build.resolve_card(sp.get("card_id"))
        claims, staged = S.load_claims(S.cited_ids(sp), args.claims_dir)
        editions = S.check_editions(sp, claims, S.load_template(), card, build.layout_problems, draft=args.draft,
                                    staged=staged, appendix_fn=build.appendix_problems)
        for edition in editions:
            report = edition.report
            tag = f"·{edition.name}" if edition.name else ""
            for label, messages in (("경고", report.warnings), ("실패", report.errors)):
                for message in messages:
                    print(f"[{label}{tag}] {message}")
            for page, pending in report.pending.items():
                print(f"[대기{tag}] {page}쪽: {', '.join(pending)}")
            print(f"[면제한 식별자{tag}] {', '.join(report.exempt_idents) or '없음'}")
            result = "통과" if report.ok else "실패"
            mode = " (초안 모드)" if args.draft else ""
            print(f"[check{tag}] {result}{mode} · 본편 {len(edition.spec.get('slides') or [])}장"
                  f" · 실패 {len(report.errors)} · 경고 {len(report.warnings)}")
            for line in report.metrics:
                print(f"[v2] {line}")
        if args.table:
            table = _table(editions, card, args.draft, claims)
            with args.table.open("x", encoding="utf-8") as out:
                out.write(table)
    except FileExistsError:
        print(f"[실패] 비교표가 이미 있다 — 덮어쓰지 않는다: {args.table}")
        return 1
    except (SystemExit, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"[실패] {exc}")
        return 1
    return int(any(not ed.report.ok for ed in editions))


if __name__ == "__main__":
    raise SystemExit(main())
