"""비공개 자료의 기존 위치와 기록 읽기 계약. 운영 자료를 열지 않는다."""
import re

import pytest

from ozl import paths as ozlpaths


# 2026-11-21 개편 전 최상위 이름과 위치는 같았다. 운영 폴더를 나열하지 않고 검증한다.
ORIGINAL_NAMES = """
결과물 README.md pulse frames frames_dense transcripts meta audio syuka slides slides_dense
slides_label slides_label_r2 ocr dense compose compose_holdout_a compose_holdout_b style
models decks out daily briefs desk plan handoff guide research p3 pilot ops notion.json
notion_issues.json .gate_shingles.pkl archive backup
""".split()


# 2026-11-21 개편 뒤 위치(옛 이름 → 지금 자리). 이 표를 바꾸면 private/ 를 실제로 옮기고 문서도 함께 고친다.
CURRENT = {"결과물": "결과물", "README.md": "README.md", "pulse": "live/pulse", "frames": "data/raw/frames", "frames_dense": "data/raw/frames_dense", "transcripts": "data/raw/transcripts", "meta": "data/raw/meta", "audio": "audio", "syuka": "data/derived/syuka", "slides": "data/derived/slides", "slides_dense": "data/derived/slides_dense", "slides_label": "data/derived/slides_label", "slides_label_r2": "data/derived/slides_label_r2", "ocr": "data/derived/ocr", "dense": "data/derived/dense", "compose": "data/derived/compose", "compose_holdout_a": "data/derived/compose_holdout_a", "compose_holdout_b": "data/derived/compose_holdout_b", "style": "data/derived/style", "models": "data/models", "decks": "outputs/decks", "out": "outputs/out", "daily": "outputs/daily", "briefs": "outputs/briefs", "desk": "records/desk", "plan": "records/plan", "handoff": "records/handoff", "guide": "records/guide", "research": "records/research", "p3": "records/runs/p3", "pilot": "records/runs/pilot", "ops": "state/ops", "notion.json": "state/notion.json", "notion_issues.json": "state/notion_issues.json", ".gate_shingles.pkl": "state/cache/.gate_shingles.pkl", "archive": "archive", "backup": "archive/backup", "templates": "templates"}


def test_original_layout(monkeypatch):
    monkeypatch.delenv("OZL_PRIVATE", raising=False)
    assert ozlpaths.LEGACY == frozenset(ORIGINAL_NAMES)            # 옛 이름은 기록 읽기용으로 고정이다
    assert ozlpaths.LAYOUT == CURRENT
    for name, where in CURRENT.items():
        assert ozlpaths.at(name) == ozlpaths.ROOT.joinpath("private", where)
    assert ozlpaths.resolve("private/desk/issues/x/issue.yaml") == ozlpaths.ROOT / "private" / CURRENT["desk"] / "issues/x/issue.yaml"
    assert ozlpaths.resolve("private/desk/../meta/a.csv") == ozlpaths.ROOT / "private" / CURRENT["meta"] / "a.csv"


def test_override_is_read_for_each_call(monkeypatch, tmp_path):
    for base in (tmp_path / "a", tmp_path / "b"):
        monkeypatch.setenv("OZL_PRIVATE", str(base))
        assert ozlpaths.at("decks", "drafts", "example") == base / ozlpaths.LAYOUT["decks"] / "drafts/example"
    with pytest.raises(KeyError):
        ozlpaths.at("unknown")


def test_resolve_stored_paths(monkeypatch, tmp_path):
    checkout = tmp_path / "checkout"
    data = tmp_path / "data"
    monkeypatch.setattr(ozlpaths, "ROOT", checkout)
    monkeypatch.setenv("OZL_PRIVATE", str(data))
    monkeypatch.setitem(ozlpaths.LAYOUT, "desk", "records/desk")
    assert ozlpaths.resolve("private/desk/card") == data / "records/desk/card"
    assert ozlpaths.resolve("private/unknown/card") == data / "unknown/card"
    assert ozlpaths.resolve("private") == data
    assert ozlpaths.resolve("claims/card") == checkout / "claims/card"
    assert ozlpaths.resolve(checkout / "private/desk/card") == data / "records/desk/card"
    assert ozlpaths.resolve(tmp_path / "elsewhere") == tmp_path / "elsewhere"


def test_web_layout_matches_python():
    script = ozlpaths.ROOT / "apps/web/scripts/paths.mjs"
    table = re.search(r"const LAYOUT = \{\n(.*?)\n\};", script.read_text(encoding="utf-8"), re.S)
    assert table is not None
    entries = [re.fullmatch(r'\s*(\w+): "([^"]+)",', line) for line in table[1].splitlines()]
    assert entries and all(entries)
    for entry in entries:
        assert entry[2] == ozlpaths.LAYOUT[entry[1]]


def test_write_connections_refuse_read_only_uris(tmp_path, monkeypatch):
    """쓰기용 연결(pulse.store·signals.store)에 'file:…?mode=ro' 를 넘기면 폴더를 만들지 않고 멈춘다."""
    from ozl.pulse import store as pulse_store
    from ozl.signals import store as signals_store
    monkeypatch.chdir(tmp_path)
    for connect in (pulse_store.connect, signals_store.connect):
        with pytest.raises(ValueError):
            connect("file:private/pulse/pulse.db?mode=ro")
    assert not (tmp_path / "file:private").exists()
