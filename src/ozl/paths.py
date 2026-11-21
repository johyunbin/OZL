"""비공개 자료(private/)의 위치를 한 곳에서 정한다.

코드는 `ROOT / "private" / "<폴더>"` 를 직접 만들지 않고 `at("<이름>", ...)` 으로 받는다. 폴더를 옮길 때는 아래 LAYOUT 의
값만 바꾼다(이름은 그대로 둔다).

뿌리는 부를 때마다 읽는다(`root()`). 환경 변수 OZL_PRIVATE 가 있으면 그 폴더이고, 없으면 체크아웃의 private/ 다. 시험은 이 변수를
임시 폴더로 두어 운영 자료에 쓰지 않는다(tests/conftest.py). 모듈이 `X = at(...)` 처럼 가져올 때 값을 정해 두면 그 값은 가져온
시점의 뿌리를 따른다. 기존의 칸별 환경 변수(OZL_DESK_ROOT, OZL_PULSE_DB 따위)는 각 모듈이 이 값보다 먼저 읽는다.

기록에 이미 적힌 경로(`private/desk/...` 같은 상대 경로나 옛 절대 경로)는 고쳐 쓰지 않는다. 승인 지문과 사양 해시가 내용에 묶여
있어서다. 읽을 때 `resolve()` 가 지금 위치로 바꿔 준다.
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV = "OZL_PRIVATE"

# 이름 → private/ 아래의 지금 위치. 이름은 옛 최상위 폴더(또는 파일) 이름과 같고 바꾸지 않는다.
LAYOUT: dict[str, str] = {
    # 사용자가 여는 입구
    "결과물": "결과물",
    "templates": "templates",
    "README.md": "README.md",
    # 실시간 수집
    "pulse": "live/pulse",
    # 원자료
    "frames": "data/raw/frames",
    "frames_dense": "data/raw/frames_dense",
    "transcripts": "data/raw/transcripts",
    "meta": "data/raw/meta",
    "audio": "audio",
    # 추출과 가공
    "syuka": "data/derived/syuka",
    "slides": "data/derived/slides",
    "slides_dense": "data/derived/slides_dense",
    "slides_label": "data/derived/slides_label",
    "slides_label_r2": "data/derived/slides_label_r2",
    "ocr": "data/derived/ocr",
    "dense": "data/derived/dense",
    "compose": "data/derived/compose",
    "compose_holdout_a": "data/derived/compose_holdout_a",
    "compose_holdout_b": "data/derived/compose_holdout_b",
    "style": "data/derived/style",
    # 모델
    "models": "data/models",
    # 자동 생성 결과물
    "decks": "outputs/decks",
    "out": "outputs/out",
    "daily": "outputs/daily",
    "briefs": "outputs/briefs",
    # 작업 기록과 장부
    "desk": "records/desk",
    "plan": "records/plan",
    "handoff": "records/handoff",
    "guide": "records/guide",
    "research": "records/research",
    "p3": "records/runs/p3",
    "pilot": "records/runs/pilot",
    # 실행 상태와 설정
    "ops": "state/ops",
    "notion.json": "state/notion.json",
    "notion_issues.json": "state/notion_issues.json",
    ".gate_shingles.pkl": "state/cache/.gate_shingles.pkl",
    # 보관
    "archive": "archive",
    "backup": "archive/backup",
}

# 옛 최상위 이름(2026-11-21 개편 전). 기록에 남은 옛 경로를 읽을 때만 쓴다. 고정이다(LAYOUT 에 새 이름이 늘어도 바꾸지 않는다).
LEGACY: frozenset[str] = frozenset({
    "결과물", "README.md", "pulse", "frames", "frames_dense", "transcripts", "meta", "audio", "syuka", "slides",
    "slides_dense", "slides_label", "slides_label_r2", "ocr", "dense", "compose", "compose_holdout_a",
    "compose_holdout_b", "style", "models", "decks", "out", "daily", "briefs", "desk", "plan", "handoff", "guide",
    "research", "p3", "pilot", "ops", "notion.json", "notion_issues.json", ".gate_shingles.pkl", "archive", "backup",
})


def root() -> pathlib.Path:
    v = os.environ.get(ENV, "").strip()
    if not v:
        return ROOT / "private"
    p = pathlib.Path(v).expanduser()
    return p if p.is_absolute() else pathlib.Path.cwd() / p   # 상대 값은 부를 때의 작업 폴더 기준으로 한 번 굳힌다


def real_root() -> pathlib.Path:
    """환경 변수와 무관한 운영 자료의 뿌리(체크아웃의 private/)."""
    return ROOT / "private"


def at(name: str, *parts: str) -> pathlib.Path:
    """이름이 가리키는 지금 위치. 모르는 이름이면 KeyError — 오타가 조용히 새 폴더를 만들지 않게 한다."""
    return root().joinpath(LAYOUT[name], *parts)


def under(base, name: str, *parts: str) -> pathlib.Path:
    """다른 뿌리(시험 사본의 private/, 복원한 백업 따위) 아래에서 이름이 가리키는 위치."""
    return pathlib.Path(base).joinpath(LAYOUT[name], *parts)


def real_at(name: str, *parts: str) -> pathlib.Path:
    """OZL_PRIVATE 와 무관한 운영 자료의 위치. 시험이 '실제 자료에 쓰지 않았다'를 확인하거나 실제 자료를 읽기만 할 때 쓴다."""
    return under(real_root(), name, *parts)


def _remap(rel: pathlib.PurePath, base: pathlib.Path) -> pathlib.Path:
    """private/ 아래의 상대 경로를 base 아래 지금 위치로. 첫 칸이 옛 이름이면 그 이름의 지금 위치 아래로 옮긴다."""
    if not rel.parts:
        return base
    head, rest = rel.parts[0], rel.parts[1:]
    if head in LEGACY:
        return under(base, head, *rest)
    return base.joinpath(*rel.parts)


def _inside(p: pathlib.Path, base: pathlib.Path) -> bool:
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


def resolve(stored, *, real: bool = False) -> pathlib.Path:
    """기록에 적힌 경로를 지금 위치로 읽는다.

    - `..` 를 먼저 정리한다(옮긴 폴더 깊이가 달라도 같은 파일을 가리키게). `~` 는 글자 그대로 둔다.
    - OZL_PRIVATE 로 바꾼 뿌리 아래를 이미 가리키면(시험 사본이 방금 적은 경로) 그대로
    - 체크아웃의 private/ 아래(상대 `private/...` 또는 절대)면: 첫 칸이 옛 이름이면 그 이름의 지금 위치로, 아니면 뿌리 아래 그대로
    - 그 밖의 상대 경로는 저장소 루트 아래, 그 밖의 절대 경로(시험의 임시 폴더 따위)는 그대로
    - real=True 면 OZL_PRIVATE 를 보지 않고 운영 위치로 푼다(실제 자료를 읽기만 하는 시험)
    """
    p = pathlib.Path(str(stored))
    q = pathlib.Path(os.path.normpath(p if p.is_absolute() else ROOT / p))
    checkout = real_root()
    cur = checkout if real else root()
    if cur != checkout:
        for base in {cur, cur.resolve()}:
            if _inside(q, base):
                return q
    for base in (checkout, checkout.resolve()):
        if _inside(q, base):
            return _remap(pathlib.PurePath(q.relative_to(base)), cur)
    return q
