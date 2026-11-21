"""예측, 사건, 판정, 주간 지표와 원문을 보존하는 장부."""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from .catalog import ROOT
from .db import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions(prediction_id TEXT PRIMARY KEY,
  broadcast_date TEXT NOT NULL,
  broadcast_at TEXT,
  kind TEXT NOT NULL CHECK(kind IN ('official','retro')),
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE, fixed_at TEXT NOT NULL, registered_at TEXT NOT NULL,
  revises TEXT, schema TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prediction_items(prediction_id TEXT NOT NULL, set_name TEXT NOT NULL CHECK(set_name IN ('pick','A','B')),
  rank INTEGER NOT NULL, story_key TEXT NOT NULL, label TEXT, category TEXT, confident INTEGER NOT NULL DEFAULT 0,
  overlap TEXT, member_ids TEXT NOT NULL, top_id TEXT, engine_rank INTEGER, title TEXT,
  PRIMARY KEY(prediction_id, set_name, story_key));
CREATE TABLE IF NOT EXISTS ledger_files(sha256 TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT, json TEXT NOT NULL, saved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS broadcast_events(prediction_id TEXT NOT NULL, event_set TEXT NOT NULL, event_id TEXT NOT NULL, video_id TEXT,
  official INTEGER NOT NULL,
  minor INTEGER NOT NULL,
  start TEXT, end TEXT, minutes REAL, label TEXT NOT NULL, summary TEXT NOT NULL, trigger TEXT,
  key_entities TEXT NOT NULL, key_numbers TEXT NOT NULL, timing TEXT NOT NULL CHECK(timing IN ('시사','중간','상시')),
  source_kind TEXT NOT NULL, source_sha256 TEXT NOT NULL, segs TEXT, fixed_at TEXT NOT NULL,
  PRIMARY KEY(prediction_id, event_set, event_id));
CREATE TABLE IF NOT EXISTS judge_masks(prediction_id TEXT NOT NULL, event_set TEXT NOT NULL, cand_id TEXT NOT NULL, story_key TEXT NOT NULL,
  PRIMARY KEY(prediction_id, event_set, cand_id), UNIQUE(prediction_id, event_set, story_key));
CREATE TABLE IF NOT EXISTS hit_judgments(prediction_id TEXT NOT NULL, event_set TEXT NOT NULL, story_key TEXT NOT NULL,
  judge TEXT NOT NULL CHECK(judge IN ('codex','gemini','chatgpt','final')),
  grade TEXT NOT NULL CHECK(grade IN ('full','adjacent','none','pending')), event_id TEXT, reason TEXT,
  by_rule TEXT,
  source_sha256 TEXT, judged_at TEXT NOT NULL, PRIMARY KEY(prediction_id, event_set, story_key, judge));
CREATE TABLE IF NOT EXISTS weekly_metrics(prediction_id TEXT NOT NULL, event_set TEXT NOT NULL, set_name TEXT NOT NULL,
  kind TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('확정','속보')), broadcast_date TEXT NOT NULL,
  events_n INTEGER NOT NULL, full_hits INTEGER NOT NULL, adjacent_hits INTEGER NOT NULL, weighted_hits REAL NOT NULL,
  recall_full REAL, recall_weighted REAL,
  confident_n INTEGER, confident_full INTEGER, confident_weighted REAL, confident_precision REAL,
  by_timing TEXT NOT NULL, matched TEXT NOT NULL, weekday TEXT NOT NULL, vs_baselines TEXT, judging TEXT NOT NULL,
  computed_at TEXT NOT NULL, PRIMARY KEY(prediction_id, event_set, set_name));
"""


def ensure(con):
    for statement in SCHEMA.split(";"):
        if statement.strip():
            con.execute(statement)


@contextmanager
def write(con):
    """검사와 갱신을 같은 쓰기 거래에서 실행한다."""
    with con:
        con.execute("BEGIN IMMEDIATE")
        yield


def dumps(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def path_name(path):
    resolved = Path(path).resolve()
    return str(resolved.relative_to(ROOT) if resolved.is_relative_to(ROOT) else resolved)


def save(con, kind, raw_text, path=None):
    digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    con.execute("INSERT OR IGNORE INTO ledger_files VALUES(?,?,?,?,?)",
                (digest, kind, str(path) if path is not None else None, raw_text, now()))
    return digest
