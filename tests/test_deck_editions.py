"""두 판 빌드와 공개 차단(사용자 결정 나 · 라) — 장의 swap 칸, 판 가르기(strip_swaps · apply_swaps · swap_errors · needs_two · plan_editions),
판마다 검사(check_editions)와 check 명령의 출력, build 가 내는 폴더 둘과 그 안의 파일, 권리 확인 대기(rights_pending · RIGHTS_PENDING_HOSTS),
비공개 등록 대장과 public_check, 검토 묶음과 비교표의 판 처리.
네트워크 없이 돈다. 그림은 PIL 로 그린 것이고 예시 문장, 이름, 주소는 전부 지어낸 것이다."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from test_deck_visuals import desk  # noqa: E402,F401  (pytest fixture)
from test_deck_kinds import entry  # noqa: E402
from test_deck_pictures_policy import _art, photo, press, screen  # noqa: E402
from ozl.render import build as B  # noqa: E402
from ozl.render import bundle as BU  # noqa: E402
from ozl.render import compare as CMP  # noqa: E402
from ozl.render import pictures as PIC  # noqa: E402
from ozl.render import progress as P  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.render.__main__ import main as render_main  # noqa: E402
from ozl.research import cards as C  # noqa: E402

CARD, TEMPLATE = V.CARD, V.TEMPLATE
GOV = f"{CARD}-c7"                       # 사람이 대조한 지어낸 기록 — 원문 주소의 기관 호스트가 권리 확인 대기 호스트다
PENDING_HOST = "example.net"             # 시험에서 쓰는 권리 확인 대기 호스트(지어낸 것)
GOV_URL = "https://briefing.example.net/policy/view?id=7"
PRIV, SWAP = PIC.EDITION_PRIVATE, PIC.EDITION_SWAP
REAL_REGISTRY = PIC.REGISTRY                # 모듈을 읽을 때의 값(아래 자동 픽스처가 시험마다 임시 파일로 돌려 둔다)


@pytest.fixture(autouse=True)
def _tmp_registry(tmp_path, monkeypatch):
    """시험은 실제 비공개 등록 대장(private/decks/private_only_registry.jsonl)을 읽지도 쓰지도 않는다."""
    monkeypatch.setattr(PIC, "REGISTRY", tmp_path / "registry_for_test.jsonl")
    monkeypatch.delenv(PIC.REGISTRY_ENV, raising=False)


def gov_claim() -> dict:
    return {"claim_id": GOV, "card_id": CARD, "text": "가상의 섬 정책 누리집은 감자 창고를 3곳으로 적었다.", "observed": "감자 창고 3곳",
            "human_verified": True, "status": "verified",
            "source": {"url": GOV_URL, "publisher": "가상 섬 정책 누리집", "tier": "T1"},
            "checks": {"base_period": "2098", "primary_doc_locator": "본문 둘째 문단"}}


REBUILT = {"stage": "배경", "kind": "image_text", "title": "감자 창고 이야기", "body": ["감자는 창고에서 겨울을 난다"], "seconds": 20}
SWAP_PRESS = {"why": "보도 사진은 공개 판에 넣지 않는다", "set": {"picture": "p2", "caption": "가상 사진가의 감자밭 사진이다"}}
SWAP_GOV = {"why": "정책 누리집 갈무리는 권리 확인 대기다", "slide": REBUILT}


@pytest.fixture
def arts(tmp_path, monkeypatch):
    """그림 셋(바이트가 서로 다르다)과 지어낸 권리 확인 대기 호스트. 등록 대장은 임시 폴더로 돌린다(실제 대장을 읽지도 쓰지도 않는다)."""
    monkeypatch.setattr(PIC, "RIGHTS_PENDING_HOSTS", (PENDING_HOST,))
    monkeypatch.setattr(B, "DRAFTS", tmp_path / "decks" / "drafts")
    B.DRAFTS.mkdir(parents=True)
    monkeypatch.setattr(PIC, "REGISTRY", B.registry_file())
    monkeypatch.delenv(PIC.REGISTRY_ENV, raising=False)
    return {"press": _art(tmp_path / "press.png"), "ok": _art(tmp_path / "ok.png", (900, 600)), "gov": _art(tmp_path / "gov.png", (1000, 640))}


def two_spec(arts, swaps=True, style="syuka") -> dict:
    """보도 사진 한 장(3쪽)과 권리 확인 대기 갈무리 한 장(4쪽)이 든 사양. swaps=True 면 두 장에 swap 을 둔다(set 하나, slide 하나)."""
    pics = [press(arts["press"], pid="p1"), entry(arts["ok"], pid="p2"),
            screen(arts["gov"], pid="p3", source_url=GOV_URL, rights_holder="가상 섬 정책 누리집", attribution="briefing.example.net")]
    a = photo("p1", caption="지어낸 통신사의 사진이다")
    b = photo("p3", claim_ids=[GOV], caption="가상 섬 정책 누리집 화면이다")
    if swaps:
        a["swap"], b["swap"] = copy.deepcopy(SWAP_PRESS), copy.deepcopy(SWAP_GOV)
    sp = V.spec_of([a, b])
    if style:
        sp["style"] = style
    sp["pictures"] = pics
    return sp


def write(tmp_path, sp, name="spec.yaml") -> pathlib.Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(sp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def save_records():
    C.save_yaml(C.claim_path(GOV), gov_claim())
    C.save_yaml(C.card_path(CARD), {"card_id": CARD, "sources": [], "risks": ["지어낸 위험 문장"]})


# ── 권리 확인 대기(결정 라) ────────────────────────────────────────────────

def test_policy_briefing_host_is_rights_pending_by_default(tmp_path):
    art = _art(tmp_path / "a.png")
    assert "korea.kr" in PIC.RIGHTS_PENDING_HOSTS
    e = screen(art, source_url="https://www.korea.kr/briefing/view?id=0")
    assert PIC.judge(e)[0] == PIC.USE and not PIC.judge(e)[1]            # 판정은 '쓴다' 그대로
    assert "권리 확인 대기" in PIC.public_block(e) and PIC.edition_block(e)
    assert not PIC.public_block(screen(art))                             # 다른 호스트의 갈무리는 막지 않는다
    assert not PIC.public_block(entry(art, source_url="https://www.korea.kr/photo/1"))   # 호스트 규칙은 원문 화면 갈무리에만


def test_rights_pending_field_blocks_any_kind_and_keeps_verdict(tmp_path):
    art = _art(tmp_path / "a.png")
    e = entry(art, rights_pending="이용 조건을 아직 읽지 못했다")
    assert PIC.judge(e)[0] == PIC.USE and not PIC.judge(e)[1]
    assert PIC.rights_pending(e) == "이용 조건을 아직 읽지 못했다" and "권리 확인 대기" in PIC.public_block(e)
    assert any("rights_pending" in x for x in PIC.judge(entry(art, rights_pending=True))[1])   # 까닭 한 줄이어야 한다
    sp = V.spec_of([photo("p1")]) | {"pictures": [e]}
    st = PIC.public_status(sp)
    assert st["public_ok"] is False and st["blocking"][0]["id"] == "p1"
    row = PIC.ledger_report(sp)[0]
    assert row["verdict"] == PIC.USE and row["rights_pending"] and row["public"].startswith("막음")
    assert f"{PIC.USE} — {PIC.RIGHTS_PENDING_MARK}" in PIC.ledger_md([row], st, CARD, "x")
    assert "rights_pending" not in PIC.ledger_report(V.spec_of([photo("p1")]) | {"pictures": [entry(art)]})[0]   # 그 밖의 행은 그대로


def test_meme_does_not_split_editions(tmp_path):
    art = _art(tmp_path / "a.png")
    meme = entry(art, kind="밈", meme_origin="가상 게시판")
    assert PIC.public_block(meme) and not PIC.edition_block(meme)        # 공개는 막지만 판을 가르지는 않는다
    assert not PIC.needs_two(V.spec_of([photo("p1")]) | {"pictures": [meme]})


# ── 판 가르기 ────────────────────────────────────────────────────────────

def test_strip_and_apply_leave_the_original_alone(arts):
    sp = two_spec(arts)
    before = copy.deepcopy(sp)
    assert PIC.needs_two(sp) and PIC.has_swaps(sp)
    private = PIC.strip_swaps(sp)
    swapped, rows = PIC.apply_swaps(sp)
    assert sp == before                                                   # 원래 사양은 고치지 않는다
    assert not PIC.has_swaps(private) and not PIC.has_swaps(swapped)
    assert [sl.get("picture") for sl in private["slides"][2:4]] == ["p1", "p3"]
    assert swapped["slides"][2]["picture"] == "p2" and swapped["slides"][2]["caption"] == "가상 사진가의 감자밭 사진이다"
    assert swapped["slides"][3] == REBUILT and swapped["slides"][3] is not sp["slides"][3]["swap"]["slide"]
    assert len(private["slides"]) == len(swapped["slides"]) == len(sp["slides"])
    assert rows == [
        {"page": 3, "from": "p1(통신사·언론사 사진)", "to": "p2(CC BY)", "why": SWAP_PRESS["why"], "mode": "set"},
        {"page": 4, "from": "p3(원문 화면 갈무리)", "to": "글과 도형으로 다시 짬", "why": SWAP_GOV["why"], "mode": "slide"},
    ]
    assert not PIC.needs_two(swapped) and PIC.public_status(swapped)["public_ok"]
    assert PIC.used_in_any_edition(sp) == {"p1", "p2", "p3"}


def test_set_with_null_removes_the_field_and_names_chart_and_capture(arts):
    sp = two_spec(arts)
    sp["slides"][2] = V.slide(stage="배경", picture="p1", claim_ids=[V.CID],
                              swap={"why": "차트로 바꾼다", "set": {"picture": None, "chart": V.line_chart()}})
    sp["slides"][3] = V.slide(stage="배경", picture="p3", claim_ids=[GOV, V.CID],
                              swap={"why": "원문 대목으로 바꾼다", "set": {"picture": None, "capture": V.CID}})
    swapped, rows = PIC.apply_swaps(sp)
    assert "picture" not in swapped["slides"][2] and swapped["slides"][2]["chart"]["kind"] == "line"
    assert [r["to"] for r in rows] == ["차트", "원문 캡처 c1"]


def _errs(arts, mutate, draft=False, **kw):
    sp = two_spec(arts)
    mutate(sp)
    return PIC.swap_errors(sp, draft, **kw)


def test_missing_swap_fails_in_strict_only(arts):
    sp = two_spec(arts, swaps=False)
    errs = PIC.swap_errors(sp)
    assert len(errs) == 2 and errs[0].startswith("3쪽: 막는 그림 p1(통신사·언론사 사진)이 든 장에 swap 이 없다")
    assert "4쪽: 막는 그림 p3(원문 화면 갈무리)" in errs[1] and "--edition 비공개판" in errs[1]
    assert PIC.swap_errors(sp, draft=True) == [] and PIC.swap_errors(sp, shape_only=True) == []
    assert PIC.swap_errors(two_spec(arts)) == []


def test_swap_on_a_slide_without_blocking_picture_fails(arts):
    def m(sp):
        sp["slides"][5]["swap"] = {"why": "지어낸 까닭", "set": {"title": "다른 제목"}}
    errs = _errs(arts, m)
    assert errs == ["6쪽: 막는 그림이 없는 장에 swap 이 있다 — swap 은 판정 '비공개 판에서만'이거나 권리 확인 대기인 그림이 든 장에만 둔다"]
    assert _errs(arts, m, draft=True) == errs                           # 초안 모드에서도 틀린 자리다


def test_blocking_picture_left_after_swap_fails(arts):
    def m(sp):
        sp["pictures"].append(press(arts["gov"], pid="p9"))
        sp["slides"][2]["swap"] = {"why": "다른 보도 사진으로", "set": {"picture": "p9"}}
    errs = _errs(arts, m)
    assert len(errs) == 1 and "3쪽: swap 을 적용한 뒤에도 막는 그림 p9(통신사·언론사 사진)이 남는다" in errs[0]


def test_swap_to_grey_placeholder_fails_in_strict(arts):
    def m(sp):
        sp["slides"][2] = V.slide(stage="배경", picture="p1", claim_ids=[], body=["감자 이야기"],
                                  swap={"why": "그림을 뺀다", "set": {"picture": None, "image": {"what": "감자밭 사진", "source": "가상 섬 농업청"}}})
    errs = _errs(arts, m)
    assert len(errs) == 1 and "3쪽: swap 이 그림 자리를 회색 자리(image)로 바꿨다" in errs[0]
    assert _errs(arts, m, draft=True) == []


@pytest.mark.parametrize("swap,frag", [
    ("그냥 글", "swap 은 {why, set 또는 slide} 사전이어야 한다"),
    ({"set": {"picture": "p2"}}, "swap.why(바꾸는 까닭 한 줄)가 있어야 한다"),
    ({"why": "까닭", "set": {"picture": "p2"}, "slide": dict(REBUILT)}, "가운데 하나만 둔다"),
    ({"why": "까닭"}, "가운데 하나만 둔다"),
    ({"why": "까닭", "set": {}}, "swap.set 은 비지 않은 사전이어야 한다"),
    ({"why": "까닭", "slide": {**REBUILT, "stage": "전개"}}, "stage('전개')는 원래 장('배경')과 같아야 한다"),
    ({"why": "까닭", "set": {"picture": "p2", "stage": "전개"}}, "swap.set 으로 stage 를 바꾸지 않는다"),
    ({"why": "까닭", "set": {"picture": "p2"}, "note": "덤"}, "모르는 칸 ['note']"),
    ({"why": "까닭", "slide": {**REBUILT, "swap": {"why": "또"}}}, "안에 swap 을 다시 두지 않는다"),
])
def test_swap_shape_errors(arts, swap, frag):
    def m(sp):
        sp["slides"][2]["swap"] = swap
    for kw in ({}, {"draft": True}, {"shape_only": True}):               # 모양은 어느 모드에서나 본다
        errs = _errs(arts, m, **kw)
        assert any(x.startswith("3쪽: ") and frag in x for x in errs), (kw, errs)
    sp = two_spec(arts)
    sp["slides"][2]["swap"] = swap
    swapped, rows = PIC.apply_swaps(sp)                                  # 모양이 틀린 swap 은 적용하지 않고 떼기만 한다
    assert swapped["slides"][2].get("picture") == "p1" and "swap" not in swapped["slides"][2] and [r["page"] for r in rows] == [4]


def test_plan_editions_by_mode(arts):
    plain = V.spec_of([photo("p2")]) | {"pictures": [entry(arts["ok"], pid="p2")]}
    errs, plan = PIC.plan_editions(plain)
    assert errs == [] and len(plan) == 1 and plan[0][0] is None and plan[0][1] is plain   # 판을 가르지 않는 사양은 그대로 돌려준다
    sp = two_spec(arts)
    errs, plan = PIC.plan_editions(sp)
    assert errs == [] and [x[0] for x in plan] == [PRIV, SWAP] and plan[0][2] == plan[1][2] and len(plan[0][2]) == 2
    errs, plan = PIC.plan_editions(sp, draft=True)                       # 초안 모드는 판을 가르지 않는다(swap 을 뗀 한 판)
    assert errs == [] and [x[0] for x in plan] == [None] and not PIC.has_swaps(plan[0][1]) and plan[0][1]["slides"][2]["picture"] == "p1"
    bare = two_spec(arts, swaps=False)
    assert len(PIC.plan_editions(bare)[0]) == 2
    errs, plan = PIC.plan_editions(bare, edition=PRIV)                   # 비공개판만: swap 이 없어도 된다
    assert errs == [] and [x[0] for x in plan] == [PRIV]
    errs, plan = PIC.plan_editions(bare, edition=SWAP)
    assert len(errs) == 2 and [x[0] for x in plan] == [SWAP]
    errs, plan = PIC.plan_editions(plain, edition=PRIV)
    assert plan == [] and "막는 그림도 swap 도 없다" in errs[0]
    assert PIC.plan_editions(sp, edition="어느판")[1] == []


# ── 검사 ────────────────────────────────────────────────────────────────

def test_cited_ids_reads_records_inside_swap():
    a, b, c, d = (f"{CARD}-c{n}" for n in (1, 2, 3, 4))
    sp = {"slides": [{"claim_ids": [a], "swap": {"why": "까닭", "set": {"claim_ids": [b], "chart": {"claims": [c]}}}},
                     {"claim_ids": [], "swap": {"why": "까닭", "slide": {"claim_ids": [a], "capture": d, "conversions": [{"claim_id": b}],
                                                                       "pair": [{"capture": c}, "모양이 틀린 자리"]}}},
                     {"claim_ids": [a], "swap": "모양이 틀린 swap"}]}
    assert S.cited_ids(sp) == [a, b, c, d]
    assert BU.all_cited(sp) == [a, b, c, d]


def test_check_refuses_a_spec_that_still_has_swap(desk, arts):
    rep = S.check(two_spec(arts), {GOV: gov_claim()}, TEMPLATE, layout_fn=B.layout_problems)
    assert sum("swap 칸이 남아 있다" in x for x in rep.errors) == 2


def test_check_editions_passes_both_and_counts_pictures_across_editions(desk, arts):
    eds = S.check_editions(two_spec(arts), {GOV: gov_claim()}, TEMPLATE, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems)
    assert [e.name for e in eds] == [PRIV, SWAP] and all(e.report.ok for e in eds), [e.report.errors for e in eds]
    assert not any("쓰지 않은 그림" in w for e in eds for w in e.report.warnings)   # p2 는 바꾼판에서만, p1 · p3 은 비공개판에서만 쓴다
    assert eds[0].swaps == eds[1].swaps and len(eds[0].swaps) == 2
    lone = S.check(PIC.strip_swaps(two_spec(arts)), {GOV: gov_claim()}, TEMPLATE, layout_fn=B.layout_problems)
    assert any("쓰지 않은 그림: p2" in w for w in lone.warnings)                    # 한 판만 따로 검사하면 경고가 난다(견줄 것)


def test_check_editions_puts_split_errors_on_the_swap_edition(desk, arts):
    eds = S.check_editions(two_spec(arts, swaps=False), {GOV: gov_claim()}, TEMPLATE, layout_fn=B.layout_problems)
    assert eds[0].report.ok and not eds[1].report.ok
    assert eds[1].report.errors[0].startswith("3쪽: 막는 그림 p1")
    one = S.check_editions(two_spec(arts, swaps=False), {GOV: gov_claim()}, TEMPLATE, layout_fn=B.layout_problems, edition=PRIV)
    assert [e.name for e in one] == [PRIV] and one[0].report.ok


def test_check_command_prints_each_edition(desk, arts, tmp_path, capsys):
    save_records()
    f = write(tmp_path, two_spec(arts))
    assert render_main(["check", str(f)]) == 0
    out = capsys.readouterr().out
    assert "[check·비공개판] 통과 · 본편 12장 · 실패 0" in out and "[check·바꾼판] 통과 · 본편 12장 · 실패 0" in out
    assert "[check] " not in out
    g = write(tmp_path, two_spec(arts, swaps=False), "bare.yaml")
    assert render_main(["check", str(g)]) == 1
    out = capsys.readouterr().out
    assert "[실패·바꾼판] 3쪽: 막는 그림 p1(통신사·언론사 사진)이 든 장에 swap 이 없다" in out
    assert "[check·비공개판] 통과" in out and "[check·바꾼판] 실패 · 본편 12장 · 실패 2" in out
    assert render_main(["check", str(g), "--edition", PRIV]) == 0
    out = capsys.readouterr().out
    assert "[check·비공개판] 통과 · 본편 12장 · 실패 0" in out and "바꾼판" not in out
    assert render_main(["check", str(g), "--edition", SWAP]) == 1
    assert "[check·바꾼판] 실패" in capsys.readouterr().out
    assert render_main(["check", str(g), "--draft"]) == 0               # 초안 모드는 판을 가르지 않는다
    out = capsys.readouterr().out
    assert "[check] 통과 (초안 모드)" in out and "비공개판" not in out
    with pytest.raises(SystemExit, match="판 이름"):
        render_main(["check", str(g), "--edition", "어느판"])


def test_check_output_of_a_plain_spec_has_no_edition_tags(desk, arts, tmp_path, capsys):
    save_records()
    sp = V.spec_of([photo("p2")]) | {"pictures": [entry(arts["ok"], pid="p2")]}
    f = write(tmp_path, sp, "plain.yaml")
    assert render_main(["check", str(f)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].startswith("[check] 통과 · 본편 11장 · 실패 0") and lines[-2] == "[면제한 식별자] 없음"
    assert all(x.split("]")[0] in ("[경고", "[면제한 식별자", "[check") for x in lines)
    assert render_main(["check", str(f), "--edition", PRIV]) == 1
    assert "막는 그림도 swap 도 없다" in capsys.readouterr().out


def test_progress_review_checks_both_editions(desk, arts, tmp_path):
    save_records()
    assert P.spec_major(str(write(tmp_path, two_spec(arts)))) == []
    major = P.spec_major(str(write(tmp_path, two_spec(arts, swaps=False), "bare.yaml")))
    assert len(major) == 2 and major[0].startswith("검사(바꾼판): 3쪽: 막는 그림 p1")


# ── 빌드 ────────────────────────────────────────────────────────────────

def _lines(p: pathlib.Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_build_makes_two_folders_with_the_same_timecode(desk, arts, tmp_path):
    from pptx import Presentation
    save_records()
    out = B.build(write(tmp_path, two_spec(arts)), export=False)
    assert list(out["editions"]) == [PRIV, SWAP] and "dir" not in out
    a, b = out["editions"][PRIV], out["editions"][SWAP]
    da, db = pathlib.Path(a["dir"]), pathlib.Path(b["dir"])
    assert sorted(x.name for x in B.DRAFTS.iterdir()) == sorted([da.name, db.name])
    ts = da.name[len(CARD) + 1:-len(PRIV) - 1]
    assert da.name == f"{CARD}_{ts}_{PRIV}" and db.name == f"{CARD}_{ts}_{SWAP}"       # 같은 타임코드
    for d, name in ((da, PRIV), (db, SWAP)):
        names = {x.name for x in d.iterdir()}
        assert {f"{d.name}.pptx", f"running_sheet_{ts}.md", f"그림_검수대장_{ts}.md", f"그림_검수대장_{ts}.json", PIC.PUBLIC_FILE,
                f"links_{ts}.md", f"links_{ts}.csv", f"spec_{ts}_{name}.yaml"} <= names, names
    # 문서 속성
    assert Presentation(a["pptx"]).core_properties.keywords == f"{PIC.PRIVATE_KEYWORD} ozl:block=p1,p3 ozl:edition=private"
    assert Presentation(b["pptx"]).core_properties.keywords == "ozl:edition=swap"
    # 공개_가부.json
    ja, jb = (json.loads((d / PIC.PUBLIC_FILE).read_text(encoding="utf-8")) for d in (da, db))
    assert (ja["edition"], ja["pair"], ja["public_ok"]) == (PRIV, db.name, False) and [x["id"] for x in ja["blocking"]] == ["p1", "p3"]
    assert (jb["edition"], jb["pair"], jb["public_ok"], jb["blocking"]) == (SWAP, da.name, True, [])
    assert ja["swaps"] == jb["swaps"] and [s["page"] for s in ja["swaps"]] == [3, 4]
    assert "권리 확인 대기" in ja["blocking"][1]["why"]
    # 그림 검수 대장: 판 이름과 「바꾼 장」 표(두 판 모두 두 줄)
    for d, name, lead in ((da, PRIV, "바꾼 판에서는 아래 장이 이렇게 바뀐다."), (db, SWAP, "비공개 판의 아래 장을 이렇게 바꿨다.")):
        md = (d / f"그림_검수대장_{ts}.md").read_text(encoding="utf-8")
        assert f"판: {name} — " in md and "## 바꾼 장" in md and lead in md
        tail = md.split("## 바꾼 장")[1]
        assert sum(x.startswith("| 3 |") or x.startswith("| 4 |") for x in tail.splitlines()) == 2
        assert "| 3 | p1(통신사·언론사 사진) | p2(CC BY) | 보도 사진은 공개 판에 넣지 않는다 |" in tail
        led = json.loads((d / f"그림_검수대장_{ts}.json").read_text(encoding="utf-8"))
        assert led["edition"] == name and len(led["swaps"]) == 2
    led_a = json.loads((da / f"그림_검수대장_{ts}.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in led_a["pictures"]] == ["p1", "p3"] and led_a["pictures"][1]["verdict"] == PIC.USE
    assert f"{PIC.USE} — {PIC.RIGHTS_PENDING_MARK}" in (da / f"그림_검수대장_{ts}.md").read_text(encoding="utf-8")
    assert [r["id"] for r in json.loads((db / f"그림_검수대장_{ts}.json").read_text(encoding="utf-8"))["pictures"]] == ["p2"]
    # 러닝시트 머리의 판 이름
    assert f"**판: {PRIV}** — 막는 그림(p1, p3)이 든 판이다. 공개하지 않는다. 바꾼 판에서는 3, 4쪽이 바뀐다." in pathlib.Path(a["md"]).read_text(encoding="utf-8")
    assert f"**판: {SWAP}** — 비공개 판의 3, 4쪽을 바꾼 판이다." in pathlib.Path(b["md"]).read_text(encoding="utf-8")
    # 판의 사양 사본: swap 이 없고 그 판의 장이 들어 있다
    ca, cb = (yaml.safe_load(pathlib.Path(x["spec"]).read_text(encoding="utf-8")) for x in (a, b))
    assert not PIC.has_swaps(ca) and not PIC.has_swaps(cb)
    assert ca["slides"][2]["picture"] == "p1" and cb["slides"][2]["picture"] == "p2" and cb["slides"][3]["title"] == "감자 창고 이야기"
    assert pathlib.Path(a["spec"]).read_text(encoding="utf-8").startswith(f"# 판의 사양 사본 — {CARD} · {ts} · {PRIV}\n# 원래 사양: spec.yaml (sha256 ")
    assert CMP.resolve_spec(db).name == f"spec_{ts}_{SWAP}.yaml" and CMP.copy_edition(pathlib.Path(b["spec"])) == SWAP
    # 판마다 링크 목록(R-265)
    assert GOV in pathlib.Path(a["links"]).read_text(encoding="utf-8") and pathlib.Path(b["links_csv"]).is_file()
    # public-check: 비공개판 1 · 바꾼판 0
    assert (a["public_check"], b["public_check"]) == (1, 0)
    assert render_main(["public-check", str(da)]) == 1 and render_main(["public-check", str(db)]) == 0
    assert PIC.public_check(pathlib.Path(a["pptx"]))[0] == 1 and PIC.public_check(pathlib.Path(b["pptx"]))[0] == 0
    # 비공개 등록 대장: 막는 그림 둘과 비공개판 pptx
    reg = _lines(B.registry_file())
    assert a["registered"] == len(reg) == 3
    assert {(r["what"], r["name"]) for r in reg} == {("막는 그림", "p1"), ("막는 그림", "p3"), ("pptx", f"{da.name}.pptx")}
    assert {r["sha256"] for r in reg} == {PIC.file_sha256(arts["press"]), PIC.file_sha256(arts["gov"]), PIC.file_sha256(pathlib.Path(a["pptx"]))}
    assert all(r["card_id"] == CARD and r["built_at"] == ts and r["dir"] == da.name for r in reg)


def _fake_export(pptx: pathlib.Path):
    """내보내기 흉내 — 쪽마다 그 쪽의 글과 그림 바이트에서 만든 가짜 PNG 를 쓴다(두 판에서 내용이 같은 쪽은 바이트가 같다 — 실제 내보내기도 그렇다)."""
    import hashlib
    from pptx import Presentation
    pdf = pptx.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF fabricated " + pptx.name.encode("utf-8"))
    out = pptx.parent / (pptx.stem + "_png")
    out.mkdir()
    pngs = []
    for i, s in enumerate(Presentation(str(pptx)).slides, 1):
        h = hashlib.sha256()
        for sh in s.shapes:
            h.update((sh.text_frame.text if sh.has_text_frame else "").encode("utf-8"))
            if sh.shape_type == 13:   # 그림
                h.update(sh.image.blob)
        f = out / f"slide-{i:02d}.png"
        f.write_bytes(h.digest())
        pngs.append(f)
    return pdf, pngs


def test_export_registers_only_pages_with_blocking_pictures(desk, arts, tmp_path, monkeypatch):
    """실제 내보내기에서 드러난 것: 두 판에서 같은 쪽은 PNG 바이트가 같다. 비공개판의 쪽 PNG 를 다 등록하면 바꾼판이 막힌다 —
    막는 그림이 든 쪽(3, 4쪽)의 PNG 만 등록한다."""
    save_records()
    monkeypatch.setattr(B.deck, "to_pdf_png", _fake_export)
    monkeypatch.setattr(B, "MD2PDF", tmp_path / "없는 도구.py")
    out = B.build(write(tmp_path, two_spec(arts)), export=True)["editions"]
    a, b = out[PRIV], out[SWAP]
    assert (a["public_check"], b["public_check"]) == (1, 0) and a["pngs"] == b["pngs"] == 12
    da, db = pathlib.Path(a["dir"]), pathlib.Path(b["dir"])
    pa, pb = sorted((da / f"{da.name}_png").glob("*.png")), sorted((db / f"{db.name}_png").glob("*.png"))
    same = [i for i in range(12) if pa[i].read_bytes() == pb[i].read_bytes()]
    assert same == [0, 1, 4, 5, 6, 7, 8, 9, 10, 11]                       # 3, 4쪽만 다르다
    reg = _lines(B.registry_file())
    assert sorted(r["name"] for r in reg if r["what"] == "쪽 png") == ["slide-03.png(3쪽)", "slide-04.png(4쪽)"]
    assert {r["what"] for r in reg} == {"막는 그림", "pptx", "pdf", "쪽 png"} and len(reg) == 6
    assert PIC.public_check(pa[2])[0] == 1 and PIC.public_check(pa[0])[0] == 0 and PIC.public_check(pb[2])[0] == 0
    assert PIC.public_check(pathlib.Path(a["pdf"]))[0] == 1 and PIC.public_check(pathlib.Path(b["pdf"]))[0] == 0
    assert "파일 해시" in PIC.public_check(db)[1][0]


def _registered(kind: str | None = None) -> list[dict]:
    reg = _lines(B.registry_file()) if B.registry_file().exists() else []
    return [r for r in reg if kind is None or r["what"] == kind]


def _private_dir() -> pathlib.Path:
    return next(x for x in B.DRAFTS.iterdir() if x.name.endswith(f"_{PRIV}"))


def _timeout():
    import subprocess
    return subprocess.TimeoutExpired(cmd=["soffice"], timeout=180)


@pytest.mark.parametrize("boom", [_timeout(), FileNotFoundError("soffice")], ids=["TimeoutExpired", "FileNotFoundError"])
def test_export_failure_after_pdf_and_pngs_still_registers_them(desk, arts, tmp_path, monkeypatch, boom):
    """내보내기가 PDF 와 쪽 PNG 를 낸 뒤 예외로 끝나도(러닝시트 PDF 단계의 시간 초과 등) 그때까지 만든 파일이 등록 대장에 남는다.
    등록이 빠지면 대장이 비어 그 PDF 와 쪽 PNG, keywords 를 지운 pptx 사본이 public_check 를 통과한다."""
    save_records()

    def export_then_fail(pptx):
        _fake_export(pptx)
        raise boom
    monkeypatch.setattr(B.deck, "to_pdf_png", export_then_fail)
    with pytest.raises(type(boom)):
        B.build(write(tmp_path, two_spec(arts)), export=True)
    d = _private_dir()
    assert {r["what"] for r in _registered()} == {"막는 그림", "pptx", "pdf", "쪽 png"} and len(_registered()) == 6
    assert sorted(r["name"] for r in _registered("쪽 png")) == ["slide-03.png(3쪽)", "slide-04.png(4쪽)"]
    pngs = sorted((d / f"{d.name}_png").glob("*.png"))
    assert PIC.public_check(d / f"{d.name}.pdf")[0] == 1 and PIC.public_check(pngs[2])[0] == 1 and PIC.public_check(pngs[0])[0] == 0
    from test_publish_gate_deck import strip
    assert PIC.public_check(strip(d / f"{d.name}.pptx", tmp_path / "사본" / "no_keywords.pptx", keywords=True))[0] == 1


def test_export_failure_before_any_output_registers_pictures_and_pptx(desk, arts, tmp_path, monkeypatch):
    save_records()

    def fail(pptx):
        raise FileNotFoundError("soffice")
    monkeypatch.setattr(B.deck, "to_pdf_png", fail)
    with pytest.raises(FileNotFoundError):
        B.build(write(tmp_path, two_spec(arts)), export=True)
    d = _private_dir()
    assert {(r["what"], r["name"]) for r in _registered()} == {("막는 그림", "p1"), ("막는 그림", "p3"), ("pptx", f"{d.name}.pptx")}
    assert PIC.public_check(arts["press"])[0] == 1 and PIC.public_check(d / f"{d.name}.pptx")[0] == 1


def test_partial_page_pngs_are_matched_by_the_number_in_their_name(desk, arts, tmp_path, monkeypatch):
    """쪽 PNG 가 덜 나온 채 끝나도(12쪽 가운데 3쪽까지) 이름의 쪽 번호로 맞춰 막는 그림이 든 쪽(3쪽)을 등록한다."""
    save_records()

    def partial(pptx):
        _, pngs = _fake_export(pptx)
        for f in pngs[3:]:
            f.unlink()
        raise KeyboardInterrupt
    monkeypatch.setattr(B.deck, "to_pdf_png", partial)
    with pytest.raises(KeyboardInterrupt):
        B.build(write(tmp_path, two_spec(arts)), export=True)
    assert [r["name"] for r in _registered("쪽 png")] == ["slide-03.png(3쪽)"] and len(_registered("pdf")) == 1


def test_sheet_pdf_timeout_still_registers(desk, arts, tmp_path, monkeypatch):
    """md2pdf(러닝시트 PDF)가 시간 초과로 끝나는 길 — to_pdf_png 는 끝났고 그 뒤 subprocess.run 이 예외를 던진다."""
    import subprocess
    save_records()
    tool = tmp_path / "md2pdf.py"
    tool.write_text("", encoding="utf-8")
    monkeypatch.setattr(B.deck, "to_pdf_png", _fake_export)
    monkeypatch.setattr(B, "MD2PDF", tool)

    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout", 0))
    monkeypatch.setattr(B.subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        B.build(write(tmp_path, two_spec(arts)), export=True)
    assert {r["what"] for r in _registered()} == {"막는 그림", "pptx", "pdf", "쪽 png"}


def test_build_that_stops_after_writing_the_pptx_still_registers(desk, arts, tmp_path, monkeypatch):
    """pptx 를 쓴 뒤 빌드가 멈추는 길(링크 번호 양쪽 대응 실패) — 폴더에 남은 비공개판 pptx 와 막는 그림이 등록된다."""
    save_records()
    monkeypatch.setattr(B, "screen_link_numbers", lambda pptx: {99})
    with pytest.raises(SystemExit, match="양쪽 대응 실패"):
        B.build(write(tmp_path, two_spec(arts)), export=False)
    d = _private_dir()
    assert {(r["what"], r["name"]) for r in _registered()} == {("막는 그림", "p1"), ("막는 그림", "p3"), ("pptx", f"{d.name}.pptx")}


def test_build_creates_nothing_when_one_edition_fails(desk, arts, tmp_path):
    save_records()
    sp = two_spec(arts)
    sp["slides"][3]["swap"] = {"why": "제목이 너무 길다", "slide": {**REBUILT, "title": "감자 " * 60}}   # 바꾼판만 넘친다
    with pytest.raises(SystemExit, match=r"\[바꾼판\] 4쪽"):
        B.build(write(tmp_path, sp), export=False)
    assert list(B.DRAFTS.iterdir()) == [] and not B.registry_file().exists()
    with pytest.raises(SystemExit, match="swap 이 없다"):
        B.build(write(tmp_path, two_spec(arts, swaps=False), "bare.yaml"), export=False)
    assert list(B.DRAFTS.iterdir()) == []


def test_build_single_edition_on_request(desk, arts, tmp_path):
    save_records()
    out = B.build(write(tmp_path, two_spec(arts, swaps=False)), export=False, edition=PRIV)
    assert list(out["editions"]) == [PRIV]
    one = out["editions"][PRIV]
    d = pathlib.Path(one["dir"])
    assert d.name.endswith(f"_{PRIV}") and one["pair"] == "" and one["public_check"] == 1 and one["swapped"] == 0
    assert "바꾼 장 없음" in pathlib.Path(one["picture_ledger"]).read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="swap 이 없다"):
        B.build(write(tmp_path, two_spec(arts, swaps=False), "b.yaml"), export=False, edition=SWAP)


def test_build_stops_when_public_check_disagrees_with_the_edition(desk, arts, tmp_path, monkeypatch):
    save_records()
    monkeypatch.setattr(PIC, "public_check", lambda path, registries=None: (0, ["[public-check] 지어낸 결과"]))
    with pytest.raises(SystemExit, match="공개 가부 확인이 판과 어긋난다"):
        B.build(write(tmp_path, two_spec(arts)), export=False)


def test_swap_edition_is_blocked_when_it_carries_a_registered_picture(desk, arts, tmp_path):
    """바꾼 그림이 막는 그림과 같은 바이트면(대장 줄만 다르게 적은 같은 사진) 끝 확인에서 멈춘다."""
    save_records()
    sp = two_spec(arts)
    sp["pictures"][1] = entry(arts["press"], pid="p2")                    # p2 가 보도 사진 p1 과 같은 파일
    with pytest.raises(SystemExit, match="비공개 등록 대장에 있다"):
        B.build(write(tmp_path, sp), export=False)


def test_old_style_spec_with_blocking_picture_also_gets_two_folders(desk, arts, tmp_path):
    save_records()
    out = B.build(write(tmp_path, two_spec(arts, style=None)), export=False)
    for name in (PRIV, SWAP):
        d = pathlib.Path(out["editions"][name]["dir"])
        names = {x.name for x in d.iterdir()}
        assert PIC.PUBLIC_FILE in names and not any(n.startswith("links_") for n in names)   # 링크 목록은 style: syuka 만
        assert any(n.startswith("그림_검수대장_") and n.endswith(".md") for n in names)


def test_draft_mode_does_not_split(desk, arts, tmp_path):
    save_records()
    f = write(tmp_path, two_spec(arts))
    info = B.build(f, export=False, draft=True)
    d = pathlib.Path(info["dir"])
    assert "editions" not in info and d.name.endswith("_draft") and PRIV not in d.name
    names = {x.name for x in d.iterdir()}
    assert not any(n.startswith("spec_") for n in names) and info["public_ok"] is False
    st = json.loads((d / PIC.PUBLIC_FILE).read_text(encoding="utf-8"))
    assert "edition" not in st and [b["id"] for b in st["blocking"]] == ["p1", "p3"]
    reg = _lines(B.registry_file())                                       # 막는 그림이 든 연습용 판도 등록한다(keywords 를 지운 사본을 잡으려고)
    assert info["registered"] == 3 and {(r["what"], r["name"]) for r in reg} == {("막는 그림", "p1"), ("막는 그림", "p3"), ("pptx", f"{d.name}.pptx")}
    one = B.build(f, export=False, draft=True, edition=SWAP)["editions"][SWAP]
    assert pathlib.Path(one["dir"]).name.endswith(f"_{SWAP}_draft") and one["public_check"] == 0


def test_plain_spec_build_is_unchanged(desk, arts, tmp_path):
    """막는 그림이 없는 사양: 폴더 하나, 파일 이름과 공개_가부.json 의 칸, 문서 속성, 러닝시트와 대장 글에 판 이야기가 없다."""
    from pptx import Presentation
    save_records()
    sp = V.spec_of([photo("p2")]) | {"style": "syuka", "pictures": [entry(arts["ok"], pid="p2")]}
    info = B.build(write(tmp_path, sp), export=False)
    d = pathlib.Path(info["dir"])
    ts = d.name[len(CARD) + 1:]
    assert "editions" not in info and "edition" not in info and "registered" not in info and "spec" not in info
    assert {x.name for x in d.iterdir()} == {f"{d.name}.pptx", f"running_sheet_{ts}.md", f"그림_검수대장_{ts}.md", f"그림_검수대장_{ts}.json",
                                             PIC.PUBLIC_FILE, f"links_{ts}.md", f"links_{ts}.csv"}
    st = json.loads((d / PIC.PUBLIC_FILE).read_text(encoding="utf-8"))
    assert list(st) == ["card_id", "built_at", "draft", "public_ok", "blocking", "pictures", "rule", "keywords"] and st["keywords"] == ""
    assert list(json.loads((d / f"그림_검수대장_{ts}.json").read_text(encoding="utf-8"))) == ["card_id", "built_at", "draft", "pictures", "public"]
    assert Presentation(info["pptx"]).core_properties.keywords == ""
    assert "판:" not in pathlib.Path(info["md"]).read_text(encoding="utf-8")
    led = pathlib.Path(info["picture_ledger"]).read_text(encoding="utf-8")
    assert "판:" not in led and "바꾼 장" not in led and "권리 확인 대기" not in led
    assert not B.registry_file().exists() and PIC.public_check(d)[0] == 0


def test_registry_file_is_the_default_registry_in_the_real_layout():
    """빌드가 덧붙이는 대장과 public_check 가 읽는 기본 대장은 실제 자리에서 같은 파일이다."""
    assert B.DRAFTS == B.ROOT / "private" / "decks" / "drafts"            # 이 시험은 DRAFTS 를 바꾸지 않았다
    assert B.registry_file() == REAL_REGISTRY == PIC.ROOT / "private" / "decks" / "private_only_registry.jsonl"


# ── 등록 대장과 public_check ──────────────────────────────────────────────

def test_register_private_skips_known_hashes(tmp_path):
    reg = tmp_path / "r" / "reg.jsonl"
    rows = [{"sha256": "a" * 64, "what": "막는 그림", "name": "p1"}, {"sha256": "z" * 64, "what": "pptx", "name": "x.pptx"}]
    assert PIC.register_private(rows, reg) == 1                          # 'z'*64 는 16진이 아니다 — 적지 않는다
    assert PIC.register_private(rows + [{"sha256": "c" * 64, "what": "pdf", "name": "x.pdf"}], reg) == 1
    got, problems = PIC.registry_rows([reg])
    assert set(got) == {"a" * 64, "c" * 64} and problems == []
    assert PIC.registry_rows([tmp_path / "없는 대장.jsonl"]) == ({}, [])


def test_public_check_reads_edition_registry_and_fails_closed(desk, arts, tmp_path, monkeypatch):
    from pptx import Presentation
    reg = B.registry_file()
    sp = V.spec_of([photo("p2")]) | {"pictures": [entry(arts["ok"], pid="p2")]}
    pptx = tmp_path / "o" / "clean.pptx"
    B.build_pptx(sp, {}, {"card_id": CARD}, pptx)
    assert PIC.public_check(pptx)[0] == 0
    # 폴더: 공개_가부.json 의 판이 비공개판이면 막는 그림 목록이 비어도 막는다
    (pptx.parent / PIC.PUBLIC_FILE).write_text(json.dumps({"public_ok": False, "blocking": [], "edition": PRIV}, ensure_ascii=False), encoding="utf-8")
    code, lines = PIC.public_check(pptx.parent)
    assert code == 1 and "그 밖 1건" in lines[0] and "판이 비공개판이다" in lines[1]
    (pptx.parent / PIC.PUBLIC_FILE).write_text(json.dumps({"public_ok": True, "blocking": [], "edition": SWAP}, ensure_ascii=False), encoding="utf-8")
    assert PIC.public_check(pptx.parent)[0] == 0
    # 문서 속성의 판 표시만 남은 pptx
    prs = Presentation(str(pptx))
    prs.core_properties.keywords = "ozl:edition=private"
    marked = tmp_path / "marked.pptx"
    prs.save(str(marked))
    assert PIC.public_check(marked)[0] == 1
    # 미디어 해시: 문서 속성이 없어도 안에 든 그림이 대장에 있으면 막는다
    PIC.register_private([{"sha256": PIC.file_sha256(arts["ok"]), "what": "막는 그림", "name": "p2", "card_id": CARD, "built_at": "x"}], reg)
    code, lines = PIC.public_check(pptx)
    assert code == 1 and any("ppt/media/" in x and "비공개 등록 대장에 있다(막는 그림 · p2" in x for x in lines), lines
    assert PIC.public_check(pptx, registries=[])[0] == 0                 # 대장을 주지 않으면 견줄 것이 없다(인자는 시험용)
    # 파일 해시: png · pdf
    assert PIC.public_check(arts["ok"])[0] == 1 and PIC.public_check(arts["press"])[0] == 0
    assert render_main(["public-check", str(arts["ok"])]) == 1
    assert PIC.public_check(tmp_path / "글.txt")[0] == 2
    # 환경 변수는 대장을 더할 뿐이다
    other = tmp_path / "other.jsonl"
    PIC.register_private([{"sha256": PIC.file_sha256(arts["press"]), "what": "막는 그림", "name": "p1"}], other)
    monkeypatch.setenv(PIC.REGISTRY_ENV, str(other))
    assert PIC.registry_paths()[0] == PIC.REGISTRY and other in PIC.registry_paths()
    assert PIC.public_check(arts["press"])[0] == 1 and PIC.public_check(arts["ok"])[0] == 1
    # 깨진 줄이 있으면 통과시키지 않는다
    monkeypatch.delenv(PIC.REGISTRY_ENV)
    reg.write_text(reg.read_text(encoding="utf-8") + "{깨진 줄\n", encoding="utf-8")
    code, lines = PIC.public_check(arts["press"])
    assert code == 1 and any("읽지 못했다" in x for x in lines)


# ── 검토 묶음과 비교표 ────────────────────────────────────────────────────

def test_bundle_carries_private_edition_and_lists_swapped_slides(desk, arts, tmp_path, capsys):
    save_records()
    f = write(tmp_path, two_spec(arts))
    out = C.DESK / "builds" / CARD / "reviews" / "b.md"
    assert render_main(["bundle", str(f), "--out", str(out)]) == 0
    head = json.loads(capsys.readouterr().out)
    assert head["check"] == "비공개판 통과 · 실패 0 · 경고 3 / 바꾼판 통과 · 실패 0 · 경고 4" or head["check"].startswith("비공개판 통과 · 실패 0")
    assert " / 바꾼판 통과 · 실패 0" in head["check"]
    text = out.read_text(encoding="utf-8")
    body, tail = text.split("## 바꾼 판에서 달라지는 장")
    assert "### 3쪽 · 배경 · photo_caption" in body and "[그림 파일] p1(검수 대장 pictures)" in body and "[그림 파일] p2" not in body
    tail = tail.split("## 인용한 검증 기록")[0]
    assert "- 3쪽: 원래 그림 p1(통신사·언론사 사진) → 바꾼 것 p2(CC BY) · 까닭: 보도 사진은 공개 판에 넣지 않는다" in tail
    assert "[그림 파일] p2(검수 대장 pictures)" in tail and "제목: 감자 창고 이야기" in tail and tail.count("### ") == 2
    assert "- c7 · 가상 섬 정책 누리집" in text
    g = write(tmp_path, two_spec(arts, swaps=False), "bare.yaml")
    assert render_main(["bundle", str(g), "--out", str(out.with_name("c.md"))]) == 1    # 바꾼판을 만들 수 없는 사양
    assert "바꾼판 실패 · 실패 2" in capsys.readouterr().out
    assert "바꾼 장 없음" in out.with_name("c.md").read_text(encoding="utf-8")


def test_bundle_of_a_plain_spec_has_no_edition_section(desk, arts, tmp_path):
    save_records()
    sp = V.spec_of([photo("p2")]) | {"pictures": [entry(arts["ok"], pid="p2")]}
    out = C.DESK / "builds" / CARD / "reviews" / "p.md"
    assert render_main(["bundle", str(write(tmp_path, sp)), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "바꾼 판에서 달라지는 장" not in text and "- 엄격 검사: 통과 · 실패 0" in text


def test_compare_picks_the_edition(arts):
    sp = two_spec(arts)
    got, name = CMP.edition_spec(sp)
    assert name == PRIV and got["slides"][3]["kind"] == "photo_caption" and not PIC.has_swaps(got)
    got, name = CMP.edition_spec(sp, SWAP)
    assert name == SWAP and got["slides"][3]["kind"] == "image_text"
    plain = PIC.strip_swaps(sp)
    assert CMP.edition_spec(plain, SWAP) == (plain, "")                   # swap 이 없는 사양(산출 폴더의 사본)은 그대로 잰다
    with pytest.raises(SystemExit):
        CMP.edition_spec(sp, "어느판")
    assert CMP.deck_metrics(CMP.edition_spec(sp)[0])["slides"] == CMP.deck_metrics(CMP.edition_spec(sp, SWAP)[0])["slides"] == 12
    assert CMP.copy_edition(pathlib.Path("spec_20990101_000000_비공개판.yaml")) == PRIV and CMP.copy_edition(pathlib.Path("s.yaml")) == ""


# ── 등록 대장이 없을 때의 알림, 이미 만든 판 채우기, 폴더 검사(재확인 지적 3 · 6) ──────

def test_public_check_says_when_there_is_no_registry_to_compare(arts, tmp_path, capsys):
    """등록 대장이 없거나 비면 해시를 견주지 못한다 — 종료 코드는 그대로 0 이고 알림 줄을 낸다('공개 가능'으로만 찍지 않는다)."""
    f = tmp_path / "쪽.png"
    f.write_bytes(arts["ok"].read_bytes())
    assert not PIC.REGISTRY.exists()
    code, lines = PIC.public_check(f)
    assert code == 0 and lines[0].startswith("[public-check] 공개 가능")
    assert len(lines) == 2 and lines[1].startswith(PIC.NOTICE) and "등록 대장이 없거나 비어 있어 파일 해시를 견주지 못했다" in lines[1]
    assert render_main(["public-check", str(f)]) == 0 and "견주지 못했다" in capsys.readouterr().out
    PIC.REGISTRY.write_text("\n", encoding="utf-8")                        # 빈 대장도 같다
    assert any(x.startswith(PIC.NOTICE) for x in PIC.public_check(f)[1])
    PIC.register_private([{"sha256": "a" * 64, "what": "pdf", "name": "x.pdf"}], PIC.REGISTRY)
    code, lines = PIC.public_check(f)
    assert code == 0 and len(lines) == 1                                  # 견줄 대장이 있으면 알림이 없다
    PIC.register_private([{"sha256": PIC.file_sha256(f), "what": "쪽 png", "name": f.name}], PIC.REGISTRY)
    code, lines = PIC.public_check(f)
    assert code == 1 and not any(x.startswith(PIC.NOTICE) for x in lines)


def _built_then_registry_lost(tmp_path, monkeypatch, arts):
    """두 판을 내보내기까지 만든 뒤 등록 대장을 지운다 — 대장이 생기기 전에 만든 비공개 판과 같은 상태다."""
    save_records()
    monkeypatch.setattr(B.deck, "to_pdf_png", _fake_export)
    monkeypatch.setattr(B, "MD2PDF", tmp_path / "없는 도구.py")
    out = B.build(write(tmp_path, two_spec(arts)), export=True)["editions"]
    before = _lines(B.registry_file())
    B.registry_file().unlink()
    return out, before


def test_register_private_fills_the_registry_from_built_editions(desk, arts, tmp_path, monkeypatch, capsys):
    """register-private 는 이미 만들어진 비공개 판(문서 속성에 표시가 있는 pptx)을 찾아 빌드가 적었을 줄을 대장에 채운다:
    막는 그림, pptx, pdf, 막는 그림이 든 쪽의 PNG. 채우기 전에는 통과하던 PDF 와 쪽 PNG 가 채운 뒤에는 막힌다. 바꾼판은 그대로 통과한다."""
    out, before = _built_then_registry_lost(tmp_path, monkeypatch, arts)
    a, b = out[PRIV], out[SWAP]
    da, db = pathlib.Path(a["dir"]), pathlib.Path(b["dir"])
    pa = sorted((da / f"{da.name}_png").glob("*.png"))
    pdf = pathlib.Path(a["pdf"])
    assert PIC.public_check(pdf)[0] == 0 and PIC.public_check(pa[2])[0] == 0          # 대장이 없다 — 통과한다(알림만)
    assert render_main(["register-private", str(B.DRAFTS.parent), "--dry-run"]) == 0
    assert "새로 적을 줄 6개" in capsys.readouterr().out and not B.registry_file().exists()
    assert render_main(["register-private", str(B.DRAFTS.parent)]) == 0
    msg = capsys.readouterr().out
    assert "비공개 판 1개" in msg and "새로 적은 줄 6개" in msg and "막는 그림 2 · pptx 1 · pdf 1 · 쪽 png 2" in msg
    after = _lines(B.registry_file())
    assert {(r["sha256"], r["what"], r["name"]) for r in after} == {(r["sha256"], r["what"], r["name"]) for r in before}   # 빌드가 적은 것과 같다
    assert all(r["card_id"] == CARD and r["dir"] == da.name and r["built_at"] for r in after)
    assert PIC.public_check(pdf)[0] == 1 and PIC.public_check(pa[2])[0] == 1 and PIC.public_check(pa[3])[0] == 1
    assert PIC.public_check(pa[0])[0] == 0                                # 막는 그림이 없는 쪽은 적지 않는다(바꾼판의 같은 쪽과 바이트가 같다)
    assert PIC.public_check(arts["press"])[0] == 1 and PIC.public_check(da)[0] == 1
    assert PIC.public_check(db)[0] == 0 and PIC.public_check(pathlib.Path(b["pdf"]))[0] == 0
    assert render_main(["register-private"]) == 0                          # 인자가 없으면 대장이 있는 폴더 아래 — 다시 돌려도 더 적지 않는다
    assert "새로 적은 줄 0개" in capsys.readouterr().out and len(_lines(B.registry_file())) == 6
    assert render_main(["register-private", str(tmp_path / "없는 폴더")]) == 2 and render_main(["register-private", "--모르는옵션"]) == 2


def test_register_private_without_the_folder_files_registers_every_page(desk, arts, tmp_path, monkeypatch, capsys):
    """공개_가부.json 도 그림 검수 대장도 없는 비공개 판은 막는 그림이 든 쪽을 알 수 없다 — 쪽 PNG 를 전부 적고 알린다(더 막는 쪽을 고른다)."""
    out, _ = _built_then_registry_lost(tmp_path, monkeypatch, arts)
    da = pathlib.Path(out[PRIV]["dir"])
    (da / PIC.PUBLIC_FILE).unlink()
    for f in da.glob("그림_검수대장_*.json"):
        f.unlink()
    rows, notes = PIC.backfill_rows(da / f"{da.name}.pptx")
    assert [r["what"] for r in rows] == ["pptx", "pdf"] + ["쪽 png"] * 12
    assert any("파일 해시를 찾지 못했다" in n and "p1, p3" in n for n in notes) and any("쪽 PNG 12장을 전부" in n for n in notes)
    assert PIC.backfill_rows(pathlib.Path(out[SWAP]["pptx"])) == ([], [])  # 바꾼판은 비공개 판 표시가 없다 — 적지 않는다
    broken = B.DRAFTS / "깨진 덱.bin"
    import zipfile
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("ppt/presentation.xml", "<지어낸 내용/>")
    assert render_main(["register-private", str(B.DRAFTS)]) == 1           # 열지 못한 덱이 있으면 종료 1 로 알린다(나머지는 적는다)
    msg = capsys.readouterr().out
    assert "검사 불가" in msg and "깨진 덱.bin" in msg and "비공개 판 1개" in msg


def test_folder_check_reads_every_file_by_content(arts, tmp_path):
    """폴더 검사는 *.pptx · *.pdf · *_png/*.png 만이 아니라 폴더 안의 모든 파일을 하위 폴더까지, 파일 안을 보고 가린다."""
    from pptx import Presentation
    d = tmp_path / "산출"
    (d / "하위" / "더 아래").mkdir(parents=True)
    (d / "읽어 보기.txt").write_text("지어낸 글", encoding="utf-8")
    assert PIC.public_check(d)[0] == 0 and PIC.public_check(tmp_path / "빈 폴더")[0] == 2
    (tmp_path / "빈 폴더").mkdir()
    assert PIC.public_check(tmp_path / "빈 폴더")[0] == 2
    PIC.register_private([{"sha256": PIC.file_sha256(arts["press"]), "what": "막는 그림", "name": "p1"}], PIC.REGISTRY)
    (d / "하위" / "더 아래" / "그림.dat").write_bytes(arts["press"].read_bytes())      # 하위 폴더의 다른 이름
    code, lines = PIC.public_check(d)
    assert code == 1 and any("하위/더 아래/그림.dat 파일의 sha256 이 비공개 등록 대장에 있다" in x for x in lines), lines
    (d / "하위" / "더 아래" / "그림.dat").unlink()
    sp = V.spec_of([photo("p2")]) | {"pictures": [entry(arts["ok"], pid="p2")]}
    B.build_pptx(sp, {}, {"card_id": CARD}, tmp_path / "o" / "clean.pptx")
    prs = Presentation(str(tmp_path / "o" / "clean.pptx"))
    prs.core_properties.keywords = "ozl:private-only ozl:block=p9"
    prs.save(str(d / "하위" / "이름 바꾼 덱.bin"))                                      # 하위 폴더에 있는, 확장자를 바꾼 비공개 판
    code, lines = PIC.public_check(d)
    assert code == 1 and "막는 그림 1장: p9" in lines[0] and any("하위/이름 바꾼 덱.bin 문서 속성에" in x for x in lines), lines
    (d / "하위" / "이름 바꾼 덱.bin").unlink()
    (d / "하위" / "깨진.pptx").write_bytes(b"not a zip")                               # 볼 수 없는 파일이 하나라도 있으면 통과시키지 않는다
    code, lines = PIC.public_check(d)
    assert code == 1 and any("검사 불가" in x and "하위/깨진.pptx" in x for x in lines), lines


def test_public_check_command_reports_unreadable_files_instead_of_a_traceback(tmp_path, capsys):
    """덱 꼴인데 열 수 없는 파일을 주면 KeyError 로 끝나지 않고 '검사 불가' 줄과 종료 코드 1 이다."""
    import zipfile
    odd = tmp_path / "odd.ppsx"
    with zipfile.ZipFile(odd, "w") as f:
        f.writestr("ppt/presentation.xml", "<지어낸 내용/>")
    assert render_main(["public-check", str(odd)]) == 1
    msg = capsys.readouterr().out
    assert "검사 불가" in msg and "odd.ppsx" in msg and "프레젠테이션으로 열지 못했다" in msg
    broken = tmp_path / "broken.pptx"
    broken.write_bytes(b"not a zip")
    assert render_main(["public-check", str(broken)]) == 1
    assert "검사 불가" in capsys.readouterr().out
    assert PIC.public_check(odd)[0] == 1 and PIC.public_check(odd.parent)[0] == 1
