"""공개 게이트(scripts/publish_gate.py)의 덱 검사 — 비공개판 pptx 는 노트를 지워도, 문서 속성 keywords 까지 지워도 막히고 바꾼판은 통과한다.
게이트는 ozl.render.pictures.public_check 를 불러 문서 속성, 같은 폴더의 공개_가부.json, pptx 안 미디어 해시, 파일 해시를 본다.
ozl 을 불러오지 못하면 통과시키지 않는다. 네트워크 없이 돈다. 그림은 PIL 로 그린 것이고 예시 문장, 이름, 주소는 전부 지어낸 것이다."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import publish_gate as pg  # noqa: E402
import test_deck_editions as E  # noqa: E402
from test_deck_editions import arts  # noqa: E402,F401  (pytest fixture)
from test_deck_visuals import desk  # noqa: E402,F401  (pytest fixture)
from ozl.render import build as B  # noqa: E402
from ozl.render import pictures as PIC  # noqa: E402

PRIV, SWAP = PIC.EDITION_PRIVATE, PIC.EDITION_SWAP


@pytest.fixture(autouse=True)
def _tmp_registry(tmp_path, monkeypatch):
    """시험은 실제 비공개 등록 대장(private/outputs/decks/private_only_registry.jsonl)을 읽지도 쓰지도 않는다."""
    monkeypatch.setattr(PIC, "REGISTRY", tmp_path / "registry_for_test.jsonl")
    monkeypatch.delenv(PIC.REGISTRY_ENV, raising=False)


def strip(src: pathlib.Path, dst: pathlib.Path, keywords: bool = False) -> pathlib.Path:
    """발표자 노트를 지운 사본(keywords=True 면 문서 속성 keywords 도 지운다) — 공개본을 만들 때 하는 일을 흉내 낸다."""
    from pptx import Presentation
    prs = Presentation(str(src))
    for s in prs.slides:
        if s.has_notes_slide:
            s.notes_slide.notes_text_frame.text = ""
    if keywords:
        prs.core_properties.keywords = ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(dst))
    return dst


@pytest.fixture
def built(desk, arts, tmp_path):  # noqa: F811
    """지어낸 사양 하나를 두 판으로 만든 것 — {판 이름: 출력 칸}. 등록 대장은 임시 폴더에 있다(arts 가 PIC.REGISTRY 를 돌려 둔다)."""
    E.save_records()
    return B.build(E.write(tmp_path, E.two_spec(arts)), export=False)["editions"]


def test_private_edition_copies_fail_and_swap_edition_passes(built, tmp_path, capsys):
    a, b = pathlib.Path(built[PRIV]["pptx"]), pathlib.Path(built[SWAP]["pptx"])
    out = tmp_path / "공개 후보"
    no_notes = strip(a, out / "private_no_notes.pptx")
    no_marks = strip(a, out / "private_no_keywords.pptx", keywords=True)
    swap_ok = strip(b, out / "swap_no_notes.pptx")
    assert pg.main([str(no_notes)]) == 1
    msg = capsys.readouterr().out
    assert "발표자 노트" not in msg and "막는 그림 2장: p1, p3" in msg and "ozl:private-only" in msg
    assert pg.main([str(no_marks)]) == 1                                  # keywords 를 지워도 안에 든 그림의 해시로 잡는다
    msg = capsys.readouterr().out
    assert "ozl:private-only" not in msg and msg.count("비공개 등록 대장에 있다(막는 그림") == 2 and "ppt/media/" in msg
    assert pg.main([str(swap_ok)]) == 0
    assert capsys.readouterr().out == ""
    assert pg.main([str(no_notes), str(no_marks), str(swap_ok)]) == 1
    capsys.readouterr()
    assert pg.main([str(b)]) == 1                                         # 바꾼판도 노트를 지우지 않으면 종전 규칙으로 막힌다
    msg = capsys.readouterr().out
    assert "발표자 노트 잔존" in msg and "public-check" not in msg


def test_untouched_private_pptx_is_caught_by_file_hash_too(built, capsys):
    assert pg.main([built[PRIV]["pptx"]]) == 1
    msg = capsys.readouterr().out
    assert "발표자 노트 잔존" in msg and "파일의 sha256 이 비공개 등록 대장에 있다(pptx" in msg


def test_folder_public_file_is_read_when_next_to_the_pptx(built, tmp_path, capsys):
    clean = strip(pathlib.Path(built[SWAP]["pptx"]), tmp_path / "곁" / "deck.pptx")
    assert pg.main([str(clean)]) == 0
    (clean.parent / PIC.PUBLIC_FILE).write_text(json.dumps({"public_ok": False, "blocking": [], "edition": PRIV}, ensure_ascii=False), encoding="utf-8")
    assert pg.main([str(clean)]) == 1                                     # 같은 폴더의 공개_가부.json 이 비공개판이라고 적었다
    assert "판이 비공개판이다" in capsys.readouterr().out


def test_pdf_png_jpg_are_checked_by_file_hash(built, arts, tmp_path, capsys):  # noqa: F811
    page = tmp_path / "slide-01.png"
    page.write_bytes(arts["ok"].read_bytes() + b"page")                   # 지어낸 쪽 그림
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4 fabricated")
    assert pg.main([str(page), str(pdf)]) == 0
    PIC.register_private([{"sha256": PIC.file_sha256(page), "what": "쪽 png", "name": page.name},
                          {"sha256": PIC.file_sha256(pdf), "what": "pdf", "name": pdf.name}], B.registry_file())
    assert pg.main([str(page)]) == 1 and pg.main([str(pdf)]) == 1
    assert "비공개 등록 대장에 있다(쪽 png · slide-01.png" in capsys.readouterr().out
    assert pg.main([str(arts["press"])]) == 1 and pg.main([str(arts["ok"])]) == 0   # 막는 그림 파일 자체 · 바꾼 판에 쓴 그림
    jpg = tmp_path / "copy.JPG"
    jpg.write_bytes(arts["press"].read_bytes())                           # 이름을 바꿔도 바이트가 같으면 막는다
    assert pg.main([str(jpg)]) == 1


def test_gate_fails_closed_when_ozl_cannot_be_loaded(built, tmp_path, monkeypatch, capsys):
    swap_ok = strip(pathlib.Path(built[SWAP]["pptx"]), tmp_path / "s.pptx")
    assert pg.main([str(swap_ok)]) == 0

    def boom():
        raise ImportError("지어낸 실패")
    monkeypatch.setattr(pg, "_pictures", boom)
    assert pg.main([str(swap_ok)]) == 1
    assert "공개 가부 검사 불가 — ozl.render.pictures 를 불러오지 못했다(ImportError" in capsys.readouterr().out
    assert pg.deck_public_errors(swap_ok)[0].startswith("공개 가부 검사 불가")


def test_gate_fails_closed_when_the_file_cannot_be_read(tmp_path, capsys):
    bad = tmp_path / "broken.pptx"
    bad.write_bytes(b"not a zip")
    errs = pg.deck_public_errors(bad)                                     # public_check 가 예외 대신 종료 1 과 '검사 불가' 줄을 낸다
    assert errs and any(e.startswith("검사 불가 — broken.pptx") for e in errs), errs
    assert pg.main([str(bad)]) == 1 and "검사 불가" in capsys.readouterr().out


def test_gate_command_line_reads_the_extra_registry(built, tmp_path):
    """명령으로 돌린다(다른 프로세스). 임시 등록 대장은 환경 변수로 더한다 — 기본 대장은 그대로 본다."""
    a, b = pathlib.Path(built[PRIV]["pptx"]), pathlib.Path(built[SWAP]["pptx"])
    no_marks = strip(a, tmp_path / "c" / "private_no_keywords.pptx", keywords=True)
    swap_ok = strip(b, tmp_path / "c" / "swap_no_notes.pptx")
    env = {**os.environ, PIC.REGISTRY_ENV: str(B.registry_file())}
    gate = [sys.executable, str(ROOT / "scripts" / "publish_gate.py")]
    r1 = subprocess.run(gate + [str(no_marks)], capture_output=True, text=True, env=env)
    r2 = subprocess.run(gate + [str(swap_ok)], capture_output=True, text=True, env=env)
    assert r1.returncode == 1 and "비공개 등록 대장에 있다" in r1.stdout, r1.stdout + r1.stderr
    assert r2.returncode == 0, r2.stdout + r2.stderr


# ── 이름을 바꾼 사본(확장자와 무관하게 파일의 실제 꼴로 본다) ─────────────────
RENAMED = ["deck.ppsx", "deck.pptx.zip", "deck", "deck.PPTM", "deck.bin"]


@pytest.mark.parametrize("name", RENAMED)
def test_renamed_private_deck_is_still_blocked(built, tmp_path, capsys, name):
    """비공개판 pptx 의 이름을 .ppsx, .pptx.zip, 확장자 없는 이름으로 바꿔도 막는다. 확장자가 아니라 파일 안(OOXML 부품)과 등록 대장의 해시로 본다."""
    a, b = pathlib.Path(built[PRIV]["pptx"]), pathlib.Path(built[SWAP]["pptx"])
    out = tmp_path / "이름 바꿈"

    def renamed(src: pathlib.Path, folder: str) -> pathlib.Path:
        (out / folder).mkdir(parents=True, exist_ok=True)
        return src.rename(out / folder / name)

    no_notes = renamed(strip(a, out / "n.pptx"), "노트만")
    assert pg.main([str(no_notes)]) == 1                                  # 문서 속성 keywords
    msg = capsys.readouterr().out
    assert "ozl:private-only" in msg and "막는 그림 2장: p1, p3" in msg
    no_marks = renamed(strip(a, out / "m.pptx", keywords=True), "표시도")
    assert pg.main([str(no_marks)]) == 1                                  # keywords 를 지워도 안에 든 그림의 해시
    assert capsys.readouterr().out.count("비공개 등록 대장에 있다(막는 그림") == 2
    (out / "그대로").mkdir()
    same = out / "그대로" / name
    same.write_bytes(a.read_bytes())
    assert pg.main([str(same)]) == 1                                      # 바이트 그대로 — 노트와 파일 해시
    msg = capsys.readouterr().out
    assert "발표자 노트 잔존" in msg and "파일의 sha256 이 비공개 등록 대장에 있다(pptx" in msg
    swap_ok = renamed(strip(b, out / "s.pptx"), "바꾼판")
    assert pg.main([str(swap_ok)]) == 0                                   # 바꾼판 사본은 이름을 바꿔도 통과한다
    assert capsys.readouterr().out == ""
    swap_notes = out / "바꾼판" / ("노트 남은 " + name)
    swap_notes.write_bytes(b.read_bytes())
    assert pg.main([str(swap_notes)]) == 1                                # 노트 검사도 이름과 무관하다
    assert "발표자 노트 잔존" in capsys.readouterr().out


def test_registered_file_is_blocked_under_any_name(built, arts, tmp_path, capsys):  # noqa: F811
    """등록 대장에 해시가 있는 파일은 pdf, png, jpg 가 아닌 이름이어도 막는다(확장자 없는 이름, 모르는 확장자, 글 파일 확장자)."""
    for name in ("그림", "그림.dat", "그림.webp", "그림.txt"):
        f = tmp_path / "곁" / name
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(arts["press"].read_bytes())                         # 막는 그림 p1 과 같은 바이트
        assert pg.main([str(f)]) == 1, name
        assert "비공개 등록 대장에 있다(막는 그림 · p1" in capsys.readouterr().out
    ok = tmp_path / "곁" / "다른 그림.dat"
    ok.write_bytes(arts["ok"].read_bytes())
    assert pg.main([str(ok)]) == 0


def test_zip_wrapping_registered_files_is_blocked(built, arts, tmp_path, capsys):  # noqa: F811
    """덱이 아닌 zip 은 안에 든 파일의 해시를 등록 대장과 견준다(비공개판 pptx 나 막는 그림을 묶은 zip)."""
    import zipfile
    z = tmp_path / "묶음.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(built[PRIV]["pptx"], "안/deck.pptx")
        f.write(arts["ok"], "안/ok.png")
    assert pg.main([str(z)]) == 1
    assert "안/deck.pptx 의 sha256 이 비공개 등록 대장에 있다(pptx" in capsys.readouterr().out
    clean = tmp_path / "깨끗한 묶음.zip"
    with zipfile.ZipFile(clean, "w") as f:
        f.write(arts["ok"], "안/ok.png")
    assert pg.main([str(clean)]) == 0


def test_deck_shaped_file_that_cannot_be_opened_fails_closed(tmp_path, capsys):
    """안에 ppt/ 부품이 있는데 열리지 않는 파일(슬라이드 쇼 형식, 깨진 묶음)은 통과시키지 않는다."""
    import zipfile
    odd = tmp_path / "odd.ppsx"
    with zipfile.ZipFile(odd, "w") as f:
        f.writestr("ppt/presentation.xml", "<지어낸 내용/>")
    assert pg.main([str(odd)]) == 1
    assert "검사 불가" in capsys.readouterr().out
    broken = tmp_path / "broken.pptx"
    broken.write_bytes(b"not a zip")
    assert pg.main([str(broken)]) == 1                                    # 확장자가 pptx 인데 열리지 않는 파일도 traceback 없이 실패로 센다
    assert "검사 불가" in capsys.readouterr().out


def test_failing_code_without_message_still_counts(built, tmp_path, monkeypatch, capsys):
    """public_check 가 실패 코드를 내면 메시지가 없어도 오류다((1, []) 을 성공으로 넘기지 않는다)."""
    swap_ok = strip(pathlib.Path(built[SWAP]["pptx"]), tmp_path / "s.pptx")
    assert pg.main([str(swap_ok)]) == 0
    for code, lines in ((1, []), (1, ["", "  "]), (2, [])):
        monkeypatch.setattr(PIC, "public_check", lambda path, registries=None, c=code, ls=lines: (c, list(ls)))
        errs = pg.deck_public_errors(swap_ok)
        assert len(errs) == 1 and f"종료 코드 {code}" in errs[0] and "s.pptx" in errs[0], (code, lines, errs)
        assert pg.main([str(swap_ok)]) == 1
        assert "메시지 없이" in capsys.readouterr().out


# ── 덱인지 가리지 못한 파일(재확인 지적 1) ───────────────────────────────────
def test_gate_fails_closed_when_deck_detection_raises(built, tmp_path, monkeypatch, capsys):
    """덱인지 가리는 함수가 예외를 내면 '덱이 아님'으로 넘기지 않는다 — 노트 검사가 빠진 채 통과하던 길이다."""
    renamed = tmp_path / "이름 바꿈" / "deck.ppsx"                         # 바꾼판인데 노트가 남았다 — 가릴 수 있으면 노트로 막힌다
    renamed.parent.mkdir()
    renamed.write_bytes(pathlib.Path(built[SWAP]["pptx"]).read_bytes())
    assert pg.main([str(renamed)]) == 1 and "발표자 노트 잔존" in capsys.readouterr().out

    class OnlyDetectionFails:                                             # 가리는 함수만 실패하고 그 밖은 실제 모듈 그대로
        def __getattr__(self, k):
            return getattr(PIC, k)

        def is_deck_file(self, p):
            raise RuntimeError("지어낸 실패")

        def public_check(self, path, registries=None):
            return 0, ["[public-check] 지어낸 통과"]
    monkeypatch.setattr(pg, "_pictures", lambda: OnlyDetectionFails())
    assert pg.main([str(renamed)]) == 1
    out = capsys.readouterr().out
    assert "검사 불가" in out and "덱인지 가리지 못했다" in out and "RuntimeError" in out


def test_zip_shaped_file_that_cannot_be_listed_is_not_called_a_non_deck(tmp_path, capsys):
    """끝에 zip 표지가 있는데 목록을 읽지 못하는 파일은 '덱이 아님'이 아니라 '가리지 못함'이다."""
    import zipfile
    whole = tmp_path / "whole.zip"
    with zipfile.ZipFile(whole, "w") as f:
        f.writestr("ppt/presentation.xml", "<지어낸 내용/>" * 50)
    raw = whole.read_bytes()
    cut = tmp_path / "cut.bin"
    cut.write_bytes(raw[:20] + raw[-22:])                                 # 끝 표지(22바이트)만 남고 목록이 사라졌다
    with pytest.raises(PIC.Unscannable):
        PIC.is_deck_file(cut)
    assert pg.main([str(cut)]) == 1
    assert "검사 불가" in capsys.readouterr().out
    headless = tmp_path / "잘린.zip"
    headless.write_bytes(raw[:-22] + b"\1" * 70_000)                      # 끝 표지가 사라지고 뒤에 다른 내용이 길게 붙었다 — zip 머리로 시작한다
    with pytest.raises(PIC.Unscannable):
        PIC.is_deck_file(headless)
    assert pg.main([str(headless)]) == 1
    assert "검사 불가" in capsys.readouterr().out


# ── 묶음 안의 덱(재확인 지적 2) ──────────────────────────────────────────────
def _zip(path: pathlib.Path, members: dict, mode: str = "w") -> pathlib.Path:
    import zipfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, mode) as f:
        for name, src in members.items():
            f.writestr(name, src.read_bytes() if isinstance(src, pathlib.Path) else src)
    return path


def _tar(path: pathlib.Path, members: dict, mode: str = "w:gz") -> pathlib.Path:
    import io
    import tarfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, mode) as f:
        for name, src in members.items():
            data = src.read_bytes() if isinstance(src, pathlib.Path) else src
            info = tarfile.TarInfo(name)
            info.size = len(data)
            f.addfile(info, io.BytesIO(data))
    return path


def test_resaved_private_deck_inside_a_zip_is_opened_as_a_deck(built, tmp_path, capsys):
    """노트만 지워 바이트가 달라진 비공개판(keywords 는 남음)을 zip 한 겹에 넣어도 막는다 — 안 파일의 해시만 견주면 통과하던 길이다.
    keywords 까지 지운 사본은 안에 든 그림의 해시로, 노트가 남은 바꾼판은 노트로 막고, 노트를 지운 바꾼판 묶음은 통과한다."""
    a, b = pathlib.Path(built[PRIV]["pptx"]), pathlib.Path(built[SWAP]["pptx"])
    no_notes = strip(a, tmp_path / "s" / "n.pptx")
    assert PIC.file_sha256(no_notes) != PIC.file_sha256(a)                # 등록된 해시와 다르다
    assert pg.main([str(_zip(tmp_path / "z" / "한 겹.zip", {"안/deck.pptx": no_notes}))]) == 1
    msg = capsys.readouterr().out
    assert "ozl:private-only" in msg and "막는 그림 2장: p1, p3" in msg and "안/deck.pptx" in msg
    no_marks = strip(a, tmp_path / "s" / "m.pptx", keywords=True)
    assert pg.main([str(_zip(tmp_path / "z" / "표시 없음.zip", {"deck.bin": no_marks}))]) == 1
    msg = capsys.readouterr().out
    assert msg.count("비공개 등록 대장에 있다(막는 그림") == 2 and "ppt/media/" in msg and "deck.bin" in msg
    assert pg.main([str(_zip(tmp_path / "z" / "노트 남음.zip", {"deck.pptx": b}))]) == 1
    assert "deck.pptx" in (msg := capsys.readouterr().out) and "발표자 노트 잔존" in msg
    swap_ok = strip(b, tmp_path / "s" / "ok.pptx")
    assert pg.main([str(_zip(tmp_path / "z" / "깨끗.zip", {"deck.pptx": swap_ok, "읽어 보기.txt": "지어낸 글".encode()}))]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("wrap", ["zip 안 zip", "tar", "tar.gz", "tar.bz2", "tar.xz", "gz", "zip 안 tar.gz 안 zip"])
def test_nested_bundles_are_opened(built, tmp_path, capsys, wrap):
    """중첩 zip, tar(압축된 것 포함), 압축 한 겹 안의 비공개판도 막는다. 같은 꼴로 싼 바꾼판(노트 지움)은 통과한다."""
    import gzip
    a, b = pathlib.Path(built[PRIV]["pptx"]), pathlib.Path(built[SWAP]["pptx"])
    no_notes, swap_ok = strip(a, tmp_path / "s" / "n.pptx"), strip(b, tmp_path / "s" / "ok.pptx")

    def packed(src: pathlib.Path, d: str) -> pathlib.Path:
        o = tmp_path / d
        if wrap == "zip 안 zip":
            return _zip(o / "바깥.zip", {"안.zip": _zip(o / "안.zip", {"deck.pptx": src})})
        if wrap == "gz":
            (o).mkdir(parents=True, exist_ok=True)
            (o / "deck.pptx.gz").write_bytes(gzip.compress(src.read_bytes()))
            return o / "deck.pptx.gz"
        if wrap == "zip 안 tar.gz 안 zip":
            return _zip(o / "바깥.zip", {"가운데.tgz": _tar(o / "가운데.tgz", {"안.zip": _zip(o / "안.zip", {"deck.pptx": src})})})
        mode = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[wrap]
        return _tar(o / f"묶음.{wrap}", {"안/deck.pptx": src}, mode)

    assert pg.main([str(packed(a, "등록된 것"))]) == 1                     # 등록된 원본 바이트
    assert "비공개 등록 대장에 있다(pptx" in capsys.readouterr().out
    assert pg.main([str(packed(no_notes, "노트만 지운 것"))]) == 1         # 바이트가 달라져도 문서 속성으로
    assert "ozl:private-only" in capsys.readouterr().out
    assert pg.main([str(packed(swap_ok, "바꾼판"))]) == 0
    assert capsys.readouterr().out == ""


def test_bundles_deeper_than_the_limit_fail_closed(tmp_path, capsys):
    """깊이 3까지 풀어 본다. 그보다 깊은 묶음은 안을 다 보지 못했으므로 통과시키지 않는다(안이 깨끗해도)."""
    def nest(n: int, d: str) -> pathlib.Path:
        cur = _zip(tmp_path / d / "1.zip", {"글.txt": "지어낸 글".encode()})
        for i in range(2, n + 1):
            cur = _zip(tmp_path / d / f"{i}.zip", {f"{i - 1}.zip": cur})
        return cur
    assert PIC.ARCHIVE_MAX_DEPTH == 3
    assert pg.main([str(nest(3, "세 겹"))]) == 0
    assert capsys.readouterr().out == ""
    assert pg.main([str(nest(4, "네 겹"))]) == 1
    msg = capsys.readouterr().out
    assert "검사 불가" in msg and "3겹" in msg


def test_bundles_over_the_size_or_count_limit_fail_closed(tmp_path, monkeypatch, capsys):
    big = _zip(tmp_path / "큰 묶음.zip", {"a.bin": b"\0" * 6000, "b.bin": b"\1" * 6000})
    assert pg.main([str(big)]) == 0
    monkeypatch.setattr(PIC, "ARCHIVE_MAX_BYTES", 10_000)                 # 풀린 크기의 합 12,000 바이트가 상한을 넘는다
    assert pg.main([str(big)]) == 1
    assert "검사 불가" in (msg := capsys.readouterr().out) and "10,000" in msg
    monkeypatch.setattr(PIC, "ARCHIVE_MAX_BYTES", 1 << 20)
    monkeypatch.setattr(PIC, "ARCHIVE_MAX_MEMBERS", 1)
    assert pg.main([str(big)]) == 1
    assert "검사 불가" in capsys.readouterr().out


def test_bundles_that_cannot_be_unpacked_fail_closed(tmp_path, capsys):
    """풀 수 없는 묶음(깨진 zip 항목, 잘린 tar.gz, 풀 줄 모르는 형식)은 통과시키지 않는다."""
    import zipfile
    body = bytes(range(256)) * 8
    broken = _zip(tmp_path / "깨진 항목.zip", {"a.bin": body})
    raw = bytearray(broken.read_bytes())
    at = raw.index(body[:64])
    raw[at:at + 8] = b"\xff" * 8                                          # 저장된 항목의 바이트를 바꿨다 — 읽으면 CRC 가 맞지 않는다
    broken.write_bytes(bytes(raw))
    assert zipfile.is_zipfile(broken)
    cut = _tar(tmp_path / "잘린.tar.gz", {"a.bin": bytes(range(256)) * 400})
    cut.write_bytes(cut.read_bytes()[:-40])
    seven = tmp_path / "묶음.7z"
    seven.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\0" * 64)                  # 7z 표지만 있는 지어낸 파일
    for f in (broken, cut, seven):
        assert pg.main([str(f)]) == 1, f.name
        assert "검사 불가" in capsys.readouterr().out, f.name
    plain = tmp_path / "그냥.bin"
    plain.write_bytes(b"BZh is how this made-up text file starts")        # 압축 표지처럼 시작하는 글 파일은 묶음이 아니다
    assert pg.main([str(plain)]) == 0


def test_member_names_with_path_escape_are_never_written(built, tmp_path, capsys):
    """항목 이름에 ../ 나 절대 경로가 있어도 디스크에 쓰지 않는다(메모리에서만 본다). 그런 이름 아래의 등록된 파일도 잡는다."""
    import zipfile
    work = tmp_path / "작업"
    work.mkdir()
    evil = work / "탈출.zip"
    with zipfile.ZipFile(evil, "w") as f:
        f.writestr("../../escaped.txt", "지어낸 글")
        f.writestr("/abs/escaped.txt", "지어낸 글")
        f.writestr("../deck.pptx", pathlib.Path(built[PRIV]["pptx"]).read_bytes())
        f.writestr("줄\n바꿈.txt", "지어낸 글")
    before = sorted(str(x) for x in tmp_path.rglob("*"))
    assert pg.main([str(evil)]) == 1
    msg = capsys.readouterr().out
    assert "비공개 등록 대장에 있다(pptx" in msg
    assert all(x.startswith("[publish-gate] ") for x in msg.splitlines())  # 항목 이름의 줄바꿈이 출력 줄을 지어내지 못한다
    assert sorted(str(x) for x in tmp_path.rglob("*")) == before          # 새로 생긴 파일이 없다
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path.parent / "escaped.txt").exists()


def test_content_stuck_before_or_after_a_bundle_fails_closed(tmp_path, capsys):
    """zip 의 첫 항목 앞이나 tar 의 마지막 항목 뒤에 붙은 내용은 묶음 목록에 나오지 않는다 — 보지 못한 부분이 있으므로 통과시키지 않는다.
    암호가 걸린 항목도 같다. 0 으로 찬 구역으로 시작하는 파일은 tar 로 보지 않는다(tarfile 은 그것을 빈 tar 로 읽는다)."""
    import gzip
    blob = "지어낸 글".encode() * 40
    front, back = _zip(tmp_path / "앞.zip", {"a.bin": blob}), _zip(tmp_path / "뒤.zip", {"b.txt": b"clean"})
    glued = tmp_path / "이어 붙인.zip"
    glued.write_bytes(front.read_bytes() + back.read_bytes())             # zip 목록에는 뒤의 것만 보인다
    t1, t2 = _tar(tmp_path / "하나.tar", {"a.txt": b"clean"}, "w"), _tar(tmp_path / "둘.tar", {"b.bin": blob}, "w")
    tars = tmp_path / "이어 붙인.tar"
    tars.write_bytes(t1.read_bytes() + t2.read_bytes())                   # tar 는 첫 끝 표지에서 멈춘다
    locked = _zip(tmp_path / "암호.zip", {"a.bin": blob})
    raw = bytearray(locked.read_bytes())
    raw[raw.index(b"PK\x01\x02") + 8] |= 1                                # 목록의 암호 표시 비트를 켰다(지어낸 암호 묶음)
    locked.write_bytes(bytes(raw))
    stub = tmp_path / "끝 표지만.bin"
    stub.write_bytes(blob + b"PK\x05\x06" + b"\0" * 18)                   # 내용 뒤에 빈 zip 의 끝 표지를 붙였다
    for f, why in ((glued, "첫 항목 앞에"), (tars, "마지막 항목 뒤에"), (locked, "풀지 못했다"), (stub, "첫 항목 앞에")):
        assert pg.main([str(f)]) == 1, f.name
        assert "검사 불가" in (msg := capsys.readouterr().out) and why in msg, (f.name, msg)
    import bz2
    import lzma
    for name, comp in (("gz", gzip.compress), ("bz2", bz2.compress), ("xz", lzma.compress)):   # 압축 흐름 뒤에 덧붙인, 풀리지 않는 내용
        ok = tmp_path / f"그대로.{name}"
        ok.write_bytes(comp(blob) + comp(blob) + b"\0" * 64)               # 이어진 흐름과 뒤의 0 은 받는다
        tail = tmp_path / f"덧붙인.{name}"
        tail.write_bytes(comp(blob) + b"appended made-up bytes" * 8)
        tar_tail = tmp_path / f"덧붙인.tar.{name}"
        tar_tail.write_bytes(_tar(tmp_path / f"t.tar.{name}", {"a.txt": b"clean"}, f"w:{name}").read_bytes() + b"appended made-up bytes" * 8)
        assert pg.main([str(ok)]) == 0, name
        for f in (tail, tar_tail):
            assert pg.main([str(f)]) == 1, f.name
            assert "검사 불가" in capsys.readouterr().out, f.name
    zeros = tmp_path / "영.bin"
    zeros.write_bytes(b"\0" * 4096)
    lead = tmp_path / "영으로 시작.bin"
    lead.write_bytes(b"\0" * 4096 + blob)
    packed = tmp_path / "영으로 시작.gz"
    packed.write_bytes(gzip.compress(b"\0" * 4096 + blob))
    assert PIC.content_kind(zeros) == PIC.content_kind(lead) == PIC.FILE_PLAIN and PIC.content_kind(packed) == PIC.FILE_PACKED
    assert pg.main([str(zeros), str(lead), str(packed), str(t1), str(back)]) == 0
    PIC.register_private([{"sha256": PIC.hashlib.sha256(b"\0" * 4096 + blob).hexdigest(), "what": "pdf", "name": "x.pdf"}], PIC.REGISTRY)
    assert pg.main([str(packed)]) == 1                                    # 압축 한 겹을 풀어 그 안의 파일을 견준다(빈 tar 로 넘기지 않는다)
    assert "(압축을 푼 것) 의 sha256 이 비공개 등록 대장에 있다" in capsys.readouterr().out


def test_gate_says_once_when_there_is_no_registry(tmp_path, capsys):
    """등록 대장이 없는 기기: 종료 코드는 그대로 0 이고, 해시를 견주지 못했다는 알림 한 줄이 stderr 로 나온다(파일마다가 아니라 한 번)."""
    a, b = tmp_path / "a.png", tmp_path / "b.pdf"
    a.write_bytes(b"\x89PNG fabricated")
    b.write_bytes(b"%PDF-1.4 fabricated")
    assert not PIC.REGISTRY.exists()
    assert pg.main([str(a), str(b)]) == 0
    got = capsys.readouterr()
    assert got.out == "" and got.err.count("견주지 못했다") == 1 and got.err.startswith("[publish-gate] 알림:")
    PIC.register_private([{"sha256": PIC.file_sha256(b), "what": "pdf", "name": b.name}], PIC.REGISTRY)
    assert pg.main([str(a)]) == 0
    assert capsys.readouterr().err == ""                                  # 견줄 대장이 있으면 알림이 없다
    assert pg.main([str(a), str(b)]) == 1
    got = capsys.readouterr()
    assert "비공개 등록 대장에 있다(pdf" in got.out and "알림" not in got.out and got.err == ""


# ── 폴더에서 보지 못한 것, 묶음 판별(표지 먼저), 적힌 크기와 항목 수를 풀기 전에 ─────────────────
def test_gate_fails_when_the_deck_folder_has_a_folder_link(built, tmp_path, capsys):
    """같은 폴더에 공개_가부.json 이 있으면 게이트는 폴더도 본다 — 그 폴더에 폴더 링크가 있으면 '검사 불가'가 오류로 세어진다."""
    b = pathlib.Path(built[SWAP]["pptx"])
    clean = strip(b, tmp_path / "후보" / "swap.pptx")
    (clean.parent / PIC.PUBLIC_FILE).write_text(json.dumps({"public_ok": True, "blocking": []}), encoding="utf-8")
    assert pg.main([str(clean)]) == 0
    capsys.readouterr()
    (clean.parent / "모음").symlink_to(pathlib.Path(built[PRIV]["dir"]), target_is_directory=True)
    assert pg.main([str(clean)]) == 1
    msg = capsys.readouterr().out
    assert "검사 불가 — 모음: 폴더로 가는 링크다" in msg


class _Counting:
    """읽은 바이트를 세는 파일 객체(시험용)."""
    def __init__(self, f, log):
        self._f, self._log = f, log

    def read(self, n=-1):
        data = self._f.read(n)
        self._log.append(len(data))
        return data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._f.close()

    def __getattr__(self, name):
        return getattr(self._f, name)


def test_zero_filled_file_is_judged_from_its_head(tmp_path, monkeypatch):
    """0 으로 찬 큰 파일을 끝까지 읽지 않는다 — tarfile 을 'r:*' 로 열면 xz 풀이가 파일 전체를 읽었다(64MiB 에 5초 넘게).
    시간이 아니라 읽은 바이트 수로 본다."""
    import tarfile
    size = 8 * 1024 * 1024
    z = tmp_path / "zeros.bin"
    with open(z, "wb") as f:
        f.truncate(size)
    read: list[int] = []
    modes: list[str] = []
    real_open, real_tar = PIC._open_src, tarfile.open
    monkeypatch.setattr(PIC, "_open_src", lambda src: _Counting(real_open(src), read))
    monkeypatch.setattr(tarfile, "open", lambda *a, **k: modes.append(k.get("mode", a[1] if len(a) > 1 else "r")) or real_tar(*a, **k))
    assert PIC.content_kind(z) == PIC.FILE_PLAIN
    assert sum(read) < size // 16, sum(read)                              # 머리와 끝 표지 자리만 읽는다
    assert modes == ["r:"]                                                # 표지가 없으면 압축 없는 tar 로만 열어 본다
    for name, mode in (("a.tar.gz", "w:gz"), ("a.tar.bz2", "w:bz2"), ("a.tar.xz", "w:xz"), ("a.tar", "w")):
        made = _tar(tmp_path / name, {"글.txt": "지어낸 글".encode()}, mode)
        modes.clear()                                                     # 시험 파일을 만들 때 연 것은 세지 않는다
        assert PIC.content_kind(made) == PIC.FILE_TAR
        assert modes == [{"w:gz": "r:gz", "w:bz2": "r:bz2", "w:xz": "r:xz", "w": "r:"}[mode]] and "r:*" not in modes


@pytest.mark.parametrize("kind", ["gz", "bz2", "xz"])
def test_compressed_stream_over_the_size_limit_fails_closed(tmp_path, monkeypatch, capsys, kind):
    """압축 한 겹(gz · bz2 · xz)을 푼 크기가 상한을 넘으면 '검사 불가' — 작은 파일이 크게 풀리는 압축 흐름을 끝까지 풀지 않는다."""
    import bz2
    import gzip
    import lzma
    packed = tmp_path / f"큰 흐름.{kind}"
    packed.write_bytes({"gz": gzip.compress, "bz2": bz2.compress, "xz": lzma.compress}[kind](b"\0" * 4_000_000))
    assert packed.stat().st_size < 20_000
    assert pg.main([str(packed)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(PIC, "ARCHIVE_MAX_BYTES", 1_000_000)
    assert pg.main([str(packed)]) == 1
    msg = capsys.readouterr().out
    assert "검사 불가" in msg and "1,000,000" in msg


def test_declared_size_is_checked_before_unpacking(tmp_path, monkeypatch):
    """zip 항목과 tar 항목의 적힌 크기가 남은 한도를 넘으면 그 항목을 풀지 않는다(푼 뒤에 세는 검사는 그대로 남아 있다)."""
    big_zip = _zip(tmp_path / "큰 항목.zip", {"작은.bin": b"\1" * 100, "큰.bin": b"\0" * 50_000})
    big_tar = _tar(tmp_path / "큰 항목.tar", {"작은.bin": b"\1" * 100, "큰.bin": b"\0" * 50_000}, "w")
    assert [f.name for f in PIC.scan(big_zip)][1:] == ["작은.bin", "큰.bin"]
    monkeypatch.setattr(PIC, "ARCHIVE_MAX_BYTES", 10_000)
    read: list[int] = []
    real = PIC._read_all
    monkeypatch.setattr(PIC, "_read_all", lambda f, budget, label: read.append(1) or real(f, budget, label))
    for path in (big_zip, big_tar):
        read.clear()
        with pytest.raises(PIC.Unscannable, match="적힌 크기\\(50,000 바이트\\)"):
            list(PIC.scan(path))
        assert len(read) == 1, (path.name, read)                           # 작은 항목만 풀었다 — 큰 항목은 열지 않았다
    code, lines = PIC.public_check(big_zip)
    assert code == 1 and any("검사 불가" in x and "큰.bin" in x and "풀지 않았다" in x for x in lines), lines


def test_zip_member_count_is_checked_before_reading_any_member(tmp_path, monkeypatch):
    many = _zip(tmp_path / "많은 항목.zip", {f"{k}.txt": b"x" for k in range(5)})
    monkeypatch.setattr(PIC, "ARCHIVE_MAX_MEMBERS", 3)
    read: list[int] = []
    real = PIC._read_all
    monkeypatch.setattr(PIC, "_read_all", lambda f, budget, label: read.append(1) or real(f, budget, label))
    with pytest.raises(PIC.Unscannable, match="항목 수가 상한"):
        list(PIC.scan(many))
    assert read == []                                                     # 항목을 하나도 읽기 전에 목록 길이로 막았다


def test_ar_and_lzma_alone_fail_closed_and_plain_files_pass(tmp_path, capsys):
    """형식 목록 밖이던 것: ar(정적 라이브러리 · deb 의 겉)와 표지 없는 lzma-alone(.lzma)은 풀 줄 모르는 묶음이다 — '검사 불가'.
    글 파일과 0 으로 찬 파일은 그 꼴로 잘못 읽히지 않는다."""
    import lzma
    ar = tmp_path / "묶음.a"
    ar.write_bytes(b"!<arch>\n" + b"note.txt/       0           0     0     644     6         `\nhello\n")
    alone = tmp_path / "묶음.lzma"
    alone.write_bytes(lzma.compress("지어낸 글 ".encode() * 500, format=lzma.FORMAT_ALONE))
    tar_alone = tmp_path / "묶음.tar.lzma"
    tar_alone.write_bytes(lzma.compress(_tar(tmp_path / "속.tar", {"글.txt": "지어낸 글".encode()}, "w").read_bytes(), format=lzma.FORMAT_ALONE))
    for f, name in ((ar, "ar"), (alone, "lzma"), (tar_alone, "lzma")):
        with pytest.raises(PIC.Unscannable, match=f"풀 줄 모르는 묶음 형식이다\\({name}\\)"):
            PIC.content_kind(f)
        assert pg.main([str(f)]) == 1, f.name
        assert "검사 불가" in capsys.readouterr().out, f.name
    texts = {
        "꺾쇠로 시작.txt": ("]" + "지어낸 글이다. " * 400).encode(),                                   # 첫 바이트가 lzma 속성값(0x5D)과 같은 글
        "꺾쇠와 0.bin": b"]\x00\x00\x80\x00" + b"\xff" * 8 + "지어낸 글이다. ".encode() * 300,       # 머리 꼴은 같지만 그 형식으로 풀리지 않는다
        "빈 것.lzma": lzma.compress(b"", format=lzma.FORMAT_ALONE),                                 # 내용이 없는 .lzma 는 볼 것이 없다
        "영.bin": b"\0" * 20_000,
        "글.md": "빵집 이야기다. ".encode() * 500,
    }
    for name, data in texts.items():
        p = tmp_path / name
        p.write_bytes(data)
        assert PIC.content_kind(p) == PIC.FILE_PLAIN, name
        assert pg.main([str(p)]) == 0, name
