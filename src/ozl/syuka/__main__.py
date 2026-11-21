"""슈카월드 영상 자료 명령줄.

    python -m ozl.syuka catalog              # 영상 목록을 만들어 DB 에 넣고 수를 찍는다
    python -m ozl.syuka sample               # 표본 60편 → private/syuka/sample_60.json
    python -m ozl.syuka put <model> <파일>   # 추출 자료 한 건을 검사해 넣는다(걸리면 종료 코드 1). model=merged 면 합친 자료
                                             # 파일은 그 판의 폴더(schema.EXTRACT_DIRS)/<model>/<video_id>.json 이어야 한다
    python -m ozl.syuka agree [a b] [--schema-version N]
                                             # 두 모델 일치율(기본 opus sonnet, 최신 판) → private/syuka/agree_v<N>.json
                                             # 계산은 늘 최신 판 계산이다. 1판 자료에 --schema-version 1 이면 '새 계산만 적용한 값'
    python -m ozl.syuka status

3판(영상 → 토막, 지침 private/syuka/extract_guide_v3.md):
    python -m ozl.syuka pilot-v3             # 시험 30편 → private/syuka/pilot30_v3.json
    python -m ozl.syuka mark-v3 <video_id> [--start N --length M]
                                             # 전사를 글자 위치·시각 표시와 함께 찍는다(토막 위치를 적을 때)
    python -m ozl.syuka validate-v3 <파일>    # 검사. 오류를 한 줄씩(걸리면 종료 코드 1)
    python -m ozl.syuka load-v3 <폴더>       # 검사를 통과한 파일을 v3_* 표에 넣는다(다시 돌려도 중복 없음)
    python -m ozl.syuka find-v3 <낱말>       # 토막의 주제·질문·키워드·인물·기관·나라에서 찾아 올린 날 순으로

예측 장부(모든 명령에 최상위 --db PATH 선택 가능):
    python -m ozl.syuka predict prepare BOARD --out DIR [--weeks 8] [--asof ISO]
    python -m ozl.syuka predict baselines BOARD --clusters FILE --out FILE [--n 15]
    python -m ozl.syuka predict add FILE [--retro] [--revises PID]
    python -m ozl.syuka predict fix DRAFT --date YYYY-MM-DD [--revises PID]
    python -m ozl.syuka predict verify [PID] [--expect SHA256]
    python -m ozl.syuka predict list
    python -m ozl.syuka score events PID (--from-json FILE | --from-v3 VID [--merge 3,4] [--minor N] [--weekday VID]) [--replace]
    python -m ozl.syuka score packet PID --out DIR [--clusters FILE] [--seed N] [--event-set ES] [--skip-gate]
    python -m ozl.syuka score mask-import PID --mask FILE --packet FILE [--event-set ES]
    python -m ozl.syuka score judge PID --judge codex|gemini|chatgpt FILE [--event-set ES]
                                             # 사건 묶음이 둘 이상이면 --event-set 필수
    python -m ozl.syuka score finalize PID [--event-set ES] [--provisional] [--out DIR]
    python -m ozl.syuka hits [PID] [--event-set ES] [--json] [--include-retro]
    python -m ozl.syuka hits --profile [--include-retro]

1판의 원래 일치율 파일(1판 계산)은 private/syuka/agree.json 과 사본 agree_20261114_0602.json 이다. 덮어쓰지 않는다.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing

from ozl import paths as ozlpaths
from . import agree, catalog, db, db_v3, hits, ledger, pilot, predict, profile, sample, schema, schema_v3

def agree_out(version: int = schema.SCHEMA_VERSION, folder=None) -> pathlib.Path:
    return (folder or db.DB_PATH.parent) / f"agree_v{version}.json"


def extract_dir(version: int = schema.SCHEMA_VERSION, folder=None) -> pathlib.Path:
    return (folder or db.DB_PATH.parent) / schema.EXTRACT_DIRS[version]


MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")


def cmd_catalog(con) -> int:
    rows = catalog.load_all()
    db.put_videos(con, rows)
    kinds = Counter(r["kind"] for r in rows)
    print(f"영상 {len(rows)}편 · " + " · ".join(f"{k} {kinds[k]}" for k in catalog.KINDS))
    print(f"전사 있음 {sum(r['has_transcript'] for r in rows)} · 업로드 목록에만 {sum(1 for r in rows if not r['in_transcripts'])}"
          f" · 전사 목록에만 {sum(1 for r in rows if not r['in_uploads'])}")
    for k in catalog.KINDS:
        sub = [r for r in rows if r["kind"] == k]
        print(f"  {k}: 전사 있음 {sum(r['has_transcript'] for r in sub)}/{len(sub)}")
    return 0


def cmd_sample(con, folder=None) -> int:
    rows = [dict(r) for r in con.execute("SELECT * FROM videos")]
    if not rows:
        print("videos 표가 비었다 — 먼저 catalog", file=sys.stderr)
        return 1
    picks = sample.pick(rows, sample.load_tags())
    out = sample.write(picks, folder / sample.OUT.name if folder else sample.OUT)
    print(f"표본 {len(picks)}편 → {out}")
    grid = Counter((r["upload_at"][:4], r["kind"]) for r in picks)
    for y in sorted({y for y, _ in grid}):
        print(f"  {y} 본편 {grid[(y, '본편')]:>2} · 생방송 전체 {grid[(y, '생방송 전체')]:>2}")
    print("  분야(기존 태그): " + ", ".join(f"{c} {n}" for c, n in Counter(r["stratum"].split("/")[-1] for r in picks if r["kind"] == "본편").most_common()))
    return 0


def cmd_put(con, model: str, path: str, folder=None) -> int:
    if not MODEL_RE.match(model):
        print(f"model 이름이 이상하다: {model!r}(소문자·숫자·._-)", file=sys.stderr)
        return 1
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"파일을 읽지 못했다: {e}", file=sys.stderr)
        return 1
    v = db.video(con, doc.get("video_id", "")) if isinstance(doc, dict) else None
    errs = []
    if not v:
        errs.append("video_id: videos 표에 없다(catalog 먼저)")
    elif not v["has_transcript"]:
        errs.append("video_id: 전사가 없는 영상이다")
    if isinstance(doc, dict) and doc.get("model") not in (None, model):
        errs.append(f"model: 파일의 {doc.get('model')!r} 와 명령의 {model!r} 가 다르다")
    want = extract_dir(folder=folder) / model / f"{doc.get('video_id') if isinstance(doc, dict) else ''}.json"
    if pathlib.Path(path).resolve() != want.resolve():
        errs.append(f"파일 위치: {schema.SCHEMA_VERSION}판 자료는 {want} 에 둔다(1판 폴더는 건드리지 않는다)")
    transcript = catalog.read_transcript(v["transcript_path"]) if v and v["has_transcript"] else None
    errs += schema.check_file(doc, transcript, v["upload_at"] if v else None)
    if errs:
        print("\n".join(errs))
        return 1
    if model == "merged":
        db.put_merged(con, doc["video_id"], doc["schema_version"], doc["record"])
    else:
        db.put_record(con, doc["video_id"], model, doc["schema_version"], doc["record"], doc["seconds"])
    print(f"넣음 {doc['video_id']} · {model} · {doc['seconds']}초")
    return 0


def cmd_agree(con, a: str, b: str, version: int = schema.SCHEMA_VERSION, folder=None) -> int:
    res = agree.compare(db.records(con, version), a, b)
    out = agree_out(version, folder)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{version}판 자료 · 계산 {schema.SCHEMA_VERSION}판")
    print(f"{a} · {b} 두 모델이 다 있는 영상 {res['n_videos']}편(한쪽만 {len(res['only_one_model'])}) — 일치율, 기준 {agree.PASS_RATE:.0%}")
    for f, r in res["fields"].items():
        rate = "-" if r["rate"] is None else f"{r['rate']:.1%}"
        print(f"  {f:<13} {r['agree']:>3}/{r['n']:<3} {rate:>6} {'통과' if r['pass'] else '미달'}")
    print(f"  편당 걸린 시간(중앙값, 초): " + ", ".join(f"{m} {s}" for m, s in res["seconds_median"].items()))
    print(f"→ {out}")
    return 0


def cmd_status(con, folder=None) -> int:
    kinds = dict(con.execute("SELECT kind, COUNT(*) FROM videos GROUP BY kind").fetchall())
    print(f"videos {sum(kinds.values())} · " + " · ".join(f"{k} {n}" for k, n in kinds.items()))
    for m, v, n, s in con.execute("SELECT model, schema_version, COUNT(*), ROUND(AVG(seconds)) FROM records "
                                  "GROUP BY model, schema_version ORDER BY schema_version, model"):
        print(f"records {m} {v}판: {n}건 · 평균 {s}초")
    print(f"merged {con.execute('SELECT COUNT(*) FROM merged').fetchone()[0]}건")
    sample_path = folder / sample.OUT.name if folder else sample.OUT
    print(f"표본 {'있음' if sample_path.exists() else '없음'} · 일치율 "
          + " · ".join(f"{v}판 {'있음' if agree_out(v, folder).exists() else '없음'}" for v in sorted(schema.EXTRACT_DIRS)))
    return 0


def v3_dir() -> pathlib.Path:
    return db.DB_PATH.parent / schema_v3.EXTRACT_DIR


def check_v3(con, path: pathlib.Path) -> tuple[dict | None, list[str]]:
    """(파일 내용, 오류 목록). DB 의 videos 표에서 전사와 올린 날을 찾아 함께 검사한다."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [f"파일을 읽지 못했다: {e}"]
    errs = []
    vid = doc.get("video_id") if isinstance(doc, dict) else None
    if isinstance(vid, str) and path.stem != vid:
        errs.append(f"파일 이름: <video_id>.json 이어야 한다({path.name} ≠ {vid}.json)")
    v = db.video(con, vid) if isinstance(vid, str) else None
    transcript = None
    if not v:
        errs.append("video_id: videos 표에 없다(catalog 먼저)")
    elif not v["has_transcript"]:
        errs.append("video_id: 전사가 없는 영상이다")
    else:
        transcript = catalog.read_transcript(v["transcript_path"])
    errs += schema_v3.validate_file(doc, transcript, v["upload_at"] if v else None)
    return doc, errs


def cmd_validate_v3(con, path: str) -> int:
    doc, errs = check_v3(con, pathlib.Path(path))
    if errs:
        print("\n".join(errs))
        return 1
    print(f"통과 {doc['video_id']} · 토막 {doc['n_segments']}")
    return 0


def cmd_load_v3(con, folder: str) -> int:
    d = pathlib.Path(folder)
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        print(f"JSON 파일이 없다: {d}", file=sys.stderr)
        return 1
    ok, bad = 0, 0
    for f in files:
        doc, errs = check_v3(con, f)
        if errs:
            bad += 1
            print(f"걸림 {f.name} · 오류 {len(errs)}")
            for e in errs:
                print(f"  {e}")
            continue
        db_v3.put(con, doc)
        ok += 1
    c = db_v3.counts(con)
    print(f"넣음 {ok} · 걸림 {bad} · 표: " + " · ".join(f"{t} {n}" for t, n in c.items()))
    return 1 if bad else 0


def cmd_find_v3(con, word: str) -> int:
    rows = db_v3.find(con, word)
    if not rows:
        print(f"'{word}' 를 다룬 토막이 없다(3판 자료 {db_v3.counts(con)['v3_videos']}편 기준)")
        return 0
    for r in rows:
        who = " · ".join(x for x in (r["main_person"], r["main_org"]) if x)
        print(f"{(r['upload_at'] or '?')[:10]}  {r['video_id']} #{r['seg']}  {r['field']}  {r['topic_line']}"
              + (f"  [{who}]" if who else "") + f"  ({', '.join(r['matched'])})")
        for c in con.execute("SELECT point, value, unit, as_of FROM v3_claims WHERE video_id=? AND seg=? "
                             "AND value IS NOT NULL ORDER BY i LIMIT 3", (r["video_id"], r["seg"])):
            print(f"      {c['point']}: {c['value']}{c['unit'] or ''}" + (f" ({c['as_of']})" if c["as_of"] else ""))
    print(f"토막 {len(rows)}개 · 영상 {len({r['video_id'] for r in rows})}편")
    return 0


def cmd_pilot_v3(con, folder=None) -> int:
    rows = [dict(r) for r in con.execute("SELECT * FROM videos")]
    if not rows:
        print("videos 표가 비었다 — 먼저 catalog", file=sys.stderr)
        return 1
    sample_path = folder / sample.OUT.name if folder else sample.OUT
    exclude = {v["video_id"] for v in json.loads(sample_path.read_text(encoding="utf-8"))["videos"]} if sample_path.exists() else set()
    if not exclude:
        print("표본 60편 파일이 없다 — 겹침을 피할 수 없어 멈춘다", file=sys.stderr)
        return 1
    picks = pilot.pick(rows, sample.load_tags(), exclude)
    out = pilot.write(picks, folder / pilot.OUT.name if folder else pilot.OUT)
    grid = Counter((r["upload_at"][:4], r["kind"]) for r in picks)
    print(f"시험 {len(picks)}편 → {out} (표본과 겹침 {len({r['video_id'] for r in picks} & exclude)})")
    for y in sorted({y for y, _ in grid}):
        print(f"  {y} 본편 {grid[(y, '본편')]} · 생방송 전체 {grid[(y, '생방송 전체')]}")
    print(f"  광고 표시 제목 {sum(r['ad_title'] for r in picks)}편")
    return 0


def cmd_mark_v3(con, video_id: str, every: int, start: int = 0, length: int | None = None) -> int:
    v = db.video(con, video_id)
    if not v or not v["has_transcript"]:
        print("videos 표에 없거나 전사가 없는 영상이다", file=sys.stderr)
        return 1
    p = ozlpaths.resolve(catalog.ROOT / v["transcript_path"])
    d = json.loads(p.read_text(encoding="utf-8"))
    text = catalog.read_transcript(v["transcript_path"])
    # 글자 위치 → 시각(다글로 segments 의 start). 유튜브 자막은 시각이 없다.
    starts, pos = [], 0
    for s in d.get("segments") or []:
        t = s.get("text") or ""
        i = text.find(t, pos) if t else -1
        if i >= 0:
            starts.append((i, s.get("start")))
            pos = i + len(t)
    stop = len(text) if length is None else min(len(text), start + length)
    print(f"# {video_id} · 전사 {len(text)}자 · 출처 {v['transcript_source']} · 표시 {every}자마다 · 이번에 찍는 범위 {start}~{stop}")
    j, out = 0, []
    for a in range(start - start % every, stop, every):
        while j + 1 < len(starts) and starts[j + 1][0] <= a:
            j += 1
        sec = starts[j][1] if starts and starts[j][0] <= a else None
        tm = (f" · {int(sec) // 3600}:{int(sec) % 3600 // 60:02d}:{int(sec) % 60:02d} ({int(sec)}초)"
              if isinstance(sec, (int, float)) else "")
        out.append(f"\n⟦글자 {a}{tm}⟧\n{text[max(a, start):min(a + every, stop)]}")
    print("".join(out))
    print(f"\n⟦끝 · 글자 {len(text)}⟧" if stop >= len(text) else f"\n⟦여기까지 {stop} · 다음은 --start {stop}⟧")
    return 0


def _add_ledger_commands(sub):
    prediction = sub.add_parser("predict").add_subparsers(dest="action", required=True)
    prepare = prediction.add_parser("prepare")
    prepare.add_argument("--weeks", type=int, default=8)
    prepare.add_argument("--asof")
    baselines = prediction.add_parser("baselines")
    baselines.add_argument("--clusters", required=True)
    baselines.add_argument("--n", type=int, default=15)
    for command in (prepare, baselines):
        command.add_argument("board")
        command.add_argument("--out", required=True)
    add = prediction.add_parser("add")
    add.add_argument("path")
    add.add_argument("--retro", action="store_true")
    fix = prediction.add_parser("fix")
    fix.add_argument("path")
    fix.add_argument("--date", required=True)
    for command in (fix, add):
        command.add_argument("--revises")
    verify = prediction.add_parser("verify")
    verify.add_argument("pid", nargs="?")
    verify.add_argument("--expect")
    prediction.add_parser("list")

    scoring = sub.add_parser("score").add_subparsers(dest="action", required=True)
    events = scoring.add_parser("events")
    events.add_argument("pid")
    source = events.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-json")
    source.add_argument("--from-v3")
    events.add_argument("--merge", action="append", default=[])
    events.add_argument("--minor", type=int, action="append", default=[])
    events.add_argument("--weekday", action="append", default=[])
    events.add_argument("--replace", action="store_true")

    packet = scoring.add_parser("packet")
    packet.add_argument("--out", required=True)
    packet.add_argument("--clusters")
    packet.add_argument("--seed", type=int)
    packet.add_argument("--skip-gate", action="store_true")
    mask = scoring.add_parser("mask-import")
    mask.add_argument("--mask", required=True)
    mask.add_argument("--packet", required=True)
    judge = scoring.add_parser("judge")
    judge.add_argument("--judge", choices=("codex", "gemini", "chatgpt"), required=True)
    finalize = scoring.add_parser("finalize")
    finalize.add_argument("--provisional", action="store_true")
    finalize.add_argument("--out")
    for command in (packet, mask, judge, finalize):
        command.add_argument("pid")
        command.add_argument("--event-set", help="사건 묶음 (둘 이상이면 필수)" if command is judge else "사건 묶음")
    judge.add_argument("path")

    report = sub.add_parser("hits")
    report.add_argument("pid", nargs="?")
    report.add_argument("--event-set")
    report.add_argument("--json", action="store_true")
    report.add_argument("--profile", action="store_true")
    report.add_argument("--include-retro", action="store_true")


def _cmd_predict(con, a):
    if a.action == "add":
        print(predict.register(con, a.path, "retro" if a.retro else "official", a.revises))
    elif a.action == "fix":
        path, pid = predict.fix(con, a.path, a.date, a.revises)
        print(f"{pid}  {path}")
    elif a.action == "verify":
        results = predict.verify(con, a.pid, a.expect)
        for row in results:
            verdict = "일치" if row["ok"] else f"불일치({', '.join(row['problems'])})"
            print(f"{row['prediction_id']}  {verdict}", file=sys.stdout if row["ok"] else sys.stderr)
        return int(any(not row["ok"] for row in results))
    else:
        print("예측 ID\t종류\t방송 날짜\t고정 시각\tpick\tA\tB\t해시")
        for r in predict.list_predictions(con):
            kind = "공식" if r["kind"] == "official" else "소급 시험"
            print(r["prediction_id"], kind, r["broadcast_date"], r["fixed_at"],
                  r["pick"], r["A"], r["B"], r["sha256"][:12], sep="\t")
    return 0


def _cmd_score(con, a):
    if a.action == "events":
        print(hits.events(con, a.pid, a.from_json, a.from_v3, a.merge, a.minor, a.weekday, a.replace))
    elif a.action == "packet":
        print(hits.packet(con, a.pid, a.out, a.clusters, a.seed, a.event_set, a.skip_gate))
    elif a.action == "mask-import":
        hits.mask_import(con, a.pid, a.mask, a.packet, a.event_set)
        print("가림 묶음 등록")
    elif a.action == "judge":
        n = hits.judge(con, a.pid, a.judge, a.path, a.event_set)
        print(f"{a.judge} 판정 {n}건")
    else:
        return hits.finalize(con, a.pid, a.event_set, a.provisional, a.out)
    return 0


def _report(con, pid, event_set, include_retro):
    if pid:
        prediction = hits._prediction(con, pid)
        pid, es = hits._scope(con, pid, event_set)
        rows = con.execute("""SELECT * FROM weekly_metrics WHERE prediction_id=? AND event_set=?
                              ORDER BY CASE set_name WHEN 'pick' THEN 0 WHEN 'A' THEN 1 ELSE 2 END""", (pid, es))
    else:
        latest = hits._latest_sets(con)
        rows = (r for r in con.execute("""SELECT * FROM weekly_metrics WHERE kind='official' OR ?
                ORDER BY broadcast_date, prediction_id, CASE set_name WHEN 'pick' THEN 0 WHEN 'A' THEN 1 ELSE 2 END""",
                                       (include_retro,)) if r["event_set"] == (event_set or latest.get(r["prediction_id"])))
    metrics = []
    for r in rows:
        metric = dict(r)
        for name in ("by_timing", "matched", "weekday", "vs_baselines", "judging"):
            if metric[name] is not None:
                metric[name] = json.loads(metric[name])
        metrics.append(metric)
    if not pid:
        report = {"official": [m for m in metrics if m["kind"] == "official"]}
        if include_retro:
            report["retro"] = [m for m in metrics if m["kind"] == "retro"]
            report["retro_note"] = "소급 시험(공식 기록 아님)"
        return report
    events = []
    for r in con.execute("""SELECT event_id,timing,minutes,label,official,minor FROM broadcast_events
                            WHERE prediction_id=? AND event_set=? ORDER BY CAST(substr(event_id,2) AS INTEGER)""", (pid, es)):
        grades = {m["set_name"]: m["matched"].get(r["event_id"], {}).get("grade") for m in metrics}
        events.append(dict(r) | {"grades": grades})
    report = {"prediction_id": pid, "event_set": es, "kind": prediction["kind"], "metrics": metrics,
              "events": events, "judging": metrics[0]["judging"] if metrics else None}
    if prediction["kind"] == "retro":
        report["note"] = "소급 시험 — 공식 적중 기록이 아니다"
    return report


def _print_metrics(metrics):
    print("방송 날짜\t예측 ID\t집합\t상태\t사건 수\tfull\tadjacent\t가중 적중\t완전 재현율\t가중 재현율\t확신 정밀도")
    fields = ("broadcast_date", "prediction_id", "set_name", "status", "events_n", "full_hits",
              "adjacent_hits", "weighted_hits", "recall_full", "recall_weighted", "confident_precision")
    for m in metrics:
        print(*[m[k] if m[k] is not None else "—" for k in fields], sep="\t")


def _print_breakdown(metrics):
    for m in metrics:
        name = m["set_name"]
        print(f"{name} 갈래별 적중 (사건 수 / full / 가중)")
        for timing, b in (*m["by_timing"].items(), ("주중", m["weekday"])):
            print(f"  {timing}: {b['n']} / {b['full']} / {b['weighted']}")
        if name == "pick":
            print(f"확신 {m['confident_n']}건: full {m['confident_full']}, 가중 {m['confident_weighted']}")
            for baseline, comparison in m["vs_baselines"].items():
                ratio = comparison["ratio_weighted"]
                multiple = f"{ratio:.2f}배" if ratio is not None else "계산 불가"
                print(f"기준선 {baseline} 대비: full 차이 {comparison['diff_full']:+d}, "
                      f"가중 차이 {comparison['diff_weighted']:+g}, 가중 배수 {multiple}")


def _cmd_hits(con, a):
    if a.profile:
        fitted = profile.fit(profile.rows(con, a.include_retro))
        note = f"표본 {fitted.n}건 — 표본이 적어 참고용"
        if a.json:
            print(ledger.dumps({"n": fitted.n, "table": fitted.table(), "note": note}))
        else:
            print(note)
            print("특징\t값\t표본\t채택\t기여도")
            for r in fitted.table():
                print(r["feature"], r["value"], r["n"], r["adopted"], f"{r['contribution']:+.3f}", sep="\t")
        return 0
    report = _report(con, a.pid, a.event_set, a.include_retro)
    if a.json:
        print(ledger.dumps(report))
    elif a.pid:
        if "note" in report:
            print(report["note"])
        print(f"{a.pid}  사건 묶음 {report['event_set']}")
        print("사건\t갈래\t분\t구분\t이름\tpick\tA\tB")
        for e in report["events"]:
            kind = "공식" if e["official"] else "주중"
            if e["minor"]:
                kind += "/짧은 언급"
            print(e["event_id"], e["timing"], e["minutes"] if e["minutes"] is not None else "—", kind, e["label"],
                  *(e["grades"].get(s) or "—" for s in ("pick", "A", "B")), sep="\t")
        _print_metrics(report["metrics"])
        _print_breakdown(report["metrics"])
        j = report["judging"]
        if j and j["n"]:
            print(f"판정 일치율 {j['agree']}/{j['n']} ({j['rate']:.1%})")
        else:
            print("판정 일치율 —")
    else:
        _print_metrics(report["official"])
        if a.include_retro:
            print(report["retro_note"])
            _print_metrics(report["retro"])
    return 0


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(f"명령 인자가 잘못됐다: {message}")


def _main(argv) -> int:
    ap = _Parser(prog="python -m ozl.syuka")
    ap.add_argument("--db", type=pathlib.Path, help=f"장부 경로 (기본: {db.DB_PATH})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog")
    sub.add_parser("sample")
    p = sub.add_parser("put")
    p.add_argument("model")
    p.add_argument("path")
    p = sub.add_parser("agree")
    p.add_argument("models", nargs="*", default=["opus", "sonnet"])
    p.add_argument("--schema-version", type=int, default=schema.SCHEMA_VERSION, choices=sorted(schema.EXTRACT_DIRS))
    sub.add_parser("status")
    sub.add_parser("pilot-v3")
    p = sub.add_parser("mark-v3")
    p.add_argument("video_id")
    p.add_argument("--every", type=int, default=2000)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--length", type=int, default=None)
    p = sub.add_parser("validate-v3")
    p.add_argument("path")
    p = sub.add_parser("load-v3")
    p.add_argument("folder")
    p = sub.add_parser("find-v3")
    p.add_argument("word")
    _add_ledger_commands(sub)
    a = ap.parse_args(argv)
    if a.cmd == "predict" and a.action in ("prepare", "baselines"):
        try:
            if a.action == "prepare":
                uri = (a.db or db.DB_PATH).resolve().as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True)) as con:
                    predict.prepare(con, a.board, a.out, a.weeks, a.asof)
            else:
                predict.baselines(a.board, a.clusters, a.out, a.n)
        except FileExistsError as exc:
            raise ValueError(f"이미 있는 경로다. 새 출력 경로를 지정한다: {exc.filename}") from exc
        except (KeyError, TypeError) as exc:
            raise ValueError(f"판이나 묶음의 입력 형식이 잘못됐다: {exc}") from exc
        print(a.out)
        return 0
    folder = a.db.parent if a.db is not None else None
    con = db.connect(a.db or db.DB_PATH)
    try:
        if a.cmd in ("predict", "score", "hits"):
            ledger.ensure(con)
            if a.cmd == "predict":
                return _cmd_predict(con, a)
            if a.cmd == "score":
                return _cmd_score(con, a)
            return _cmd_hits(con, a)
        if a.cmd == "catalog":
            return cmd_catalog(con)
        if a.cmd == "sample":
            return cmd_sample(con, folder)
        if a.cmd == "put":
            return cmd_put(con, a.model, a.path, folder)
        if a.cmd == "agree":
            if len(a.models) != 2:
                ap.error("agree 는 모델 두 개")
            return cmd_agree(con, *a.models, version=a.schema_version, folder=folder)
        if a.cmd == "pilot-v3":
            return cmd_pilot_v3(con, folder)
        if a.cmd == "mark-v3":
            return cmd_mark_v3(con, a.video_id, max(200, a.every), max(0, a.start), a.length)
        if a.cmd == "validate-v3":
            return cmd_validate_v3(con, a.path)
        if a.cmd == "load-v3":
            return cmd_load_v3(con, a.folder)
        if a.cmd == "find-v3":
            return cmd_find_v3(con, a.word)
        return cmd_status(con, folder)
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
