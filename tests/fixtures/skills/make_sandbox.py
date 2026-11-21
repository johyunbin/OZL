"""스킬 따라가기용 시험 저장소 사본을 만든다.

    .venv/bin/python tests/fixtures/skills/make_sandbox.py <대상 폴더> [--no-git]

사본에 두는 것:
  복사   src/, tracks/, skills/, .claude/skills/, agent/, docs/, CLAUDE.md, README.md, tests/fixtures/
         (docs/ 와 README.md 는 CLAUDE.md 의 진입 순서가 가리키는 공개 문서다)
  링크   .venv (실제 저장소의 가상 환경. 사본에서는 PYTHONPATH=<사본>/src 를 주어 사본의 코드가 먼저 잡히게 한다)
  만든다 private/live/pulse/out/board.json   지어낸 후보 판(tests/fixtures/skills/board.json)
         private/test_desk/issues/      지어낸 이슈 예시 둘(tests/fixtures/issues/) — 시험 자료 루트
         private/data/derived/syuka/syuka.db         지어낸 슈카 3판 추출 5편(tests/fixtures/skills/syuka_v3/)
         private/outputs/decks/drafts/          빈 폴더(덱 빌드의 산출 폴더가 이 아래에 생긴다)
         private/data/raw/meta/                  지어낸 영상 목록과 주제 태그(tests/fixtures/skills/syuka_meta/ 의 csv 둘)
         private/data/raw/transcripts/trading_export/   지어낸 전사 3편과 색인(같은 폴더의 transcripts/, transcripts_index.csv)
                                        지어낸 영상의 날짜는 2097~2098년이다. 전사 본문 찾기에는 --asof 2099-01-02T12:00 을 준다
         kit/                           지어낸 공식 문서와 기사 요지, 광고주 자료(tests/fixtures/skills/kit/)

사본 안에서 `git init` 을 한 번 한다(커밋은 하지 않는다). 사본을 실제 저장소 아래의 비공개 폴더에 둘 때, 화면 없는
세션이 실제 저장소가 아니라 사본을 프로젝트로 잡게 하려는 것이다. `--no-git` 이면 하지 않는다.

끝에 사본의 파이썬으로 `ozl.research.cards.ROOT` 를 찍어 사본 경로인지 본다. 아니면 종료 코드 3 으로 멈춘다
(그 사본에서 명령을 돌리면 실제 저장소의 자료를 읽고 쓰게 된다).

실제 자료(private/)는 읽지도 복사하지도 않는다. 이 스크립트가 쓰는 곳은 대상 폴더뿐이다.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "src"))
from ozl import paths as ozlpaths  # noqa: E402  (사본 구조를 정본 LAYOUT 에 맞춘다)

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
COPY_DIRS = ("src", "tracks", "skills", ".claude/skills", "agent", "docs", "tests/fixtures")
COPY_FILES = ("CLAUDE.md", "README.md")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "*.egg-info", ".pytest_cache")
TEST_DESK = "private/test_desk"

# 사본의 코드로 지어낸 슈카 자료를 넣는다. DB 경로가 사본 밖이면 아무것도 쓰지 않고 멈춘다.
LOAD_SYUKA = r"""
import json, pathlib, sys
from ozl.syuka import db, db_v3, schema_v3
copy, src = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2])
if copy not in db.DB_PATH.resolve().parents:
    sys.exit(f"슈카 DB 경로가 사본 밖이다: {db.DB_PATH}")
videos = json.loads((src / "videos.json").read_text(encoding="utf-8"))["videos"]
rows = [{"video_id": v["video_id"], "title": v["title"], "upload_at": v["upload_at"], "duration_sec": v["duration_sec"],
         "kind": v["kind"], "has_transcript": 0, "transcript_source": None, "transcript_path": None, "chars": None,
         "in_uploads": 1, "in_transcripts": 0} for v in videos]
up = {v["video_id"]: v["upload_at"] for v in videos}
con = db.connect(db.DB_PATH)
try:
    db.put_videos(con, rows)
    n = 0
    for p in sorted(src.glob("fake*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        errs = schema_v3.validate_file(doc, None, up.get(doc.get("video_id")))
        if errs:
            sys.exit(f"{p.name}: " + " / ".join(errs))
        db_v3.put(con, doc)
        n += 1
    c = db_v3.counts(con)
finally:
    con.close()
print(f"슈카 3판 {n}편 · 토막 {c['v3_segments']} · {db.DB_PATH}")
"""


class Stop(Exception):
    def __init__(self, msg: str, code: int = 2) -> None:
        super().__init__(msg)
        self.code = code


def sandbox_env(copy: pathlib.Path) -> dict[str, str]:
    """사본에서 명령을 돌릴 때의 환경: 사본의 코드가 먼저 잡히고 자료 루트는 사본의 시험 루트다."""
    env = {k: v for k, v in os.environ.items() if k not in SLOT_ENV}   # 셸에서 물려받은 칸별 위치 변수는 운영을 가리킬 수 있다
    env.update(copy_vars(copy))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# 칸별 위치 변수(운영 자료를 가리킬 수 있어 사본 환경에서는 비운다)
SLOT_ENV = ("OZL_DESK_ROOT", "OZL_PULSE_DB", "OZL_ENGINE_DB", "OZL_BOARD_OUT", "OZL_ENGINE_OVERRIDES", "OZL_WEB_OUT", "OZL_CARDS_OUT")


def copy_vars(copy: pathlib.Path) -> dict[str, str]:
    """사본에서 명령을 돌릴 때 정하는 변수 — 자식 환경, 출력 JSON, 안내 문구가 모두 이 값을 쓴다."""
    return {"PYTHONPATH": str(copy / "src"), "OZL_PRIVATE": str(copy / "private"), "OZL_DESK_ROOT": str(copy / TEST_DESK)}


def build(target: pathlib.Path, git: bool = True, repo: pathlib.Path = REPO) -> pathlib.Path:
    target = target.expanduser().resolve()
    repo = repo.resolve()
    if target == repo or target in repo.parents:
        raise Stop("대상이 저장소 자신이거나 그 위 폴더다")
    if target.exists() and any(target.iterdir()):
        raise Stop(f"대상 폴더가 비어 있지 않다: {target}")
    target.mkdir(parents=True, exist_ok=True)

    for rel in COPY_DIRS:
        shutil.copytree(repo / rel, target / rel, ignore=IGNORE)
    for rel in COPY_FILES:
        shutil.copy2(repo / rel, target / rel)
    venv = repo / ".venv"
    if not (venv / "bin" / "python").exists():
        raise Stop(f"가상 환경이 없다: {venv}")
    (target / ".venv").symlink_to(venv, target_is_directory=True)

    fx = target / "tests" / "fixtures"
    board = ozlpaths.under(target / "private", "pulse", "out", "board.json")
    board.parent.mkdir(parents=True)
    shutil.copy2(fx / "skills" / "board.json", board)
    shutil.copytree(fx / "issues", target / TEST_DESK / "issues", ignore=IGNORE)
    shutil.copytree(fx / "skills" / "kit", target / "kit", ignore=IGNORE)
    (ozlpaths.under(target / "private", "syuka")).mkdir(parents=True)
    (ozlpaths.under(target / "private", "decks", "drafts")).mkdir(parents=True)      # 덱 빌드는 이 폴더 바로 아래에 산출 폴더를 만든다(없으면 멈춘다)
    meta = fx / "skills" / "syuka_meta"                       # 주제 태그 찾기와 전사 본문 찾기가 읽는 자리
    (ozlpaths.under(target / "private", "meta")).mkdir(parents=True)
    for name in ("catalog_syukaworld.csv", "video_tags_syukaworld.csv"):
        shutil.copy2(meta / name, ozlpaths.under(target / "private", "meta", name))
    export = ozlpaths.under(target / "private", "transcripts", "trading_export")
    shutil.copytree(meta / "transcripts", export / "syuka", ignore=IGNORE)
    shutil.copy2(meta / "transcripts_index.csv", export / "index.csv")

    env = sandbox_env(target)
    py = str(target / ".venv" / "bin" / "python")
    r = subprocess.run([py, "-c", LOAD_SYUKA, str(target), str(fx / "skills" / "syuka_v3")], cwd=target, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Stop("슈카 자료를 넣지 못했다: " + (r.stderr.strip() or r.stdout.strip()))
    print(r.stdout.strip())

    if git:
        g = subprocess.run(["git", "init", "-q"], cwd=target, capture_output=True, text=True)
        if g.returncode != 0:
            raise Stop("git init 실패: " + g.stderr.strip())

    r = subprocess.run([py, "-c", "from ozl.research import cards; print(cards.ROOT)"], cwd=target, env=env,
                       capture_output=True, text=True)
    root = r.stdout.strip()
    print(f"cards.ROOT {root}")
    if r.returncode != 0 or not root or pathlib.Path(root).resolve() != target:
        raise Stop(f"cards.ROOT 가 사본 경로가 아니다(사본 {target}, 찍힌 값 {root or r.stderr.strip()}). "
                   "이 사본에서 명령을 돌리지 않는다", 3)
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="스킬 따라가기용 시험 저장소 사본을 만든다")
    ap.add_argument("target", help="사본을 만들 폴더(없거나 비어 있어야 한다)")
    ap.add_argument("--no-git", action="store_true", help="사본 안에서 git init 을 하지 않는다")
    a = ap.parse_args(argv)
    try:
        t = build(pathlib.Path(a.target), git=not a.no_git)
    except Stop as e:
        print(f"멈춤: {e}", file=sys.stderr)
        return e.code
    n = sum(1 for p in t.rglob("*") if p.is_file())
    print(json.dumps({"sandbox": str(t), "files": n, "env": copy_vars(t)}, ensure_ascii=False))
    print("사본에서 명령을 돌릴 때: cd <사본> && env -u OZL_PULSE_DB -u OZL_ENGINE_DB -u OZL_BOARD_OUT -u OZL_ENGINE_OVERRIDES -u OZL_WEB_OUT -u OZL_CARDS_OUT "
          "PYTHONPATH=<사본>/src OZL_PRIVATE=<사본>/private OZL_DESK_ROOT=<사본>/private/test_desk .venv/bin/python …")
    return 0


if __name__ == "__main__":
    sys.exit(main())
