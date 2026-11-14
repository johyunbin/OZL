"""원출처 대조의 두 값 — 지각 해시 거리와 구역 차이(local_diff), 두 상한, origin 명령과 측정 표(--survey).
상한은 실측 표(pictures.ORIGIN_SURVEY_FILE)에서 정했다: 품질 30 재압축 사본은 받고, 넓이 1% 의 뚜렷한 덧칠 사본은 거른다.
그림은 PIL 로 그린 지어낸 것이고 주소와 이름도 지어낸 것이다. 웹을 열지 않는다."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from test_deck_pictures_policy import _art, press  # noqa: E402
from ozl.render import pictures as PIC  # noqa: E402
from ozl.render.__main__ import main as render_main  # noqa: E402

URL = "https://news.example.org/photo/77"
AT = "2099-01-02T10:00:00+09:00"


@pytest.fixture
def orig(tmp_path):
    return _art(tmp_path / "orig.png")                      # 800×500


def _copy(orig: pathlib.Path, name: str, box=None, fill="black", quality=None, size=None) -> pathlib.Path:
    """가공 사본 — box 를 fill 로 덧칠하거나, 품질 quality 의 JPEG 로 다시 저장하거나, size 로 줄인다."""
    from PIL import Image, ImageDraw
    g = Image.open(orig).convert("RGB")
    if box:
        ImageDraw.Draw(g).rectangle(box, fill=fill)
    if size:
        g = g.resize(size)
    out = orig.parent / name
    g.save(out, **({"quality": quality} if quality else {}))
    return out


# 넓이 1% 덧칠(800×500 의 80×50 상자) — 초록 타원 위의 흰 상자, 흰 바탕 귀퉁이의 검은 상자
PAINT_WHITE = (360, 225, 439, 274)
PAINT_BLACK = (10, 10, 89, 59)


def _check(mine: pathlib.Path, orig: pathlib.Path, **kw) -> dict:
    oc = {"url": URL, "sha256": PIC.file_sha256(orig), "phash_distance": PIC.phash_distance(mine, orig), "local_diff": PIC.local_diff(mine, orig),
          "checked_at": AT, "original_path": str(orig)}
    oc.update(kw)
    return {k: v for k, v in oc.items() if v is not None}


def _judge(mine: pathlib.Path, oc: dict) -> list[str]:
    return PIC.judge(press(mine, origin_check=oc, sha256=PIC.file_sha256(mine)))[1]


def test_local_diff_is_zero_small_for_recompression_large_for_a_small_paint(orig):
    assert PIC.local_diff(orig, orig) == 0.0
    q30 = _copy(orig, "q30.jpg", quality=30)
    half = _copy(orig, "half.png", size=(400, 250))
    assert PIC.local_diff(q30, orig) < 10 and PIC.local_diff(half, orig) < 10
    for name, box, fill in (("w.png", PAINT_WHITE, "white"), ("b.png", PAINT_BLACK, "black")):
        painted = _copy(orig, name, box=box, fill=fill)
        assert PIC.phash_distance(painted, orig) <= PIC.PHASH_MAX       # 지각 해시 거리만으로는 통과한다 — 구역 차이를 더한 까닭
        assert PIC.local_diff(painted, orig) > PIC.LOCAL_DIFF_MAX
    assert PIC.local_diff(orig, _copy(orig, "w2.png", box=PAINT_WHITE, fill="white")) == PIC.local_diff(orig.parent / "w.png", orig)   # 순서와 무관


def test_origin_check_passes_quality_30_copy_and_fails_one_percent_paint(orig):
    """됐다고 볼 조건: 품질 30 재압축 사본은 통과, 넓이 1% 덧칠 사본은 실패."""
    q30 = _copy(orig, "q30.jpg", quality=30)
    assert _judge(q30, _check(q30, orig)) == []
    painted = _copy(orig, "painted.png", box=PAINT_WHITE, fill="white")
    why = _judge(painted, _check(painted, orig))
    assert len(why) == 1 and "구역 차이" in why[0] and f"상한 {PIC.LOCAL_DIFF_MAX:g} 를 넘는다" in why[0], why
    # 값을 작게 적어도 받은 파일(original_path)로 다시 재서 잡는다
    why = _judge(painted, _check(painted, orig, local_diff=0.0))
    assert any("구역 차이를 다시 재니" in x for x in why), why
    # 받은 파일이 없으면 적힌 값으로만 본다
    assert any("넘는다" in x for x in _judge(painted, _check(painted, orig, original_path=None)))
    assert _judge(q30, _check(q30, orig, original_path=None)) == []


def test_row_without_local_diff_is_measured_from_the_original_file(orig):
    """local_diff 칸이 없는 옛 줄: 받은 파일이 있으면 잰 값으로 판정하고, 잴 파일도 없으면 실패다."""
    q30 = _copy(orig, "q30.jpg", quality=30)
    painted = _copy(orig, "painted.png", box=PAINT_BLACK)
    assert _judge(q30, _check(q30, orig, local_diff=None)) == []
    why = _judge(painted, _check(painted, orig, local_diff=None))
    assert any("구역 차이를 재니" in x and "넘는다" in x for x in why), why
    why = _judge(q30, _check(q30, orig, local_diff=None, original_path=None))
    assert any("origin_check.local_diff" in x and "구역 차이가 없다" in x for x in why), why


@pytest.mark.parametrize("bad", ["작다", True, -1, 300])
def test_local_diff_must_be_a_number_in_range(orig, bad):
    q30 = _copy(orig, "q30.jpg", quality=30)
    assert any("origin_check.local_diff" in x for x in _judge(q30, _check(q30, orig, local_diff=bad)))


def test_ledger_text_shows_both_values(orig):
    q30 = _copy(orig, "q30.jpg", quality=30)
    e = press(q30, origin_check=_check(q30, orig))
    text = PIC._check_text(e, "origin_check")
    assert f"(상한 {PIC.PHASH_MAX})" in text and f"구역 차이 {e['origin_check']['local_diff']:g} (상한 {PIC.LOCAL_DIFF_MAX:g})" in text
    e["origin_check"].pop("local_diff")
    assert "구역 차이는 검사 때 받은 파일로 잰다" in PIC._check_text(e, "origin_check")


def test_origin_cli_prints_both_values(orig, capsys):
    import yaml
    painted = _copy(orig, "painted.png", box=PAINT_WHITE, fill="white")
    assert render_main(["origin", str(painted), str(orig), "--url", URL]) == 0
    out = capsys.readouterr().out
    block = yaml.safe_load(out)["origin_check"]
    assert block["local_diff"] == PIC.local_diff(painted, orig) and block["phash_distance"] == PIC.phash_distance(painted, orig)
    assert "넘는다" in out and "쓰지 않는다" in out and f"상한 {PIC.LOCAL_DIFF_MAX:g}" in out
    assert _judge(painted, block) != []                                # 찍힌 칸을 그대로 대장에 옮기면 검사가 거른다


def test_origin_survey_cli_prints_a_table(orig, tmp_path, capsys):
    q30 = _copy(orig, "q30.jpg", quality=30)
    painted = _copy(orig, "painted.png", box=PAINT_WHITE, fill="white")
    flipped = orig.parent / "flip.png"
    from PIL import Image
    Image.open(orig).transpose(Image.FLIP_LEFT_RIGHT).save(flipped)
    out_json = tmp_path / "survey.json"
    assert render_main(["origin", "--survey", str(orig), str(q30), str(painted), str(flipped), "--json", str(out_json)]) == 0
    out = capsys.readouterr().out
    assert "| 사본 | 크기 | 지각 해시 거리 | 구역 차이 | 판정 |" in out
    assert "| q30.jpg | 800x500 | 0 |" in out and "| 받는다 |" in out
    assert "| painted.png | 800x500 |" in out and "넘는다(구역 차이" in out and "넘는다(지각 해시 거리" in out
    d = json.loads(out_json.read_text(encoding="utf-8"))
    assert d["phash_max"] == PIC.PHASH_MAX and d["local_diff_max"] == PIC.LOCAL_DIFF_MAX
    assert [r["ok"] for r in d["rows"]] == [True, False, False]
    assert render_main(["origin", "--survey", str(orig)]) == 2
    assert render_main(["origin", "--survey", str(orig), str(tmp_path / "없음.png")]) == 1


def test_constants_match_the_survey_file():
    """상한 상수가 가리키는 실측 표가 있으면 그 수와 같아야 한다(다시 쟀으면 상수도 옮긴다). 표는 비공개 폴더에 있어 없는 환경에서는 건너뛴다."""
    p = (PIC.ROOT / PIC.ORIGIN_SURVEY_FILE).with_suffix(".json")
    if not p.is_file():
        pytest.skip("실측 표가 없는 환경")
    r = json.loads(p.read_text(encoding="utf-8"))
    assert r["phash_max"] == PIC.PHASH_MAX and r["local_diff_max"] == PIC.LOCAL_DIFF_MAX
    # 재압축과 축소 사본의 최댓값보다 크고, 뚜렷한 넓이 1% 덧칠의 최솟값보다 작다
    assert r["core_benign"]["local_diff_max"] < PIC.LOCAL_DIFF_MAX < r["clear_paint"]["1"]["local_diff_min"]
    assert r["shrink25_q30_local_diff_max"] < PIC.LOCAL_DIFF_MAX < r["crop1_local_diff_min"]
    assert r["core_benign"]["phash_max"] <= PIC.PHASH_MAX
    assert all(v["passed"] == 0 for v in r["clear_paint"].values())    # 뚜렷한 덧칠은 넓이 0.5% 부터 하나도 통과하지 않았다
    assert all(x["ok"] for x in r["real"])                             # 실제 재게시 사본은 통과했다
    assert (PIC.ROOT / PIC.ORIGIN_SURVEY_FILE).is_file()
