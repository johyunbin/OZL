"""그림 장 템플릿의 경계값과 실제 pptx의 정수 좌표. 문구와 그림은 모두 시험용이다."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

import test_deck_editions as editions
import test_deck_style as old
from test_deck_editions import arts  # noqa: F401
from test_deck_kinds import entry
from test_deck_visuals import CARD, desk  # noqa: F401
from ozl.render import build, compare, pictures, spec, style
from ozl.render.__main__ import main as render_main
from ozl.research import cards

ATTACHMENT = "보도자료 첨부(유형 표시 없음)"


def deck(n=20):
    return {"template": "v1", "style": "syuka", "minutes": n * 25 / 60,
            "slides": [{"kind": "image_text", "picture": "p1", "seconds": 25} for _ in range(n)]}


def check(sp, draft=False):
    errors, warnings, metrics = style.template_v1_check(sp, draft=draft)
    return "\n".join(errors), "\n".join(warnings), "\n".join(metrics)


def test_template_is_opt_in_and_requires_syuka():
    sp = old.syuka()
    assert old.run(sp).metrics == []
    for invalid in (None, "v3", []):
        assert "를 모른다" in old.run({**sp, "template": invalid}).errors[0]
    del sp["style"]
    sp["template"] = "v1"
    assert "template: v1 에는 style: syuka 가 필요하다" in old.run(sp).errors
    assert old.run(sp).metrics


def test_check_cli_appends_only_v1_metrics(desk, tmp_path, capsys):
    cards.save_yaml(cards.card_path(CARD), {"card_id": CARD, "titles": ["가상제분 소식"]})
    sp = old.syuka()
    path = tmp_path / "deck.yaml"
    path.write_text(yaml.safe_dump(sp, allow_unicode=True))
    assert render_main(["check", str(path)]) == 0
    assert "[v1]" not in capsys.readouterr().out
    sp.update(template="v1", minutes=4)
    path.write_text(yaml.safe_dump(sp, allow_unicode=True))
    assert render_main(["check", str(path)]) == 1  # 옛 사양의 회색 그림 자리는 완성본에 둘 수 없다.
    lines = capsys.readouterr().out.splitlines()
    expected = ["[v1] " + line for line in old.run(sp).metrics]
    assert lines[-len(expected):] == expected


def test_check_without_fcntl(desk, tmp_path):
    cards.save_yaml(cards.card_path(CARD), {"card_id": CARD})
    source = editions.write(tmp_path, old.syuka())
    script = """
import sys
sys.modules["fcntl"] = None
from pathlib import Path
from ozl.research import cards
cards.CARDS = Path(sys.argv[2])
from ozl.render.__main__ import main
sys.exit(main(["check", sys.argv[1]]))
"""
    result = subprocess.run([sys.executable, "-c", script, str(source), str(cards.CARDS)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "[check] 통과" in result.stdout and "fcntl" not in result.stderr


def test_check_reads_claim_ids_mapping_keys(desk, tmp_path, capsys):
    editions.save_records()
    sp = old.syuka()
    sp["slides"][0]["claim_ids"] = {editions.GOV: None}
    source = editions.write(tmp_path, sp)
    assert render_main(["check", str(source)]) == 0, capsys.readouterr().out


def test_build_without_fcntl_warns_once(desk, arts, tmp_path, monkeypatch, capsys):
    editions.save_records()
    source = editions.write(tmp_path, old.syuka())
    monkeypatch.setitem(sys.modules, "fcntl", None)
    output = build.build(source, export=False)
    assert Path(output["pptx"]).is_file()
    assert len([line for line in capsys.readouterr().err.splitlines() if "fcntl" in line]) == 1


@pytest.mark.parametrize("bad", [None, 0, -2, True, "몇 분", float("inf"), float("nan")])
def test_minutes_required_and_positive(bad):
    sp = deck()
    assert check(sp)[0] == ""
    if bad is None:
        del sp["minutes"]
    else:
        sp["minutes"] = bad
    assert "minutes" in check(sp)[0]


@pytest.mark.parametrize(("n", "outside"), [(16, True), (17, False), (23, False), (24, True)])
def test_count_tolerance_without_ads(n, outside):
    sp = deck(n)
    sp["minutes"] = 20 * 25 / 60
    sp["slides"].append({"kind": "photo_caption", "seconds": 25, "stage": "광고"})
    errors, _, metrics = check(sp)
    assert ("목표 20장의 ±15%" in errors) == outside
    assert f"본편 {n}장 · 목표 20장" in metrics


@pytest.mark.parametrize(("seconds", "outside"), [(449, True), (450, False), (550, False), (551, True)])
def test_duration_includes_ads(seconds, outside):
    sp = deck()
    sp["slides"].append({"kind": "image_text", "stage": "광고", "seconds": 50})
    for sl in sp["slides"][:-1]:
        sl["seconds"] = 20
    sp["slides"][0]["seconds"] += seconds - 450
    assert ("전체 seconds 합" in check(sp)[0]) == outside


def test_picture_and_text_ratios_match_compare():
    sp = deck()
    for i in range(2):
        del sp["slides"][i]["picture"]
    sp["slides"][0]["seconds"] = 45
    errors, _, metrics = check(sp)
    assert errors == ""
    measured = compare.deck_metrics(sp)
    assert f"그림 든 장 {measured['picture_share']:.1%} · 글만 장 10.0%" in metrics
    assert f"평균 {measured['sec_mean']:.1f}초 · 중앙값 {measured['sec_median']:.1f}초" in metrics
    for layout in style.LAYOUT_SHARE:
        assert f"({measured['layout'][layout]:.1%})" in metrics.split(layout + " ")[1].split(",")[0]
    del sp["slides"][2]["picture"]
    errors = check(sp)[0]
    assert "글만 있는 장" in errors and "그림 든 장" in errors


@pytest.mark.parametrize("alternative", ["photo_caption", "image_pair"])
def test_main_layout_thresholds(alternative):
    sp = deck(29)
    ad = {"stage": "광고", "kind": alternative, "seconds": 25}
    sp["slides"].append(ad)
    assert "image_full" not in check(sp)[0]
    sp["slides"].append(dict(sp["slides"][0]))
    assert "image_full" in check(sp)[0]
    sp["slides"][0]["kind"] = alternative
    if alternative == "image_pair":
        sp["slides"][0].pop("picture")
        sp["slides"][0]["pair"] = [{"picture": "p1"}, {"picture": "p2"}]
    assert "image_full" not in check(sp)[0]

    sp = deck(39)
    sp["slides"].append({**sp["slides"][0], "stage": "광고", "side": "right"})
    assert "image_right" not in check(sp)[1]
    sp["slides"].append(dict(sp["slides"][0]))
    assert "image_right" in check(sp)[1]
    sp["slides"][0]["side"] = "right"
    assert "image_right" not in check(sp)[1]


@pytest.mark.parametrize("kind", ["image_text", "number", "closing", "image_pair"])
def test_grey_slot_in_strict_and_draft(kind):
    sp = deck()
    grey = {"image": {"what": "구름", "source": "가상제분"}}
    assert "회색 그림 자리" not in check(sp)[0] + check(sp, True)[1]
    sp["slides"][0] = {"kind": kind, "seconds": 25, **({"pair": [{"picture": "p1"}, grey]} if kind == "image_pair" else grey)}
    errors, warnings, _ = check(sp)
    assert "1쪽: 회색 그림 자리" in errors and "회색 그림 자리" not in warnings
    errors, warnings, _ = check(sp, True)
    assert "1쪽: 회색 그림 자리" in warnings and "회색 그림 자리" not in errors


@pytest.mark.parametrize("source_kind", [pictures.SCREEN, ATTACHMENT, *(f"공공누리 {n}유형" for n in range(1, 5))])
def test_evidence_counts_pages_not_slots(source_kind):
    sp = deck()
    sp["pictures"] = [{"id": "p2", "kind": source_kind}]
    sp["slides"][:2] = [
        {"kind": "image_pair", "seconds": 25, "pair": [{"capture": "가"}, {"capture": "나"}]},
        {"kind": "image_pair", "seconds": 25, "pair": [{"picture": "p2"}, {"picture": "p2"}]},
    ]
    _, warnings, metrics = check(sp)
    assert "옮겨 그린 상자 1장 · 화면 갈무리 1장" in metrics and "화면 갈무리를 먼저" not in warnings
    sp["pictures"][0]["kind"] = "직접 그린 도표"
    assert "원문 화면 갈무리를 먼저 쓴다" in check(sp)[1]


def test_attachment_requires_credit_and_unchanged_private_edition(tmp_path):
    p = tmp_path / "art.png"
    Image.new("RGB", (900, 600), "white").save(p)
    e = entry(p, kind=ATTACHMENT, commercial_ok=False, modify_ok=False, license="유형 표시 없음")
    verdict, errors, _ = pictures.judge(e)
    assert verdict == pictures.PRIVATE_ONLY and not errors and pictures.edition_block(e)
    assert pictures.KIND_RULES[ATTACHMENT].credit and pictures.judge({**e, "as_is": False})[1]


def test_strict_v1_is_checked_after_splitting_editions(tmp_path):
    path = tmp_path / "cloud.png"
    Image.new("RGB", (900, 600), "white").save(path)
    sp = old.syuka(template="v1", minutes=4, pictures=[
        old.entry(path), entry(path, pid="p2", kind=ATTACHMENT, commercial_ok=False, license="유형 표시 없음"),
    ])
    for sl in sp["slides"]:
        sl["seconds"] = 24
        if sl.pop("image", None):
            sl["picture"] = "p1"
    sp["slides"][0].update(picture="p2", swap={"why": "첨부 그림을 뺀다", "set": {"picture": None}})
    private, swapped = spec.check_editions(sp, {}, old.TEMPLATE, layout_fn=build.layout_problems)
    assert private.report.ok, private.report.errors
    assert not swapped.report.ok and any("글만 있는 장 2/10장" in e for e in swapped.report.errors)
    assert private.report.metrics != swapped.report.metrics


def test_side_validation_even_without_style():
    sp = old.syuka()
    del sp["style"]
    sl = sp["slides"][0]
    for side in ("right", "left"):
        sl["side"] = side
        assert old.run(sp).ok
    for side in ("center", None, False):
        sl["side"] = side
        assert any("side 는 left 또는 right" in e for e in old.run(sp).errors)
    sl.pop("image")
    sl["side"] = "right"
    assert style.layout_of(sl) == "text_only"


# 변경 전 plan_slide가 실제 도형에 쓰던 좌표 (EMU): 왼쪽·위·폭·높이.
TITLE = (845811, 620595, 10465039, 600576)
IMAGE = (880845, 1761690, 3843687, 3763610)
BODY = (5129921, 1876800, 6180929, 4386839)
LEFT = {
    "image_text": {"그림 자리": IMAGE, "본문": BODY},
    "quote_translation": {"그림 자리": (880845, 1761690, 2377440, 1554480), "원문·번역": (3806925, 1876800, 7503925, 4386839)},
    "number": {"그림 자리": IMAGE, "큰 숫자": (5129921, 1876800, 6180929, 1143000),
               "숫자 설명": (5129921, 3111240, 6180929, 914400), "본문": (5129921, 4117080, 6180929, 2146560)},
}


@pytest.mark.parametrize("kind", LEFT)
def test_pptx_side_mirrors_exact_emu_and_preserves_old_geometry(tmp_path, kind):
    sl = {"kind": kind, "title": "봄", "body": ["봄 소식"], "image": {"what": "구름", "source": "가상제분"},
          "number": {"value": "봄", "label": "계절"}, "en": "Spring", "ko": "봄"}
    right = {**sl, "side": "right"}
    assert style.layout_of(sl) == "image_left" and style.layout_of(right) == "image_right"
    path = tmp_path / "sides.pptx"
    build.build_pptx({"slides": [sl, {**sl, "side": "left"}, right]}, {}, {}, path, appendix=False)
    prs = Presentation(path)
    for i, slide in enumerate(prs.slides):
        coords = {s.name: (s.left, s.top, s.width, s.height) for s in slide.shapes}
        assert coords["제목"] == TITLE
        for name, (x, y, w, h) in LEFT[kind].items():
            assert coords[name] == (prs.slide_width - x - w if i == 2 else x, y, w, h)


@pytest.mark.parametrize("field", ["minutes", "seconds", "integer_seconds"])
def test_duration_overflow_is_a_spec_error(field):
    sp = old.syuka(template="v1", minutes=4)
    if field == "minutes":
        sp["minutes"] = sys.float_info.max / 60
    else:
        for sl in sp["slides"][:2]:
            sl["seconds"] = 1e308 if field == "seconds" else 10**400
    report = old.run(sp)
    assert any(("minutes" if field == "minutes" else "seconds") in msg for msg in report.errors)


def test_strict_quote_translation_picture_checks_and_builds(tmp_path):
    path = tmp_path / "cloud.png"
    Image.new("RGB", (900, 600), "white").save(path)
    sp = old.syuka(template="v1", minutes=4, pictures=[old.entry(path)])
    for sl in sp["slides"]:
        sl["seconds"] = 24
        if sl.pop("image", None):
            sl["picture"] = "p1"
    sp["slides"][0].update(kind="quote_translation", side="right", en="Cloud mill", ko="구름 방앗간")
    report = old.run(sp)
    assert report.ok, report.errors
    out = tmp_path / "quote.pptx"
    build.build_pptx(sp, {}, {}, out)
    prs = Presentation(out)
    assert any(s.shape_type == MSO_SHAPE_TYPE.PICTURE and s.left > prs.slide_width / 2 for s in prs.slides[0].shapes)


def test_whole_ad_cli_reports_and_checks_total_slides(desk, tmp_path, capsys):
    from test_deck_sponsorship import LABEL, SPONSOR, sponsorship
    cards.save_yaml(cards.card_path(CARD), {"card_id": CARD})
    path = tmp_path / "art.png"
    Image.new("RGB", (900, 600), "white").save(path)
    sp = old.syuka(template="v1", minutes=4, sponsorship=sponsorship(whole=True), pictures=[old.entry(path)])
    for sl in sp["slides"]:
        sl["seconds"] = 24
        if sl.pop("image", None):
            sl["picture"] = "p1"
    for sl in (sp["slides"][0], sp["slides"][-1]):
        sl.update(title=f"{LABEL} · {SPONSOR}", spoken=LABEL)
    source = editions.write(tmp_path, sp)
    assert render_main(["check", str(source)]) == 0
    out = capsys.readouterr().out
    assert "[check] 통과 · 본편 10장" in out
    assert "[v1] 전체 10장 · 본편 10장" in out
    assert any("회차 전체가 광고" in line for line in out.splitlines() if line.startswith("[v1]"))
    assert "장수 검사를 하지 않는다" not in out
    sp["minutes"] = 5
    for sl in sp["slides"]:
        sl["seconds"] = 30
    editions.write(tmp_path, sp)
    assert render_main(["check", str(source)]) == 1
    assert "목표 12장의 ±15% 밖" in capsys.readouterr().out
    sp["slides"].insert(1, None)
    editions.write(tmp_path, sp)
    assert render_main(["check", str(source)]) == 1
    out = capsys.readouterr().out
    assert "[check] 실패 · 본편 11장" in out and "[v1] 전체 11장 · 본편 11장" in out


def test_meme_removed_from_pair_does_not_satisfy_two_picture_rule():
    sp = deck(30)
    sp["pictures"] = [{"id": "p2", "kind": "밈"}]
    sp["slides"][0] = {"kind": "image_pair", "seconds": 25, "pair": [{"picture": "p1"}, {"picture": "p2"}]}
    strict, dropped = pictures.drop_memes(sp)
    assert dropped and len(spec.slot_views(strict["slides"][0])) == 1
    errors, _, metrics = check(strict)
    assert "그림 2장(image_pair)이 한 장도 없다" in errors
    assert "image_pair 0장" in metrics


@pytest.mark.parametrize("mode", ["direct", "direct_draft", "single", "draft", "editions"])
def test_build_records_original_yaml_for_each_output(desk, arts, tmp_path, mode):
    editions.save_records()
    sp = editions.two_spec(arts) if mode == "editions" else old.syuka()
    source = editions.write(tmp_path, sp)
    source.write_bytes(source.read_bytes() + b"# source bytes\n")
    if mode.startswith("direct"):
        out = tmp_path / "direct" / "deck.pptx"
        build.build_pptx(source, {}, {}, out, pending={} if mode == "direct_draft" else None)
        folders = {None: out.parent}
    else:
        info = build.build(source, export=False, draft=mode == "draft")
        outputs = info["editions"] if mode == "editions" else {None: info}
        folders = {name: Path(one["dir"]) for name, one in outputs.items()}
    for edition, folder in folders.items():
        meta = json.loads((folder / "build_meta.json").read_text())
        assert meta["draft"] is (mode in ("draft", "direct_draft"))
        assert meta["edition"] == edition
        assert meta["spec"] == str(source.resolve())
        assert meta["spec_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert datetime.fromisoformat(meta["built_at"])
        pptx, = folder.glob("*.pptx")
        assert meta["pptx"] == pptx.name
        assert meta["pptx_sha256"] == hashlib.sha256(pptx.read_bytes()).hexdigest()

def test_legacy_average_preserves_upper_boundary():
    sp = old.syuka()
    for sl, sec in zip(sp["slides"], [37.1] * 5 + [38.7] * 5, strict=True):
        sl["seconds"] = sec
    report = old.run(sp)
    assert report.ok, report.errors
    sp["template"] = "v1"
    assert any("장당 평균" in err for err in old.run(sp).errors)


@pytest.mark.parametrize("side", ["left", "right"])
def test_chart_link_box_stays_at_lower_right(side):
    sl = {"kind": "image_text", "title": "구름 수", "body": ["하늘 관측"], "side": side,
          "chart": {"title": "구름"}, spec.LINKS_KEY: {"corner": {-1: "[1]"}}}
    plan = build.plan_slide(sl)
    image, = plan.imgs
    box, = [b for b in plan.boxes if b.name == "링크 번호"]
    assert box.left + box.width == pytest.approx(image.left + image.width)
    assert box.top == pytest.approx(image.top + image.height + 0.02)


def test_direct_build_rechecks_pptx_before_replacing_meta(tmp_path, monkeypatch):
    source = editions.write(tmp_path, old.syuka())
    out = tmp_path / "direct" / "deck.pptx"
    write_text = Path.write_text

    def swap_after_meta_staged(path, data, *args, **kwargs):
        result = write_text(path, data, *args, **kwargs)
        if '"built_at"' in data:
            out.write_bytes(b"another deck")
        return result

    monkeypatch.setattr(Path, "write_text", swap_after_meta_staged)
    with pytest.raises(ValueError, match="pptx"):
        build.build_pptx(source, {}, {}, out)
    assert not (out.parent / "build_meta.json").exists()


def test_build_rejects_pptx_changed_during_export(desk, arts, tmp_path, monkeypatch):
    editions.save_records()
    source = editions.write(tmp_path, old.syuka())

    def replace_pptx(pptx):
        pptx.write_bytes(b"another deck")
        return None, []

    monkeypatch.setattr(build.deck, "to_pdf_png", replace_pptx)
    monkeypatch.setattr(build, "MD2PDF", tmp_path / "unused")
    with pytest.raises(ValueError, match="pptx"):
        build.build(source)
    assert not list(build.DRAFTS.glob("*/build_meta.json"))


def test_dict_build_removes_stale_meta_after_previous_pptx_moved(tmp_path):
    sp = old.syuka()
    source = editions.write(tmp_path, sp)
    out = tmp_path / "direct" / "deck.pptx"
    build.build_pptx(source, {}, {}, out)
    out.rename(tmp_path / "previous.pptx")
    sp["slides"][0]["title"] = "새 방앗간"
    build.build_pptx(sp, {}, {}, out)
    assert not (out.parent / "build_meta.json").exists()
