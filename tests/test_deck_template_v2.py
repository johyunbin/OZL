"""지어낸 사양과 임시 폴더의 카드만으로 두 템플릿과 비교표를 대조한다."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pptx import Presentation

import test_deck_editions as editions
import test_deck_style as old
from test_deck_editions import arts  # noqa: F401
from test_deck_style import png  # noqa: F401
from test_deck_template_v1 import deck
from test_deck_visuals import CARD, desk  # noqa: F401
from ozl.render import design_v2 as v2, spec, style, template


def page(stage="전개", **fields):
    return {"kind": "image_text", "stage": stage, "title": "종이 마을의 아침", "picture": "p",
            "body": ["골목에 햇빛이 든다"], "seconds": 25, **fields}


def design(slides):
    return {"template": "v2", "style": "syuka", "minutes": len(slides) * 25 / 60, "slides": slides}


def result(sp, card=None):
    _, warns, metrics = v2.template_v2_check(sp, card=card)
    rows = v2.compare_rows(sp, card=card)
    flags = [w.split(" · ")[0].split(":")[0] for w in warns if w.startswith("W-")]
    assert sum(r["verdict"] == "다름(경고)" for r in rows if r["item"] != "v1 경고") == len(flags)
    return flags, metrics, {r["item"]: r for r in rows}


@pytest.mark.parametrize("minutes,n,v1_fail,v2_fail,warn", [
    (40, 80, True, False, False), (30, 80, False, False, True),
    (40, 60, True, True, True), (15, 33, False, False, False),
])
def test_count_accepts_union_and_warns_only_for_v2(minutes, n, v1_fail, v2_fail, warn):
    sp = deck(n)
    sp["minutes"] = minutes
    for sl in sp["slides"]:
        sl.update(stage="전개", seconds=minutes * 60 / n)
    sp["slides"][0].update(kind="photo_caption", stage="여는 장")
    sp["slides"][-1]["stage"] = "닫는 장"
    sp["slides"][1]["side"] = "right"
    errors1, warns1, metrics1 = style.template_v1_check(sp)
    errors2, warns2, metrics2 = v2.template_v2_check({**sp, "template": "v2"})
    assert bool(errors1) == v1_fail and bool(errors2) == v2_fail
    assert metrics2[:len(metrics1)] == metrics1 and warns2[:len(warns1)] == warns1
    assert bool(warns2) == warn
    if warn:
        assert "W-장수" in warns2[0]


@pytest.mark.parametrize("minutes,expected,reason", [
    (.1, 1, "직선"), (15, 33, "직선"), (20, 48, "[20,25)"), (25, 58, "[25,30)"),
    (30, 66, "[30,35)"), (35, 71, "[35,∞)"), (40, 81, "26편 장당 초 29.68초"),
])
def test_duration_bins(minutes, expected, reason):
    target, basis = v2.v2_expected(minutes)
    assert target == expected and reason in basis


@pytest.mark.parametrize("bad", [None, True, -3, "짧게", float("nan"), sys.float_info.max, 10**400])
def test_invalid_duration_leaves_metrics_available(bad):
    sp = {**deck(), "minutes": bad}
    errors, _, metrics = v2.template_v2_check(sp)
    assert any("minutes" in e for e in errors)
    assert any("기대 장수 미정" in line for line in metrics)


@pytest.mark.parametrize("mode", ["기본", "오른쪽", "번역", "초안"])
def test_v1_accepted_spec_still_passes_v2(png, mode):
    draft = mode == "초안"
    sp = old.syuka(template="v1", minutes=4)
    if not draft:
        sp["pictures"] = [old.entry(png)]
    for sl in sp["slides"]:
        sl["seconds"] = 24
        if not draft and sl.pop("image", None):
            sl["picture"] = "p1"
    if mode == "오른쪽":
        sp["slides"][0]["side"] = "right"
    if mode == "번역":
        sp["slides"][0].update(kind="quote_translation", en="Paper village", ko="종이 마을")
    r1 = old.run(sp, draft=draft)
    assert r1.ok, r1.errors
    r2 = old.run({**sp, "template": "v2"}, draft=draft)
    assert r2.ok, r2.errors
    assert r2.metrics[:len(r1.metrics)] == r1.metrics


def test_v2_style_message_and_average():
    sp = old.syuka(template="v2", minutes=6)
    del sp["style"]
    assert "template: v2 에는 style: syuka 가 필요하다" in old.run(sp).errors
    for sl, sec in zip(sp["slides"], [37.1] * 5 + [38.7] * 5, strict=True):
        sl["seconds"] = sec
    assert any("장당 평균" in e for e in style.style_check(sp)[0])


@pytest.mark.parametrize("source,expected", [
    ("직접 그린 도표", "chart"), ("직접 그린 지도", "map"), ("원문 화면 갈무리", "article"),
    ("보도자료 첨부(유형 표시 없음)", "article"), ("기업 뉴스룸", "article"), ("무료 스톡 인물 사진", "person"),
    ("통신사·언론사 사진", "photo"), ("방송 화면 캡처", "photo"), ("로고", "logo"), ("AI 개념도", "drawing"),
    ("실존 인물 AI 그림", "drawing"), ("사실처럼 보이는 AI 장면", "drawing"), ("밈", "meme"), ("화제 그림", "meme"),
    ("공공누리 2유형", "unknown"), ("CC BY", "unknown"), ("비상업(NC) 라이선스 그림", "unknown"),
])
def test_picture_ledger_map(source, expected):
    assert v2.picture_kind(page(), {"p": {"kind": source}}) == expected


def test_first_real_slot_partial_and_chart_precedence():
    pics = {"p": {"kind": "로고"}}
    sl = page(kind="image_pair", pair=[{"image": {"what": "구름"}}, {"picture": "p"}])
    assert v2.picture_kind(sl, pics) == "logo"
    sl["pair"][0] = {"capture": "구름"}
    assert v2.picture_kind(sl, pics) == "article"
    sl["pair"] = [{}, {"chart": {"title": "구름"}}]
    assert v2.picture_kind(sl, pics) == "chart"
    assert "그림 두 자리 중 하나" in result(design([sl]))[2]["전개 장 모양"]["deck"]
    assert v2.picture_kind(page(kind="compare_table"), {}) == "table"
    assert v2.picture_kind(page(kind="compare_table", chart={"title": "구름"}), {}) == "chart"
    assert v2.picture_kind({"image": {"what": "구름"}}, {}) == "unknown"
    assert v2.picture_kind({}, {}) == "none"
    assert v2.picture_kind(page(chart={}), pics) == "logo"


def test_red_lines_wrap_and_do_not_count_highlighted_words():
    sl = page(body=[{"text": "강둑에 하얀 꽃이 피었다 " * 8, "red": True}, "꽃"], emphasis=["꽃"])
    red, lines = v2.red_lines(sl)
    assert red > 1 and red + 1 == lines == style.body_lines(sl)
    assert v2.red_lines(page(kind="quote_translation", en="Paper moon", ko="종이 달", body=[])) == (1, 2)


def test_data_chart_threshold_and_excluded_ads():
    data = page("근거 수치")
    sp = design([data, data, page("광고", chart={"title": "구름"})])
    assert "W-근거 수치 도표" not in result(sp)[0]
    sp["slides"].append(data)
    assert "W-근거 수치 도표" in result(sp)[0]
    sp["slides"][0] = page("근거 수치", kind="compare_table")
    flags, _, rows = result(sp)
    assert "W-근거 수치 도표" not in flags and "1/3장" in rows["근거 수치 도표"]["deck"]


def test_open_close_and_labeler_ranges():
    sp = design([page("광고"), page("우회 도입"), page("반전"), page("시사점"), page("광고")])
    flags, metrics, rows = result(sp)
    assert {"W-여는 장", "W-닫는 장"} <= set(flags)
    for k in ("반전 단계 장 비율", "한국 연결 위치", "유머 장 수"):
        assert rows[k]["verdict"] == "범위만" and all(k not in w for w in flags)
    assert "33.3%" in rows["반전 단계 장 비율"]["deck"] and "11~18%" in metrics[-1]
    assert "재지 않음" in rows["한국 연결 위치"]["deck"]
    sp["slides"][1]["stage"], sp["slides"][3]["stage"] = "여는 장", "닫는 장"
    assert not {"W-여는 장", "W-닫는 장"} & set(result(sp)[0])


@pytest.mark.parametrize("red,total,warning", [(0, 19, False), (0, 20, True), (3, 20, False), (9, 20, True)])
def test_overall_red_minimum_and_range(red, total, warning):
    body = [{"text": "종이 달", "red": i < red} for i in range(total)]
    flags, _, _ = result(design([page(body=body)]))
    assert ("W-빨강 전체" in flags) == warning


def test_stage_red_compares_pooled_lines_and_excludes_ends():
    red = {"text": "종이 꽃", "red": True}
    slides = [page("여는 장", body=[red] * 5), page("근거 수치", body=[red] * 2),
              page("해법", body=[red] * 3), page(body=["구름"] * 4), page("닫는 장", body=["구름"])]
    assert "W-빨강 단계" not in result(design(slides))[0]
    slides[3]["body"].append("구름")
    assert "W-빨강 단계" in result(design(slides))[0]
    slides[3]["body"] = [red] * 5
    assert "W-빨강 단계" not in result(design(slides))[0]


def test_skeleton_warning_by_stage_and_run_order():
    slides = [page(s) for s in ("여는 장", "근거 수치", "전개", "반전", "비교", "전개", "닫는 장")]
    card = {"category": "국내 경제·정책"}
    flags, metrics, rows = result(design(slides), card)
    assert flags.count("W-뼈대") == 1 and rows["국내 뼈대 · 해법"]["verdict"] == "다름(경고)"
    assert "전개(42.9%) → 반전(57.1%) → 비교(71.4%) → 전개(85.7%)" in metrics[-2]
    slides.insert(-1, page("해법"))
    assert "W-뼈대" not in result(design(slides), card)[0]
    for category in ("기타", "분류 밖", None):
        flags, metrics, _ = result(design(slides), {"category": category})
        assert "W-뼈대" not in flags and "갈래 없음" in metrics[-2]


def test_data_before_background_relaxed_only_for_market_v2():
    sp = design([page(s) for s in ("여는 장", "근거 수치", "배경", "닫는 장")])
    def order_errors(version, card):
        report = spec.check({**sp, "template": version}, {}, old.TEMPLATE, card=card, draft=True)
        return [e for e in report.errors if "템플릿 순서" in e]

    market = {"category": "금융·증시"}
    assert not order_errors("v2", market)
    assert order_errors("v1", market) and order_errors("v2", None)


def test_cli_checks_an_unchanged_yaml_and_writes_an_exclusive_table(tmp_path):
    # 별도 프로세스에서도 카드 정본을 임시 폴더로 돌린다.
    (tmp_path / "sitecustomize.py").write_text(
        "from pathlib import Path\nfrom ozl.research import cards\ncards.CARDS = Path(__file__).parent\n")
    (tmp_path / f"{CARD}.yaml").write_text(yaml.safe_dump({"card_id": CARD, "category": "사회·문화"}))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tmp_path), str(Path(old.__file__).resolve().parents[1] / "src")]))
    sp = old.syuka(template="옛판", minutes=4)
    for sl in sp["slides"]:
        sl["seconds"] = 24
    path, table = tmp_path / "사양.yaml", tmp_path / "표.md"
    path.write_text(yaml.safe_dump(sp, allow_unicode=True))
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    cmd = [sys.executable, "-m", "ozl.render.design_v2", str(path), "--claims-dir", str(tmp_path),
           "--claims-dir", str(tmp_path / "대기"), "--draft", "--table", str(table)]
    first = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    assert first.stdout.startswith("[v2] 사양의 template '옛판' 을 v2 로 보고 검사한다(파일은 그대로)\n")
    assert "[check] 통과" in first.stdout and "[v2] 범위로만:" in first.stdout
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    md = table.read_text()
    assert "| 항목 | 원본 | 이 덱 | 판단 |" in md and "국내 뼈대" in md
    second = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert second.returncode == 1 and "덮어쓰지 않는다" in second.stdout and table.read_text() == md
    (tmp_path / f"{CARD}.yaml").unlink()
    missing = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert missing.returncode == 1 and "카드" in missing.stdout and "가 없다" in missing.stdout


def test_outline_cli():
    ran = subprocess.run([sys.executable, "-m", "ozl.render", "outline", "--minutes", "40", "--template", "v2"],
                         capture_output=True, text=True)
    assert ran.returncode == 0 and "목표 장수 81장" in ran.stdout and "29.68초" in ran.stdout


def test_hand_template_cli_notes_and_order(tmp_path):
    sp = template.template_spec("v2")
    def no_stage(slides):   # v2 는 장의 단계를 노트가 설명하는 단계로 바꾼다. 나머지 칸은 v1 과 같다
        return [{k: v for k, v in sl.items() if k != "stage"} for sl in slides]
    assert no_stage(sp["slides"][:3] + sp["slides"][4:]) == no_stage(template.template_spec("v1")["slides"])
    assert [sl["stage"] for sl in sp["slides"]][:2] == ["여는 장", "여는 장"] and sp["slides"][4]["stage"] == sp["slides"][6]["stage"] == "근거 수치"
    assert all("분량:" in note for _, note in template.SLIDES_V2)
    assert sp["slides"][2]["body"] is not sp["slides"][3]["body"]
    assert not template.problems(sp)
    assert len(sp["slides"]) == 13 and sp["slides"][3]["side"] == "right"
    ran = subprocess.run([sys.executable, "-m", "ozl.render.template", "--out", str(tmp_path), "--no-export"],
                         capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    output, = tmp_path.glob("손템플릿_v2_*.pptx")
    slides = Presentation(output).slides
    assert len(slides) == 13
    notes = [slide.notes_slide.notes_text_frame.text for slide in slides]
    assert all("원본 장 모양" in note and "뒤 49.6%" in note and "시장·기업:" in note for note in notes)
    assert "그림 없는" in notes[0] and "51.5%" in notes[-1]
    assert "우 그림 + 좌 글" in notes[3] and "도표 54.5%" in notes[4]

def test_unmeasurable_table_is_reported_not_raised():
    sp = old.syuka(template="v2", minutes=4)
    sp["slides"][2].update(kind="compare_table", table={"header": ["항목"], "rows": [["달"]], "widths": [0]})
    assert any("widths" in e for e in old.run(sp).errors)


def test_cli_table_is_scoped_to_each_strict_edition(desk, arts, tmp_path, capsys):
    editions.save_records()
    sp = editions.two_spec(arts, style="syuka")
    sp.update(minutes=5, template="v1")
    # 비공개판의 보도 사진과 갈무리가 바뀌고, 밈 장은 두 판 모두에서 빠진다.
    sp["pictures"].append({"id": "p4", "kind": "밈"})
    sp["slides"].append(page("여담", kind="photo_caption", picture="p4"))
    output = tmp_path / "두판.md"
    source = editions.write(tmp_path, sp)
    assert v2.main([str(source), "--table", str(output)]) == 1  # 기존 회색 자리는 엄격 모드 실패
    stdout = capsys.readouterr().out
    assert "밈 1장" in stdout
    for name in (editions.PRIV, editions.SWAP):
        assert f"[check·{name}]" in stdout
    sections = output.read_text().split("## ")
    assert len(sections) == 3
    assert sections[1].startswith(editions.PRIV) and sections[2].startswith(editions.SWAP)
    def picture_rows(section):
        return [line for line in section.splitlines() if "그림 종류 |" in line]

    assert picture_rows(sections[1]) != picture_rows(sections[2])


def test_render_check_prints_v2_metric_tag(desk, tmp_path, capsys):
    from ozl.research import cards
    from ozl.render.__main__ import main as render_main
    cards.save_yaml(cards.card_path(CARD), {"card_id": CARD, "titles": ["가상제분 소식"]})
    sp = old.syuka(template="v2", minutes=4)
    path = tmp_path / "deck.yaml"
    path.write_text(yaml.safe_dump(sp, allow_unicode=True))
    render_main(["check", str(path)])
    lines = capsys.readouterr().out.splitlines()
    tagged = [line for line in lines if line.startswith("[v2] ")]
    assert tagged and not any(line.startswith("[v1] ") for line in lines)
    assert tagged == ["[v2] " + line for line in old.run(sp).metrics]


def _rows(sp, **kw):
    return {r["item"]: r for r in v2.compare_rows(sp, **kw)}


def test_red_lines_measured_on_rendered_copy_with_links(monkeypatch):
    sp = design([page(), page()])
    seen = []
    real = v2.red_lines

    def spy(view):
        seen.append(view)
        return real(view)

    class Plan:
        errors = []
        slides = [{"표시": 1}, {"표시": 2}]

    monkeypatch.setattr(spec, "link_plan", lambda s, c: Plan())
    monkeypatch.setattr(v2, "red_lines", spy)
    v2.template_v2_check(sp, claims={})
    assert [v[spec.LINKS_KEY] for v in seen] == Plan.slides
    seen.clear()
    v2.template_v2_check(sp)   # 기록이 없으면 링크 번호 없이 잰다
    assert all(spec.LINKS_KEY not in v for v in seen)
    assert "링크 번호 없이" in _rows(sp)["빨강 본문 줄 전체"]["deck"]


def test_unmeasurable_page_is_not_counted_as_zero_lines():
    red = {"text": "빨강 한 줄", "red": True}
    bad = {"kind": "compare_table", "stage": "전개", "title": "종이 마을 견주기", "seconds": 25,
           "table": {"header": ["가"], "rows": [["나"]], "widths": [0]}, "body": [red]}
    sp = design([page(body=[red] * 3) for _ in range(9)] + [bad])
    _, warns, metrics = v2.template_v2_check(sp)
    rows = _rows(sp)
    assert rows["빨강 본문 줄 전체"]["verdict"] == "범위만" and "10쪽 배치 실패" in rows["빨강 본문 줄 전체"]["deck"]
    assert rows["단계별 빨강 비교"]["verdict"] == "범위만"
    assert not any(w.startswith("W-빨강") for w in warns)
    assert any("배치 실패" in m for m in metrics)


def test_stage_red_uses_per_slide_mean_like_source():
    sp = design([page(body=[{"text": "빨강", "red": True}]), page(body=["검정 하나", "검정 둘", "검정 셋"])])
    row = _rows(sp)["전개 빨강 줄"]
    assert row["deck"].startswith("장별 평균 50.0%(2장)") and row["verdict"] == "다름(경고 없음)"


def test_turn_share_is_range_only_and_boundaries_are_inclusive():
    sp = design([page("여는 장"), page("반전"), page(), page(), page("닫는 장")])
    assert _rows(sp)["반전 장 비율"]["verdict"] == "범위만"
    assert v2._within(93 / 200, v2.STAGE_MIX["development"].red, v2.V2_RED_TOL)
    assert v2._within(v2.OVERALL_RED + v2.V2_RED_TOL, v2.OVERALL_RED, v2.V2_RED_TOL)


def test_constants_match_p3_rule_table():
    assert [(b.videos, b.seconds) for b in v2.DURATION_BANDS] == [
        (1, 32.05), (3, 23.49), (11, 24.81), (44, 25.67), (40, 27.43), (26, 29.68)]
    assert {k: (m.videos, m.layout_sample, m.picture_sample, m.red) for k, m in v2.STAGE_MIX.items()} == {
        "hook": (121, 102, 102, .157), "lead_in": (14, 37, 37, .211), "background": (83, 256, 256, .283),
        "data": (73, 132, 132, .215), "development": (119, 763, 762, .315), "turn": (119, 334, 334, .336),
        "comparison": (82, 295, 295, .304), "implication": (67, 133, 133, .271), "solution": (48, 113, 113, .152),
        "digression": (27, 36, 36, .223), "closing": (118, 97, 97, .265)}
    assert v2.STAGE_MIX["data"].pictures == {"chart": .545, "table": .076, "photo": .068}
    assert {b: (n, [(k, round(p, 3)) for k, _, p, _ in st]) for b, (n, st) in v2.SKELETONS.items()} == {
        "국제": (42, [("hook", .014), ("background", .082), ("development", .172), ("turn", .317),
                    ("comparison", .52), ("implication", .797), ("closing", .973)]),
        "국내": (23, [("hook", .015), ("background", .082), ("data", .13), ("development", .181), ("turn", .342),
                    ("comparison", .424), ("solution", .516), ("closing", .976)]),
        "시장·기업": (50, [("hook", .014), ("data", .096), ("background", .167), ("development", .217),
                       ("turn", .311), ("comparison", .47), ("implication", .76), ("closing", .982)])}


def test_v2_notes_keep_v1_amounts_and_default_output_folders(tmp_path, monkeypatch):
    from ozl.render import potx
    notes = dict((sl["kind"] + sl.get("side", ""), note) for sl, note in template.SLIDES_V2)
    assert "4.20×4.12in(왼쪽 0.96in" in notes["image_text"] and "(좌우 거울 자리)" in notes["image_textright"]
    assert "57초를 넘기지 않는다" in notes["image_text"] and "전체의 10%" in notes["closing"]
    assert template.OUT_V2.name == "20_템플릿v2" and template.OUT.name == "12_템플릿" and potx.OUT.name == "16_템플릿v1"
    v1_dir, v2_dir = tmp_path / "v1", tmp_path / "v2"
    monkeypatch.setattr(template, "OUT", v1_dir)
    monkeypatch.setattr(template, "OUT_V2", v2_dir)
    potx_v1 = tmp_path / "potx_v1"
    monkeypatch.setattr(potx, "OUT", potx_v1)
    template.build(export=False)
    assert list(v2_dir.glob("손템플릿_v2_*.pptx")) and not v1_dir.exists()
    potx.build(export=False, version="v1")
    assert list(potx_v1.glob("*.potx")) and not list(potx_v1.glob("*v2*")) and not v1_dir.exists()


def test_unmeasured_page_holds_its_stage_verdict_and_missing_claims_are_marked(monkeypatch):
    red = {"text": "빨강 한 줄", "red": True}
    bad = {"kind": "compare_table", "stage": "전개", "title": "종이 마을 견주기", "seconds": 25,
           "table": {"header": ["가"], "rows": [["나"]], "widths": [0]}, "body": [red, red]}
    sp = design([page(body=[red, "검정 하나", "검정 둘"]), bad])
    row = _rows(sp)["전개 빨강 줄"]
    assert row["verdict"] == "범위만" and "2쪽 배치 실패" in row["deck"]
    assert "링크 번호 없이" in _rows(sp)["빨강 본문 줄 전체"]["deck"]
    ok = design([page(claim_ids=["2026-11-21-am-01-c1"]), page()])

    class Plan:
        errors = []
        slides = [{}, {}]

    monkeypatch.setattr(spec, "link_plan", lambda s, c: Plan())
    assert "링크 번호 없이" in _rows(ok, claims={})["빨강 본문 줄 전체"]["deck"]   # 인용 기록을 찾지 못했다
    assert any("링크 번호 없이" in m for m in v2.template_v2_check(ok, claims={})[2])
    assert any("링크 번호 없이" in m for m in v2.template_v2_check(sp)[2])   # 배치 실패 분기의 지표 줄
    assert "링크 번호 없이" not in _rows(ok, claims={"2026-11-21-am-01-c1": {}})["빨강 본문 줄 전체"]["deck"]


def test_raw_sponsor_without_band_does_not_raise():
    sp = design([page(), page()])
    errors, _, _ = v2.template_v2_check(sp, sponsor={"pages": []})
    assert errors == style.template_v1_check(sp, sponsor={"pages": []})[0]


def test_other_default_output_folders(tmp_path, monkeypatch):
    from ozl.render import potx
    v1_dir, v2_dir = tmp_path / "v1", tmp_path / "v2"
    monkeypatch.setattr(template, "OUT", v1_dir)
    monkeypatch.setattr(template, "OUT_V2", v2_dir)
    potx_v1 = tmp_path / "potx_v1"
    monkeypatch.setattr(potx, "OUT", potx_v1)
    template.build(export=False, version="v1")
    assert list(v1_dir.glob("손템플릿_2*.pptx")) and not v2_dir.exists() and not potx_v1.exists()
    potx.build(export=False)
    assert list(v2_dir.glob("*v2*.potx")) and not potx_v1.exists()
