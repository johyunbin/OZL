"""확정 판정에서 방송 채택 여부를 읽고, 이야기 특징별 채택 로그 오즈 차이를 구한다."""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

from . import hits

FEATURES = ("category", "overlap", "engine_rank_band", "members_band", "in_A", "in_B", "picked")
FORBIDDEN = ("view", "like", "comment", "조회", "좋아요", "댓글")


def _rank_band(rank):
    if rank is None:
        return "없음"
    if rank <= 5:
        return "1–5"
    if rank <= 15:
        return "6–15"
    return "16+"


def _members_band(count):
    if count >= 6:
        return "6+"
    if count >= 2:
        return "2–5"
    return "1" if count else None


def rows(con, include_retro=False) -> list[dict]:
    """가장 최근 사건 묶음에서 판정된 예측·이야기마다 표본 한 행을 만든다."""
    query = """
        SELECT i.*, j.grade, j.event_set
        FROM predictions AS p
        JOIN hit_judgments AS j USING (prediction_id)
        JOIN prediction_items AS i USING (prediction_id, story_key)
        WHERE (p.kind = 'official' OR ?) AND j.judge = 'final'
              AND j.grade IN ('full', 'adjacent', 'none')
        ORDER BY i.prediction_id, i.story_key,
                 CASE i.set_name WHEN 'pick' THEN 0 WHEN 'A' THEN 1 ELSE 2 END
    """
    samples = []
    latest = hits._latest_sets(con)
    records = (r for r in con.execute(query, (include_retro,))
               if latest.get(r["prediction_id"]) == r["event_set"])
    for (pid, story), group in groupby(records, key=itemgetter("prediction_id", "story_key")):
        items = list(group)
        sets = {item["set_name"] for item in items}
        category = next((r["category"] for r in items if r["category"]), None)
        overlap = items[0]["overlap"]
        rank = next((r["engine_rank"] for r in items if r["engine_rank"] is not None), None)
        # 기준선의 대표 기사만으로는 묶음 전체의 크기를 알 수 없다.
        members_band = "모름"
        if "pick" in sets:
            members_band = _members_band(len(set(json.loads(items[0]["member_ids"]))))
        samples.append({
            "prediction_id": pid, "story_key": story, "adopted": int(items[0]["grade"] != "none"),
            "category": category, "overlap": overlap if overlap in ("없음", "후속", "이미 다룸") else None,
            "engine_rank_band": _rank_band(rank),
            "members_band": members_band,
            "in_A": "A" in sets, "in_B": "B" in sets, "picked": "pick" in sets,
        })
    return samples


def _features(item):
    for name in item:
        if any(word in name.lower() for word in FORBIDDEN):
            raise ValueError(f"반응 수치는 특징으로 쓸 수 없다: {name}")
    return [(name, value) for name, value in item.items()
            if name in FEATURES and not (name == "members_band" and value is None)]


@dataclass
class Profile:
    n: int
    # (특징, 값) → (표본 수, 채택 수, 기여도)
    stats: dict

    def score(self, item) -> tuple[float, list[tuple]]:
        parts = []
        for name, value in _features(item):
            n, _, contribution = self.stats.get((name, value), (0, 0, 0.0))
            parts.append((name, value, contribution, n))
        return sum(part[2] for part in parts), parts

    def table(self) -> list[dict]:
        rows = [
            {"feature": name, "value": value, "n": n, "adopted": adopted, "contribution": contribution}
            for (name, value), (n, adopted, contribution) in self.stats.items()
        ]
        return sorted(rows, key=lambda row: (FEATURES.index(row["feature"]), str(row["value"])))


def fit(rows) -> Profile:
    """각 특징값에서 전체와 같은 방식으로 성공·실패에 하나씩 더해 로그 오즈를 비교한다."""
    counts, successes = Counter(), Counter()
    total = adopted = 0
    for row in rows:
        features = _features(row)
        target = row.get("adopted")
        if target not in (0, 1):
            raise ValueError("adopted: 방송 채택 여부는 0 또는 1이어야 한다")
        total += 1
        adopted += target
        for key in features:
            counts[key] += 1
            successes[key] += target

    base = math.log((adopted + 1) / (total - adopted + 1))
    stats = {}
    for key, n in counts.items():
        k = successes[key]
        stats[key] = n, k, math.log((k + 1) / (n - k + 1)) - base
    return Profile(total, stats)
