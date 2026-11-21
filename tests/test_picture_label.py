"""그림 종류 API 라벨 실행기 시험 — 네트워크 없이 가짜 응답으로 돈다(지어낸 자료만)."""
import io
import json
import sqlite3
import urllib.error
from contextlib import closing

import pytest
from PIL import Image

from ozl.analyze import picture_label as pl
from ozl.analyze import slide_db

FAKE_KEY = "test-not-a-real-key-123"


def make_db(tmp_path, labeled=()):
    db = tmp_path / "s.db"
    frames = tmp_path / "frames"
    with closing(sqlite3.connect(db)) as con, con:
        for stmt in slide_db.SCHEMA.split(";"):
            if stmt.strip():
                con.execute(stmt)
        for vid in ("va", "vb"):
            (frames / vid).mkdir(parents=True)
            for no in (1, 2, 3):
                Image.new("RGB", (64, 40), "white").save(frames / vid / f"s{no}.png")
                con.execute("INSERT INTO sd_slides(video_id, no, flash, layout, best_frame) VALUES (?,?,?,?,?)",
                            (vid, no, 1 if no == 3 else 0, "image_left" if no != 2 or vid == "va" else None, f"s{no}.png"))
        for vid, no, labeler, note in labeled:
            con.execute("INSERT INTO sd_picture_labels(video_id, no, labeler, primary_kind, note) VALUES (?,?,?,?,?)",
                        (vid, no, labeler, "chart", note))
    return db, frames


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_ok(primary="person", seen=None):
    def op(req, timeout=0):
        if seen is not None:
            seen.append(req)
        body = {"output": [{"type": "message", "content": [{"type": "output_text",
                 "text": json.dumps({"kinds": [primary], "primary": primary, "confidence": .9})}]}],
                "usage": {"input_tokens": 600, "output_tokens": 100}}
        return FakeResp(json.dumps(body).encode())
    return op


def test_targets_and_missing(tmp_path):
    db, _ = make_db(tmp_path, labeled=[("vb", 1, "codex-x", "s1.png")])
    with closing(sqlite3.connect(db)) as con:
        got = pl.targets(con, videos=["va", "vb"])
        assert [(t["video_id"], t["no"]) for t in got] == [("va", 1), ("va", 2), ("vb", 1)]  # 반짝 장·layout 없는 장 제외
        assert {t["video_id"] for t in pl.targets(con, missing=True)} == {"va"}  # 다른 라벨러 라벨이 있는 편은 제외
        with pytest.raises(ValueError):
            pl.targets(con, videos=["va"], missing=True)


def test_run_writes_labels_with_frame_and_skips_done(tmp_path, capsys):
    db, frames = make_db(tmp_path)
    seen = []
    with closing(sqlite3.connect(db)) as con:
        s = pl.run(con, pl.targets(con, videos=["va"]), FAKE_KEY, frames=frames, log_dir=tmp_path / "log",
                   opener=opener_ok(seen=seen), pause=0)
        rows = con.execute("SELECT no, labeler, primary_kind, kinds, note FROM sd_picture_labels ORDER BY no").fetchall()
        assert pl.targets(con, videos=["va"]) == []  # 같은 프레임으로 라벨한 장은 다시 고르지 않는다
    assert s["labeled"] == 2 and s["input_tokens"] == 1200 and s["usd_estimate"] == pytest.approx(pl.cost(pl.MODEL, 1200, 200))
    assert rows == [(1, pl.LABELER, "person", '["person"]', "s1.png"), (2, pl.LABELER, "person", '["person"]', "s2.png")]
    sent = json.loads(seen[0].data)
    assert sent["model"] == "gpt-6.1-terra" and sent["input"][0]["content"][1]["detail"] == "low"
    assert sent["store"] is False
    out = capsys.readouterr().out + "".join(p.read_text() for p in (tmp_path / "log").iterdir())
    assert FAKE_KEY not in out  # 키는 출력과 기록에 남지 않는다


def test_relabel_when_frame_changed(tmp_path):
    db, _ = make_db(tmp_path, labeled=[("va", 1, pl.LABELER, "old.png")])
    with closing(sqlite3.connect(db)) as con:
        assert (("va", 1) in {(t["video_id"], t["no"]) for t in pl.targets(con, videos=["va"])})


@pytest.mark.parametrize("code", [401, 402, 403, 429])
def test_stop_on_key_or_quota_error_sends_once(tmp_path, code):
    db, frames = make_db(tmp_path)
    calls = []

    def op(req, timeout=0):
        calls.append(1)
        raise urllib.error.HTTPError(pl.URL, code, "stop", {}, None)
    with closing(sqlite3.connect(db)) as con:
        s = pl.run(con, pl.targets(con, videos=["va"]), FAKE_KEY, frames=frames, log_dir=tmp_path / "l", opener=op, pause=0)
    assert s["stopped"] == f"OpenAI API http {code}" and s["labeled"] == 0 and len(calls) == 1


def test_usd_cap(tmp_path):
    db, frames = make_db(tmp_path)
    with closing(sqlite3.connect(db)) as con:
        s = pl.run(con, pl.targets(con, videos=["va"]), FAKE_KEY, frames=frames, log_dir=tmp_path / "l2",
                   opener=opener_ok(), pause=0, max_usd=0.0001)
        assert s["labeled"] == 0 and "상한" in s["stopped"]


def bad_opener(kinds, usage=(600, 100), calls=None):
    def op(req, timeout=0):
        if calls is not None:
            calls.append(1)
        body = {"output": [{"type": "message", "content": [{"type": "output_text",
                 "text": json.dumps({"kinds": kinds, "primary": kinds[0], "confidence": 1})}]}]}
        if usage:
            body["usage"] = {"input_tokens": usage[0], "output_tokens": usage[1]}
        return FakeResp(json.dumps(body).encode())
    return op


def test_unknown_kind_mixed_in_is_failure(tmp_path):
    """11종 밖의 값이 하나라도 섞이면 그 종류만 지우고 적지 않는다 — 실패로 센다."""
    db, frames = make_db(tmp_path)
    with closing(sqlite3.connect(db)) as con:
        s = pl.run(con, pl.targets(con, videos=["va"]), FAKE_KEY, frames=frames, log_dir=tmp_path / "l",
                   opener=bad_opener(["chart", "bogus"]), pause=0)
        assert s["failed"] == 2 and con.execute("SELECT count(*) FROM sd_picture_labels").fetchone()[0] == 0
    assert s["input_tokens"] == 1200  # 실패한 응답도 과금 토큰은 센다


def test_failed_answers_count_toward_usd_cap(tmp_path):
    """쓸 수 없는 응답이 이어져도 과금된 토큰이 상한에 들어가 멈춘다."""
    db, frames = make_db(tmp_path)
    with closing(sqlite3.connect(db)) as con, con:
        for no in range(10, 60):
            con.execute("INSERT INTO sd_slides(video_id, no, flash, layout, best_frame) VALUES ('va',?,0,'image_left','s1.png')", (no,))
    calls = []
    with closing(sqlite3.connect(db)) as con:
        s = pl.run(con, pl.targets(con, videos=["va"]), FAKE_KEY, frames=frames, log_dir=tmp_path / "l",
                   opener=bad_opener(["x"], usage=(600000, 0), calls=calls), pause=0, max_usd=0.5)
    assert "상한" in s["stopped"] and len(calls) == 1


def test_missing_usage_uses_estimate(tmp_path):
    db, frames = make_db(tmp_path)
    with closing(sqlite3.connect(db)) as con:
        s = pl.run(con, pl.targets(con, videos=["va"]), FAKE_KEY, frames=frames, log_dir=tmp_path / "l",
                   opener=bad_opener(["bogus"], usage=None), pause=0)
    assert s["input_tokens"] == 2 * pl.EST_TOKENS[0]


def test_unexpected_answer_shape_closes_log(tmp_path):
    db, frames = make_db(tmp_path)

    def weird(req, timeout=0):
        return FakeResp(b"[1, 2]")
    with closing(sqlite3.connect(db)) as con:
        s = pl.run(con, pl.targets(con, videos=["va"]), FAKE_KEY, frames=frames, log_dir=tmp_path / "l", opener=weird, pause=0)
    assert s["failed"] == 2
    lines = (next((tmp_path / "l").iterdir())).read_text().splitlines()
    assert json.loads(lines[-1])["summary"]["failed"] == 2


def test_load_key_env_first(tmp_path, monkeypatch):
    f = tmp_path / "k.json"
    f.write_text(json.dumps({"api_key": "from-file"}))
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert pl.load_key(f) == "from-env"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert pl.load_key(f) == "from-file"
    with pytest.raises(pl.Stop) as e:
        pl.load_key(tmp_path / "absent.json")
    assert "absent.json" in str(e.value) and str(tmp_path) not in str(e.value)


def test_dry_run_does_not_need_key(tmp_path, monkeypatch, capsys):
    db, _ = make_db(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert pl.main(["run", "--videos", "va", "--dry-run", "--db", str(db), "--key-file", str(tmp_path / "none.json")]) == 0
    assert "대상 2장" in capsys.readouterr().out
