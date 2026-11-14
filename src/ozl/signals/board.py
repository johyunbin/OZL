"""board.json(§8-1): 후보 목록, 두 구역(§6-2), 출처 상태. 운영 화면과 웹 첫 화면이 읽는다. 원자적으로 쓴다(임시 파일 → os.replace).

두 구역(계획 4-2, 5-2):
- 오늘 새로 뜬 것(많아야 4줄): 1~2일째, v_new = max(v(D), v(D−1)) ≥ 0.1(1일째는 v(D)). v_new → 간접 포착 → S_raw → 번호 순.
- 며칠째 이어지는 것(많아야 6줄): 3일째 이상, v ≥ 0.1 인 날 2일 이상, v(D) 또는 v(D−1) ≥ 0.1, 휴면 아님. S_raw → 번호 순.
- 한국어, 종료 아님. 한 분야는 구역 최대 줄 수의 절반까지(넘으면 건너뛰고 capped 에 센다).
  '기타'(분야를 정하지 못한 이슈)는 분야가 아니므로 상한을 걸지 않는다.
- 민감 높음(RED)도 목록과 두 구역에 남긴다(2026-11-15 · 가장 큰 화제가 위에서 빠지던 것을 고침). 줄에 sensitivity 와
  deck_blocked(덱 만들기 막음)가 붙고, 덱 선택을 막는 것은 운영 화면(/pick)의 일이다.

큰 이야기 순서(story, story_rank · 2026-11-15): 화제 점수와 따로 둔 줄 세우기 값. 점수식(처음 30일 고정)은 바꾸지 않는다.
  story = 0.3 min(1, H/2.5) + 0.5 min(1, ln(1+F3)/ln 31) + 0.2 G3  (F3: 그날과 앞 이틀의 매체 계열 수 합, G3: 그 사흘의 급상승어 등급 최댓값)
  story_rank 는 같은 언어 후보 안에서 story(반올림 전 값) → 반올림 전 화제 점수 → 번호 순으로 1부터.
searches_unmatched: 이슈에 잇지 못한 한국어 급상승어 가운데 검색량 표기가 있는 것(검색어, 등급, 날, 검색량 표기, 딸린 기사 제목).
"""
from __future__ import annotations

import json
import math
import os
import pathlib
from collections import Counter

from ozl.signals import category, config

SCHEMA = "ozl.board/1"
NOTE = "검증 전 신호다. 화제 점수는 얼마나 화제인가만 잰다. 사실 여부와 중요성과 무관하다."
NO_NEW = "오늘 새로 잡힌 이슈가 없다"
NO_COND = "조건(v 0.1 이상)을 넘는 이슈가 없다"
FAILED = "수집 실패로 오늘 값을 내지 못했다"
FORMULA_NOTE = ["정상일의 식(위키백과 수집 없음): v = (0.6 L(A) + 0.25 g) / 0.85",
                "B 의 분모는 3(언론, 검색, 공공 원문)이다"]


def _num(x):
    return None if x is None else round(float(x), 6)


def full_row(r: dict, aliases: list[str]) -> dict:
    """issue_days 의 기준일 줄(+ detail.row) → 후보 한 줄."""
    base = dict(r["detail"]["row"])
    sens = r.get("sensitivity") or {}
    out = {"issue_id": base["issue_id"], "aliases": sorted(aliases), "lang": base["lang"], "title": base["title"],
           "score": r["score"], "score_raw": _num(r["score_raw"]), "state": r["state"], "day_n": base["day_n"],
           "first_day": base["first_day"], "status_line": base["status_line"], "new_thing": base["new_thing"],
           "parts": {"v": _num(r["v"]), "H": _num(r["H"]), "B": _num(r["B"]), "P": _num(r["P"]), "D": _num(r["D"]),
                     "A": r["A"], "g": _num(r["g"]), "w": _num(r["w"])},
           "outlets_n": base["outlets_n"], "articles_n": base["articles_n"], "copies_n": base["copies_n"],
           "kinds": list(r["kinds_present"]), "kinds_ok": list(r["kinds_ok"]), "missing": list(r["missing"]),
           "category": r["category"],
           "sensitivity": {"level": sens.get("level", "GREEN"), "reason": "; ".join(sens.get("reasons") or [])},
           "person": bool(r["person"]), "indirect": base["indirect"], "links": base["links"],
           "prev_day": base.get("prev_day"), "zone": None,
           "deck_blocked": sens.get("level") == "RED",
           "story": story_value(base.get("story_in")), "story_rank": None,
           "_z": base["_z"], "_raw": r["score_raw"], "_story": story_raw(base.get("story_in"))}
    return out


def story_raw(si: dict | None) -> float | None:
    """큰 이야기 순서 값(머리말)의 반올림 전 값. 줄 세우기에는 이 값을 쓴다. 입력이 없는 옛 계산 행이면 None."""
    if not si:
        return None
    H = float(si.get("H") or 0.0)
    F3 = int(si.get("families_3d") or 0)
    G3 = float(si.get("grade_max_3d") or 0.0)
    return (config.STORY_W_H * min(1.0, H / config.H_SCREEN)
            + config.STORY_W_F * min(1.0, math.log(1 + F3) / math.log(config.L_BASE))
            + config.STORY_W_G * G3)


def story_value(si: dict | None) -> dict | None:
    """큰 이야기 순서 값(머리말). 판에 싣는 값은 소수 여섯 자리로 반올림한다. 입력이 없는 옛 계산 행이면 None."""
    if not si:
        return None
    return {"value": round(story_raw(si), 6), "H": _num(float(si.get("H") or 0.0)),
            "families_3d": int(si.get("families_3d") or 0), "families_by_day": list(si.get("families_by_day") or []),
            "grade_max_3d": _num(float(si.get("grade_max_3d") or 0.0))}


def _story_key(c):
    """story(반올림 전) → 반올림 전 화제 점수 → 번호. 반올림한 값으로 세우면 작은 차이가 동점이 되어 화제 점수가 순서를 뒤집는다."""
    v = c.get("_story")
    if v is None:
        v = (c.get("story") or {}).get("value")
    return (-(v if v is not None else -1.0), -_raw(c), c["issue_id"])


def rank_stories(cands: list[dict]) -> None:
    """story_rank 를 언어마다 1부터 매긴다(제자리)."""
    by_lang: dict[str, list] = {}
    for c in cands:
        by_lang.setdefault(c["lang"], []).append(c)
    for lst in by_lang.values():
        for i, c in enumerate(sorted(lst, key=_story_key), 1):
            c["story_rank"] = i


def _raw(c) -> float:
    """정렬에 쓰는 반올림 전 화제 점수(§5-1). 없음은 맨 뒤."""
    x = c.get("_raw", c["score_raw"])
    return -1.0 if x is None else float(x)


def _key_new(c):
    z = c["_z"]
    return (-_vnew(c), 0 if c["indirect"] else 1, -_raw(c), c["issue_id"])


def _vnew(c) -> float:
    z = c["_z"]
    xs = [z["v"]] if c["day_n"] == 1 else [z["v"], z["v_prev"]]
    xs = [x for x in xs if x is not None]
    return max(xs) if xs else -1.0


def _eligible(c) -> bool:
    return c["lang"] == "ko" and not c["_z"].get("ended") and c["state"] != "종료"


def _fill(cands: list[dict], limit: int) -> tuple[list[str], list[dict]]:
    cap = limit // 2
    used, skipped, rows = Counter(), Counter(), []
    for c in cands:
        if len(rows) >= limit:
            break
        cat = c["category"]
        if cat != category.OTHER and used[cat] >= cap:
            skipped[cat] += 1
            continue
        used[cat] += 1
        rows.append(c["issue_id"])
    return rows, [{"category": k, "skipped": v} for k, v in sorted(skipped.items())]


def zones(cands: list[dict], failed_both: bool) -> dict:
    pool = [c for c in cands if _eligible(c)]
    young = [c for c in pool if c["day_n"] in (1, 2)]
    new = sorted([c for c in young if _vnew(c) >= config.ZONE_V], key=_key_new)

    def ok_old(c):
        z = c["_z"]
        return (c["day_n"] >= 3 and z["vdays"] >= 2 and c["state"] != "휴면"
                and ((z["v"] or 0) >= config.ZONE_V or (z["v_prev"] or 0) >= config.ZONE_V))
    old = sorted([c for c in pool if ok_old(c)],
                 key=lambda c: (-_raw(c), c["issue_id"]))
    out = {}
    for name, lst, limit in (("new", new, config.ZONE_NEW_MAX), ("ongoing", old, config.ZONE_ONGOING_MAX)):
        rows, capped = _fill(lst, limit)
        reason = None
        if not rows:
            if failed_both:
                reason = FAILED
            elif not pool or (name == "new" and not young):
                reason = NO_NEW
            else:
                reason = NO_COND
        out[name] = {"rows": rows, "empty_reason": reason, "capped": capped}
    return out


def build(meta: dict, day_rows: list[dict], aliases: dict[str, list[str]]) -> dict:
    """meta: 계산 기록에 남긴 판의 머리(asof, 출처 상태 …). day_rows: 기준일의 issue_days 줄(detail 포함)."""
    cands = [full_row(r, aliases.get(r["issue_id"], [])) for r in day_rows
             if r.get("detail", {}).get("row") and r["detail"].get("active")]
    cands.sort(key=lambda c: (-_raw(c), c["issue_id"]))
    rank_stories(cands)
    z = zones(cands, meta["failed_both"])
    where = {i: name for name, zz in z.items() for i in zz["rows"]}
    for c in cands:
        c["zone"] = where.get(c["issue_id"])
        c.pop("_z", None)
        c.pop("_raw", None)
        c.pop("_story", None)
    return {"schema": SCHEMA, "asof": meta["asof"], "base_day": meta["base_day"], "base_day_partial": meta["partial"],
            "decided_at": meta["decided_at"], "calc_id": meta["calc_id"], "mode": meta["mode"],
            "versions": meta["versions"], "basis": meta["basis"], "formula_note": FORMULA_NOTE,
            "sources": meta["sources"], "missing": meta["missing"], "zones": z, "candidates": cands,
            "searches_unmatched": unmatched_rows(meta["unmatched"]),
            "merge_hints": meta["merge_hints"], "note": NOTE}


def unmatched_rows(un: list[dict]) -> list[dict]:
    """이슈에 잇지 못한 한국어 급상승어. 검색량 표기를 함께 받은 계산(2026-11-15 부터)이면 표기가 있는 것만, 딸린 기사 제목과 함께."""
    out = []
    for s in un:
        if s.get("lang", "ko") != "ko":
            continue
        row = {k: s[k] for k in ("keyword", "grade", "day")}
        if "traffic_raw" in s:
            if not s.get("traffic_raw"):
                continue
            row["traffic_raw"] = s["traffic_raw"]
            row["news_title"] = s.get("news_title") or ""
        out.append(row)
    return out


def write(b: dict, path: pathlib.Path | str) -> pathlib.Path:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return p
