#!/usr/bin/env python3
"""공개본 추출 게이트.

검사 대상: 인자로 받은 파일 전부. pre-commit 훅은 files 필터 없이 커밋하는 파일을 모두 넘긴다(2026-11-15, .pre-commit-config.yaml).
인자로 받은 파일은 확장자가 아니라 파일 안을 보고 가린다(2026-11-15 — 이름을 .ppsx · .pptx.zip · 확장자 없는 이름으로 바꾼 비공개판 사본이
검사 없이 통과하던 것을 막았다).
- 덱(zip 안에 프레젠테이션 부품이 있는 파일 — 이름이 .pptx 가 아니어도, 그리고 이름이 .pptx 인 파일): 발표자 노트·숨김 슬라이드가 남아 있으면 실패
  (공개본은 export 로 제거해야 함). 덱 꼴인데 열리지 않으면 '검사 불가'로 실패한다. 덱인지 가리지 못한 파일(가리는 함수가 예외를 냈다,
  zip 꼴인데 목록이 깨졌다)도 '덱이 아님'으로 넘기지 않고 '검사 불가'로 실패한다(2026-11-15 재확인 지적).
- 덱: 비공개 판의 덱이면 실패(deck_public_errors — ozl.render.pictures.public_check 를 부른다). 보는 것은 문서 속성 keywords 의
  ozl:private-only · ozl:edition=private, 안에 든 파일(ppt/media/* 등)의 sha256 과 파일 sha256 이 비공개 등록 대장
  (private/decks/private_only_registry.jsonl)에 있는가. 같은 폴더에 공개_가부.json 이 있으면 그 폴더도 본다(폴더 안의 모든 파일, 하위 폴더까지).
  노트만 지운 사본은 keywords 로, keywords 까지 지운 사본은 안에 든 그림의 해시로 잡는다. ozl 을 불러오지 못하면 '검사 불가'로 실패한다(통과시키지 않는다).
  public_check 가 실패 코드를 내면 메시지가 없어도 실패로 센다.
- 그 밖의 모든 파일(pdf · png · jpg · 글 파일 · 모르는 확장자 · 확장자 없는 이름): 파일 sha256 이 비공개 등록 대장에 있으면 실패
  (비공개판의 PDF, 쪽 PNG, 막는 그림 파일).
- 묶음(zip · tar · tar.gz 같은 압축된 tar · gz/bz2/xz 한 겹): 안에 든 파일마다 sha256 을 견주고, 안의 파일도 파일 안을 보고 가려 덱이면 덱으로 연다
  (문서 속성, 안에 든 그림, 발표자 노트와 숨김 슬라이드 — inner_deck_errors). 겹친 묶음은 3겹(pictures.ARCHIVE_MAX_DEPTH)까지 풀어 본다.
  그보다 깊은 묶음, 풀린 크기의 합이 pictures.ARCHIVE_MAX_BYTES 를 넘거나 항목이 ARCHIVE_MAX_MEMBERS 개를 넘는 묶음, 풀 수 없는 묶음
  (암호, 깨진 항목, 7z · rar 같은 풀 줄 모르는 형식), 묶음 목록에 나오지 않는 내용이 붙은 파일(zip 의 첫 항목 앞, tar 의 마지막 항목 뒤, 압축 흐름 뒤)은
  '검사 불가'로 실패한다. 묶음은 메모리에서만 읽는다(디스크에 풀지 않고 항목 이름을 경로로 쓰지 않는다).
  못 잡는 것: 다시 저장해 바이트가 달라진 그림(재압축, 자르기, 화면을 찍은 그림), 표지로 알아보지 못하는 묶음 형식(iso · dmg · cab 등),
  부호화한 파일(base64 등)이나 zip 이 아닌 방식으로 암호를 건 파일 안의 것, zip 의 덧글과 항목 사이 빈틈에 넣은 내용.
  해시가 같은 파일과 문서 속성이 남은 덱만 잡는다.
- 등록 대장이 없거나 빈 기기(대장은 비공개판을 만든 기기에만 있다)에서는 해시를 견주지 못한다. 종료 코드는 그대로이고 끝에 알림 한 줄을 stderr 로 낸다.
- md: 비공개 전사 코퍼스(private/transcripts/**/*.json 의 text, private/pilot/**/*.txt)와 연속 N자(정규화) 일치하면 실패
  · 코퍼스 셔글은 private/.gate_shingles.pkl 에 캐시(index.csv mtime 기준 무효화)
- md: 비공개 슬라이드 문구(문자 인식 결과 — private/slides_dense/*.json 의 title·body, private/ocr/*.jsonl)와 연속 N_SLIDE자 일치해도 실패
  · 슬라이드 줄은 짧아서(제목 중앙값 27자) 전사보다 짧은 창을 쓴다. 화면 필기 도구의 대화상자 문구(UI 글자)는 코퍼스에서 뺀다
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import pickle
import re
import sys


def h64(s: str) -> int:
    """프로세스 간 안정적인 64비트 해시 — 내장 hash()는 솔트가 매 프로세스 달라 캐시와 불일치(2026-11-09 자가검증에서 적발)."""
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "little")

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANS = ROOT / "private" / "transcripts"
PILOT = ROOT / "private" / "pilot"
CACHE = ROOT / "private" / ".gate_shingles.pkl"
SLIDES = ROOT / "private" / "slides_dense"
OCR = ROOT / "private" / "ocr"
N = 20        # 셔글 길이(정규화 문자)
TRANS_MIN_HANGUL = 8  # 전사 창도 한글이 이만큼 있어야 코퍼스에 넣는다 — 방송에서 읽어 준 영문 기관명('federalreservebankof'·'internationalmonetar')이
                      # 클레임 발행처와 겹쳐 오탐(2026-11-10 하루 두 번). 실측: 전사 창 821만 개 중 한글 0자 0.45% · 7자 이하 0.57%(영문·숫자 위주)
N_SLIDE = 14  # 슬라이드 문구용 창(정규화 문자) — 코퍼스가 작아 1칸 간격으로 전부 넣는다
SLIDE_MIN_HANGUL = 8  # 창 안에 한글이 이만큼 있어야 대조한다 — 'financialtimes' 같은 매체명·영문 고유명사 오탐 방지(2026-11-10 docs/sources.md 에서 실증)
SLIDE_MIN_HITS = 2    # 연속 15자 이상 겹칠 때만 인용으로 본다
UI_TEXT = re.compile(r"저장하시겠습니까|저장하지 않은 변경|저장하지 않음")
STRIDE = 7    # 코퍼스 셔글 추출 간격 — STRIDE 칸 묶음마다 한글 기준을 넘는 첫 창을 넣는다(transcript_windows).
              # 보장: 옮긴 문장이 N+2·STRIDE−1(=33)자 이상이고 그 안에 한글 기준을 넘는 20자 창이 하나라도 있으면 반드시 걸린다
MIN_HITS = 1
# 글로 읽어 대조하는 파일 종류. 웹 화면(astro, ts, mjs, js, css, html)도 본다 — 화면 틀과 예시 자료에 비공개 문구가 섞이면 사이트로 나간다(2026-11-14)
TEXT_SUFFIXES = (".md", ".py", ".json", ".txt", ".swift", ".yml", ".yaml", ".toml", ".sh", ".astro", ".ts", ".mjs", ".js", ".css", ".html")


def norm(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", s or "").lower()


def _note_errors(prs) -> list[str]:
    errs = []
    for i, s in enumerate(prs.slides, 1):
        if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
            errs.append(f"slide {i}: 발표자 노트 잔존")
        if s._element.get("show") == "0":
            errs.append(f"slide {i}: 숨김 슬라이드 잔존")
    return errs


def check_pptx(p: pathlib.Path, folders: dict | None = None) -> list[str]:
    try:
        from pptx import Presentation
    except ImportError:
        return ["python-pptx 미설치 — 검사 불가"]
    try:
        prs = Presentation(str(p))
    except Exception as e:  # noqa: BLE001 — 덱 꼴인데 열리지 않는 파일(슬라이드 쇼 형식, 깨진 묶음)은 노트를 볼 수 없다. 통과시키지 않는다
        return [f"검사 불가 — 프레젠테이션으로 열지 못했다({type(e).__name__}: {e})"] + deck_public_errors(p, folders)
    return _note_errors(prs) + deck_public_errors(p, folders)


def _pictures():
    """ozl.render.pictures(덱의 공개 가부 검사). 저장소의 src 를 찾는 길에 더한 뒤 불러온다. 못 불러오면 예외가 그대로 난다."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from ozl.render import pictures
    return pictures


def is_deck(p: pathlib.Path) -> bool:
    """파일 안을 보고 가린 덱(프레젠테이션)인가 — 확장자는 보지 않는다(pictures.is_deck_file). 거짓 = 덱이 아니다.
    가리지 못하면(ozl 을 불러오지 못했다, 가리는 함수가 예외를 냈다, zip 꼴인데 목록이 깨졌다) 예외가 그대로 난다 —
    '덱이 아님'으로 바꾸지 않는다. 부르는 쪽(main)이 '검사 불가'로 실패시킨다."""
    return bool(_pictures().is_deck_file(p))


def inner_deck_errors(p: pathlib.Path) -> list[str]:
    """묶음(zip · tar · 압축 한 겹)이나 덱 안에 든 덱의 발표자 노트와 숨김 슬라이드 — 맨 바깥 덱과 같은 규칙이다(pictures.scan 이 안의 파일을 낸다).
    안을 끝까지 보지 못하면(너무 깊다, 너무 크다, 풀 수 없다) '검사 불가' 한 줄. 묶음도 덱도 아닌 파일은 볼 것이 없다."""
    import io
    try:
        pic = _pictures()
        from pptx import Presentation
        if pic.content_kind(p) == pic.FILE_PLAIN:
            return []
        errs: list[str] = []
        for f in pic.scan(p):
            if f.kind != pic.FILE_DECK or not f.holder:
                continue
            try:
                prs = Presentation(io.BytesIO(f.src))
            except Exception as e:  # noqa: BLE001
                errs.append(f"검사 불가 — {f.label} 을 프레젠테이션으로 열지 못했다({type(e).__name__}: {e})")
                continue
            errs += [f"{f.label} {x}" for x in _note_errors(prs)]
        return errs
    except Exception as e:  # noqa: BLE001 — 안을 다 보지 못했다. 통과시키지 않는다
        return [f"검사 불가 — 안에 든 파일을 끝까지 보지 못했다({type(e).__name__}: {e})"]


def deck_public_errors(p: pathlib.Path, folders: dict | None = None) -> list[str]:
    """비공개 판의 산출물이면 그 까닭(public_check 의 출력 줄). 덱은 문서 속성과 안에 든 파일의 해시, 파일 해시를 보고
    그 밖의 파일은 파일 해시를, 묶음은 안에 든 파일마다(덱이면 덱으로 열어) 본다. 같은 폴더에 공개_가부.json 이 있으면 그 폴더도 본다
    (folders = 한 번의 실행에서 이미 본 폴더의 결과 — 같은 폴더의 파일이 여럿이어도 폴더는 한 번만 본다).
    검사를 돌리지 못하면(ozl 을 불러오지 못했다, 파일을 읽지 못했다) 통과시키지 않고 '검사 불가'로 실패한다.
    public_check 가 실패 코드를 냈는데 출력 줄이 없어도 실패다(빈 메시지를 성공으로 넘기지 않는다). 알림 줄(pictures.NOTICE)은 오류로 세지 않는다."""
    try:
        pic = _pictures()
    except Exception as e:  # noqa: BLE001 — 불러오지 못한 까닭이 무엇이든 통과시키지 않는다
        return [f"공개 가부 검사 불가 — ozl.render.pictures 를 불러오지 못했다({type(e).__name__}: {e})"]
    notice = getattr(pic, "NOTICE", None)   # 종료 코드에 영향이 없는 알림 줄의 머리

    def run(target: pathlib.Path) -> list[str]:
        try:
            code, lines = pic.public_check(target)
        except Exception as e:  # noqa: BLE001
            return [f"공개 가부 검사 불가 — {target.name} 을 읽지 못했다({type(e).__name__}: {e})"]
        if code == 0:
            return []
        said = list(dict.fromkeys(x.strip() for x in lines if x.strip() and not (notice and x.strip().startswith(notice))))
        # 실패 코드인데 까닭이 없다 — 그래도 실패다
        return said or [f"공개 가부 검사가 {target.name} 에서 메시지 없이 종료 코드 {code} 로 끝났다 — 통과시키지 않는다"]
    errs = run(p)
    if (p.parent / pic.PUBLIC_FILE).is_file():
        key = str(p.parent.resolve())
        if folders is None or key not in folders:
            got = run(p.parent)
            if folders is not None:
                folders[key] = got
        else:
            got = folders[key]
        errs += [x for x in got if x not in errs]
    return errs


def registry_notice() -> str:
    """비공개 등록 대장이 없거나 비어 해시를 견주지 못했으면 알림 한 줄, 아니면 빈 문자열. 종료 코드에는 영향이 없다."""
    try:
        pic = _pictures()
        rows, problems = pic.registry_rows()
    except Exception:  # noqa: BLE001 — 불러오지 못한 것은 파일마다 '검사 불가'로 이미 알렸다
        return ""
    if rows or problems:
        return ""
    return ("[publish-gate] 알림: 비공개 등록 대장이 없거나 비어 있어 파일 해시를 견주지 못했다 — 덱의 문서 속성, 공개_가부.json, 노트, "
            "전사와 슬라이드 문구만 봤다. 대장은 비공개판을 만든 기기에만 있다(private/decks/private_only_registry.jsonl)")


def _corpus_signature() -> str:
    idx = TRANS / "trading_export" / "index.csv"
    parts = [f"v6-blake2b-slides-hangul-trans{TRANS_MIN_HANGUL}-blockfirst", str(idx.stat().st_mtime_ns) if idx.exists() else "0"]
    parts.append(str(sum(1 for _ in PILOT.rglob("*.txt")) if PILOT.exists() else 0))
    for d in (SLIDES, OCR):
        fs = sorted(d.glob("*.json*")) if d.exists() else []
        parts.append(f"{len(fs)}:{max((f.stat().st_mtime_ns for f in fs), default=0)}")
    return "|".join(parts)


def _slide_lines():
    if SLIDES.exists():
        for f in SLIDES.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for s in d.get("slides", []):
                yield s.get("title") or ""
                yield from (s.get("body") or [])
    if OCR.exists():
        for f in OCR.glob("*.jsonl"):
            for line in f.open(encoding="utf-8"):
                try:
                    d = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                for ln in d.get("lines", []):
                    yield ln.get("text", "")


def _build_slide_shingles() -> set[int]:
    sh: set[int] = set()
    for raw in _slide_lines():
        if UI_TEXT.search(raw):
            continue
        t = norm(raw)
        for k in range(0, max(0, len(t) - N_SLIDE + 1)):
            w = t[k:k + N_SLIDE]
            if sum(1 for c in w if "가" <= c <= "힣") >= SLIDE_MIN_HANGUL:
                sh.add(h64(w))
    return sh


def _hangul(w: str) -> int:
    return sum(1 for c in w if "가" <= c <= "힣")


def transcript_windows(t: str):
    """정규화된 전사 문자열에서 코퍼스에 넣을 창.

    시작 위치를 STRIDE 칸씩 묶고, 묶음마다 한글이 TRANS_MIN_HANGUL 자 이상인 첫 창 하나를 넣는다.
    정렬 위치의 창만 보고 버리면 숫자·티커가 많은 구간에서 연속 두 묶음이 통째로 빠져 39자 인용도 놓쳤다
    (2026-11-10 독립 리뷰 반례) — 묶음 안에서 다음 위치로 미뤄 보면 그 구멍이 메워진다.
    마지막 창(k = len−N)까지 본다(이전 range 는 끝 창을 빠뜨렸다)."""
    last = len(t) - N
    for k in range(0, last + 1, STRIDE):
        for j in range(k, min(k + STRIDE, last + 1)):
            w = t[j:j + N]
            if _hangul(w) >= TRANS_MIN_HANGUL:
                yield w
                break


def _build_shingles() -> set[int]:
    sh: set[int] = set()
    files = list(TRANS.rglob("*.json")) if TRANS.exists() else []
    for f in files:
        try:
            t = norm(json.loads(f.read_text(encoding="utf-8")).get("text", ""))
        except Exception:  # noqa: BLE001
            continue
        sh.update(h64(w) for w in transcript_windows(t))
    if PILOT.exists():
        for f in PILOT.rglob("*.txt"):
            t = norm(f.read_text(encoding="utf-8", errors="ignore"))
            sh.update(h64(w) for w in transcript_windows(t))
    return sh


def transcript_shingles() -> tuple[set[int], set[int]]:
    sig = _corpus_signature()
    if CACHE.exists():
        try:
            d = pickle.loads(CACHE.read_bytes())
            if d.get("sig") == sig and d.get("N") == N and d.get("stride") == STRIDE and d.get("N_SLIDE") == N_SLIDE:
                return d["sh"], d["slide_sh"]
        except Exception:  # noqa: BLE001
            pass
    sh, slide_sh = _build_shingles(), _build_slide_shingles()
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(pickle.dumps({"sig": sig, "N": N, "stride": STRIDE, "N_SLIDE": N_SLIDE, "sh": sh, "slide_sh": slide_sh}))
    except Exception:  # noqa: BLE001
        pass
    return sh, slide_sh


def check_md(p: pathlib.Path, sh: set[int], slide_sh: set[int] | None = None) -> list[str]:
    t = norm(p.read_text(encoding="utf-8", errors="ignore"))
    errs = []
    for name, corpus, n, need in (("전사 전문", sh, N, MIN_HITS), ("슬라이드 문구", slide_sh or set(), N_SLIDE, SLIDE_MIN_HITS)):
        if not corpus:
            continue
        hits, run, best_run = [], 0, 0
        for k in range(0, max(0, len(t) - n + 1)):
            if h64(t[k:k + n]) in corpus:
                run += 1
                best_run = max(best_run, run)
                if run == need:  # 창이 need 개 연달아 맞아야(= n + need - 1 자 연속 일치) 한 건으로 친다
                    hits.append(t[k - need + 1:k + n])
                    if len(hits) >= 5:
                        break
            else:
                run = 0
        if hits:
            errs.append(f"{name} 인용 의심 {len(hits)}건 이상 (예: {hits[0]!r})")
    return errs


def main(argv: list[str]) -> int:
    sh = slide_sh = None
    bad = 0
    looked = False
    folders: dict = {}
    for a in argv:
        p = pathlib.Path(a)
        if not p.exists():
            continue
        errs: list[str] = []
        if p.is_file():
            looked = True
            # 확장자가 아니라 파일 안을 본다 — 이름을 .ppsx · .pptx.zip · 확장자 없는 이름으로 바꾼 덱도 덱으로 검사하고,
            # 그 밖의 파일은 종류와 상관없이 파일 해시(비공개판의 PDF, 쪽 PNG, 막는 그림 파일)를 등록 대장과 견준다.
            # 덱인지 가리지 못했으면 '덱이 아님'으로 넘기지 않는다 — 노트 검사가 빠진 채 통과하던 길이다(재확인 지적 1)
            try:
                deck = p.suffix.lower() == ".pptx" or is_deck(p)
            except Exception as e:  # noqa: BLE001
                deck = False
                errs.append(f"검사 불가 — 덱인지 가리지 못했다({type(e).__name__}: {e})")
            errs += check_pptx(p, folders) if deck else deck_public_errors(p, folders)
            errs += [x for x in inner_deck_errors(p) if x not in errs]   # 묶음 · 덱 안에 든 덱의 노트와 숨김 슬라이드
        if p.suffix in TEXT_SUFFIXES:  # 소스·데이터 파일도 대조(2026-11-10: deck.py 시제품 예시에 슬라이드 제목이 들어가 있던 것을 md 전용 게이트가 못 잡았다)
            if sh is None:
                sh, slide_sh = transcript_shingles()
            errs += check_md(p, sh, slide_sh)
        for e in errs:
            print(f"[publish-gate] {p}: {e}")
            bad += 1
    if looked:
        note = registry_notice()
        if note:
            print(note, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
