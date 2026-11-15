"""/syuka deck 의 도우미(.claude/skills/syuka/deck/bundle_guard.py) 시험.

검토 묶음은 다른 모델 계열로 나가는 글이다. 지난 방송을 가리키는 것(영상 번호, 제목, 올린 날)이 실리면 멈추는지 본다.
묶음, 카드, 영상 목록은 전부 지어낸 것이고 임시 폴더에만 둔다. 실제 카드와 실제 영상 목록은 읽지 않는다.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "skills" / "syuka" / "deck" / "bundle_guard.py"
CARD_ID = "2099-01-02-am-01"

_spec = importlib.util.spec_from_file_location("ozl_skill_bundle_guard", SCRIPT)
bg = importlib.util.module_from_spec(_spec)
_keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True      # 스킬 폴더에 __pycache__ 를 남기지 않는다
try:
    _spec.loader.exec_module(bg)
finally:
    sys.dont_write_bytecode = _keep

VIDEOS = [{"video_id": "fakeSYK0002", "title": "공유 자전거는 왜 늘 적자일까 (지어낸 영상)", "date": "2098-06-03",
           "relation": "후속", "gist": "지어낸 요지"}]
KNOWN = {"fakeSYK0001", "fakeSYK0002", "fakeSYK0003"}


def bundle(*slide_lines: str, claims: tuple[str, ...] = ()) -> str:
    """ozl.render bundle 이 내는 글의 꼴(머리, 쪽, 검증 기록 절)로 지어낸 묶음."""
    head = [f"# 검토 묶음 — {CARD_ID}", "", "- 사양: x.yaml · sha256 0123456789abcdef", "- 엄격 검사: 통과 · 실패 0 · 경고 0", "",
            "## 덱 본문(쪽마다: 단계 · 종류 · 제목 / 화면 글 / 말 / 넘김 / 인용 / 각주)", "", "### 1쪽 · 여는 장 · full_picture", "제목: "]
    tail = ["", "## 인용한 검증 기록(번호 · 출처 · 원문 표기 · 등급 · 기준 · 재대조 맥락)", "",
            "- c1 · 한빛시 보도자료 · T1 · observed: 「1,240만 건」 · 등급 A · 기준 2098년 · 주소: https://hanbit.example/press/1", *claims]
    return "\n".join(head + list(slide_lines) + tail) + "\n"


CLEAN = bundle("화면: 2098년 이용 1,240만 건", "말: 전에 이 방송에서 빛바퀴 적자를 다룬 적이 있는데, 오늘은 그 뒷이야기입니다.",
               "인용: c1", "각주: 출처: 한빛시 보도자료 · 기준 2098년, 2099-03-01",
               "작성자 메모: 이용 건수는 대여 한 번을 한 건으로 센 횟수다.")


def kinds(text: str, videos=VIDEOS, known=KNOWN) -> list[tuple[int, str, str]]:
    return [(h["line"], h["kind"], h["value"]) for h in bg.scan(text, videos, known)]


def test_clean_bundle_has_no_hits():
    assert kinds(CLEAN) == []


def test_note_with_video_id_and_upload_date_is_caught():
    """따라가기에서 실제로 난 꼴: 장의 메모에 지난 방송의 날짜와 영상 번호를 적었다."""
    text = bundle("말: 오늘은 그 뒷이야기입니다.",
                  "작성자 메모: 겹침: 2098-06-03 방송(fakeSYK0002)과 같은 사건의 후속. 그 방송의 내용은 옮기지 않는다.")
    hits = kinds(text)
    line = text.splitlines().index("말: 오늘은 그 뒷이야기입니다.") + 2
    assert (line, bg.K_COV_ID, "fakeSYK0002") in hits and (line, bg.K_COV_DATE, "2098-06-03") in hits
    assert len(hits) == 2                                         # 같은 줄의 같은 값은 한 번만 적는다


def test_catalog_id_outside_the_card_is_caught():
    hits = kinds(bundle("작성자 메모: 금리 편(fakeSYK0001)도 참고."))
    assert [(k, v) for _, k, v in hits] == [(bg.K_CATALOG, "fakeSYK0001")]


def test_id_shape_in_a_video_slot_is_caught_without_the_catalog():
    """영상 목록에 없는 번호도 "방송(…)" 자리, "video_id: …" 자리에 있으면 걸린다."""
    for line in ("작성자 메모: 지난 방송(abcDEF12345)과 겹친다.", "작성자 메모: video_id: abcDEF12345", "넘김: 영상 번호 `x1_y2-z3A4B` 참고"):
        hits = kinds(bundle(line), known=set())
        assert [k for _, k, _ in hits] == [bg.K_SHAPE], line


def test_eleven_letter_product_names_are_not_caught():
    """11자인 이름(GPT-4o-mini 같은 것)과 날짜, 번호는 영상 자리에 있지 않으면 걸리지 않는다."""
    text = bundle("화면: GPT-4o-mini 요금 인하", "말: 이 영상 생성 기능은 GPT-4o-mini 에는 없습니다.", "화면: 방송(생방송) 기준 2026-11-15",
                  "작성자 메모: 사양 2099-01-02-am-01_20990102_101010.yaml · 12345678901 건")
    assert kinds(text) == []
    assert bg.looks_like_id("GPT-4o-mini") and not bg.looks_like_id("screenshots") and not bg.looks_like_id("12345678901")


def test_youtube_address_in_the_body_is_caught_and_source_address_only_when_known():
    body = kinds(bundle("화면: https://youtu.be/zzzZZZ99999 에서"), known=set())
    assert [(k, v) for _, k, v in body] == [(bg.K_URL, "zzzZZZ99999")]
    src_unknown = bundle(claims=("- c2 · 한빛시 유튜브 · T1 · 주소: https://www.youtube.com/watch?v=zzzZZZ99999",))
    assert kinds(src_unknown) == []                              # 기관이 올린 영상을 출처로 든 기록은 받는다
    src_known = bundle(claims=("- c2 · 지난 방송 · T3 · 주소: https://www.youtube.com/watch?t=3&v=fakeSYK0003",))
    assert {(k, v) for _, k, v in kinds(src_known)} == {(bg.K_CATALOG, "fakeSYK0003")}


def test_title_is_caught_even_with_different_spacing():
    hits = kinds(bundle("작성자 메모: 「공유 자전거는  왜 늘 적자일까 (지어낸 영상)」 의 후속"))
    assert [k for _, k, _ in hits] == [bg.K_COV_TITLE]
    short = [{"video_id": "fakeSYK0009", "title": "금리", "date": "2098-01-01"}]
    assert kinds(bundle("화면: 금리 인하"), videos=short, known=set()) == []     # 짧은 제목은 보지 않는다


@pytest.mark.parametrize("written", ["2098-06-03", "2098.06.03", "2098. 6. 3", "2098/6/3", "2098년 6월 3일"])
def test_upload_date_forms(written):
    assert [k for _, k, _ in kinds(bundle(f"말: {written} 에 다룬 내용의 뒷이야기입니다."))] == [bg.K_COV_DATE]


def test_upload_date_is_not_checked_in_lines_taken_from_records():
    """각주와 인용 줄, 검증 기록 절에는 근거 문서의 날짜가 들어간다. 올린 날과 우연히 같아도 걸리지 않는다."""
    text = bundle("각주: 출처: 한빛시 보도자료 · 기준 2098-06-03", "인용: c1",
                  claims=("- c2 · 한빛시 공고 · T1 · 기준 2098-06-03 · 주소: https://hanbit.example/notice/2",))
    assert kinds(text) == []
    assert kinds(bundle("화면: 2098-06-30 기준", "화면: 12098-06-03")) == []        # 다른 날, 더 긴 숫자


# ── 명령으로 ──────────────────────────────────────────────────────────────

@pytest.fixture
def desk(tmp_path, monkeypatch):
    """지어낸 카드와 영상 목록만 보게 한다."""
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / f"{CARD_ID}.yaml").write_text(yaml.safe_dump({"card_id": CARD_ID, "coverage": {"summary": "지어낸 요약", "searched": ["빛바퀴"],
                                                                                         "videos": VIDEOS}}, allow_unicode=True), encoding="utf-8")
    cat = tmp_path / "catalog.csv"
    cat.write_text("video_id,title\n" + "".join(f"{v},지어낸 제목\n" for v in sorted(KNOWN)), encoding="utf-8")
    monkeypatch.setattr(bg.C, "CARDS", cards)
    monkeypatch.setattr(bg, "CATALOG", cat)
    return tmp_path


def test_command_stops_on_a_hit_and_passes_a_clean_bundle(desk, capsys):
    bad = desk / "bundle_bad.md"
    bad.write_text(bundle("작성자 메모: 겹침: 2098-06-03 방송(fakeSYK0002)과 같은 사건의 후속."), encoding="utf-8")
    assert bg.main([str(bad)]) == 1
    out = capsys.readouterr().out
    assert "실렸다 2곳" in out and "fakeSYK0002" in out and "이 묶음을 보내지 않는다" in out
    assert "카드 coverage 의 영상 1편 · 영상 목록 3편" in out
    good = desk / "bundle_good.md"
    good.write_text(CLEAN, encoding="utf-8")
    assert bg.main([str(good), "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["hits"] == [] and res["card_id"] == CARD_ID and res["coverage_videos"] == 1 and res["catalog_videos"] == 3


def test_command_reads_only(desk):
    before = {p: p.stat().st_mtime_ns for p in desk.rglob("*") if p.is_file()}
    f = desk / "bundle.md"
    f.write_text(CLEAN, encoding="utf-8")
    before[f] = f.stat().st_mtime_ns
    assert bg.main([str(f)]) == 0
    assert {p: p.stat().st_mtime_ns for p in desk.rglob("*") if p.is_file()} == before


def test_command_refuses_when_it_cannot_check(desk, capsys, monkeypatch):
    assert bg.main([str(desk / "none.md")]) == 2                 # 묶음이 없다
    f = desk / "bundle.md"
    f.write_text(CLEAN.replace(CARD_ID, "2099-01-02-am-09"), encoding="utf-8")
    assert bg.main([str(f)]) == 2                                # 그 카드가 없다
    err = capsys.readouterr().err
    assert "묶음 파일이 없다" in err and "coverage 를 대조하지 못했다" in err
    f.write_text("머리 없는 글\n", encoding="utf-8")
    assert bg.main([str(f)]) == 2                                # 카드 번호를 읽지 못했다
    assert bg.main([str(f), "--card", CARD_ID]) == 0             # 번호를 주면 본다
    capsys.readouterr()
    monkeypatch.setattr(bg, "CATALOG", desk / "no_catalog.csv")  # 영상 목록이 없으면 그렇게 알리고, 카드와 꼴은 본다
    f.write_text(bundle("작성자 메모: 지난 방송(fakeSYK0002)의 후속"), encoding="utf-8")
    assert bg.main([str(f)]) == 1
    assert "영상 목록을 읽지 못했다" in capsys.readouterr().out


def test_fixture_sandbox_bundle_shape_matches_the_engine():
    """이 시험의 지어낸 묶음이 엔진이 내는 머리와 절 제목을 그대로 쓴다(엔진이 바뀌면 검사도 함께 봐야 한다)."""
    import inspect

    from ozl.render import bundle as B
    src = inspect.getsource(B)
    assert '"# 검토 묶음 — {sp.get(\'card_id\', \'\')}"' in src.replace("f\"", "\"")
    assert bg.CLAIMS_HEAD in src and "작성자 메모: " in src and "각주: " in src and '"인용: "' in src
    assert bg.HEAD.search(CLEAN).group(1) == CARD_ID


def test_help_runs_as_a_script():
    r = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "--card" in r.stdout and "--json" in r.stdout
    assert not (SCRIPT.parent / "__pycache__").exists()


def test_filled_external_head_is_checked_with_the_card_option(desk, capsys):
    """다른 계열에 보내는 머리말(skills/ozl/review/external_head.md 를 채운 글)도 같은 검사로 본다. 머리말에는 카드 번호 줄이 없어 --card 를 준다."""
    import re
    template = (ROOT / "skills" / "ozl" / "review" / "external_head.md").read_text(encoding="utf-8")

    def fill(prev: str) -> str:
        out = template.replace("{ROUND}", "2판").replace("{PREV}", prev).replace("{PRESS}", "- (지어낸 기사) 한빛시는 빛바퀴 요금을 올리기로 했다")
        assert not re.findall(r"\{[A-Z_]+\}", out)                 # 채우지 않은 자리가 없다
        return out

    f = desk / "head.md"
    f.write_text(fill("이전 판 지적: 7쪽의 넘김이 근거를 넘는다."), encoding="utf-8")
    assert bg.main([str(f)]) == 2                                # 카드 번호 줄이 없으면 검사하지 못한 것이다(보내지 않는 쪽)
    assert bg.main([str(f), "--card", CARD_ID]) == 0
    capsys.readouterr()
    # 구성 평가의 D 절(지난 방송과 겹침의 근거)을 그대로 옮긴 머리말
    f.write_text(fill("이전 판 지적: 나7 모자람. 2098년 6월 3일 방송(fakeSYK0002)이 같은 질문에 이미 답했다."), encoding="utf-8")
    assert bg.main([str(f), "--card", CARD_ID]) == 1
    out = capsys.readouterr().out
    assert "fakeSYK0002" in out and "2098-06-03" in out
