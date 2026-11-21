"""슈카월드 본편과 구성 라벨에서 덱 설계표와 조회수 기술 통계를 낸다."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ozl import paths as ozlpaths
from ozl.syuka.catalog import KST, classify

CUTS = (15, 20, 25, 30, 35)
BANDS = ("[0,15)", "[15,20)", "[20,25)", "[25,30)", "[30,35)", "[35,∞)")
UNKNOWN = "분류 없음"
FIELDS = {
    "국제": ("국제 정치·외교", "전쟁·안보", "해외 경제"),
    "국내": ("국내 경제·정책", "사회·인구·노동", "부동산", "문화·생활", "역사"),
    "시장·기업": ("기업·증시", "금리·통화·환율", "에너지·원자재", "과학·기술"),
}
BRANCH = {field: branch for branch, fields in FIELDS.items() for field in fields}
LEDGER_COLUMNS = (
    "video_id", "upload_date", "duration_min", "seg", "start_sec", "end_sec",
    "field", "field2", "korea_level", "evergreen", "topic_line",
    "view_count", "views_fetched_at", "age_days_at_fetch",
)


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def quantile(values, p):
    """두 순서통계량 사이를 선형 보간한다."""
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (index - lower) * (ordered[upper] - ordered[lower])


def shares(counts):
    total = sum(counts.values())
    return {key: count / total for key, count in sorted(counts.items())}


def band(minutes):
    return BANDS[bisect_right(CUTS, minutes)]


def slides_by_duration(con):
    videos = []
    bins = {key: [] for key in BANDS}
    for vid, seconds, slides, media in con.execute("""
        SELECT d.video_id, d.duration_sec, COUNT(s.no) FILTER (WHERE s.kind='slide'),
               COUNT(s.no) FILTER (WHERE s.kind='media')
        FROM sd_videos d JOIN videos v USING(video_id)
        LEFT JOIN sd_slides s ON s.video_id=d.video_id AND s.flash=0
        WHERE v.kind='본편' GROUP BY d.video_id ORDER BY d.video_id
    """):
        minutes = seconds / 60
        row = dict(video_id=vid, minutes=minutes, n_slides=slides, n_media=media,
                   sec_per_slide=seconds / slides if slides else None)
        videos.append(row)
        bins[band(minutes)].append(row)
    stats = {}
    for key, rows in bins.items():
        counts = [r["n_slides"] for r in rows]
        stats[key] = dict(n_videos=len(rows), n_slides_median=median(counts),
                          n_slides_p25=quantile(counts, .25), n_slides_p75=quantile(counts, .75),
                          sec_per_slide_median=median(r["sec_per_slide"] for r in rows))
    xx = sum(r["minutes"] ** 2 for r in videos)
    xy = sum(r["minutes"] * r["n_slides"] for r in videos)
    yy = sum(r["n_slides"] ** 2 for r in videos)
    slope = xy / xx if xx else None
    # 절편 없는 모형의 결정계수는 0을 기준으로 한다.
    fit = dict(slides_per_minute=slope, r2_uncentered=xy ** 2 / (xx * yy) if xx and yy else None)
    return dict(n_videos=len(videos), bins=stats, origin_fit=fit, videos=videos)


def read_input(path):
    raw = path.read_bytes()
    return raw, dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())


def load_compositions(directories):
    docs, files = {}, []
    for directory in directories:
        for path in sorted(directory.iterdir()):
            # 영상 번호가 밑줄로 시작할 수 있으므로(예: __f_…) 이름으로 거르지 않고 video_id 칸으로 가른다.
            if path.suffix != ".json" or not path.is_file():
                continue
            raw, info = read_input(path)
            doc = json.loads(raw)
            if not isinstance(doc, dict) or not doc.get("video_id"):
                continue
            docs[doc["video_id"]] = doc
            files.append(info)
    return docs, files


VOCAB = {
    "stage": {"hook", "lead_in", "background", "development", "data", "turn", "comparison", "digression",
              "solution", "implication", "briefing", "closing", "other"},
    "role": {"hook", "context", "quote", "data", "case", "explainer", "turn", "comparison", "humor", "solution",
             "implication", "summary", "transition", "non_slide", "other"},
    "source_type": {"foreign_press", "domestic_press", "official", "research_report", "market_data", "social",
                    "own_chart", "photo_only", "none", "unclear", "other"},
    "layout": {"text_only", "image_left", "image_right", "image_full", "image_pair", "image_stack", "media"},
    "primary_kind": {"photo", "article", "chart", "table", "logo", "person", "map", "sns", "meme", "drawing", "none"},
    "title_color": {"red", "black", "mixed", "on_dark", "other", "none"},
}


def category(value, kind="stage"):
    """정해 둔 어휘만 집계에 낸다. other: 뒤의 자유 문구와 어휘 밖의 값(문구가 섞였을 수 있다)은 옮기지 않는다."""
    if value is None or value == "":
        return UNKNOWN
    base = str(value).split(":", 1)[0].strip()
    return base if base in VOCAB[kind] else UNKNOWN


def vocab(value, kind):
    """None 은 그대로(분모에서 빠진다), 어휘 밖 값은 분류 없음."""
    return None if value is None else category(value, kind)


def stage_numbers(doc):
    """원래 배열에서 먼저 만난 단계에 장 번호를 배정한다."""
    assigned = {}
    for stage in doc["stages"]:
        name = category(stage["stage"])
        for no in range(max(1, stage["slide_from"]), min(doc["n_slides"], stage["slide_to"]) + 1):
            assigned.setdefault(no, name)
    return assigned


def slide_times(directories, vid):
    """라벨을 붙일 때 쓴 슬라이드 목록({no: t_first}, no 가 없으면 순번). 뒤 폴더가 우선한다. 없으면 None."""
    times = None
    for directory in directories:
        for name in (f"{vid}.json", f"{vid}.slides.json"):
            path = Path(directory) / name
            if path.is_file():
                slides = json.loads(path.read_text(encoding="utf-8"))["slides"]
                times = {int(s["no"]) if s.get("no") is not None else i: s.get("t_first")
                         for i, s in enumerate(slides, 1)}
    return times


def slide_features(con, vid, labelers, times=None):
    """라벨 번호에 원래 장의 관측값을 잇는다. 목록 시각(times)이 있으면 t_first 로 잇고(3초 안의 가장 가까운 장),
    없으면 반짝 장을 뺀 순번으로 잇는다. 슬라이드 자료를 다시 만들면 순번이 밀리므로 시각이 우선이다."""
    pictures = defaultdict(dict)
    for no, labeler, kind in con.execute("""
        SELECT p.no, p.labeler, p.primary_kind FROM sd_picture_labels p
        JOIN sd_slides s ON s.video_id=p.video_id AND s.no=p.no
        WHERE p.video_id=? AND p.primary_kind IS NOT NULL AND p.primary_kind!=''
          -- note 에 라벨 때의 대표 프레임 이름이 있으면 지금 그 장의 프레임과 같을 때만 쓴다(재생성으로 번호가 밀린 라벨 차단)
          AND (p.note IS NULL OR p.note='' OR p.note=s.best_frame)
        ORDER BY p.no, p.labeler
    """, (vid,)):
        pictures[no][labeler] = kind
    rows = con.execute("""
        SELECT s.no, s.layout, s.n_graphics, s.title_color, b.red_share, s.t_first, s.flash
        FROM sd_slides s LEFT JOIN (
            SELECT no, AVG(color='red') AS red_share FROM sd_lines
            WHERE video_id=? AND size_class='body' GROUP BY no
        ) b USING(no)
        WHERE s.video_id=? ORDER BY s.no
    """, (vid, vid)).fetchall()

    def feature(row):
        no, layout, graphics, color, red = row[:5]
        labels = pictures[no]
        preferred = next((k for k in labelers if k in labels), None)
        kind = labels[preferred] if preferred is not None else next(iter(labels.values()), None)
        return dict(layout=layout, n_graphics=graphics, title_color=color, primary_kind=kind, red_body_share=red)

    if times is None:
        return {i: feature(r) for i, r in enumerate((r for r in rows if not r[6]), 1)}
    if not isinstance(times, dict):
        times = dict(enumerate(times, 1))
    timed = [r for r in rows if r[5] is not None]
    features = {}
    for i, t in times.items():
        if t is None:
            continue
        near = min(timed, key=lambda r: (abs(r[5] - t), r[6]), default=None)
        if near is not None and abs(near[5] - t) <= 3:
            features[i] = feature(near)
    return features


def mix_row(rows, total):
    result = dict(n_videos=len({r["video_id"] for r in rows}), n_slides=len(rows),
                  slide_share=len(rows) / total if total else None)
    for key in ("source_type", "role", "layout", "primary_kind", "title_color"):
        # 영상 화면(non_slide)은 장 수와 단계 순서에는 넣되 역할·자료 비율의 분모에서는 뺀다(compose_aggregate 와 같다)
        pool = [r for r in rows if r.get("role") != "non_slide"] if key in ("source_type", "role") else rows
        counts = Counter(r[key] for r in pool if r.get(key) is not None)
        result[key] = dict(denominator=sum(counts.values()), shares=shares(counts))
    for key in ("red_body_share", "n_graphics"):
        known = [r[key] for r in rows if r.get(key) is not None]
        result[key] = dict(denominator=len(known), mean=statistics.mean(known) if known else None)
    return result


def stage_mix(con, docs, assignments, labelers, slide_lists=()):
    groups = defaultdict(list)
    total = []
    for vid, doc in docs.items():
        roles = {r["no"]: r for r in doc["slide_roles"]}
        features = slide_features(con, vid, labelers, slide_times(slide_lists, vid))
        for no in range(1, doc["n_slides"] + 1):
            role = roles.get(no, {})
            feat = dict(features.get(no, {}))
            for key in ("layout", "primary_kind", "title_color"):
                if key in feat:
                    feat[key] = vocab(feat[key], key)
            row = dict(video_id=vid, source_type=category(role.get("source_type"), "source_type"),
                       role=category(role.get("role"), "role"), **feat)
            groups[assignments[vid].get(no, UNKNOWN)].append(row)
            total.append(row)
    overall = mix_row(total, len(total))
    overall["n_videos"] = len(docs)
    return dict(n_videos=len(docs), labeler_priority=list(labelers),
                stages={k: mix_row(v, len(total)) for k, v in sorted(groups.items())}, total=overall)


def representative_segments(con):
    """토막이 여럿인데 잰 길이가 하나도 없으면 대표를 고르지 않는다."""
    return {row["video_id"]: dict(row) for row in con.execute("""
        SELECT video_id, field, korea_level, evergreen FROM (
            SELECT video_id, field, korea_level, evergreen, end_sec-start_sec AS duration,
                   COUNT(*) OVER (PARTITION BY video_id) AS n_segments, ROW_NUMBER() OVER (
                PARTITION BY video_id ORDER BY end_sec-start_sec DESC, seg ASC
            ) AS rank FROM v3_segments
        ) WHERE rank=1 AND (n_segments=1 OR duration IS NOT NULL)
    """)}


def branch_skeleton(ids, docs, assignments):
    stage_counts, reversal_counts, first_reversals, korea_positions, humor_counts = [], [], [], [], []
    first, fractions = defaultdict(list), defaultdict(list)
    for vid in ids:
        doc = docs[vid]
        n = doc["n_slides"]
        stage_counts.append(len(doc["stages"]))
        positions = defaultdict(list)
        for no, name in assignments[vid].items():
            positions[name].append(no)
        for name, numbers in positions.items():
            first[name].append(min(numbers) / n)
            fractions[name].append(len(numbers) / n)
        reversals = doc.get("reversals") or []
        reversal_counts.append(len(reversals))
        numbers = [r["slide_no"] for r in reversals if r.get("slide_no")]
        if numbers and n:
            first_reversals.append(min(numbers) / n)
        korea = doc.get("korea_link") or {}
        if korea.get("present") and korea.get("mode") != "topic" and korea.get("slide_no") and n:
            korea_positions.append(korea["slide_no"] / n)
        humor_counts.append(len(doc.get("humor_slides") or []))
    stages = [dict(stage=name, video_share=len(nums) / len(ids), first_position_median=median(nums),
                   slide_share_median=median(fractions[name])) for name, nums in first.items()]
    stages.sort(key=lambda s: (s["first_position_median"], s["stage"]))
    return dict(n_videos=len(ids), video_ids=ids, n_stages_median=median(stage_counts), stages=stages,
                skeleton=[s for s in stages if s["video_share"] >= .5],
                n_reversals_median=median(reversal_counts), first_reversal_median=median(first_reversals),
                korea_link_position_median=median(korea_positions), n_humor_slides_median=median(humor_counts))


def skeletons(docs, assignments, representatives):
    groups = {key: [] for key in (*FIELDS, UNKNOWN)}
    for vid in sorted(docs):
        field = representatives.get(vid, {}).get("field")
        groups[BRANCH.get(field, UNKNOWN)].append(vid)
    return dict(n_videos=len(docs), branches={key: branch_skeleton(ids, docs, assignments)
                                              for key, ids in groups.items()})


def timestamp(value, default_zone):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=default_zone)


def catalog_views(raw, asof, db_kinds):
    """조회수는 적격 행에만 남기고, 장부 대조용 측정 시각과 나이는 보존한다."""
    observations, eligible = {}, {}
    discarded = Counter()
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")):
        vid = row["video_id"]
        if vid in observations:
            raise ValueError(f"목록의 영상 번호 중복: {vid}")
        fetched = timestamp(row["fetched_at"], timezone.utc)
        published = timestamp(row["published_kst"], KST)
        age = (fetched - published).days if fetched and published else None
        observation = dict(view_count=None, views_fetched_at=row["fetched_at"], age_days_at_fetch=age)
        observations[vid] = observation
        duration = int(row["duration_sec"] or 0)
        kind = db_kinds.get(vid)
        if kind is None:
            kind = row["kind"]
            if kind in ("video", "short", "live"):
                kind = classify(duration, kind)
        if not fetched:
            discarded["missing_fetched_at"] += 1
            continue
        days = (asof - fetched.astimezone(KST).date()).days
        if days > 30:
            discarded["stale"] += 1
        elif days < 0:
            discarded["future"] += 1
        elif kind != "본편":
            discarded["not_main"] += 1
        elif not published or published.astimezone(KST).date() < date(2025, 1, 1):
            discarded["publication_date"] += 1
        elif age < 14:
            discarded["under_14_days"] += 1
        elif not row["view_count"]:
            discarded["missing_views"] += 1
        else:
            observation["view_count"] = int(row["view_count"])
            eligible[vid] = dict(view_count=observation["view_count"], minutes=duration / 60,
                                 fetched=fetched.astimezone(timezone.utc), published=published.astimezone(KST))
    return observations, eligible, discarded


def views_stats(eligible, discarded, asof, representatives):
    counts = [r["view_count"] for r in eligible.values()]
    overall = median(counts)
    dates = [r["fetched"] for r in eligible.values()]
    groups = {k: defaultdict(list) for k in ("field", "branch", "duration", "weekday", "year",
                                              "korea_level", "evergreen")}
    for vid, row in eligible.items():
        rep = representatives.get(vid, {})
        field = rep.get("field") or UNKNOWN
        published = row["published"]
        keys = dict(field=field, branch=BRANCH.get(field, UNKNOWN), duration=band(row["minutes"]),
                    weekday="월화수목금토일"[published.weekday()], year=str(published.year),
                    korea_level=rep.get("korea_level") or UNKNOWN, evergreen=rep.get("evergreen") or UNKNOWN)
        for name, key in keys.items():
            groups[name][key].append(row["view_count"])
    summaries = {}
    for name, buckets in groups.items():
        summaries[name] = {}
        for key, values in sorted(buckets.items()):
            stats = dict(n_videos=len(values))
            if len(values) >= 5:
                middle = median(values)
                stats.update(median=middle, multiple_of_overall=middle / overall if overall else None)
            summaries[name][key] = stats
    return dict(n_videos=len(counts), asof=asof.isoformat(),
                fetched_at_min=min(dates).isoformat() if dates else None,
                fetched_at_max=max(dates).isoformat() if dates else None,
                discarded_rows=sum(discarded.values()), discarded_stale=discarded["stale"],
                discarded_by_reason=dict(discarded), median=overall, p25=quantile(counts, .25),
                p75=quantile(counts, .75), p90=quantile(counts, .90),
                mean=statistics.mean(counts) if counts else None, groups=summaries)


def topic_ledger(con, observations, output):
    ids, by_field = set(), defaultdict(set)
    segments, years, months, evergreen = Counter(), Counter(), Counter(), Counter()
    query = """
        SELECT v.video_id, substr(v.upload_at,1,10) AS upload_date, v.duration_sec/60.0 AS duration_min,
               s.seg, s.start_sec, s.end_sec, s.field, s.field2, s.korea_level, s.evergreen, s.topic_line
        FROM videos v JOIN v3_segments s USING(video_id) WHERE v.kind='본편' ORDER BY v.video_id, s.seg
    """
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LEDGER_COLUMNS)
        writer.writeheader()
        for row in con.execute(query):
            vid, field = row["video_id"], row["field"]
            writer.writerow({**dict(row), **observations.get(vid, {})})
            if vid not in ids:
                uploaded = row["upload_date"]
                years[uploaded[:4] if uploaded else UNKNOWN] += 1
                months[uploaded[:7] if uploaded else UNKNOWN] += 1
                ids.add(vid)
            by_field[field].add(vid)
            segments[field] += 1
            evergreen[row["evergreen"] or UNKNOWN] += 1
    total = sum(segments.values())
    return dict(n_videos=len(ids), n_segments=total,
                fields={k: dict(n_videos=len(v), n_segments=segments[k]) for k, v in sorted(by_field.items())},
                videos_by_year=years, videos_by_month=months, evergreen_shares=shares(evergreen),
                evergreen_share=evergreen["상시"] / total if total else None)


def generate(db, catalog, compose_dirs, asof, out, labelers=(), slide_lists=()):
    """읽기 전용 DB의 한 시점으로 여섯 파일을 계산한 뒤 교체한다."""
    docs, files = load_compositions(compose_dirs)
    assignments = {vid: stage_numbers(doc) for vid, doc in docs.items()}
    raw, catalog_info = read_input(catalog)
    inputs = dict(db=str(db.resolve()), catalog=catalog_info, compose=files)
    header = dict(generated_at=datetime.now(KST).isoformat(timespec="seconds"), inputs=inputs)
    targets = {(out / f"{name}.json").resolve() for name in
               ("slides_by_duration", "stage_mix", "skeletons", "topic_ledger_summary", "views_stats")}
    targets.add((out / "topic_ledger.csv").resolve())
    if db.resolve() in targets or catalog.resolve() in targets:
        raise ValueError("출력 파일이 입력 DB 나 목록 파일을 덮는다 — --out 을 바꾼다")
    out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out) as temp:
        staging = Path(temp)
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            con.execute("BEGIN")
            representatives = representative_segments(con)
            observations, eligible, discarded = catalog_views(
                raw, asof, dict(con.execute("SELECT video_id, kind FROM videos")))
            reports = {
                "slides_by_duration": slides_by_duration(con),
                "stage_mix": stage_mix(con, docs, assignments, labelers, slide_lists),
                "skeletons": skeletons(docs, assignments, representatives),
                "topic_ledger_summary": topic_ledger(con, observations, staging / "topic_ledger.csv"),
                "views_stats": views_stats(eligible, discarded, asof, representatives),
            }
        for name, report in reports.items():
            content = json.dumps({**header, **report}, ensure_ascii=False, indent=2, allow_nan=False)
            (staging / f"{name}.json").write_text(content + "\n", encoding="utf-8")
        for path in staging.iterdir():
            path.replace(out / path.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ozlpaths.at("syuka", "syuka.db"))
    parser.add_argument("--catalog", type=Path, default=ozlpaths.at("meta", "catalog_syukaworld.csv"))
    parser.add_argument("--compose-dirs", type=Path, nargs="+", default=[], help="기본 폴더 뒤에 읽을 구성 폴더")
    parser.add_argument("--labeler", nargs="+", action="extend", default=[], help="앞에서부터 그림 라벨러 우선순위")
    parser.add_argument("--asof", type=date.fromisoformat, default=datetime.now(KST).date())
    parser.add_argument("--slide-lists", type=Path, nargs="+", default=[ozlpaths.at("slides_label_r2")],
                        help="라벨 번호의 기준이 된 슬라이드 목록 폴더(뒤가 우선). 장을 t_first 로 잇는다")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    compose = ozlpaths.at("compose")   # 부를 때 정한다(시험이 OZL_PRIVATE 로 바꾼다)
    directories = [compose] if compose.is_dir() or not args.compose_dirs else []
    generate(args.db, args.catalog, [*directories, *args.compose_dirs], args.asof, args.out, args.labeler, args.slide_lists)


if __name__ == "__main__":
    main()
