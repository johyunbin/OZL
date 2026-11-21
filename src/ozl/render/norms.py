"""원본 방송 슬라이드 집계 — 덱 새 규칙(style: syuka)의 기준값을 다시 센다.

    python -m ozl.render norms [--out <폴더>] [--no-frames] [--no-pdf]

읽는 것(읽기만 한다):
  private/data/derived/slides_dense/<영상>.json   장마다 머문 초, 제목 상자, 본문 글줄 상자, 흰 바탕 비율, 대표 프레임 이름
  private/data/raw/frames_dense/<영상>/<프레임>.png   장마다 고른 대표 프레임
장 모양은 `ozl.analyze.slide_layout.classify`(그 모듈은 고치지 않는다)를 대표 프레임마다 다시 불러 센다.
반짝 지나간 장(flash)은 세지 않는다(slide_structure.label_input 과 같다).

내는 것: <폴더>/원본_집계_<YYYYMMDD_HHMMSS>.json 과 .md(사람이 읽는 표, md2pdf 로 PDF 쌍).
결과에는 수와 비율만 담는다. 제목과 본문의 문구는 담지 않는다(제목은 글자 수와 끝맺음 갈래만 센다).
2026년 분석이 아직 도는 동안에는 편수가 늘어난다 — 몇 편까지 센 값인지 결과 머리에 적는다.
결과로 나온 수는 src/ozl/render/style.py 의 상수로 옮긴다(이 명령은 style.py 를 고치지 않는다).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import statistics as st
import subprocess
import sys
from collections import Counter

from ozl import paths as ozlpaths

ROOT = pathlib.Path(__file__).resolve().parents[3]
DENSE = ozlpaths.at("slides_dense")
FRAMES = ozlpaths.at("frames_dense")
OUT = ozlpaths.at("decks", "규칙")
MD2PDF = pathlib.Path.home() / "Claude" / "tools" / "md2pdf.py"

LAYOUTS = ("image_left", "image_stack", "text_only", "image_full", "media", "image_pair", "image_right")
LAYOUT_NAME = {
    "image_left": "좌 그림 + 우 글", "image_stack": "그림 위아래 + 글", "text_only": "글만", "image_full": "그림 위주",
    "media": "제목 없는 화면", "image_pair": "그림 2장", "image_right": "우 그림 + 좌 글",
}
ENDINGS = ("명사 등", "~다", "말투 어미", "물음", "느낌")
_TALK = ("요", "죠", "네", "지", "야", "냐", "어", "아", "라", "자", "군", "구나", "걸", "까", "니", "래", "대", "게")


def title_ending(title: str) -> str:
    """제목 끝맺음 갈래(문자 인식 결과라 오차가 있다). 문구는 돌려주지 않는다."""
    t = re.sub(r"[\s\"'”’)\]…·.,~]+$", "", title or "")
    if not t:
        return "명사 등"
    if t.endswith("?") or t.endswith("？"):
        return "물음"
    if t.endswith("!") or t.endswith("！"):
        return "느낌"
    t = t.rstrip("?!？！")
    if t.endswith("다"):
        return "~다"
    if t.endswith(_TALK):
        return "말투 어미"
    return "명사 등"


def title_len(title: str) -> int:
    return len(re.sub(r"\s+", "", title or ""))


def _q(xs: list[float], p: float) -> float:
    """p 분위(0~1) — 선형 보간."""
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _layout_of(vid: str, s: dict, use_frames: bool) -> str | None:
    """장 모양. 대표 프레임이 있으면 classify 로 다시 판정하고, 없으면 None(세지 않는다)."""
    if not use_frames:
        return s.get("layout")
    fp = FRAMES / vid / str(s.get("best_frame") or "")
    if not fp.is_file():
        return None
    import numpy as np
    from PIL import Image

    from ozl.analyze.slide_layout import classify
    with Image.open(fp) as g:
        a = np.asarray(g.convert("RGB"))
    return classify(a, s.get("title_box"), s.get("body_boxes") or [], s.get("white_ratio"))["layout"]


def collect(use_frames: bool = True, dense: pathlib.Path = DENSE) -> dict:
    vids = []
    per_sec: list[float] = []
    per_sec_all: list[float] = []   # 반짝 장까지 센 장당 초(앞선 집계와 견줄 값)
    open_all = 0                    # 반짝 장까지 셀 때 첫 두 장이 모두 제목 없는 화면인 편
    n_slides: list[int] = []
    durations: list[int] = []
    dwell: list[int] = []
    body_lines: list[int] = []
    tlen: list[int] = []
    ends: Counter = Counter()
    lay: Counter = Counter()
    lay_missing = 0
    open1_media = open2_both = open2_any = 0
    media_kind = 0
    titled = 0
    for p in sorted(dense.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        raw = d.get("slides") or []
        slides = [s for s in raw if not s.get("flash")]
        dur = int(d.get("duration_sec") or 0)
        if not slides or dur <= 0:
            continue
        per_sec_all.append(dur / len(raw))
        open_all += len(raw) >= 2 and all(x.get("kind") == "media" for x in raw[:2])
        vid = str(d.get("video_id") or p.stem)
        vids.append(vid)
        n_slides.append(len(slides))
        durations.append(dur)
        per_sec.append(dur / len(slides))
        kinds = []
        for s in slides:
            dwell.append(int(s.get("dwell_sec") or 0))
            L = _layout_of(vid, s, use_frames)
            is_media = s.get("kind") == "media" or L == "media"
            kinds.append(is_media)
            if L is None:
                lay_missing += 1
            else:
                lay[L] += 1
            if is_media:
                media_kind += 1
                continue
            body_lines.append(int(s.get("body_text_lines") or 0))
            if s.get("title"):
                titled += 1
                tlen.append(title_len(s["title"]))
                ends[title_ending(s["title"])] += 1
        open1_media += kinds[0]
        if len(kinds) >= 2:
            open2_both += kinds[0] and kinds[1]
            open2_any += kinds[0] or kinds[1]
    nv = len(vids)
    nl = sum(lay.values())
    nt = sum(ends.values())
    return {
        "counted_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "videos": nv,
        "slides": sum(n_slides),
        "frames_used": use_frames,
        "slides_per_video": {"median": st.median(n_slides), "min": min(n_slides), "max": max(n_slides)},
        "duration_sec": {"median": st.median(durations), "min": min(durations), "max": max(durations)},
        "sec_per_slide": {"median": round(st.median(per_sec), 1), "mean": round(st.mean(per_sec), 1),
                          "min": round(min(per_sec), 1), "max": round(max(per_sec), 1),
                          "p10": round(_q(per_sec, 0.10), 1), "p90": round(_q(per_sec, 0.90), 1)},
        "sec_per_slide_with_flash": {"median": round(st.median(per_sec_all), 1), "min": round(min(per_sec_all), 1), "max": round(max(per_sec_all), 1)},
        "slides_per_30min": round(st.median([n * 1800 / d for n, d in zip(n_slides, durations)]), 1),
        "dwell_sec": {"median": _q(dwell, 0.5), "p90": _q(dwell, 0.90), "p95": _q(dwell, 0.95), "p99": _q(dwell, 0.99), "max": max(dwell)},
        "body_lines": {"median": _q(body_lines, 0.5), "p90": _q(body_lines, 0.90), "p95": _q(body_lines, 0.95),
                       "p99": _q(body_lines, 0.99), "max": max(body_lines) if body_lines else 0},
        "layout": {k: {"n": lay[k], "share": round(lay[k] / nl, 4) if nl else 0.0} for k in LAYOUTS},
        "layout_counted": nl,
        "layout_missing_frame": lay_missing,
        "media_slides": media_kind,
        "titled_slides": titled,
        "title_len": {"q1": _q(tlen, 0.25), "median": _q(tlen, 0.5), "q3": _q(tlen, 0.75)},
        "title_ending": {k: {"n": ends[k], "share": round(ends[k] / nt, 4) if nt else 0.0} for k in ENDINGS},
        "opening": {"first_media": open1_media, "first_two_media": open2_both, "either_of_first_two_media": open2_any,
                    "first_two_media_with_flash": open_all, "videos": nv},
    }


def to_md(r: dict) -> str:
    sp = r["sec_per_slide"]
    L = [
        "---", "kicker: 덱 규칙", f"date: {r['counted_at'][:10]}", "theme: doc", "---", "",
        "# 원본 방송 슬라이드 집계", "",
        f"{r['counted_at']} 에 `python -m ozl.render norms` 로 센 값이다. 영상 {r['videos']}편, 장 {r['slides']}장(반짝 지나간 장 제외). "
        "제목과 본문의 문구는 담지 않고 수와 비율만 담는다. 2026년 분석이 도는 동안에는 편수가 늘어난다.", "",
        "## 장수와 장당 초", "",
        "| 항목 | 값 |", "|---|---|",
        f"| 편당 장수 | 중앙값 {r['slides_per_video']['median']}장 (최소 {r['slides_per_video']['min']}, 최대 {r['slides_per_video']['max']}) |",
        f"| 편 길이 | 중앙값 {r['duration_sec']['median']}초 (최소 {r['duration_sec']['min']}, 최대 {r['duration_sec']['max']}) |",
        f"| 편별 장당 초(편 길이 ÷ 반짝 장을 뺀 장수) | 중앙값 {sp['median']}초, 평균 {sp['mean']}초, 범위 {sp['min']}~{sp['max']}초, 10~90% {sp['p10']}~{sp['p90']}초 |",
        f"| 반짝 장(3초 표본 한 장)까지 센 장당 초 | 중앙값 {r['sec_per_slide_with_flash']['median']}초, 범위 {r['sec_per_slide_with_flash']['min']}~{r['sec_per_slide_with_flash']['max']}초 |",
        f"| 30분 환산 장수 | 중앙값 {r['slides_per_30min']}장 |",
        f"| 한 장에 머문 초 | 중앙값 {r['dwell_sec']['median']:.0f}, 90% {r['dwell_sec']['p90']:.0f}, 95% {r['dwell_sec']['p95']:.0f}, 99% {r['dwell_sec']['p99']:.0f}, 최대 {r['dwell_sec']['max']} |",
        f"| 본문 크기 글줄 수(제목 있는 장) | 중앙값 {r['body_lines']['median']:.0f}, 90% {r['body_lines']['p90']:.0f}, 95% {r['body_lines']['p95']:.0f}, 99% {r['body_lines']['p99']:.0f}, 최대 {r['body_lines']['max']} |",
        "",
        "## 장 모양", "",
        f"대표 프레임 {r['layout_counted']}장을 `ozl.analyze.slide_layout.classify` 로 다시 판정했다(프레임이 없는 장 {r['layout_missing_frame']}장은 세지 않았다).", "",
        "| 장 모양 | 장수 | 비율 |", "|---|---|---|",
    ]
    for k in LAYOUTS:
        v = r["layout"][k]
        L.append(f"| {LAYOUT_NAME[k]} (`{k}`) | {v['n']} | {v['share'] * 100:.1f}% |")
    L += ["", "## 제목", "",
          f"제목이 있는 장 {r['titled_slides']}장. 글자 수(공백 제외) 사분위 {r['title_len']['q1']:.0f} / {r['title_len']['median']:.0f} / {r['title_len']['q3']:.0f}. "
          "끝맺음은 문자 인식 결과의 마지막 글자로 갈랐다(오차가 있다).", "",
          "| 끝맺음 | 장수 | 비율 |", "|---|---|---|"]
    for k in ENDINGS:
        v = r["title_ending"][k]
        L.append(f"| {k} | {v['n']} | {v['share'] * 100:.1f}% |")
    o = r["opening"]
    L += ["", "## 여는 장", "",
          f"- 첫 장이 제목 없는 화면인 편: {o['first_media']} / {o['videos']}",
          f"- 첫 두 장이 모두 제목 없는 화면인 편: {o['first_two_media']} / {o['videos']}",
          f"- 첫 두 장 가운데 하나라도 제목 없는 화면인 편: {o['either_of_first_two_media']} / {o['videos']}",
          f"- 반짝 장까지 셀 때 첫 두 장이 모두 제목 없는 화면인 편: {o['first_two_media_with_flash']} / {o['videos']}",
          "- 반짝 장을 빼면 이어진 제목 없는 화면은 한 장으로 묶인다(slide_dense 의 묶음). 그래서 반짝 장을 뺀 '첫 두 장 모두'는 0에 가깝다.",
          "", "## 쓰는 곳", "",
          "이 값은 `src/ozl/render/style.py` 의 상수로 옮겨 `style: syuka` 사양의 검사(`check`)와 장 배분(`outline`)이 쓴다.", ""]
    return "\n".join(L)


def main(argv: list[str]) -> int:
    out, frames, pdf = OUT, True, True
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = pathlib.Path(next(it, "") or ".")
        elif a == "--no-frames":
            frames = False
        elif a == "--no-pdf":
            pdf = False
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print(f"모르는 인자 {a}", file=sys.stderr)
            return 2
    r = collect(frames)
    out.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    js, md = out / f"원본_집계_{ts}.json", out / f"원본_집계_{ts}.md"
    js.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    md.write_text(to_md(r), encoding="utf-8")
    print(js)
    print(md)
    if pdf and MD2PDF.exists():
        p = subprocess.run(["python3", str(MD2PDF), str(md), "--theme", "doc", "--footer-title"], capture_output=True, text=True, timeout=300)
        print(md.with_suffix(".pdf") if md.with_suffix(".pdf").exists() else f"PDF 실패: {(p.stderr or p.stdout)[-300:]}")
    sp = r["sec_per_slide"]
    print(f"[norms] 영상 {r['videos']}편 · 장 {r['slides']}장 · 장당 초 중앙값 {sp['median']} (편별 {sp['min']}~{sp['max']}) · 장 모양 {r['layout_counted']}장")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
