"""그림 넣기와 공개 차단(라-2) — 새 판정 '비공개 판에서만', 원문 화면 갈무리, AI 개념도 칸, 원출처 대조(origin_check), 맥락 점검(context_check),
그림 검수 대장 파일과 공개_가부.json, pptx 문서 속성 표시, public-check, 화면 갈무리 명령(shots.py)의 robots·차단 멈춤.
권리 확인 대기(결정 라)와 문서 속성의 판 표시도 여기서 본다. 두 판 빌드는 tests/test_deck_editions.py, 공개 게이트는 tests/test_publish_gate_deck.py.
생성 그림 칸(결정 다 — concept · concept_check · 프롬프트의 정해 둔 꼴 · 초안 모드에서도 실패하는 갈래)과 대장의 「생성 그림」 절,
화면 갈무리의 단계별 리다이렉트(robots 먼저)와 찍는 범위(--clip · --band)도 여기서 본다. 구역 차이와 원출처 대조의 상한은 tests/test_deck_origin.py.
네트워크는 127.0.0.1 의 가짜 서버만 쓴다(실제 웹 없음). Chrome 은 띄우지 않는다(가짜 실행기). 예시 문장, 이름, 주소는 전부 지어낸 것이다."""
from __future__ import annotations

import http.server
import json
import pathlib
import sys
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from test_deck_visuals import desk  # noqa: E402,F401  (pytest fixture)
from test_deck_kinds import AI_OK, CONTEXT_OK, ORIGIN_OK, entry  # noqa: E402
from ozl.render import build as B  # noqa: E402
from ozl.render import pictures as PIC  # noqa: E402
from ozl.render import shots as SH  # noqa: E402
from ozl.render import spec as S  # noqa: E402
from ozl.render.__main__ import main as render_main  # noqa: E402
from ozl.research import cards as C  # noqa: E402

CID, CARD, TEMPLATE = V.CID, V.CARD, V.TEMPLATE


@pytest.fixture(autouse=True)
def _tmp_registry(tmp_path, monkeypatch):
    """시험은 실제 비공개 등록 대장(private/decks/private_only_registry.jsonl)을 읽지도 쓰지도 않는다."""
    monkeypatch.setattr(PIC, "REGISTRY", tmp_path / "registry_for_test.jsonl")
    monkeypatch.delenv(PIC.REGISTRY_ENV, raising=False)


def _art(p: pathlib.Path, size=(800, 500)) -> pathlib.Path:
    """무늬가 있는 지어낸 그림(지각 해시가 의미 있게 갈리게)."""
    from PIL import Image, ImageDraw
    g = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(g)
    w, h = size
    for i in range(0, w, w // 20):
        y = (i * 7) % int(h * 0.8)
        d.rectangle([i, y, i + w // 27, y + h // 5], fill=(i % 255, 80, 200 - (i % 200)))
    d.ellipse([int(w * 0.37), int(h * 0.2), int(w * 0.75), int(h * 0.8)], fill=(20, 120, 40))
    g.save(p)
    return p


@pytest.fixture
def art(tmp_path):
    return _art(tmp_path / "art.png")


def press(png, pid="p3", **kw):
    e = entry(png, pid=pid, kind="통신사·언론사 사진", rights_holder="지어낸 통신사", attribution="사진: 지어낸 통신사", license="보도 사진(이용 허락 없음)",
              commercial_ok=False, modify_ok=False, source_url="https://news.example.org/photo/77", origin="지어낸 통신사 사진 기사",
              **ORIGIN_OK, **CONTEXT_OK)
    e.update(kw)
    return e


def screen(png, pid="p1", **kw):
    e = entry(png, pid=pid, kind="원문 화면 갈무리", source_url="https://www.stats.example.org/board/view?id=3", origin="가상 섬 통계청 화면을 찍었다",
              rights_holder="가상 섬 통계청", license="공공누리 제1유형", attribution="stats.example.org")
    e.update(kw)
    return e


def ai(png, pid="p4", **kw):
    e = entry(png, pid=pid, kind="AI 개념도", rights_holder="지어낸 제작팀", attribution="지어낸 제작팀 생성", license="자체 생성", **AI_OK)
    e.update(kw)
    return e


def photo(pid, **kw):
    base = {"stage": "배경", "kind": "photo_caption", "title": "감자밭", "picture": pid, "caption": "가상의 섬 풍경이다", "seconds": 20}
    base.update(kw)
    return base


def chk(slides, claims=None, pictures=(), draft=False):
    sp = V.spec_of(list(slides))
    sp["pictures"] = list(pictures)
    return S.check(sp, claims or {}, TEMPLATE, draft=draft, layout_fn=B.layout_problems, appendix_fn=B.appendix_problems)


# ── 판정 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,extra", [
    ("통신사·언론사 사진", {**ORIGIN_OK, **CONTEXT_OK}),
    ("화제 그림", {**ORIGIN_OK, **CONTEXT_OK}),
    ("공공누리 2유형", {"license": "공공누리 제2유형"}),
    ("공공누리 4유형", {"license": "공공누리 제4유형", "modify_ok": False}),
    ("비상업(NC) 라이선스 그림", {"license": "CC BY-NC 4.0"}),
])
def test_private_only_kinds_pass_both_modes_and_block_public(art, kind, extra):
    e = entry(art, kind=kind, commercial_ok=False, **extra)
    verdict, why, _ = PIC.judge(e)
    assert verdict == PIC.PRIVATE_ONLY and not why, why        # 상업적 이용이 안 되어도 실패가 아니다
    assert not PIC.judge(e, draft=True)[1]
    assert PIC.public_block(e)
    rep = chk([photo("p1")], pictures=[e])
    assert rep.ok, rep.errors


@pytest.mark.parametrize("kind", ["방송 화면 캡처", "실존 인물 AI 그림", "사실처럼 보이는 AI 장면"])
def test_never_kinds_stay_never(art, kind):
    verdict, why, _ = PIC.judge(entry(art, kind=kind))
    assert verdict == PIC.NEVER and why and PIC.judge(entry(art, kind=kind), draft=True)[1]


def test_commercial_false_still_never_for_ordinary_kinds(art):
    assert PIC.judge(entry(art, commercial_ok=False))[0] == PIC.NEVER   # CC BY 인데 상업적 이용이 안 된다고 적으면 칸끼리 어긋난다


def test_nc_kind_needs_nc_condition_and_as_is_with_nd(art):
    why = PIC.judge(entry(art, kind="비상업(NC) 라이선스 그림", license="CC BY 4.0", commercial_ok=False))[1]
    assert any("['NC'] 조건이 없다" in x for x in why), why
    e = entry(art, kind="비상업(NC) 라이선스 그림", license="CC BY-NC-ND 4.0", commercial_ok=False, modify_ok=False, as_is=False, edits="잘랐다")
    assert any("원형 그대로(as_is: true)만" in x for x in PIC.judge(e)[1])
    assert any("NC" in x for x in PIC.judge(entry(art, license="CC BY-NC 4.0"))[1])   # 'CC BY' 종류로 NC 그림을 올리면 그대로 실패


def test_old_ledger_entries_pass_without_new_fields(art):
    """옛 대장 고정본(새 칸 없는 CC BY · 공공누리 1유형 · 직접 그린 도표)은 그대로 통과한다 — 새 칸은 그 종류에서만 요구한다."""
    for e in (entry(art), entry(art, kind="공공누리 1유형", license="공공누리 제1유형"), entry(art, kind="직접 그린 도표")):
        assert not PIC.judge(e)[1], e["kind"]
        assert not PIC.public_block(e)
    rep = chk([photo("p1")], pictures=[entry(art)])
    assert rep.ok and PIC.public_status(V.spec_of([photo("p1")]) | {"pictures": [entry(art)]})["public_ok"]


# ── 원출처 대조 · 맥락 점검 ───────────────────────────────────────────────

def test_origin_and_context_are_required_for_press_meme_viral_logo(art):
    for kind in ("통신사·언론사 사진", "화제 그림", "밈", "로고"):
        e = entry(art, kind=kind, commercial_ok=kind not in ("통신사·언론사 사진", "화제 그림"), meme_origin="가상 게시판", license="상표")
        why = PIC.judge(e, draft=True)[1]
        assert any("원출처 대조(origin_check" in x for x in why), (kind, why)
        assert any("맥락 점검(context_check" in x for x in why) == (kind != "로고"), (kind, why)
    e = press(art, context_check={"spread": "가상 누리집", "mockery": "", "manipulation": "없음"})
    assert any("context_check.mockery" in x for x in PIC.judge(e)[1])


def test_origin_distance_limit_and_recheck(art, tmp_path):
    from PIL import Image, ImageDraw
    orig = tmp_path / "orig.png"
    Image.open(art).resize((1600, 1000)).save(orig)       # 원 게시처의 큰 원본 — 줄인 사본과 거리 0
    d = PIC.phash_distance(art, orig)
    assert d <= PIC.PHASH_MAX
    oc = {"url": "https://news.example.org/photo/77", "sha256": PIC.file_sha256(orig), "phash_distance": d,
          "checked_at": "2099-01-02T10:00:00+09:00", "original_path": str(orig)}
    assert not PIC.judge(press(art, origin_check=oc))[1]
    bad = tmp_path / "painted.png"
    g = Image.open(art).copy()
    ImageDraw.Draw(g).rectangle([0, 0, 400, 500], fill="black")   # 덧칠한 사본
    g.save(bad)
    far = PIC.phash_distance(bad, orig)
    assert far > PIC.PHASH_MAX
    why = PIC.judge(press(bad, origin_check={**oc, "phash_distance": far}, sha256=PIC.file_sha256(bad)))[1]
    assert any("상한" in x and "넘는다" in x for x in why), why
    why = PIC.judge(press(bad, origin_check=oc, sha256=PIC.file_sha256(bad)))[1]   # 거리를 작게 적어도 다시 재서 잡는다
    assert any("다시 재니" in x for x in why), why
    why = PIC.judge(press(art, origin_check={**oc, "sha256": "b" * 64}))[1]
    assert any("받은 파일 해시" in x for x in why), why
    why = PIC.judge(press(art, origin_check={"url": "없음", "phash_distance": "가까움"}))[1]
    assert sum("origin_check" in x for x in why) >= 3, why


def test_origin_cli_prints_block(art, tmp_path, capsys):
    from PIL import Image
    orig = tmp_path / "o.png"
    Image.open(art).save(orig)
    assert render_main(["origin", str(art), str(orig), "--url", "https://news.example.org/photo/77"]) == 0
    out = capsys.readouterr().out
    assert "phash_distance: 0" in out and "받는다" in out
    assert render_main(["origin", str(art)]) == 2


# ── AI 개념도 · 원문 화면 갈무리 ─────────────────────────────────────────

def test_ai_concept_needs_generator_prompt_time(art):
    assert not PIC.judge(ai(art))[1]
    for k in ("generator", "prompt", "generated_at"):
        e = ai(art)
        e.pop(k)
        assert any(k in x for x in PIC.judge(e)[1]), k
    assert any("시각으로 읽지 못했다" in x for x in PIC.judge(ai(art, generated_at="어제"))[1])


def test_generated_picture_must_be_a_concept_diagram(art):
    """결정 다: 생성 그림은 개념도만. 갈래 다섯 — 개념도 아님, 점검 칸에 참, 칸 빠짐, 다른 종류에 생성 그림 칸, 프롬프트의 정해 둔 꼴."""
    assert not PIC.judge(ai(art))[1] and not PIC.hard_block(ai(art))
    # ① 개념도가 아니다(concept 가 참이 아니다 — 거짓이거나 칸이 없다)
    for bad in ({"concept": False}, {"concept": None}, {"concept": "예"}):
        e = ai(art, **bad)
        assert any("개념도 여부(concept)" in x for x in PIC.judge(e)[1]), bad
        assert PIC.hard_block(e), bad
    # ② 점검 칸에 참이 있다
    for k in PIC.CONCEPT_CHECKS:
        e = ai(art, concept_check={**dict.fromkeys(PIC.CONCEPT_CHECKS, False), k: True})
        assert any(f"concept_check.{k} — " in x and "참이다" in x for x in PIC.judge(e)[1]), k
        assert any(k in x for x in PIC.hard_block(e)), k
    # ③ 칸이 빠졌다(점검 칸이 없거나 덜 찼다) — 엄격 실패, 초안은 그림 대기(hard_block 은 비어 있다)
    e = ai(art)
    e.pop("concept_check")
    assert any("개념도 점검(concept_check" in x for x in PIC.judge(e)[1]) and not PIC.hard_block(e)
    e = ai(art, concept_check={"people": False, "real_place": False, "photoreal": "아님"})
    why = PIC.judge(e)[1]
    assert any("concept_check.photoreal" in x for x in why) and any("concept_check.logo_text" in x for x in why) and not PIC.hard_block(e)
    # ④ 다른 종류의 줄에 생성 그림 칸이 있다(종류를 바꿔 적은 생성 그림)
    for k in PIC.GENERATED_FIELDS:
        e = entry(art, **{k: AI_OK[k]})
        assert any("종류를 'AI 개념도' 로 적는다" in x for x in PIC.judge(e)[1]), k
        assert PIC.hard_block(e), k
    assert not PIC.hard_block(entry(art)) and not PIC.hard_block(press(art))
    e = entry(art, kind="사실처럼 보이는 AI 장면", generator="가상 그림 모델 1판")
    assert any("개념도('AI 개념도')만 쓴다" in x for x in PIC.hard_block(e))
    # ⑤ 프롬프트에 사실처럼 보이게 하라는 정해 둔 꼴
    for prompt in ("빈 들판 위 상자 세 개, photorealistic", "실사풍으로 그린 빈 창고", "실제 사진처럼 보이는 감자밭", "hyper realistic boxes on a field"):
        why = PIC.judge(ai(art, prompt=prompt))[1]
        assert any("사실처럼 보이게 하라는 말" in x for x in why), prompt
    for prompt in ("상자 세 개와 화살표로 그린 흐름 도식, not photorealistic", "실사풍이 아닌 납작한 도식", "사진처럼 보이는 질감을 넣지 않는다",
                   "flat diagram without any photorealistic texture"):
        assert not PIC.judge(ai(art, prompt=prompt))[1], prompt
    assert PIC.prompt_realism("사진처럼 보이게, 글자는 넣지 않는다") == "사진처럼 보이"   # 부정은 같은 마디 안에서만 센다


def test_generated_hard_block_fails_in_draft_too(art):
    """개념도가 아닌 생성 그림과 종류를 바꿔 적은 생성 그림은 초안 모드에서도 실패다([그림 대기]로 미루지 않는다). 칸이 덜 찬 것은 그림 대기."""
    for e in (ai(art, pid="p1", concept=False), ai(art, pid="p1", concept_check={**dict.fromkeys(PIC.CONCEPT_CHECKS, False), "people": True}),
              entry(art, generator="가상 그림 모델 1판", prompt="감자밭 사진")):
        for draft in (True, False):
            rep = chk([photo("p1")], pictures=[e], draft=draft)
            assert not rep.ok and not rep.pending, (e["kind"], draft)
        rep = chk([photo("p1")], pictures=[e], draft=True)
        assert any("초안 모드에서도 실패다" in x for x in rep.errors), rep.errors
    waiting = ai(art, pid="p1")
    waiting.pop("concept_check")
    for e in (waiting, ai(art, pid="p1", prompt="실사풍으로 그린 빈 창고")):
        assert not chk([photo("p1")], pictures=[e]).ok
        rep = chk([photo("p1")], pictures=[e], draft=True)
        assert rep.ok and rep.pending[3] == [S.WAIT_IMAGE + "p1"], rep.errors
    assert chk([photo("p1")], pictures=[ai(art, pid="p1")]).ok


def test_ledger_has_a_generated_section(art):
    sp = V.spec_of([photo("p4", caption="상자 세 개로 그린 개념도다"), photo("p2", caption="가상 사진가의 사진이다")])
    sp["pictures"] = [ai(art), entry(art, pid="p2")]
    rows = PIC.ledger_report(sp)
    gen = next(r for r in rows if r["id"] == "p4")
    assert gen["concept"] is True and gen["prompt"] == AI_OK["prompt"] and gen["generated_at"] == AI_OK["generated_at"]
    assert gen["concept_check"] == dict.fromkeys(PIC.CONCEPT_CHECKS, False)
    assert "concept" not in next(r for r in rows if r["id"] == "p2")          # 생성 그림이 아닌 행은 지금까지와 같다
    md = PIC.ledger_md(rows, PIC.public_status(sp), CARD, "20990102_100000")
    page = gen["pages"][0]
    assert "## 생성 그림" in md and f"| p4 | {page} | 가상 그림 모델 1판 | 2099-01-02T09:00:00+09:00 | 예 | 사람 없음 · 실제 건물이나 장소 없음" in md
    assert f"- p4: {AI_OK['prompt']}" in md                                   # 프롬프트 전문
    sp2 = V.spec_of([photo("p2")]) | {"pictures": [entry(art, pid="p2")]}
    assert "## 생성 그림" not in PIC.ledger_md(PIC.ledger_report(sp2), PIC.public_status(sp2), CARD, "20990102_100000")


def test_ai_concept_without_file_waits_in_draft_fails_in_strict(tmp_path):
    e = ai(tmp_path / "아직 없는 생성 그림.png", pid="p1", sha256="c" * 64)
    rep = chk([photo("p1")], pictures=[e])
    assert any("생성 그림 파일이 아직 없다" in x for x in rep.errors), rep.errors
    rep = chk([photo("p1")], pictures=[e], draft=True)
    assert rep.ok and rep.pending[3] == [S.WAIT_IMAGE + "p1"]


def test_screen_capture_host_must_match_cited_record(desk, art):
    c = V.machine_claim(desk, image=False)                     # 원문 https://stats.example.org/potato.html
    sl = photo("p1", claim_ids=[CID], caption="가상 섬 통계청 화면이다")
    rep = chk([sl], {CID: c}, pictures=[screen(art)])
    assert rep.ok, rep.errors
    assert PIC.credit_lines(screen(art)) == ["원문: www.stats.example.org"]
    rep = chk([sl], {CID: c}, pictures=[screen(art, source_url="https://other.example.net/x")])
    assert any("기관 호스트 'example.net'" in x for x in rep.errors), rep.errors
    rep = chk([photo("p1")], {}, pictures=[screen(art)])
    assert any("claim_ids 에 있어야 한다" in x for x in rep.errors), rep.errors


def test_org_host():
    assert PIC.org_host("https://www.stats.go.kr/a") == "stats.go.kr"
    assert PIC.org_host("https://kosis.kr/b") == "kosis.kr"
    assert PIC.org_host("https://m.news.example.co.uk/c") == "example.co.uk"
    assert PIC.org_host("https://sub.stats.example.org") == "example.org"


# ── 공개 차단: 문서 속성 · public-check · 빌드 산출 ───────────────────────

def test_build_pptx_marks_private_and_public_check(desk, art, tmp_path):
    from pptx import Presentation
    sp = V.spec_of([photo("p1"), photo("p3")])
    sp["pictures"] = [entry(art), press(art)]
    out = tmp_path / "o" / "private.pptx"
    info = B.build_pptx(sp, {}, {"card_id": CARD}, out)
    assert info["public_ok"] is False
    assert Presentation(str(out)).core_properties.keywords == f"{PIC.PRIVATE_KEYWORD} ozl:block=p3"
    code, lines = PIC.public_check(out)
    assert code == 1 and "p3" in lines[0]
    sp2 = V.spec_of([photo("p1")])
    sp2["pictures"] = [entry(art)]
    out2 = tmp_path / "o" / "public.pptx"
    info2 = B.build_pptx(sp2, {}, {"card_id": CARD}, out2)
    assert "public_ok" not in info2                            # 막는 그림이 없으면 문서 속성도 빌드 출력도 그대로(옛 사양 출력 불변)
    assert Presentation(str(out2)).core_properties.keywords == ""
    assert PIC.public_check(out2)[0] == 0
    assert render_main(["public-check", str(out)]) == 1 and render_main(["public-check", str(out2)]) == 0
    assert render_main(["public-check", str(tmp_path / "없음")]) == 2


def test_rights_pending_host_keeps_verdict_and_blocks_public(desk, art, tmp_path):
    """결정 라: 권리 확인 대기 호스트(korea.kr)의 원문 화면 갈무리는 판정이 '쓴다' 그대로이고 공개만 막힌다."""
    from pptx import Presentation
    gov = {**V.old_claim(), "source": {"url": "https://www.korea.kr/briefing/view?id=0", "publisher": "가상 섬 정책 누리집", "tier": "T1"}}
    e = screen(art, source_url="https://www.korea.kr/briefing/view?id=0", rights_holder="가상 섬 정책 누리집", attribution="www.korea.kr")
    sl = photo("p1", claim_ids=[V.OLD], caption="가상 섬 정책 누리집 화면이다")
    rep = chk([sl], {V.OLD: gov}, pictures=[e])
    assert rep.ok, rep.errors                                  # 검사는 통과한다(판 하나의 사양 — 판 가르기는 check · build 명령이 한다)
    assert PIC.judge(e) == (PIC.USE, [], [])
    sp = V.spec_of([sl]) | {"pictures": [e]}
    st = PIC.public_status(sp)
    assert st["public_ok"] is False and "권리 확인 대기" in st["blocking"][0]["why"] and PIC.needs_two(sp)
    out = tmp_path / "o" / "pending.pptx"
    assert B.build_pptx(sp, {V.OLD: gov}, {"card_id": CARD}, out)["public_ok"] is False
    assert Presentation(str(out)).core_properties.keywords == f"{PIC.PRIVATE_KEYWORD} ozl:block=p1"
    assert PIC.public_check(out, registries=[])[0] == 1
    assert not PIC.public_block(screen(art)) and not PIC.needs_two(V.spec_of([photo("p1", claim_ids=[CID])]) | {"pictures": [screen(art)]})


def test_keywords_value_carries_the_edition():
    blocked = {"public_ok": False, "blocking": [{"id": "p3"}, {"id": "p5"}]}
    clear = {"public_ok": True, "blocking": []}
    assert PIC.keywords_value(blocked) == "ozl:private-only ozl:block=p3,p5" and PIC.keywords_value(clear) == ""   # 판을 가르지 않는 빌드는 그대로
    assert PIC.keywords_value(blocked, PIC.EDITION_PRIVATE) == "ozl:private-only ozl:block=p3,p5 ozl:edition=private"
    assert PIC.keywords_value(clear, PIC.EDITION_SWAP) == "ozl:edition=swap"
    assert PIC.keywords_value(clear, PIC.EDITION_PRIVATE) == "ozl:private-only ozl:edition=private"   # 목록이 비어도 비공개판은 막는다


def test_build_pptx_marks_the_edition(desk, art, tmp_path):
    from pptx import Presentation
    sp = V.spec_of([photo("p1"), photo("p3")]) | {"pictures": [entry(art), press(art)]}
    a, b = tmp_path / "o" / "a.pptx", tmp_path / "o" / "b.pptx"
    assert B.build_pptx(sp, {}, {"card_id": CARD}, a, edition=PIC.EDITION_PRIVATE)["public_ok"] is False
    assert Presentation(str(a)).core_properties.keywords == f"{PIC.PRIVATE_KEYWORD} ozl:block=p3 ozl:edition=private"
    sp2 = V.spec_of([photo("p1")]) | {"pictures": [entry(art)]}
    assert "public_ok" not in B.build_pptx(sp2, {}, {"card_id": CARD}, b, edition=PIC.EDITION_SWAP)
    assert Presentation(str(b)).core_properties.keywords == "ozl:edition=swap"
    assert PIC.public_check(a, registries=[])[0] == 1 and PIC.public_check(b, registries=[])[0] == 0


def _syuka_spec(art, tmp_path, with_press=True) -> dict:
    ai_png = _art(tmp_path / "ai.png", (1200, 800))
    pics = [screen(art), entry(art, pid="p2"), ai(ai_png)]
    slides = [photo("p1", claim_ids=[CID], caption="가상 섬 통계청 화면이다"), photo("p2", caption="가상 사진가의 감자밭 사진이다"),
              photo("p4", caption="상자 세 개로 그린 개념도다")]
    if with_press:
        pics.append(press(art))
        slides.append(photo("p3", caption="지어낸 통신사의 사진이다"))
    sp = V.spec_of(slides)
    sp["style"] = "syuka"
    sp["pictures"] = pics
    return sp


def test_strict_build_writes_ledger_and_public_file(desk, art, tmp_path, monkeypatch):
    """지어낸 사양(원문 갈무리 · CC BY 사진 · 보도 사진 · 파일 있는 AI 개념도)이 엄격 build 되고 public-check 가 1 과 보도 사진 번호를 낸다.
    보도 사진을 빼면 0. 보도 사진이 든 사양은 swap 이 없으면 기본 build 가 실패하고(두 판 — tests/test_deck_editions.py),
    --edition 비공개판 으로 그 판 하나를 만든다."""
    import yaml
    V.machine_claim(desk, image=False)
    C.save_yaml(C.card_path(CARD), {"card_id": CARD, "sources": [], "risks": ["지어낸 위험 문장"]})
    for with_press, want in ((True, 1), (False, 0)):
        monkeypatch.setattr(B, "DRAFTS", tmp_path / f"drafts_{with_press}" / "drafts")   # 같은 초에 두 번 빌드해도 폴더가 겹치지 않게(등록 대장도 따로)
        B.DRAFTS.mkdir(parents=True)
        p = tmp_path / f"spec_{with_press}.yaml"
        p.write_text(yaml.safe_dump(_syuka_spec(art, tmp_path, with_press), allow_unicode=True, sort_keys=False), encoding="utf-8")
        if with_press:
            with pytest.raises(SystemExit, match="swap 이 없다"):
                B.build(p, export=False)
            assert list(B.DRAFTS.iterdir()) == []                  # 검사에 실패하면 어느 폴더도 만들지 않는다
            info = B.build(p, export=False, edition=PIC.EDITION_PRIVATE)["editions"][PIC.EDITION_PRIVATE]
        else:
            info = B.build(p, export=False)
        d = pathlib.Path(info["dir"])
        st = json.loads((d / PIC.PUBLIC_FILE).read_text(encoding="utf-8"))
        assert st["public_ok"] is (not with_press)
        assert [b["id"] for b in st["blocking"]] == (["p3"] if with_press else [])
        led = json.loads(pathlib.Path(info["picture_ledger"]).with_suffix(".json").read_text(encoding="utf-8"))
        assert [r["id"] for r in led["pictures"]] == (["p1", "p2", "p4", "p3"] if with_press else ["p1", "p2", "p4"])
        assert {r["verdict"] for r in led["pictures"]} == ({"쓴다", "비공개 판에서만"} if with_press else {"쓴다"})
        md = pathlib.Path(info["picture_ledger"]).read_text(encoding="utf-8")
        assert ("공개 불가 — 막는 그림 p3" in md) is with_press and "| p4 |" in md
        assert "## 생성 그림" in md and f"- p4: {AI_OK['prompt']}" in md          # 대장 md 의 「생성 그림」 절(프롬프트 전문)
        p4 = next(r for r in led["pictures"] if r["id"] == "p4")
        assert p4["concept"] is True and p4["prompt"] == AI_OK["prompt"] and p4["concept_check"]["people"] is False
        code, lines = PIC.public_check(d)
        assert code == want, lines
        if with_press:
            assert "p3" in lines[0]


def test_old_style_build_writes_no_new_files(desk, art, tmp_path, monkeypatch):
    import yaml
    C.save_yaml(C.card_path(CARD), {"card_id": CARD, "sources": [], "risks": []})
    monkeypatch.setattr(B, "DRAFTS", tmp_path / "drafts")
    B.DRAFTS.mkdir()
    sp = V.spec_of([photo("p2")])
    sp["pictures"] = [entry(art, pid="p2")]
    p = tmp_path / "old.yaml"
    p.write_text(yaml.safe_dump(sp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    info = B.build(p, export=False)
    names = {x.name for x in pathlib.Path(info["dir"]).iterdir()}
    assert not any(n.startswith("그림_검수대장") or n == PIC.PUBLIC_FILE for n in names), names
    assert "picture_ledger" not in info and "public_ok" not in info


# ── 화면 갈무리(shots.py) — 가짜 서버 ──────────────────────────────────────

class _Server:
    def __init__(self, routes: dict[str, tuple[int, str]]):
        routes_ = routes
        self.hits: list[str] = []
        hits = self.hits

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                hits.append(self.path)
                status, body = routes_.get(self.path.split("?")[0], (404, "없다"))
                b = body.encode("utf-8")
                self.send_response(status)
                if status in (301, 302):
                    self.send_header("Location", body.replace("{port}", str(self.server.server_address[1])))
                self.send_header("Content-Type", "text/plain; charset=utf-8" if self.path == "/robots.txt" else "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    made = []

    def make(routes):
        s = _Server(routes)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


class FakeTime:
    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _clock(tmp_path, ft: FakeTime):
    return SH.HostClock(tmp_path / "hosts.json", sleep=ft.sleep, clock=ft.clock)


PAGE = "<html><body><h1>가상 섬 통계청</h1><p>지어낸 보도자료 목록이다.</p></body></html>"


def _fake_chrome(calls):
    def run(cmd, **kw):
        from PIL import Image
        calls.append(cmd)
        out = pathlib.Path(next(a for a in cmd if a.startswith("--screenshot="))[len("--screenshot="):])
        _art(out, (1280, 900))
        return type("R", (), {"returncode": 0, "stderr": ""})()
    return run


def test_shot_stops_when_robots_blocks(server, tmp_path):
    s = server({"/robots.txt": (200, "User-agent: *\nDisallow: /secret\n"), "/secret/page": (200, PAGE)})
    calls, logs, ft = [], [], FakeTime()
    with pytest.raises(SH.Stop, match="robots.txt 가 이 경로를 막는다"):
        SH.shot(s.base + "/secret/page", tmp_path / "x.png", clock=_clock(tmp_path, ft), run=_fake_chrome(calls), log=logs.append)
    assert calls == [] and s.hits == ["/robots.txt"]                 # 페이지도 Chrome 도 열지 않았다
    assert any(x.startswith("[robots]") and "막힘" in x for x in logs), logs
    assert not (tmp_path / "x.png").exists()


@pytest.mark.parametrize("robots,page,match", [
    ((500, "오류"), (200, PAGE), "규칙을 확인하지 못해"),
    ((403, "거부"), (200, PAGE), "막는다"),
    ((200, "User-agent: *\nAllow: /\n"), (200, PAGE.replace("</p>", "</p><div class='g-recaptcha'></div>")), "CAPTCHA"),
    ((200, "User-agent: *\nAllow: /\n"), (200, "<form><input type='password' name='pw'></form>"), "로그인"),
    ((404, "없다"), (429, "잦다"), "응답 429"),
])
def test_shot_stops_on_unknown_robots_block_captcha_login(server, tmp_path, robots, page, match):
    s = server({"/robots.txt": robots, "/board": page})
    calls = []
    with pytest.raises(SH.Stop, match=match):
        SH.shot(s.base + "/board", tmp_path / "x.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=lambda x: None)
    assert calls == []


def test_shot_takes_picture_with_gap_and_fresh_profile(server, tmp_path):
    s = server({"/robots.txt": (200, "User-agent: *\nDisallow: /private\n"), "/board": (200, PAGE)})
    calls, logs, ft = [], [], FakeTime()
    out = tmp_path / "shot.png"
    e = SH.shot(s.base + "/board", out, clock=_clock(tmp_path, ft), run=_fake_chrome(calls), log=logs.append)
    assert len(calls) == 1 and out.is_file()
    cmd = calls[0]
    assert "--headless=new" in cmd and any(a.startswith("--user-data-dir=") and "ozl-shot-" in a for a in cmd)
    assert not any("profile-directory" in a or "Default" in a for a in cmd)
    assert ft.sleeps and all(abs(x - SH.MIN_GAP) < 1e-9 for x in ft.sleeps) and len(ft.sleeps) == 2   # robots→페이지→Chrome 사이 2초씩
    assert e["kind"] == "원문 화면 갈무리" and e["sha256"] == PIC.file_sha256(out)
    assert e["shot_log"]["robots"]["allowed"] is True and e["shot_log"]["http_status"] == 200
    assert e["rights_holder"] == "" and e["commercial_ok"] is None    # 권리 칸은 비워 둔다 — 엄격 모드는 채우기 전에 실패
    assert any("허용" in x for x in logs if x.startswith("[robots]"))
    y = SH.write_draft(out, e)
    assert y.is_file() and "원문 화면 갈무리" in y.read_text(encoding="utf-8")
    assert "&id" not in y.read_text(encoding="utf-8") and "hops:" in y.read_text(encoding="utf-8")   # 초안을 잘라 붙여도 되게 YAML 별칭을 쓰지 않는다
    with pytest.raises(SH.Stop, match="이미 있다"):
        SH.shot(s.base + "/board", out, clock=_clock(tmp_path, ft), run=_fake_chrome(calls))


def test_shot_checks_robots_of_redirect_host(server, tmp_path):
    """다른 호스트(127.0.0.1 → localhost)로 넘어가면 그쪽 robots.txt 도 본다 — 막혀 있으면 Chrome 을 띄우지 않는다."""
    s = server({"/robots.txt": (200, "User-agent: *\nDisallow: /moved\n"), "/board": (302, "http://localhost:{port}/moved"), "/moved": (200, PAGE)})
    calls, logs = [], []
    with pytest.raises(SH.Stop, match="robots.txt 가 이 경로를 막는다"):
        SH.shot(s.base + "/board", tmp_path / "x.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=logs.append)
    assert calls == [] and sum(x.startswith("[robots]") for x in logs) == 2


ALLOW = (200, "User-agent: *\nAllow: /\n")


def test_shot_redirect_to_blocked_host_never_requests_its_page(server, tmp_path):
    """A → B(다른 호스트)로 넘어가라는 응답에서 B 의 robots.txt 가 그 경로를 막으면 B 의 페이지는 한 번도 요청하지 않는다."""
    b = server({"/robots.txt": (200, "User-agent: *\nDisallow: /landing\n"), "/landing": (200, PAGE)})
    a = server({"/robots.txt": ALLOW, "/start": (302, b.base + "/landing")})
    calls, logs = [], []
    with pytest.raises(SH.Stop, match="robots.txt 가 이 경로를 막는다") as x:
        SH.shot(a.base + "/start", tmp_path / "x.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=logs.append)
    assert b.hits == ["/robots.txt"]                                  # B 의 페이지 요청 0번
    assert a.hits == ["/robots.txt", "/start"] and calls == [] and not (tmp_path / "x.png").exists()
    hops = x.value.hops
    assert [h["n"] for h in hops] == [1, 2] and hops[0]["status"] == 302 and hops[0]["next"] == b.base + "/landing"
    assert hops[1]["robots"]["allowed"] is False and "status" not in hops[1] and "막는다" in hops[1]["stopped"]


def test_shot_redirect_to_allowed_host_checks_its_robots_first(server, tmp_path):
    b = server({"/robots.txt": ALLOW, "/landing": (200, PAGE)})
    a = server({"/robots.txt": ALLOW, "/start": (301, b.base + "/landing")})
    calls, logs, ft = [], [], FakeTime()
    e = SH.shot(a.base + "/start", tmp_path / "s.png", clock=_clock(tmp_path, ft), run=_fake_chrome(calls), log=logs.append)
    assert b.hits == ["/robots.txt", "/landing"]                      # robots 요청이 페이지 요청보다 먼저
    i_robots = next(i for i, x in enumerate(logs) if x.startswith("[robots]") and b.base in x)
    i_page = next(i for i, x in enumerate(logs) if x.startswith("[page]") and b.base in x)
    assert i_robots < i_page
    hops = e["shot_log"]["hops"]
    assert [(h["n"], h["status"]) for h in hops] == [(1, 301), (2, 200)] and hops[0]["next_via"] == "응답 301 의 Location"
    assert all(h["robots"]["allowed"] for h in hops) and hops[1]["via"] == "응답 301 의 Location"
    assert e["source_url"] == b.base + "/landing" and e["shot_log"]["final_url"] == b.base + "/landing" and calls[0][-1] == b.base + "/landing"
    assert e["shot_log"]["requested_url"] == a.base + "/start" and e["shot_log"]["robots"]["allowed"] is True
    assert all(abs(x - SH.MIN_GAP) < 1e-9 for x in ft.sleeps) and len(ft.sleeps) >= 3   # 두 서버가 같은 127.0.0.1 이라 요청마다 2초


def test_shot_meta_refresh_is_a_hop_and_robots_is_fetched_once_per_host(server, tmp_path):
    meta = '<html><head><meta http-equiv="refresh" content="0; url=/next"></head><body>옮겼다</body></html>'
    s = server({"/robots.txt": (200, "User-agent: *\nDisallow: /hidden\n"), "/start": (200, meta), "/next": (200, PAGE),
                "/trap": (200, meta.replace("/next", "/hidden/page")), "/hidden/page": (200, PAGE),
                "/self": (200, '<meta http-equiv="refresh" content="300">' + PAGE), "/late": (200, meta.replace("0; url", "60; url") + PAGE)})
    calls, logs = [], []
    e = SH.shot(s.base + "/start", tmp_path / "m.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=logs.append)
    assert s.hits == ["/robots.txt", "/start", "/next"]               # 같은 호스트의 robots.txt 는 한 번만 받는다
    assert [h["via"] for h in e["shot_log"]["hops"]] == ["요청한 주소", "meta refresh"] and e["shot_log"]["hops"][1]["robots"]["cached"] is True
    assert e["source_url"] == s.base + "/next"
    s.hits.clear()
    with pytest.raises(SH.Stop, match="robots.txt 가 이 경로를 막는다"):
        SH.shot(s.base + "/trap", tmp_path / "t.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=logs.append)
    assert s.hits == ["/robots.txt", "/trap"]                          # 막힌 경로는 요청하지 않았다
    assert SH.meta_refresh_target('<noscript><meta http-equiv="refresh" content="0; url=/nojs"></noscript>' + PAGE) == ""   # 스크립트를 켠 브라우저는 따르지 않는다
    assert SH.meta_refresh_target('<!-- <meta http-equiv="refresh" content="0; url=/old"> -->' + PAGE) == ""
    assert SH.meta_refresh_target("<META HTTP-EQUIV=Refresh CONTENT='3;URL=https://stats.example.org/x'>") == "https://stats.example.org/x"
    for path in ("/self", "/late"):                                    # 제자리 새로 고침과 늦은 이동은 단계가 아니다
        e = SH.shot(s.base + path, tmp_path / f"{path[1:]}.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=logs.append)
        assert len(e["shot_log"]["hops"]) == 1 and e["source_url"] == s.base + path


def test_shot_stops_after_max_hops_and_on_bad_locations(server, tmp_path):
    routes = {"/robots.txt": ALLOW, "/ftp": (302, "ftp://files.example.org/a.png"), "/js": (302, "javascript:alert(1)"),
              "/tologin": (302, "/member/login?next=/board"), "/login": (200, PAGE), "/r6": (200, PAGE)}
    routes.update({f"/r{i}": (302, f"/r{i + 1}") for i in range(1, 6)})
    s = server(routes)
    calls = []

    def run(path):
        return SH.shot(s.base + path, tmp_path / f"{path[1:]}.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=lambda x: None)
    with pytest.raises(SH.Stop, match=f"{SH.MAX_HOPS}단계를 받고도") as x:
        run("/r1")
    assert s.hits == ["/robots.txt"] + [f"/r{i}" for i in range(1, SH.MAX_HOPS + 1)]   # 여섯째 주소는 받지 않았다
    assert len(x.value.hops) == SH.MAX_HOPS
    for path, match in (("/ftp", r"http\(s\) 가 아니다"), ("/js", r"http\(s\) 가 아니다"), ("/tologin", "로그인 주소로 넘어가라는 응답")):
        s.hits.clear()
        with pytest.raises(SH.Stop, match=match):
            run(path)
        assert s.hits == ["/robots.txt", path]
    assert calls == []
    s2 = server({"/robots.txt": ALLOW, "/noloc": (302, ""), "/multi": (300, "고를 곳이 여럿이다")})
    with pytest.raises(SH.Stop, match="Location"):
        SH.shot(s2.base + "/noloc", tmp_path / "n.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=lambda x: None)
    with pytest.raises(SH.Stop, match="응답 300"):
        SH.shot(s2.base + "/multi", tmp_path / "m.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=lambda x: None)
    assert calls == []


def test_shot_follows_redirect_of_robots_txt_itself(server, tmp_path):
    """robots.txt 자체가 30x 면 따라가서 읽는다(막는 규칙을 놓치지 않는다)."""
    s = server({"/robots.txt": (301, "/robots_real.txt"), "/robots_real.txt": (200, "User-agent: *\nDisallow: /secret\n"),
                "/secret/a": (200, PAGE), "/board": (200, PAGE)})
    calls = []
    with pytest.raises(SH.Stop, match="막는다"):
        SH.shot(s.base + "/secret/a", tmp_path / "a.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=lambda x: None)
    assert s.hits == ["/robots.txt", "/robots_real.txt"] and calls == []
    assert SH.shot(s.base + "/board", tmp_path / "b.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=lambda x: None)["kind"] == "원문 화면 갈무리"


def test_shot_clip_keeps_only_the_chosen_box(server, tmp_path, monkeypatch):
    from PIL import Image
    s = server({"/robots.txt": ALLOW, "/board": (200, PAGE)})
    calls, logs = [], []
    out = tmp_path / "clip.png"
    e = SH.shot(s.base + "/board", out, clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=logs.append, clip=(100, 50, 400, 300))
    with Image.open(out) as g:
        assert g.size == (400, 300)
    log = e["shot_log"]
    assert log["clip"] == [100, 50, 400, 300] and log["window"] == "1280x900" and log["image"] == "400x300"
    assert e["as_is"] is True and e["sha256"] == PIC.file_sha256(out)      # 범위를 고른 것이지 찍은 뒤 고친 것이 아니다
    assert any("범위 100,50,400,300" in x for x in logs if x.startswith("[shot]"))
    e2 = SH.shot(s.base + "/board", tmp_path / "full.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=logs.append)
    assert "clip" not in e2["shot_log"] and e2["shot_log"]["image"] == "1280x900"
    s.hits.clear()
    with pytest.raises(ValueError, match="창\\(1280x900\\) 밖"):
        SH.shot(s.base + "/board", tmp_path / "bad.png", clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), clip=(1000, 0, 400, 300))
    assert s.hits == []                                                    # 범위가 틀리면 아무것도 요청하지 않는다
    monkeypatch.setattr(SH, "HOST_LOG", tmp_path / "h.json")
    assert render_main(["shot", s.base + "/board", "--out", str(tmp_path / "c.png"), "--clip", "1,2,3"]) == 2
    assert render_main(["shot", s.base + "/board", "--out", str(tmp_path / "c.png"), "--band", "0.1,0.5"]) == 2   # --band 는 --pdf 에만
    assert SH.parse_clip("0, 10, 300,400") == (0, 10, 300, 400) and SH.parse_band("0.2,0.55") == (0.2, 0.55)
    for bad in ("0.5,0.2", "0,1.2", "가,나"):
        with pytest.raises(ValueError):
            SH.parse_band(bad)



def test_shot_scale_multiplies_pixels_not_css_box(server, tmp_path, monkeypatch):
    """--scale 2: Chrome 에 배율을 넘기고, 범위는 CSS 픽셀 그대로 두어 그림 픽셀만 두 배가 된다. 1 이면 명령도 기록도 예전과 같다."""
    from PIL import Image
    s = server({"/robots.txt": ALLOW, "/board": (200, PAGE)})
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        k = next((float(a.split("=", 1)[1]) for a in cmd if a.startswith("--force-device-scale-factor=")), 1.0)
        _art(pathlib.Path(next(a for a in cmd if a.startswith("--screenshot="))[len("--screenshot="):]), (round(1280 * k), round(900 * k)))
        return type("R", (), {"returncode": 0, "stderr": ""})()
    e = SH.shot(s.base + "/board", tmp_path / "s2.png", clock=_clock(tmp_path, FakeTime()), run=run, log=lambda x: None,
                clip=(100, 50, 400, 300), scale=2)
    assert "--force-device-scale-factor=2" in calls[-1]
    with Image.open(tmp_path / "s2.png") as g:
        assert g.size == (800, 600)
    log = e["shot_log"]
    assert log["clip"] == [100, 50, 400, 300] and log["scale"] == 2 and log["image"] == "800x600"
    assert abs(PIC.screen_readable_pt(e, 4.0) - 14 * 4.0 / 400 * 72) < 1e-9          # 글자 어림은 CSS 폭(400)으로 잰다 — 배율과 무관
    e1 = SH.shot(s.base + "/board", tmp_path / "s1.png", clock=_clock(tmp_path, FakeTime()), run=run, log=lambda x: None, clip=(100, 50, 400, 300))
    assert not any(a.startswith("--force-device-scale-factor") for a in calls[-1]) and "scale" not in e1["shot_log"]
    with pytest.raises(ValueError, match="1~4"):
        SH.shot(s.base + "/board", tmp_path / "s5.png", clock=_clock(tmp_path, FakeTime()), run=run, scale=5)
    monkeypatch.setattr(SH, "HOST_LOG", tmp_path / "h.json")
    s.hits.clear()
    for bad in (["--scale", "가"], ["--scale", "9"], ["--scale", "0.5"], ["--scale"]):
        assert render_main(["shot", s.base + "/board", "--out", str(tmp_path / "c.png"), *bad]) == 2, bad
    assert s.hits == [] and not (tmp_path / "c.png").exists()                      # 틀린 배율은 요청 전에 거부한다
    for sc in ("1", "2"):                                                            # --pdf 와 함께면 값과 상관없이 사용법 오류
        assert render_main(["shot", "--pdf", str(tmp_path / "없는.pdf"), "--source-url", "https://stats.example.org/a.pdf",
                            "--out", str(tmp_path / "p.png"), "--scale", sc]) == 2


def test_shot_cli_scale_crops_the_css_box_at_n_times_pixels(server, tmp_path, monkeypatch):
    """CLI 의 --scale 2 --clip 100,50,400,300: 화면 그림의 (200,100)~(1000,700) 픽셀이 그대로 남는다(원점이 0,0 으로 밀리지 않는다)."""
    from PIL import Image
    s = server({"/robots.txt": ALLOW, "/board": (200, PAGE)})
    seen = []

    def fake_chrome_shot(url, out, width, height, run=None, chrome=None, scale=1.0):
        seen.append(scale)
        W, H = round(width * scale), round(height * scale)
        im = Image.new("RGB", (W, H))
        im.putdata([(x % 251, y % 241, (x // 251 + y // 241) % 256) for y in range(H) for x in range(W)])
        im.save(out)
    monkeypatch.setattr(SH, "chrome_shot", fake_chrome_shot)
    monkeypatch.setattr(SH, "HOST_LOG", tmp_path / "h.json")
    out = tmp_path / "cli2.png"
    assert render_main(["shot", s.base + "/board", "--out", str(out), "--clip", "100,50,400,300", "--scale", "2"]) == 0
    assert seen == [2.0]
    with Image.open(out) as g:
        assert g.size == (800, 600)
        for (x, y) in ((0, 0), (799, 0), (0, 599), (799, 599), (321, 207)):
            X, Y = x + 200, y + 100
            assert g.getpixel((x, y)) == (X % 251, Y % 241, (X // 251 + Y // 241) % 256), (x, y)

@pytest.mark.skipif(not SH.shutil.which("pdftoppm"), reason="pdftoppm 없음")
def test_pdf_band_keeps_the_height_range(tmp_path):
    from PIL import Image
    pdf = tmp_path / "copy.pdf"
    Image.open(_art(tmp_path / "pg.png")).convert("RGB").save(pdf)
    full = SH.pdf_page(pdf, 1, tmp_path / "full.png", "https://stats.example.org/doc.pdf", dpi=72, log=lambda x: None)
    with Image.open(tmp_path / "full.png") as g:
        w, h = g.size
    assert "band" not in full["shot_log"] and full["shot_log"]["page_px"] == f"{w}x{h}" and full["shot_log"]["dpi"] == 72
    e = SH.pdf_page(pdf, 1, tmp_path / "band.png", "https://stats.example.org/doc.pdf", dpi=72, log=lambda x: None, band=(0.2, 0.6))
    with Image.open(tmp_path / "band.png") as g:
        assert g.size == (w, round(h * 0.6) - round(h * 0.2))
    assert e["shot_log"]["band"] == [0.2, 0.6] and e["shot_log"]["page_px"] == f"{w}x{h}" and e["as_is"] is True
    assert e["sha256"] == PIC.file_sha256(tmp_path / "band.png") and "0.2~0.6 구간" in e["origin"]
    assert render_main(["shot", "--pdf", str(pdf), "--source-url", "https://stats.example.org/doc.pdf", "--out", str(tmp_path / "x.png"), "--clip", "0,0,10,10"]) == 2


def test_host_clock_persists_between_runs(tmp_path):
    ft = FakeTime()
    c1 = _clock(tmp_path, ft)
    c1.mark("stats.example.org")
    ft.t += 0.5
    c2 = _clock(tmp_path, ft)                                       # 다른 명령 실행(파일에서 읽는다)
    assert abs(c2.wait("stats.example.org") - 1.5) < 1e-9 and abs(ft.sleeps[-1] - 1.5) < 1e-9
    assert c2.wait("other.example.org") == 0.0


def test_shot_cli_returns_3_when_stopped(server, tmp_path, monkeypatch):
    s = server({"/robots.txt": (200, "User-agent: *\nDisallow: /\n")})
    monkeypatch.setattr(SH, "HOST_LOG", tmp_path / "h.json")
    assert render_main(["shot", s.base + "/a", "--out", str(tmp_path / "a.png")]) == 3
    assert render_main(["shot"]) == 2


@pytest.mark.parametrize("how", ["종료 1", "시간 초과"])
def test_failed_chrome_run_still_marks_the_host_and_ends_as_an_error(server, tmp_path, how):
    """Chrome 이 실패해도(그림을 남기지 않았다, 시간 초과) 그 호스트에 요청은 나갔다 — 마지막 요청 시각을 적어 다음 명령이 간격을 지킨다.
    시간 초과(subprocess.TimeoutExpired)도 RuntimeError 로 끝난다(명령이 traceback 으로 죽지 않는다)."""
    import subprocess
    s = server({"/robots.txt": (200, "User-agent: *\nAllow: /\n"), "/board": (200, PAGE)})
    ft = FakeTime()
    clock = _clock(tmp_path, ft)

    def run(cmd, **kw):
        ft.t += 30.0                                                  # Chrome 이 30초 동안 그 호스트에서 화면을 받았다
        if how == "시간 초과":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout", 0))
        return type("R", (), {"returncode": 1, "stderr": "지어낸 실패"})()
    with pytest.raises(RuntimeError, match="끝나지 않았다" if how == "시간 초과" else "그림을 남기지 않았다"):
        SH.shot(s.base + "/board", tmp_path / "x.png", clock=clock, run=run, log=lambda x: None)
    assert clock.last["127.0.0.1"] == ft.t                            # Chrome 이 끝난 시각 — 페이지를 받은 시각(30초 전)이 아니다
    assert json.loads((tmp_path / "hosts.json").read_text(encoding="utf-8"))["127.0.0.1"] == ft.t
    assert abs(_clock(tmp_path, ft).wait("127.0.0.1") - SH.MIN_GAP) < 1e-9   # 바로 다음 명령은 간격을 다 기다린다


def test_shot_cli_ends_with_code_1_on_subprocess_timeout(tmp_path, monkeypatch, capsys):
    """명령 줄: 바깥 도구의 시간 초과는 '[shot] 오류'와 종료 코드 1 이다(traceback 이 아니다) — 웹 화면 길과 PDF 길 둘 다."""
    import subprocess

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=["지어낸 도구"], timeout=120)
    monkeypatch.setattr(SH, "shot", timeout)
    assert render_main(["shot", "https://stats.example.org/a", "--out", str(tmp_path / "a.png")]) == 1
    assert "[shot] 오류" in capsys.readouterr().out
    pdf = tmp_path / "copy.pdf"
    pdf.write_bytes(b"%PDF-1.4 fabricated")
    monkeypatch.setattr(SH.shutil, "which", lambda name: "/지어낸/pdftoppm")
    monkeypatch.setattr(SH.subprocess, "run", timeout)
    assert render_main(["shot", "--pdf", str(pdf), "--source-url", "https://stats.example.org/doc.pdf", "--out", str(tmp_path / "p.png")]) == 1
    assert "[shot] 오류" in capsys.readouterr().out


@pytest.mark.skipif(not SH.shutil.which("pdftoppm"), reason="pdftoppm 없음")
def test_pdf_page_from_saved_copy(tmp_path):
    from PIL import Image
    pdf = tmp_path / "copy.pdf"
    Image.open(_art(tmp_path / "pg.png")).convert("RGB").save(pdf)
    e = SH.pdf_page(pdf, 1, tmp_path / "pdf_p1.png", "https://stats.example.org/doc.pdf", dpi=72, log=lambda x: None)
    assert (tmp_path / "pdf_p1.png").is_file() and e["kind"] == "원문 화면 갈무리"
    assert e["shot_log"]["web"] == "다시 열지 않음" and e["source_url"] == "https://stats.example.org/doc.pdf"
    with pytest.raises(SH.Stop):
        SH.pdf_page(tmp_path / "없음.pdf", 1, tmp_path / "z.png", "https://stats.example.org/doc.pdf")


def test_build_pptx_clears_template_props(desk, art, tmp_path):
    """python-pptx 기본 틀의 흔적(comments · last_modified_by · 2013년 시각)이 문서 속성에 남지 않는다. keywords 는 그대로."""
    from pptx import Presentation
    sp = V.spec_of([photo("p1"), photo("p3")])
    sp["pictures"] = [entry(art), press(art)]
    out = tmp_path / "o" / "props.pptx"
    B.build_pptx(sp, {}, {"card_id": CARD}, out)
    cp = Presentation(str(out)).core_properties
    assert cp.comments == "" and cp.last_modified_by == "" and cp.author == ""
    assert "python-pptx" not in (cp.comments + cp.last_modified_by + cp.title + cp.subject)
    assert cp.created.year >= 2026 and cp.modified.year >= 2026
    assert cp.keywords == f"{PIC.PRIVATE_KEYWORD} ozl:block=p3"   # 비공개 표시는 지우지 않는다


@pytest.mark.parametrize("how", ["종료 1", "시간 초과"])
def test_abnormal_chrome_exit_removes_the_leftover_png(server, tmp_path, how):
    """Chrome 이 그림을 쓰다가 비정상 종료하면(종료 코드, 시간 초과) 남은 PNG 를 지운다 — 다음 실행이 '출력 파일이 이미 있다'로 멈추지 않는다(재확인 지적 7)."""
    import subprocess
    s = server({"/robots.txt": (200, "User-agent: *\nAllow: /\n"), "/board": (200, PAGE)})
    out = tmp_path / "shot.png"

    def crash(cmd, **kw):
        _art(pathlib.Path(next(a for a in cmd if a.startswith("--screenshot="))[len("--screenshot="):]), (1280, 900))
        if how == "시간 초과":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout", 0))
        return type("R", (), {"returncode": 1, "stderr": "지어낸 실패"})()
    with pytest.raises(RuntimeError, match="끝나지 않았다.*지웠다" if how == "시간 초과" else "비정상 종료했다.*지웠다"):
        SH.shot(s.base + "/board", out, clock=_clock(tmp_path, FakeTime()), run=crash, log=lambda x: None)
    assert not out.exists()
    calls = []
    e = SH.shot(s.base + "/board", out, clock=_clock(tmp_path, FakeTime()), run=_fake_chrome(calls), log=lambda x: None)   # 바로 다시 찍을 수 있다
    assert out.is_file() and len(calls) == 1 and e["sha256"] == PIC.file_sha256(out)


def test_chrome_shot_does_not_delete_a_file_it_did_not_write(tmp_path):
    """chrome_shot 을 바로 부를 때: 실패해도 부르기 전부터 있던 파일은 지우지 않는다."""
    out = tmp_path / "있던 그림.png"
    _art(out, (640, 480))
    before = out.read_bytes()
    with pytest.raises(RuntimeError):
        SH.chrome_shot("https://stats.example.org/a", out, 1280, 900, run=lambda cmd, **kw: type("R", (), {"returncode": 1, "stderr": ""})())
    assert out.read_bytes() == before
