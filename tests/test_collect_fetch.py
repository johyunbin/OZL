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
