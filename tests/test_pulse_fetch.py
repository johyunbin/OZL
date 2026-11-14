"""매시 수집의 요청 간격과 피드 목록 시험. 네트워크 없이 가짜 시계와 가짜 받기 함수만 쓴다. 피드 주소와 제목은 지어낸 것이다."""
from __future__ import annotations

import pathlib
import sys
import threading
from datetime import datetime, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.pulse import snapshot  # noqa: E402

NOW = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)


class FakeClock:
    """sleep 하면 시각이 그만큼 흐르고, 받기 한 번에 0.4초가 흐른다."""

    def __init__(self):
        self.t = 100.0
        self.lock = threading.Lock()
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        with self.lock:
            self.sleeps.append(s)
            self.t += s


def feed(fid: str, host: str) -> dict:
    return {"id": fid, "outlet": host, "url": f"https://{host}/rss/{fid}.xml", "tier": "T3", "lang": "ko", "kind": "news"}


def make_fetch(fc: FakeClock, calls: list):
    def fetch(f, now):
        calls.append((f["id"], snapshot.host_of(f["url"]), fc.clock()))
        fc.t += 0.4
        return [{"title": f"지어낸 제목 {f['id']}", "feed": f["id"]}], {"id": f["id"], "outlet": f["outlet"], "http": 200, "entries": 1, "error": None}
    return fetch


def test_same_host_feeds_run_in_order_with_gap(monkeypatch):
    monkeypatch.setattr(snapshot.ledger, "allowed", lambda fid, use: True)
    fc, calls = FakeClock(), []
    feeds = [feed("a1", "news.example"), feed("a2", "news.example"), feed("a3", "news.example")]
    items, st = snapshot.fetch_all(NOW, feeds=feeds, fetch=make_fetch(fc, calls), sleep=fc.sleep, clock=fc.clock)
    assert [c[0] for c in calls] == ["a1", "a2", "a3"]
    starts = [c[2] for c in calls]
    # 앞 응답이 끝난 뒤(받기 0.4초)부터 2초 — 요청 시작 사이는 2.4초
    assert all(b - a >= snapshot.HOST_GAP + 0.4 - 1e-9 for a, b in zip(starts, starts[1:]))
    assert fc.sleeps == [snapshot.HOST_GAP, snapshot.HOST_GAP]
    assert [s["id"] for s in st] == ["a1", "a2", "a3"]
    assert len(items) == 3


def test_one_request_per_feed_and_order_kept(monkeypatch):
    monkeypatch.setattr(snapshot.ledger, "allowed", lambda fid, use: True)
    fc, calls = FakeClock(), []
    feeds = [feed("a1", "one.example"), feed("b1", "two.example"), feed("a2", "one.example"), feed("c1", "three.example")]
    _, st = snapshot.fetch_all(NOW, feeds=feeds, fetch=make_fetch(fc, calls), sleep=fc.sleep, clock=fc.clock)
    assert sorted(c[0] for c in calls) == ["a1", "a2", "b1", "c1"]   # 재시도 없음, 피드마다 한 번
    assert [s["id"] for s in st] == ["a1", "b1", "a2", "c1"]          # 상태는 피드 목록 순서 그대로
    one = [c for c in calls if c[1] == "one.example"]
    assert [c[0] for c in one] == ["a1", "a2"]
    assert len(fc.sleeps) == 1   # 간격은 같은 호스트 안에서만 생긴다


def test_different_hosts_do_not_wait(monkeypatch):
    monkeypatch.setattr(snapshot.ledger, "allowed", lambda fid, use: True)
    fc, calls = FakeClock(), []
    feeds = [feed("x", "x.example"), feed("y", "y.example"), feed("z", "z.example")]
    snapshot.fetch_all(NOW, feeds=feeds, fetch=make_fetch(fc, calls), sleep=fc.sleep, clock=fc.clock)
    assert fc.sleeps == []
    assert len(calls) == 3


def test_ledger_off_feed_is_not_queued(monkeypatch):
    """대장 collect 가 허용이 아닌 피드는 요청이 없으니 같은 호스트 줄의 간격을 만들지 않는다."""
    monkeypatch.setattr(snapshot.ledger, "allowed", lambda fid, use: fid != "off")
    fc, calls = FakeClock(), []
    feeds = [feed("off", "news.example"), feed("on", "news.example")]
    _, st = snapshot.fetch_all(NOW, feeds=feeds, fetch=make_fetch(fc, calls), sleep=fc.sleep, clock=fc.clock)
    assert fc.sleeps == []
    assert [s["id"] for s in st] == ["off", "on"]


def test_host_of():
    assert snapshot.host_of("https://RSS.Example.com/a.xml?x=1") == "rss.example.com"
    assert snapshot.host_of("") == ""


# ── 피드 목록과 대장 ─────────────────────────────────────────────────
FEEDS = yaml.safe_load((ROOT / "src/ozl/research/feeds.yaml").read_text(encoding="utf-8"))["feeds"]
LEDGER = yaml.safe_load((ROOT / "src/ozl/research/sources_ledger.yaml").read_text(encoding="utf-8"))["sources"]


def test_enabled_feeds_have_ledger_rows_with_basis_and_evidence():
    for f in FEEDS:
        if not f.get("enabled", True):
            continue
        row = LEDGER.get(f["id"])
        assert row, f["id"]
        assert row.get("basis") and row.get("evidence") and row.get("verified"), f["id"]
        if f.get("lang") == "ko" and f["kind"] in ("news", "official"):   # 켜 둔 국내 피드는 수집이 허용으로 확인된 것만
            assert row.get("collect") == "허용", f["id"]


def test_feed_ids_unique_and_same_host_count_bounded():
    ids = [f["id"] for f in FEEDS]
    assert len(ids) == len(set(ids))
    per_host: dict[str, int] = {}
    for f in FEEDS:
        if f.get("enabled", True):
            h = snapshot.host_of(f["url"])
            per_host[h] = per_host.get(h, 0) + 1
    # 한 호스트 줄이 매시 수집을 오래 붙잡지 않게(10개 × 2초 = 20초 남짓)
    assert max(per_host.values()) <= 10


def test_new_sections_map_to_categories():
    from ozl.signals import category
    secs = category.table()["sections"]
    for s in ("정치", "사회", "연예", "스포츠"):
        assert secs.get(s) == s
    assert secs.get("문화") == "연예"
    used = {f.get("section") for f in FEEDS if f.get("enabled", True) and f.get("lang") == "ko" and f["kind"] == "news"}
    assert {"정치", "사회", "연예", "스포츠"} <= used
