"""소재 후보 수집(research.collect)의 요청 간격 시험. 네트워크 없이 가짜 받기 함수만 쓴다. 피드 주소와 제목은 지어낸 것이다."""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.pulse import snapshot  # noqa: E402
from ozl.research import collect  # noqa: E402

NOW = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)
GAP = 0.05


def feed(fid: str, host: str) -> dict:
    return {"id": fid, "outlet": host, "url": f"https://{host}/rss/{fid}.xml", "tier": "T3", "lang": "ko", "kind": "news"}


def test_collect_uses_host_lanes_and_gap(monkeypatch, tmp_path):
    """한 호스트에 피드 9개가 몰려도 그 호스트에는 한 번에 한 요청만, 앞 응답이 끝난 뒤 HOST_GAP 을 두고 보낸다
    (매시 수집의 pulse.snapshot.fetch_all 과 같은 줄). 서로 다른 호스트는 기다리지 않는다."""
    feeds = [feed(f"big{i}", "big.example") for i in range(9)] + [feed("x1", "x.example"), feed("y1", "y.example")]
    feeds.insert(3, feed("z1", "z.example"))
    lock = threading.Lock()
    inflight: dict[str, int] = {}
    worst: dict[str, int] = {}
    spans: dict[str, list] = {}

    def fake_fetch(f, now):
        h = snapshot.host_of(f["url"])
        with lock:
            inflight[h] = inflight.get(h, 0) + 1
            worst[h] = max(worst.get(h, 0), inflight[h])
        t0 = time.monotonic()
        time.sleep(0.02)
        t1 = time.monotonic()
        with lock:
            inflight[h] -= 1
            spans.setdefault(h, []).append((t0, t1, f["id"]))
        return [], {"id": f["id"], "outlet": f["outlet"], "http": 200, "entries": 0, "error": None}

    monkeypatch.setattr(collect, "load_config", lambda: {"feeds": feeds, "channels": []})
    monkeypatch.setattr(collect, "fetch_feed", fake_fetch)
    monkeypatch.setattr(collect, "fetch_uploads", lambda cfg, now: ([], []))
    monkeypatch.setattr(collect, "DESK", tmp_path)
    monkeypatch.setattr(collect.ledger, "allowed", lambda fid, use: True)
    monkeypatch.setattr(collect.ledger, "scorable", lambda *a, **k: (lambda it: True))
    monkeypatch.setattr(collect.coverage, "load_catalog", lambda: [])
    monkeypatch.setattr(snapshot, "HOST_GAP", GAP)

    out = collect.collect("am", date="2026-11-15", now=NOW)
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert [f["id"] for f in data["feeds"]] == [f["id"] for f in feeds]          # 상태는 피드 목록 순서 그대로, 피드마다 한 번
    assert sum(len(v) for v in spans.values()) == len(feeds)
    assert worst["big.example"] == 1                                              # 같은 호스트에 동시에 둘 이상 보내지 않는다
    big = sorted(spans["big.example"])
    assert [s[2] for s in big] == [f"big{i}" for i in range(9)]                   # 줄 안에서는 목록 순서대로
    assert all(b[0] - a[1] >= GAP - 0.005 for a, b in zip(big, big[1:]))          # 앞 응답이 끝난 뒤부터 간격
    others = min(spans[h][0][0] for h in ("x.example", "y.example", "z.example"))
    assert others < big[1][0]                                                     # 다른 호스트는 큰 호스트의 줄을 기다리지 않는다


# ── 급상승어의 딸린 기사 제목 전부 읽기(2026-11-15). 본문은 지어낸 것이다.
TREND_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.example/rss" version="2.0"><channel><title>가상 급상승</title>
<item><title>가람시 정전</title><ht:approx_traffic>2000+</ht:approx_traffic><link>https://trends.example/rss?geo=KR</link>
<pubDate>Sun, 15 Nov 2026 02:00:00 +0000</pubDate>
<ht:news_item><ht:news_item_title>가람시 대규모 정전…&amp;quot;복구 중&amp;quot;</ht:news_item_title><ht:news_item_url>https://a.example/1</ht:news_item_url></ht:news_item>
<ht:news_item><ht:news_item_title><![CDATA[한빛전력 "가람시 정전 원인 조사"]]></ht:news_item_title></ht:news_item>
<ht:news_item><ht:news_item_title>가람시 정전 3시간 만에 복구</ht:news_item_title></ht:news_item>
</item>
<item><title>김하람</title><ht:approx_traffic>500+</ht:approx_traffic><pubDate>Sun, 15 Nov 2026 02:10:00 +0000</pubDate>
<ht:news_item><ht:news_item_title>김하람 새 음반 발표</ht:news_item_title></ht:news_item></item>
<item><title>한빛전자 신공장</title><ht:approx_traffic>100+</ht:approx_traffic><pubDate>Sun, 15 Nov 2026 02:20:00 +0000</pubDate></item>
</channel></rss>""".encode("utf-8")
TREND_FEED = {"id": "tr", "outlet": "가상트렌드", "url": "https://trends.example/rss?geo=KR", "tier": "T5", "lang": "ko",
              "kind": "trend"}


class _Resp:
    status_code = 200

    def __init__(self, content):
        self.content = content


def _fetch_trend(monkeypatch, content=TREND_XML, feed_def=TREND_FEED):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _Resp(content)
    monkeypatch.setattr(collect.requests, "get", fake_get)
    items, st = collect.fetch_feed(feed_def, NOW)
    return {i["title"]: i for i in items}, st, calls


def test_trend_feed_keeps_every_news_title_without_extra_requests(monkeypatch):
    """feedparser 는 딸린 기사 제목을 마지막 하나만 남긴다. 이미 받은 본문에서 전부 읽어 trend_news_all 에 담는다(요청은 한 번)."""
    by, st, calls = _fetch_trend(monkeypatch)
    assert calls == [TREND_FEED["url"]] and st["error"] is None and st["entries"] == 3
    a = by["가람시 정전"]
    assert a["trend_news_all"] == ['가람시 대규모 정전…"복구 중"', '한빛전력 "가람시 정전 원인 조사"', "가람시 정전 3시간 만에 복구"]
    assert a["trend_news"] == "가람시 정전 3시간 만에 복구" and a["traffic"] == "2000+"     # 옛 칸은 그대로(마지막 하나)
    assert by["김하람"]["trend_news_all"] == ["김하람 새 음반 발표"]
    assert "trend_news_all" not in by["한빛전자 신공장"] and by["한빛전자 신공장"]["trend_news"] == ""   # 딸린 기사 없음


def test_trend_news_titles_are_capped_and_deduplicated():
    body = "".join(f"<ht:news_item><ht:news_item_title>가상 제목 {i % 7}</ht:news_item_title></ht:news_item>" for i in range(14))
    xml = f"<rss><channel><item><title>가람시  정전</title>{body}</item></channel></rss>".encode("utf-8")
    got = collect.trend_news_titles(xml)
    assert got == {"가람시정전": [f"가상 제목 {i}" for i in range(collect.TREND_NEWS_MAX)]}
    assert collect.trend_news_titles(b"") == {} and collect.trend_news_titles(b"<rss>broken") == {}
    assert collect.trend_news_titles(b"x" * (collect.TREND_FEED_MAX_BYTES + 1)) == {}


def test_trend_feed_falls_back_to_one_title_when_reading_all_fails(monkeypatch):
    """본문을 다시 읽다 오류가 나면 지금처럼 trend_news 하나만 담고 수집은 이어진다."""
    class Boom:
        def finditer(self, doc):
            raise RuntimeError("지어낸 오류")
    monkeypatch.setattr(collect, "_T_ITEM", Boom())
    assert collect.trend_news_titles(TREND_XML) == {}
    by, st, _ = _fetch_trend(monkeypatch)
    assert st["error"] is None and st["entries"] == 3
    assert by["가람시 정전"]["trend_news"] == "가람시 정전 3시간 만에 복구" and "trend_news_all" not in by["가람시 정전"]


def test_news_feed_is_not_read_twice(monkeypatch):
    """딸린 기사 제목은 급상승어 피드에서만 다시 읽는다. 언론 피드의 항목에는 칸이 생기지 않는다."""
    seen = []
    monkeypatch.setattr(collect, "trend_news_titles", lambda content: seen.append(1) or {})
    by, st, _ = _fetch_trend(monkeypatch, feed_def={**TREND_FEED, "id": "nw", "kind": "news"})
    assert seen == [] and st["entries"] == 3 and all("trend_news_all" not in i and "trend_news" not in i for i in by.values())


def test_pulse_store_keeps_trend_news_all(tmp_path, monkeypatch):
    """수집 DB 의 extra 에 목록 그대로 들어가고, 창 읽기에서 목록으로 나온다. 옛 화면이 쓰는 trend_news 는 그대로다."""
    from ozl.pulse import store
    by, _, _ = _fetch_trend(monkeypatch)
    con = store.connect(tmp_path / "p.db")
    assert store.add_items(con, list(by.values()), NOW) == 3
    con.commit()
    extra = json.loads(con.execute("SELECT extra FROM items WHERE title='가람시 정전'").fetchone()[0])
    assert extra["trend_news_all"] == by["가람시 정전"]["trend_news_all"] and extra["trend_news"] == "가람시 정전 3시간 만에 복구"
    win = {i["title"]: i for i in store.window_items(con, NOW, 24)}
    assert win["가람시 정전"]["trend_news_all"][0].startswith("가람시 대규모 정전") and win["김하람"]["trend_news"] == "김하람 새 음반 발표"


def test_broken_feed_body_is_read_in_linear_time():
    """닫히지 않은 요소가 많은 본문에서도 한 번 훑고 끝난다(전에는 시간이 제곱으로 늘어 수집이 멈출 수 있었다)."""
    import time
    for body in (b"<item>" * 300_000, b"<item><title>x</title>" + b"<ht:news_item_title>" * 200_000,
                 (b"<item><title>k</title><ht:news_item_title>a</ht:news_item_title></item>" * 5000) + b"<item>" * 100_000):
        start = time.perf_counter()
        got = collect.trend_news_titles(body)
        assert time.perf_counter() - start < 2.0
        assert got in ({}, {"k": ["a"]})
