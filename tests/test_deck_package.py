"""pptx 틀 값 정리(deck.finish_package) — 문서 통계(docProps/app.xml)를 실제 값으로, 틀의 축소 그림과 인쇄 설정 파일 빼기.
저장하는 자리 네 곳(build.build_pptx · deck.build_prototype · replica.build · style.samples 의 다시 저장)이 모두 거치는지,
안에 든 그림의 바이트와 문서 속성 keywords 가 그대로인지 본다. 네트워크 없이 돈다. 그림은 PIL 로 그린 것이고 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys
import zipfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import test_deck_visuals as V  # noqa: E402
from test_deck_kinds import entry  # noqa: E402
from test_deck_pictures_policy import _art, photo  # noqa: E402
from ozl.render import build as B  # noqa: E402
from ozl.render import deck  # noqa: E402
from ozl.render import pictures as PIC  # noqa: E402
from ozl.render import style as ST  # noqa: E402

CARD = V.CARD
EP = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
VT = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"


def app(pptx) -> dict:
    """app.xml 에서 읽은 값 — 칸 이름 → 글, 그리고 pairs(HeadingPairs 의 짝)와 titles(TitlesOfParts)."""
    from lxml import etree
    with zipfile.ZipFile(pptx) as z:
        root = etree.fromstring(z.read("docProps/app.xml"))
    out = {el.tag.replace(EP, ""): (el.text or "") for el in root if not len(el)}
    cells = [v[0].text for v in root.find(EP + "HeadingPairs").iter(VT + "variant")]
    out["pairs"] = [(cells[k], int(cells[k + 1])) for k in range(0, len(cells), 2)]
    out["titles"] = [x.text for x in root.find(EP + "TitlesOfParts").iter(VT + "lpstr")]
    out["sizes"] = (int(root.find(EP + "HeadingPairs")[0].get("size")), int(root.find(EP + "TitlesOfParts")[0].get("size")))
    return out


def names(pptx) -> list[str]:
    with zipfile.ZipFile(pptx) as z:
        return z.namelist()


def read(pptx, name: str) -> str:
    with zipfile.ZipFile(pptx) as z:
        return z.read(name).decode("utf-8")


def template_left(pptx) -> list[str]:
    """틀이 남긴 것 — 축소 그림, 인쇄 설정 파일, 그 관계 줄과 종류 줄. 비어 있어야 한다."""
    out = [n for n in names(pptx) if "thumbnail" in n.lower() or "printersettings" in n.lower()]
    if "thumbnail" in read(pptx, "_rels/.rels"):
        out.append("_rels/.rels 의 thumbnail 관계")
    if "printerSettings" in read(pptx, "ppt/_rels/presentation.xml.rels"):
        out.append("presentation.xml.rels 의 printerSettings 관계")
    if re.search(r'Extension="bin"', read(pptx, "[Content_Types].xml")):
        out.append("[Content_Types].xml 의 bin 줄")
    return out


def test_unfinished_template_values_are_what_the_plan_measured():
    """고치기 전의 값 — python-pptx 기본 틀이 남기는 것(이 시험이 깨지면 틀이 바뀐 것이다)."""
    prs = deck.new_deck()
    deck._blank(prs)
    buf = io.BytesIO()
    prs.save(buf)
    a = app(buf)
    assert (a["Slides"], a["Notes"], a["Words"], a["PresentationFormat"], a["AppVersion"]) == ("0", "0", "0", "On-screen Show (4:3)", "14.0000")
    assert sorted(template_left(buf)) == sorted(["docProps/thumbnail.jpeg", "ppt/printerSettings/printerSettings1.bin", "_rels/.rels 의 thumbnail 관계",
                                                 "presentation.xml.rels 의 printerSettings 관계", "[Content_Types].xml 의 bin 줄"])


def test_finish_package_writes_real_counts_and_drops_template_files():
    from pptx import Presentation
    prs = deck.new_deck()
    for k in range(3):
        s = deck._blank(prs)
        deck.title(s, "감자 이야기 첫째 장")                      # 낱말 4개
        if k < 2:
            s.notes_slide.notes_text_frame.text = "노트 한 줄\n둘째 줄이다"   # 문단 2개, 낱말 5개
    prs.slides[2]._element.set("show", "0")                       # 숨긴 장
    prs.core_properties.keywords = "ozl:private-only ozl:block=p1"
    deck.clear_template_props(prs)
    got = deck.finish_package(prs)
    assert got == {"slides": 3, "notes": 2, "hidden": 1, "words": 3 * 4 + 2 * 5, "paragraphs": 3 + 2 * 2,
                   "dropped": ["/docProps/thumbnail.jpeg", "/ppt/printerSettings/printerSettings1.bin"]}
    buf = io.BytesIO()
    prs.save(buf)
    a = app(buf)
    assert (a["Slides"], a["Notes"], a["HiddenSlides"], a["Words"], a["Paragraphs"]) == ("3", "2", "1", "22", "7")
    assert a["PresentationFormat"] == deck.SCREEN_FORMAT == "Widescreen" and a["AppVersion"] == deck.APP_VERSION == "16.0000"
    assert a["Application"] == "Microsoft Macintosh PowerPoint"                       # 틀 값 그대로
    assert a["pairs"] == [("Theme", 1), (deck.SLIDE_TITLES, 3)]
    assert a["titles"] == ["Office Theme"] + [deck.SLIDE_TITLE] * 3                   # 쪽의 글을 문서 통계에 옮기지 않는다
    assert a["sizes"] == (2 * len(a["pairs"]), sum(n for _, n in a["pairs"])) == (4, 4)   # 두 표의 개수가 서로 맞는다
    assert template_left(buf) == []
    assert "jpeg" not in read(buf, "[Content_Types].xml")                             # 그림이 없는 덱에는 jpeg 기본 줄도 없다
    buf.seek(0)
    again = Presentation(buf)                                                         # 다시 열린다
    assert len(again.slides) == 3 and again.core_properties.keywords == "ozl:private-only ozl:block=p1"
    cp = again.core_properties
    assert cp.author == "" and cp.comments == "" and cp.last_modified_by == "" and cp.created.year >= 2026
    # 다시 열어 고친 뒤 한 번 더 거쳐도 값이 맞는다(견본집의 다시 저장)
    again.slides[0].notes_slide.notes_text_frame.text = "노트를 세 낱말로"
    st = deck.finish_package(again)
    assert st["dropped"] == [] and st["words"] == 22 - 5 + 3
    buf2 = io.BytesIO()
    again.save(buf2)
    b = app(buf2)
    assert b["Words"] == "20" and b["pairs"] == a["pairs"] and b["titles"] == a["titles"] and template_left(buf2) == []


def test_words_on_both_sides_of_a_line_break_are_counted_apart():
    """글은 어절 단위로 미리 줄을 나눠 줄바꿈(a:br)을 넣는다 — 줄 끝 낱말과 다음 줄 첫 낱말을 한 낱말로 세지 않는다. 위첨자 번호 조각은 앞 낱말에 붙어 있다."""
    prs = deck.new_deck()
    s = deck._blank(prs)
    B.draw_box(s, B.Box("본문", 1.0, 1.0, 2.2, 3.0, [B.Para("감자는 땅속에서 자란다 그리고 또 자란다", marks={2: "1"})]))
    tf = s.shapes[0].text_frame
    assert len(tf.paragraphs) == 1 and "\v" in tf.text                                # 한 문단 안에서 줄이 나뉘었다
    st = deck.deck_stats(prs)
    assert st["paragraphs"] == 1 and st["words"] == 6


def test_jpeg_pictures_keep_their_content_type_and_bytes(tmp_path):
    """jpeg 그림을 쓴 덱이면 jpeg 기본 줄은 남는다(틀의 축소 그림만 빠진다). 안에 든 그림의 바이트는 그대로다."""
    from PIL import Image
    jpg = tmp_path / "밭.jpg"
    Image.open(_art(tmp_path / "a.png")).convert("RGB").save(jpg, "JPEG", quality=85)
    sp = V.spec_of([photo("p1")]) | {"pictures": [entry(jpg, pid="p1")]}
    out = tmp_path / "o" / "d.pptx"
    B.build_pptx(sp, {}, {"card_id": CARD}, out)
    assert template_left(out) == [] and re.search(r'Extension="jp', read(out, "[Content_Types].xml"))
    media = PIC.pptx_media_hashes(out)
    assert [sha for _, sha in media] == [PIC.file_sha256(jpg)]
    assert not any("thumbnail" in n for n, _ in media)


def test_build_pptx_goes_through_finish_package_and_keeps_keywords(tmp_path):
    """막는 그림이 든 덱: 문서 속성 keywords 가 남고, 안에 든 그림의 해시가 대장의 그림 해시와 같다(틀 값 정리 뒤에도 그림으로 잡힌다)."""
    from pptx import Presentation
    from test_deck_pictures_policy import press
    art = _art(tmp_path / "press.png")
    sp = V.spec_of([photo("p1", caption="지어낸 통신사의 사진이다")]) | {"pictures": [press(art, pid="p1")]}
    out = tmp_path / "o" / "private.pptx"
    info = B.build_pptx(sp, {}, {"card_id": CARD}, out)
    a = app(out)
    n = info["total"]                                                                 # 옛 규칙이라 부록 쪽이 붙는다 — 장수는 본편과 부록을 더한 실제 쪽수다
    assert info["public_ok"] is False and n > len(sp["slides"]) and a["Slides"] == str(n) == str(len(Presentation(str(out)).slides))
    assert a["Notes"] == str(n) and a["pairs"][-1] == (deck.SLIDE_TITLES, n) and len(a["titles"]) == 1 + n and int(a["Words"]) > 0
    assert a["PresentationFormat"] == "Widescreen" and template_left(out) == []
    assert Presentation(str(out)).core_properties.keywords == "ozl:private-only ozl:block=p1"
    assert PIC.file_sha256(art) in {sha for _, sha in PIC.pptx_media_hashes(out)}


def test_every_save_site_goes_through_finish_package(tmp_path, monkeypatch):
    """저장하는 자리 네 곳: build_pptx(위 시험), build_prototype, replica.build, 견본집의 다시 저장."""
    from ozl.render import replica as R
    monkeypatch.setattr(deck, "DRAFTS", tmp_path / "drafts")
    proto = deck.build_prototype()
    a = app(proto)
    assert a["Slides"] == "5" and a["Notes"] == "5" and a["PresentationFormat"] == "Widescreen" and template_left(proto) == []
    spec = tmp_path / "replica.json"
    spec.write_text(json.dumps({"title": {"runs": [["감자 이야기", {}]], "x0": 92, "top": 71},
                                "body": {"x0": 500, "top": 211, "lines": [[["감자는 땅속에서 자란다", {}]]]}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(R, "SPEC", spec)
    monkeypatch.setattr(R, "OUT", tmp_path / "replica")
    rep = R.build()
    a = app(rep)
    assert a["Slides"] == "1" and a["Words"] == "5" and a["AppVersion"] == "16.0000" and template_left(rep) == []   # 제목 두 낱말, 본문 세 낱말
    info = ST.samples(tmp_path / "samples", export=False, link=None)
    a = app(info["pptx"])
    n = info["slides"]
    assert a["Slides"] == str(n) and a["Notes"] == str(n) and a["pairs"][-1] == (deck.SLIDE_TITLES, n) and template_left(info["pptx"]) == []
    from pptx import Presentation
    words = sum(len(t.split()) for s in Presentation(info["pptx"]).slides for t in
                [p.text for sh in s.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs] +
                [c.text for sh in s.shapes if sh.has_table for r in sh.table.rows for c in r.cells] +
                [p.text for p in s.notes_slide.notes_text_frame.paragraphs])
    assert a["Words"] == str(words)                                                   # 다시 저장한 노트까지 센 값


@pytest.mark.parametrize("edition_spec", ["syuka", None])
def test_two_edition_build_registers_the_final_bytes(tmp_path, monkeypatch, edition_spec):
    """두 판 빌드: 등록 대장에 적힌 pptx 의 sha256 이 폴더에 남은 파일의 해시와 같다(finish_package 뒤에 pptx 를 다시 쓰지 않는다).
    노트와 keywords 를 지운 사본도 안에 든 그림의 해시로 막힌다."""
    import test_deck_editions as E
    from pptx import Presentation
    from ozl.research import cards as C
    monkeypatch.setattr(C, "DESK", tmp_path / "desk")
    monkeypatch.setattr(C, "CARDS", tmp_path / "desk" / "cards")
    monkeypatch.setattr(C, "CLAIMS", tmp_path / "desk" / "claims")
    monkeypatch.setattr(C, "PUB_CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(PIC, "RIGHTS_PENDING_HOSTS", (E.PENDING_HOST,))
    monkeypatch.setattr(B, "DRAFTS", tmp_path / "decks" / "drafts")
    B.DRAFTS.mkdir(parents=True)
    monkeypatch.setattr(PIC, "REGISTRY", B.registry_file())
    monkeypatch.delenv(PIC.REGISTRY_ENV, raising=False)
    arts = {"press": _art(tmp_path / "press.png"), "ok": _art(tmp_path / "ok.png", (900, 600)), "gov": _art(tmp_path / "gov.png", (1000, 640))}
    E.save_records()
    out = B.build(E.write(tmp_path, E.two_spec(arts, style=edition_spec)), export=False)["editions"]
    priv, swap = pathlib.Path(out[PIC.EDITION_PRIVATE]["pptx"]), pathlib.Path(out[PIC.EDITION_SWAP]["pptx"])
    rows = [json.loads(x) for x in B.registry_file().read_text(encoding="utf-8").splitlines()]
    assert [r["sha256"] for r in rows if r["what"] == "pptx"] == [PIC.file_sha256(priv)]
    for p in (priv, swap):
        a = app(p)
        assert a["Slides"] == str(len(Presentation(str(p)).slides)) and a["PresentationFormat"] == "Widescreen" and template_left(p) == []
    assert "ozl:edition=private" in Presentation(str(priv)).core_properties.keywords
    prs = Presentation(str(priv))
    for s in prs.slides:
        s.notes_slide.notes_text_frame.text = ""
    prs.core_properties.keywords = ""
    bare = tmp_path / "후보" / "bare.pptx"
    bare.parent.mkdir()
    prs.save(str(bare))
    code, lines = PIC.public_check(bare)
    assert code == 1 and any("안 그림" in x and "비공개 등록 대장에 있다" in x for x in lines), lines
    assert PIC.public_check(pathlib.Path(out[PIC.EDITION_PRIVATE]["dir"]))[0] == 1 and PIC.public_check(pathlib.Path(out[PIC.EDITION_SWAP]["dir"]))[0] == 0
