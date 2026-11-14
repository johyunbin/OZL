"""원본 비교표 — 우리 덱(style: syuka 사양)과 원본 방송 한 편, 원본 전체 중앙값을 같은 잣대로 잰다.

    python -m ozl.render compare <사양.yaml 또는 사양 사본이 든 산출 폴더> [--video <영상 id>] [--out <폴더>] [--no-pdf] [--edition 비공개판|바꾼판]

두 판 사양(장에 swap 칸이 있는 사양)은 --edition 으로 고른 판을 잰다(기본 비공개판). 산출 폴더를 주면 그 폴더의 사양 사본(이미 판이 갈린 것)을 잰다.

읽는 것(읽기만 한다):
  우리 덱: 사양의 slides(종류, seconds, title). 장 모양은 style.layout_of(종류와 그림 자리)로 원본 7종에 맞춘다.
  원본 한 편: private/slides_label/<영상>.json 의 장마다 layout(라벨) · dwell_sec · title. --video 가 없으면
             편 길이(duration_sec)가 우리 덱의 말할 시간(seconds 합)에 가장 가까운 편을 고른다.
  원본 전체: private/slides_dense/*.json — 편마다 같은 잣대로 잰 값의 중앙값(반짝 지나간 장은 뺀다, 장 모양은 norms 와 같이
             private/frames_dense/ 의 대표 프레임을 slide_layout.classify 로 다시 판정한다).
잣대: 장수, 길이, 30분 환산 장수, 장당 초(중앙값 · 평균), 장 모양 7종 분포, 그림 든 장 비율(장 모양이 '글만'이 아닌 장),
      제목 글자 수 중앙값(공백 제외, 제목 있는 장), 제목 끝맺음 분포(norms.title_ending), 첫 세 장의 꼴(장 모양).
원본 쪽은 수와 갈래 이름만 낸다. 제목과 본문의 문구는 담지 않는다(제목은 글자 수와 끝맺음 갈래로만 센다).
모양을 모르는 장: 대표 프레임도 저장된 layout 칸도 없는 장, layout 칸의 값이 7종 이름 밖인 장은 '글만'으로도 그림 든 장으로도 세지 않는다.
따로 세고(layout_unknown) 장 모양 비율과
그림 든 장 비율의 분모에서 뺀다. 모양을 아는 장이 하나도 없으면 그 비율은 0 이 아니라 '모름'(None)이다.

원본 장당 초의 잣대 차이: 원본은 장마다 화면에 머문 초(dwell_sec), 우리 덱은 사양의 seconds(말할 초)다.
라벨 편과 전체 편의 장 모양 판정도 다르다(라벨은 slide_structure 의 라벨, 전체는 대표 프레임 자동 판정).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import statistics as st
import subprocess
import sys
from collections import Counter

import yaml

from ozl.render import norms as NM

ROOT = pathlib.Path(__file__).resolve().parents[3]
LABEL = ROOT / "private" / "slides_label"
DENSE = NM.DENSE
OUT = ROOT / "private" / "decks" / "compare"
LAYOUTS = NM.LAYOUTS
UNKNOWN = "unknown"   # 모양을 모르는 장(대표 프레임도 저장된 layout 칸도 없다) — LAYOUTS 에 넣지 않는다(비율의 분모에서 뺀다)
LAYOUT_NAME = {**NM.LAYOUT_NAME, UNKNOWN: "모양 모름"}
ENDINGS = NM.ENDINGS
TEXT_ONLY = "text_only"


def _share(c: Counter, n: int, keys) -> dict:
    return {k: round(c[k] / n, 4) if n else 0.0 for k in keys}


def _known_layout(layout) -> str:
    """허용 목록(LAYOUTS)의 이름만 장 모양으로 받는다. 목록 밖의 값(모르는 이름, 빈 값, 글이 아닌 값)은 모양을 모르는 장(UNKNOWN)이다 —
    그림이 있는 장으로 세지 않는다."""
    return layout if isinstance(layout, str) and layout in LAYOUTS else UNKNOWN


def _metrics(rows: list[dict], duration: float) -> dict:
    """rows: [{layout, sec, title}] — 원본과 덱이 같은 함수로 잰다.
    장 모양 비율(layout)과 그림 든 장 비율(picture_share)의 분모는 모양을 아는 장(layout_known)이다. 아는 장이 없으면 None.
    layout 이 허용 목록(LAYOUTS) 밖이면 모양을 모르는 장으로 센다(layout_unknown)."""
    n = len(rows)
    secs = [float(r["sec"] or 0) for r in rows]
    lays = [_known_layout(r["layout"]) for r in rows]
    lay = Counter(lays)
    unknown = lay.pop(UNKNOWN, 0)
    known = n - unknown
    titles = [r["title"] for r, k in zip(rows, lays) if r.get("title") and k != "media"]
    ends = Counter(NM.title_ending(t) for t in titles)
    return {
        "slides": n,
        "duration_sec": round(duration, 1),
        "per_30min": round(n * 1800 / duration, 1) if duration else 0.0,
        "sec_median": round(st.median(secs), 1) if secs else 0.0,
        "sec_mean": round(st.mean(secs), 1) if secs else 0.0,
        "layout": _share(lay, known, LAYOUTS) if known else {k: None for k in LAYOUTS},
        "layout_known": known,
        "layout_unknown": unknown,
        "picture_share": round(sum(v for k, v in lay.items() if k != TEXT_ONLY) / known, 4) if known else None,
        "titled": len(titles),
        "title_len_median": float(st.median([NM.title_len(t) for t in titles])) if titles else 0.0,
        "ending": _share(ends, len(titles), ENDINGS),
        "first3": lays[:3],
    }


def deck_metrics(spec: dict) -> dict:
    from ozl.render import style as ST
    rows = []
    for sl in spec.get("slides") or []:
        if not isinstance(sl, dict):
            continue
        rows.append({"layout": ST.layout_of(sl), "sec": sl.get("seconds") or 0, "title": ST._title(sl)})
    return _metrics(rows, sum(float(r["sec"] or 0) for r in rows))


def _stored_layout(vid: str, s: dict) -> str:
    """저장된 layout 칸. 칸이 없으면 제목 없는 화면(kind media)은 media, 그 밖은 모양을 모른다(UNKNOWN — '글만'으로 세지 않는다)."""
    return s.get("layout") or ("media" if s.get("kind") == "media" else UNKNOWN)


def frame_layout(vid: str, s: dict) -> str:
    """원본 전체 쪽 — norms 와 같이 대표 프레임을 slide_layout.classify 로 다시 판정한다(slides_dense 의 layout 칸은 자동 판정 전 값이다).
    제목 없는 화면(kind media)은 media, 프레임이 없으면 저장된 칸, 그것도 없으면 UNKNOWN."""
    if s.get("kind") == "media":
        return "media"
    return NM._layout_of(vid, s, True) or _stored_layout(vid, s)


def video_rows(d: dict, drop_flash: bool = True, layout_fn=_stored_layout) -> list[dict]:
    out = []
    vid = str(d.get("video_id") or "")
    for s in d.get("slides") or []:
        if drop_flash and s.get("flash"):
            continue
        out.append({"layout": layout_fn(vid, s),
                    "sec": s.get("dwell_sec") or 0, "title": s.get("title") or ""})
    return out


def video_metrics(d: dict, layout_fn=_stored_layout) -> dict:
    m = _metrics(video_rows(d, layout_fn=layout_fn), float(d.get("duration_sec") or 0))
    m["video_id"] = str(d.get("video_id") or "")
    return m


def _load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def pick_video(target_sec: float, label_dir: pathlib.Path = LABEL, video: str | None = None) -> dict:
    """라벨이 있는 편 가운데 --video 또는 길이가 target_sec 에 가장 가까운 편."""
    files = sorted(label_dir.glob("*.json"))
    if video:
        p = label_dir / f"{video}.json"
        if not p.is_file():
            raise SystemExit(f"[compare] 라벨이 있는 편이 아니다: {video} ({label_dir})")
        return _load(p)
    best = None
    for p in files:
        d = _load(p)
        dur = float(d.get("duration_sec") or 0)
        if dur <= 0 or not d.get("slides"):
            continue
        key = (abs(dur - target_sec), p.stem)
        if best is None or key < best[0]:
            best = (key, d)
    if best is None:
        raise SystemExit(f"[compare] 라벨이 있는 편이 없다: {label_dir}")
    return best[1]


def corpus_median(dense_dir: pathlib.Path = DENSE, layout_fn=frame_layout) -> dict:
    """원본 전체 — 편마다 잰 값의 중앙값. 첫 세 장의 꼴은 가장 흔한 꼴과 그 편수.
    장 모양 비율과 그림 든 장 비율은 모양을 아는 장이 있는 편(layout_videos)만으로 중앙값을 낸다. 그런 편이 없으면 None.
    layout_unknown 은 모양을 모르는 장의 전체 합이다."""
    ms = []
    for p in sorted(dense_dir.glob("*.json")):
        d = _load(p)
        if float(d.get("duration_sec") or 0) <= 0 or not video_rows(d):
            continue
        ms.append(video_metrics(d, layout_fn))
    if not ms:
        raise SystemExit(f"[compare] 원본 분석 파일이 없다: {dense_dir}")

    def med(f, among=None):
        xs = [f(m) for m in (ms if among is None else among)]
        return round(float(st.median(xs)), 4) if xs else None
    shaped = [m for m in ms if m["layout_known"]]   # 모양을 아는 장이 있는 편
    first3 = Counter(tuple(m["first3"]) for m in ms)
    top, cnt = first3.most_common(1)[0]
    return {
        "videos": len(ms),
        "slides": med(lambda m: m["slides"]), "duration_sec": med(lambda m: m["duration_sec"]),
        "per_30min": med(lambda m: m["per_30min"]), "sec_median": med(lambda m: m["sec_median"]), "sec_mean": med(lambda m: m["sec_mean"]),
        "layout": {k: med(lambda m, k=k: m["layout"][k], shaped) for k in LAYOUTS},
        "layout_videos": len(shaped),
        "layout_unknown": sum(m["layout_unknown"] for m in ms),
        "picture_share": med(lambda m: m["picture_share"], shaped),
        "titled": med(lambda m: m["titled"]), "title_len_median": med(lambda m: m["title_len_median"]),
        "ending": {k: med(lambda m, k=k: m["ending"][k]) for k in ENDINGS},
        "first3": list(top), "first3_videos": cnt,
    }


def _pct(x: float | None) -> str:
    return "모름" if x is None else f"{x * 100:.1f}%"


def _first3(xs: list[str]) -> str:
    return " · ".join(LAYOUT_NAME.get(x, x) for x in xs) if xs else "(장 없음)"


def table_rows(deck: dict, one: dict, corpus: dict) -> list[tuple[str, str, str, str]]:
    """(잣대, 원본 한 편, 원본 전체 중앙값, 우리 덱) — 모든 칸이 채워진다."""
    R = [
        ("장수", f"{one['slides']}장", f"{corpus['slides']:g}장", f"{deck['slides']}장"),
        ("길이", f"{one['duration_sec']:g}초", f"{corpus['duration_sec']:g}초", f"{deck['duration_sec']:g}초(말할 초 합)"),
        ("30분 환산 장수", f"{one['per_30min']:g}장", f"{corpus['per_30min']:g}장", f"{deck['per_30min']:g}장"),
        ("장당 초 중앙값", f"{one['sec_median']:g}초", f"{corpus['sec_median']:g}초", f"{deck['sec_median']:g}초"),
        ("장당 초 평균", f"{one['sec_mean']:g}초", f"{corpus['sec_mean']:g}초", f"{deck['sec_mean']:g}초"),
    ]
    for k in LAYOUTS:
        R.append((f"장 모양: {LAYOUT_NAME[k]}", _pct(one["layout"][k]), _pct(corpus["layout"][k]), _pct(deck["layout"][k])))
    R.append(("모양을 모르는 장(비율의 분모에서 뺌)", f"{one['layout_unknown']}장",
              f"{corpus['layout_unknown']}장({corpus['videos']}편 가운데 모양을 아는 장이 있는 편 {corpus['layout_videos']}편)", f"{deck['layout_unknown']}장"))
    R.append(("그림 든 장 비율('글만'이 아닌 장)", _pct(one["picture_share"]), _pct(corpus["picture_share"]), _pct(deck["picture_share"])))
    R.append(("제목 있는 장", f"{one['titled']}장", f"{corpus['titled']:g}장", f"{deck['titled']}장"))
    R.append(("제목 글자 수 중앙값(공백 제외)", f"{one['title_len_median']:g}자", f"{corpus['title_len_median']:g}자", f"{deck['title_len_median']:g}자"))
    for k in ENDINGS:
        R.append((f"제목 끝맺음: {k}", _pct(one["ending"][k]), _pct(corpus["ending"][k]), _pct(deck["ending"][k])))
    R.append(("첫 세 장의 꼴", _first3(one["first3"]), f"{_first3(corpus['first3'])} ({corpus['first3_videos']}/{corpus['videos']}편)", _first3(deck["first3"])))
    return R


def to_md(spec_path: pathlib.Path, card: str, deck: dict, one: dict, corpus: dict, at: str, edition: str = "") -> str:
    L = ["---", "kicker: 덱 비교", f"date: {at[:10]}", "theme: doc", "---", "",
         f"# 원본 비교표 — {card}" + (f" ({edition})" if edition else ""), "",
         f"{at} 에 `python -m ozl.render compare` 로 잰 값이다. 우리 덱은 `{spec_path.name}`" + (f"의 {edition}" if edition else "") + f", 원본 한 편은 라벨이 있는 편 `{one['video_id']}`"
         f"(편 길이가 덱의 말할 시간에 가장 가까운 편 또는 --video), 원본 전체는 분석 파일 {corpus['videos']}편의 편별 값 중앙값이다. "
         "원본 쪽은 수와 갈래만 적고 문구는 담지 않는다.", "",
         "| 잣대 | 원본 한 편 | 원본 전체 중앙값 | 우리 덱 |", "|---|---|---|---|"]
    for r in table_rows(deck, one, corpus):
        L.append("| " + " | ".join(c.replace("|", "/") for c in r) + " |")
    L += ["", "## 읽을 때 주의", "",
          "- 원본 장당 초는 장이 화면에 머문 초(3초 표본), 우리 덱은 사양의 `seconds`(말할 초)다.",
          "- 원본 한 편의 장 모양은 slide_structure 의 라벨(`private/slides_label/`), 원본 전체는 대표 프레임 자동 판정(`norms` 와 같은 `slide_layout.classify`)이라 잣대가 조금 다르다. 우리 덱은 `style.KIND_LAYOUT` 의 대응표다.",
          "- 원본 전체의 비율 칸은 편마다 잰 비율의 중앙값이라 칸을 더해도 100%가 되지 않는다.",
          "- 대표 프레임도 저장된 장 모양도 없는 장은 모양을 모르는 장으로 따로 세고, 장 모양 비율과 그림 든 장 비율의 분모에서 뺐다('글만'으로 세지 않는다).",
          "- 제목 끝맺음은 원본이 문자 인식 결과라 오차가 있다.", ""]
    return "\n".join(L)


def resolve_spec(path: pathlib.Path) -> pathlib.Path:
    if path.is_file():
        return path
    if path.is_dir():
        ys = sorted(path.glob("*.yaml"))
        if len(ys) == 1:
            return ys[0]
        raise SystemExit(f"[compare] 폴더에 사양 사본(.yaml)이 하나가 아니다({len(ys)}개): {path} — 사양 파일을 직접 준다")
    raise SystemExit(f"[compare] 없는 경로: {path}")


def edition_spec(spec: dict, edition: str | None = None) -> tuple[dict, str]:
    """(잴 사양, 판 이름 또는 빈 문자열). swap 칸이 있는 사양은 고른 판(기본 비공개판)으로 가른다. 없으면 그대로."""
    from ozl.render import pictures as PIC
    if not PIC.has_swaps(spec):
        return spec, ""
    edition = edition or PIC.EDITION_PRIVATE
    if edition not in PIC.EDITIONS:
        raise SystemExit(f"[compare] --edition '{edition}' 를 모른다({' | '.join(PIC.EDITIONS)})")
    return (PIC.strip_swaps(spec) if edition == PIC.EDITION_PRIVATE else PIC.apply_swaps(spec)[0]), edition


def copy_edition(spec_path: pathlib.Path) -> str:
    """산출 폴더의 사양 사본(spec_<ts>_<판>.yaml) 이름에서 읽은 판 이름. 아니면 빈 문자열."""
    from ozl.render import pictures as PIC
    stem = spec_path.stem
    return next((e for e in PIC.EDITIONS if stem.startswith("spec_") and stem.endswith("_" + e)), "")


def compare(spec_path: pathlib.Path, video: str | None = None, label_dir: pathlib.Path = LABEL, dense_dir: pathlib.Path = DENSE,
            *, edition: str | None = None) -> dict:
    spec, ed = edition_spec(yaml.safe_load(spec_path.read_text(encoding="utf-8")), edition)
    deck = deck_metrics(spec)
    one = video_metrics(pick_video(deck["duration_sec"], label_dir, video))
    corpus = corpus_median(dense_dir)
    return {"card_id": str(spec.get("card_id") or ""), "edition": ed or copy_edition(spec_path), "deck": deck, "original_one": one, "original_all": corpus}


def main(argv: list[str]) -> int:
    pos, video, out, pdf, edition = [], None, OUT, True, None
    it = iter(argv)
    for a in it:
        if a == "--video":
            video = next(it, None)
        elif a == "--edition":
            edition = next(it, None)
        elif a == "--out":
            out = pathlib.Path(next(it, "") or ".")
        elif a == "--no-pdf":
            pdf = False
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif a.startswith("--"):
            print(f"모르는 인자 {a}", file=sys.stderr)
            return 2
        else:
            pos.append(a)
    if len(pos) != 1:
        print(__doc__)
        return 2
    sp = resolve_spec(pathlib.Path(pos[0]))
    r = compare(sp, video, edition=edition)
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    md = out / (f"원본_비교표_{r['card_id']}_{ts}" + (f"_{r['edition']}" if r["edition"] else "") + ".md")
    md.write_text(to_md(sp, r["card_id"], r["deck"], r["original_one"], r["original_all"], at, r["edition"]), encoding="utf-8")
    md.with_suffix(".json").write_text(json.dumps({"at": at, "spec": str(sp), **r}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    if pdf and NM.MD2PDF.exists():
        p = subprocess.run(["python3", str(NM.MD2PDF), str(md), "--theme", "doc", "--footer-title"], capture_output=True, text=True, timeout=300)
        print(md.with_suffix(".pdf") if md.with_suffix(".pdf").exists() else f"PDF 실패: {(p.stderr or p.stdout)[-300:]}")
    o, d = r["original_one"], r["deck"]
    print(f"[compare] 원본 {o['video_id']} {o['slides']}장/{o['duration_sec']:g}초 · 덱 {d['slides']}장/{d['duration_sec']:g}초 · 원본 전체 {r['original_all']['videos']}편")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
