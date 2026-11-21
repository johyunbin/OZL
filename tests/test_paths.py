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


def test_original_layout(monkeypatch):
    monkeypatch.delenv("OZL_PRIVATE", raising=False)
    assert ozlpaths.LAYOUT == {name: name for name in ORIGINAL_NAMES}
    for name in ORIGINAL_NAMES:
        assert ozlpaths.at(name) == ozlpaths.ROOT.joinpath("private", name)


def test_override_is_read_for_each_call(monkeypatch, tmp_path):
    for base in (tmp_path / "a", tmp_path / "b"):
        monkeypatch.setenv("OZL_PRIVATE", str(base))
        assert ozlpaths.at("decks", "drafts", "example") == base / "decks/drafts/example"
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
