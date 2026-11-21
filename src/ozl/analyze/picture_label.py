"""슬라이드 대표 화면의 그림 종류 라벨 — OpenAI API(gpt-6.1-terra, 낮은 해상도)로 붙여 sd_picture_labels 에 적는다.

사용자 결정(2026-11-21): 매주 새 본편의 그림 종류 라벨은 이 API 로 한다. 보내는 것은 슬라이드 대표 화면뿐이다.
키: 환경 변수 OPENAI_API_KEY, 없으면 --key-file(기본 ~/Trading/settings/openai.json 의 api_key). 키는 출력하지 않는다.
대상: 장 모양(layout)이 있고 반짝 장이 아닌 장. 같은 라벨러가 같은 대표 프레임으로 이미 라벨한 장은 건너뛴다.

    python -m ozl.analyze.picture_label run --videos <id> [<id> ...] [--dry-run] [--max-usd 2]
    python -m ozl.analyze.picture_label run --missing [--dry-run]

상한이나 한도 응답으로 한 편 중간에 멈추면 그 편에는 이미 라벨이 있어 --missing 이 다시 고르지 않는다.
남은 장은 --videos <그 편> 으로 다시 돌린다(같은 프레임으로 라벨한 장은 건너뛴다).
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ozl.analyze.slide_db import FRAMES_DIR, PICTURE_KINDS, validate_kinds
from ozl.syuka.db import DB_PATH, ROOT
from ozl import paths as ozlpaths

URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-6.1-terra"
DETAIL = "low"
LABELER = "openai-terra-low"
KEY_FILE = Path.home() / "Trading" / "settings" / "openai.json"
LOG_DIR = ozlpaths.at("p3", "picture_api")
# Trading `src/youtube/market_brief.py` 의 단가표(백만 토큰당 달러, 입력·출력). 현행 단가는 확인하지 못한 값이다.
PRICE = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-terra": (1.00, 5.00), "gpt-6.1-sol": (2.00, 10.00)}
# 2026-11-21 시험의 장당 실측(낮은 해상도): 입력 606 토큰, 출력 약 71~121 토큰
EST_TOKENS = (606, 120)
STOP_CODES = (401, 402, 403, 429)
KST = timezone(timedelta(hours=9))

RUBRIC = """한 장에 보이는 그림(글줄이 아닌 시각 요소)마다 종류를 고르고, 장 전체의 대표 종류(가장 넓거나 중심인 그림) 하나를 고른다.
- photo: 장면·사물·장소 사진(실존 인물이 주인공이 아닌 것)
- person: 실존 인물이 주인공인 사진
- article: 기사·보도 화면(뉴스 영상 썸네일 포함), 문서·보고서·웹 페이지 갈무리
- chart: 그래프(선·막대·원), 주가·지표 차트
- table: 표, 달력처럼 칸으로 된 구조
- logo: 기업·기관·정부 로고, CI
- map: 지도
- sns: X(트위터)·인스타그램·페이스북·커뮤니티 게시물 화면
- meme: 밈·짤(유행하는 웃음 그림, 합성 그림)
- drawing: 일러스트, 아이콘, 국기, 캐릭터, 직접 그린 도식
- none: 그림 없음(글뿐. 손글씨 표시, 밑줄, 화살표, 펜 자국은 그림이 아니다)"""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["kinds", "primary", "confidence"],
          "properties": {"kinds": {"type": "array", "items": {"type": "string", "enum": list(PICTURE_KINDS)}},
                         "primary": {"type": "string", "enum": list(PICTURE_KINDS)},
                         "confidence": {"type": "number"}}}


class Stop(Exception):
    """키 오류·잔액·한도 응답. 더 보내지 않는다."""


class BadAnswer(ValueError):
    """응답이 왔지만 쓸 수 없다. 과금된 토큰은 달러 상한 계산에 넣는다."""

    def __init__(self, msg, tokens_in=0, tokens_out=0):
        super().__init__(msg)
        self.tokens_in, self.tokens_out = tokens_in, tokens_out


def load_key(key_file: Path = KEY_FILE) -> str:
    """환경 변수가 먼저, 없으면 설정 파일의 api_key. 값은 돌려줄 뿐 출력하지 않는다."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        key = str(json.loads(Path(key_file).read_text(encoding="utf-8")).get("api_key") or "").strip()
    except (OSError, ValueError) as e:
        raise Stop(f"키를 읽지 못했다: {Path(key_file).name} ({type(e).__name__})") from None
    if not key:
        raise Stop("키가 비어 있다")
    return key


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pi, po = PRICE[model]
    return tokens_in / 1e6 * pi + tokens_out / 1e6 * po


def targets(con, videos=None, missing=False) -> list[dict]:
    """라벨할 장. layout 이 있고 반짝 장이 아니며, 같은 라벨러가 같은 프레임으로 라벨하지 않은 장."""
    if bool(videos) == bool(missing):
        raise ValueError("--videos 와 --missing 가운데 하나만 준다")
    sql = """SELECT s.video_id, s.no, s.best_frame FROM sd_slides s
             LEFT JOIN sd_picture_labels p ON p.video_id=s.video_id AND p.no=s.no AND p.labeler=? AND p.note=s.best_frame
             WHERE s.layout IS NOT NULL AND s.flash=0 AND s.best_frame IS NOT NULL AND p.no IS NULL"""
    args: list = [LABELER]
    if videos:
        sql += f" AND s.video_id IN ({','.join('?' * len(videos))})"
        args += list(videos)
    else:  # 어느 라벨러의 그림 라벨도 없는 편만(이미 다른 레인으로 라벨한 편을 다시 보내지 않는다)
        sql += " AND s.video_id NOT IN (SELECT DISTINCT video_id FROM sd_picture_labels)"
    rows = con.execute(sql + " ORDER BY s.video_id, s.no", args).fetchall()
    return [dict(video_id=v, no=n, best_frame=bf) for v, n, bf in rows]


def label_one(image: Path, key: str, model: str = MODEL, detail: str = DETAIL, opener=urllib.request.urlopen):
    """그림 한 장 → ({kinds, primary, confidence}, 입력 토큰, 출력 토큰)."""
    data = base64.b64encode(Path(image).read_bytes()).decode()
    body = {"model": model,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": "한국 시사 방송 슬라이드 화면 한 장이다. 아래 기준으로 그림 종류를 판정하라. 화면 글을 옮겨 적지 마라.\n" + RUBRIC},
                {"type": "input_image", "image_url": f"data:image/png;base64,{data}", "detail": detail}]}],
            "text": {"format": {"type": "json_schema", "name": "picture_kind", "schema": SCHEMA, "strict": True}},
            "store": False}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with opener(req, timeout=120) as resp:
            d = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in STOP_CODES:
            raise Stop(f"OpenAI API http {e.code}") from None
        raise
    # 과금은 응답이 온 순간 정해지므로 토큰부터 읽는다(없으면 어림값)
    u = d.get("usage") if isinstance(d, dict) else None
    a, b = (int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))) if isinstance(u, dict) else EST_TOKENS
    try:
        text = next((c.get("text") for o in d.get("output", []) if o.get("type") == "message"
                     for c in o.get("content", []) if c.get("type") == "output_text"), None)
        lab = json.loads(text or "{}")
        kinds = validate_kinds(lab.get("kinds", []))  # 11종 밖이 하나라도 있으면 쓰지 않는다
        if lab.get("primary") not in PICTURE_KINDS or not kinds:
            raise ValueError("응답에 그림 종류가 없다")
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        raise BadAnswer(f"쓸 수 없는 응답({type(e).__name__})", a, b) from None
    return {"kinds": kinds, "primary": lab["primary"], "confidence": lab.get("confidence")}, a, b


def run(con, items, key, *, frames=FRAMES_DIR, model=MODEL, max_usd=2.0, log_dir=LOG_DIR,
        opener=urllib.request.urlopen, pause=0.2, out=sys.stdout) -> dict:
    """장마다 보내고 바로 적는다. 달러 상한(어림)에 닿거나 한도 응답이 오면 멈춘다."""
    run_id = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / f"run_{run_id}.jsonl").open("a", encoding="utf-8")
    tin = tout = done = failed = 0
    stopped = None
    t0 = time.time()
    try:
        _loop(con, items, key, frames, model, max_usd, opener, pause, log, run_id, state := {})
    finally:
        tin, tout, done, failed, stopped = (state.get(k, 0 if k != "stopped" else None)
                                            for k in ("tin", "tout", "done", "failed", "stopped"))
        summary = {"run_id": run_id, "model": model, "targets": len(items), "labeled": done, "failed": failed,
                   "input_tokens": tin, "output_tokens": tout, "usd_estimate": round(cost(model, tin, tout), 4),
                   "sec": round(time.time() - t0), "stopped": stopped}
        log.write(json.dumps({"summary": summary}, ensure_ascii=False) + "\n")
        log.close()
    print(json.dumps(summary, ensure_ascii=False), file=out)
    return summary


def _loop(con, items, key, frames, model, max_usd, opener, pause, log, run_id, state):
    """run 의 본체. 상태(state)를 바로바로 적어, 중간에 예외가 나도 요약이 남게 한다."""
    state.update(tin=0, tout=0, done=0, failed=0, stopped=None)
    for it in items:
        if cost(model, state["tin"], state["tout"]) + cost(model, *EST_TOKENS) > max_usd:
            state["stopped"] = f"달러 상한 {max_usd} 에 닿았다"
            break
        try:
            lab, a, b = label_one(Path(frames) / it["video_id"] / it["best_frame"], key, model, DETAIL, opener)
        except Stop as e:
            state["stopped"] = str(e)
            break
        except BadAnswer as e:
            state["tin"] += e.tokens_in
            state["tout"] += e.tokens_out
            state["failed"] += 1
            log.write(json.dumps({"video_id": it["video_id"], "no": it["no"], "error": "BadAnswer"}) + "\n")
            continue
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError) as e:
            state["failed"] += 1
            log.write(json.dumps({"video_id": it["video_id"], "no": it["no"], "error": type(e).__name__}) + "\n")
            continue
        state["tin"] += a
        state["tout"] += b
        state["done"] += 1
        with con:
            con.execute("""INSERT OR REPLACE INTO sd_picture_labels
                (video_id, no, labeler, model, kinds, primary_kind, confidence, run_id, labeled_at, note)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (it["video_id"], it["no"], LABELER, f"{model} {DETAIL}", json.dumps(lab["kinds"]), lab["primary"],
                         lab["confidence"], run_id, datetime.now(KST).isoformat(timespec="seconds"), it["best_frame"]))
        log.write(json.dumps({"video_id": it["video_id"], "no": it["no"], "primary": lab["primary"], "in": a, "out": b}) + "\n")
        if pause:
            time.sleep(pause)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--videos", nargs="+")
    g.add_argument("--missing", action="store_true", help="그림 라벨이 하나도 없는 편 전부")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--max-usd", type=float, default=2.0, help="이번 실행의 달러 상한(어림)")
    r.add_argument("--db", type=Path, default=DB_PATH)
    r.add_argument("--key-file", type=Path, default=KEY_FILE)
    a = ap.parse_args(argv)
    with closing(sqlite3.connect(a.db)) as con:
        items = targets(con, a.videos, a.missing)
        est = cost(MODEL, EST_TOKENS[0] * len(items), EST_TOKENS[1] * len(items))
        print(f"대상 {len(items)}장 · 편 {len({i['video_id'] for i in items})} · 어림 {est:.3f}달러(상한 {a.max_usd})")
        if a.dry_run or not items:
            return 0
        try:
            key = load_key(a.key_file)
        except Stop as e:
            print(f"멈춤: {e}", file=sys.stderr)
            return 2
        s = run(con, items, key, max_usd=a.max_usd)
    return 0 if not s["stopped"] and not s["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
