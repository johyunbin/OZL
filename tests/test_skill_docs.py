"""스킬 문서(.claude/skills/)가 실제 명령, 실제 파일과 어긋나지 않는지 본다.

- 문서가 적은 `-m ozl.<모듈> <하위 명령>` 이 그 모듈의 --help 에 있다.
- 문서가 가리키는 저장소 안의 파일이 있다.
- SKILL.md 첫머리 표에 갈래마다 네 가지(언제 부르는가, 받는 것과 내는 것, 사용자가 하는 일과 스킬이 하는 일, 하지 않는 것)가 있다.
- 승인, 내림, 공개용 내보내기 명령이 든 줄은 하지 않는다는 말을 함께 가진다.
- 정해진 때마다 도는 실행을 전제로 한 문장이 없다.
- /syuka 스킬(find, deck, ad): 명령 셋의 순서, 덮는 범위, 요약 규칙, 겹침 판정, 카드 한 건의 순서, 광고 칸의 지금 상태.
- 옛 일일 데스크 문서(skills/ozl/SKILL.md)의 머리에 예약 실행 문장이 없고, 옛 0~4절은 보관 파일에 있다.
"""
import functools
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

from ozl import paths as ozlpaths

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".claude" / "skills"
DOCS = sorted(p for p in SKILLS.rglob("*") if p.is_file() and p.suffix in (".md", ".js"))
# 스킬마다 첫머리 표에 있어야 하는 갈래
BRANCHES = {"ozl": ["/ozl find", "/ozl make", "/ozl status"], "syuka": ["/syuka find", "/syuka deck", "/syuka ad", "/syuka predict", "/syuka score"]}
# --help 를 부를 때 주는 자료 루트. 도움말은 아무것도 쓰지 않아야 하므로 이 폴더는 끝까지 생기지 않는다.
PROBE = pathlib.Path(tempfile.gettempdir()) / "ozl_skill_docs_probe_root"
COLUMNS = ["언제 부르는가", "받는 것", "내는 것", "사용자가 하는 일", "스킬이 하는 일", "하지 않는 것"]

CMD = re.compile(r"(?:-m\s+|`)(ozl(?:\.[a-z_]+)+)\s+([a-z][a-z0-9-]*)(?![\w.])(?:\s+([a-z][a-z-]*)(?![\w.-]))?")
PATH = re.compile(r"(?<![\w/.~-])((?:src|tests|scripts|agent|docs|skills|apps|tracks|\.claude)/[\w./-]+)")
LOCAL = re.compile(r"`((?:make|find|deck|review)/[\w./-]*)`")
SIBLING = re.compile(r"`(\d\d_\w+\.md|principles\.md|runner\.md|find\.md|ad\.md|workflow_\w+\.js|board_view\.py)`")
HELPER = re.compile(r"(?:`BV|board_view\.py)\s+([a-z][a-z-]*)(?![\w.-])")
FORBIDDEN_CMD = re.compile(r"(?<![/\w])approve\b|\bwithdraw\b|export\s+--public")
NEGATION = ("않는다", "금지", "막")
SCHEDULED = ("예약 실행이면", "하루 한 번 아침", "ozl-am", "ozl-pm", "ozl-weekly")
SYUKA = SKILLS / "syuka"
SYUKA_DOCS = ("SKILL.md", "find.md", "deck/01_card.md", "ad.md")
OLD_DOC = ROOT / "skills" / "ozl" / "SKILL.md"          # 옛 일일 데스크 문서. 지금은 5절(덱 완성 절차)과 옛 인자 대응표만 남는다
ARCHIVE = ROOT / "skills" / "ozl" / "archive"
SECTION5 = "## 5. `build"
# 예약 실행을 전제로 한 옛 문장의 조각. 옛 문서의 머리(5절 앞)에 남아 있으면 안 된다
OLD_PREMISE = SCHEDULED + ("예약 실행에서는", "예약 실행인데", "쓰기 범위(예약 실행)", "**멱등**", "무동작 종료")
# 외부 모델을 부르는 길의 이름. /syuka 지시서에는 없어야 한다(외부로 나가는 것은 5절의 검토 묶음뿐이다)
EXTERNAL_CALLS = ("multimodel_request", "mm_request", "codex exec", "codex_smart", "gemini_web", "chatgpt_web", "agy ")


def text(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def rel(p: pathlib.Path) -> str:
    return str(p.relative_to(ROOT))


def skill_root(p: pathlib.Path) -> pathlib.Path:
    return SKILLS / p.relative_to(SKILLS).parts[0]


def doc_commands() -> list[tuple[str, str, str]]:
    found = set()
    for p in DOCS:
        for m in CMD.finditer(text(p)):
            found.add((m.group(1), m.group(2), m.group(3) or ""))
    return sorted(found)


def doc_flags() -> list[tuple[str, str, str, str]]:
    """명령 뒤에 같은 코드 조각 안에서 따라오는 긴 옵션(--이름). (모듈, 하위 명령, 그 아래 명령 또는 "", 옵션)"""
    found = set()
    for p in DOCS:
        for line in text(p).splitlines():
            for m in CMD.finditer(line):
                tail = line[m.end():].split("`", 1)[0]
                found.update((m.group(1), m.group(2), m.group(3) or "", f)
                             for f in re.findall(r"(?<![\w-])(--[a-z][^\s=]*)", tail))
    return sorted(found)


@functools.lru_cache(maxsize=None)
def help_text(*argv: str) -> str:
    env = dict(os.environ, OZL_DESK_ROOT=str(PROBE))
    r = subprocess.run([sys.executable, "-m", *argv, "--help"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def choices(help_out: str) -> set[str]:
    out = set()
    for group in re.findall(r"\{([^{}]+)\}", help_out):
        out.update(x.strip() for x in group.split(","))
    return out


def test_docs_found():
    names = {rel(p) for p in DOCS}
    for need in ("SKILL.md", "find/find.md", "find/board_view.py", "make/runner.md", "make/01_draft.md", "make/workflow_make.js"):
        assert (SKILLS / "ozl" / need).is_file(), need
    assert ".claude/skills/ozl/SKILL.md" in names and ".claude/skills/ozl/find/find.md" in names


def test_doc_commands_are_collected():
    cmds = doc_commands()
    assert ("ozl.issues", "article-new", "") in cmds
    assert ("ozl.ops", "queue", "set") in cmds and ("ozl.ops", "queue", "list") in cmds
    assert ("ozl.signals", "explain", "") in cmds
    assert all(not sub.startswith("t2") for _, sub, _ in cmds)


@pytest.mark.parametrize("module,sub,sub2", doc_commands(), ids=lambda v: v or "-")
def test_doc_command_exists_in_help(module, sub, sub2):
    top = help_text(module)
    assert sub in choices(top) or re.search(rf"{re.escape(module)}\s+{re.escape(sub)}(?![\w-])", top), \
        f"{module} {sub}: `python -m {module} --help` 에 없는 하위 명령이다"
    if sub2:
        inner = choices(help_text(module, sub))
        if inner:
            assert sub2 in inner, f"{module} {sub} {sub2}: `python -m {module} {sub} --help` 에 없다"


@pytest.mark.parametrize("module,sub,sub2,flag", doc_flags(), ids=lambda v: v or "-")
def test_doc_command_option_exists_in_help(module, sub, sub2, flag):
    # 그 아래 명령(예: score events)이 있으면 옵션은 그 명령의 도움말에 있다
    argv = (module, sub, sub2) if sub2 and sub2 in choices(help_text(module, sub)) else (module, sub)
    assert re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text(*argv)), \
        f"{' '.join(argv)} {flag}: `python -m {' '.join(argv)} --help` 에 없는 옵션이다"


def test_flag_check_reads_whole_option_token(monkeypatch, tmp_path):
    """옵션 이름은 토큰 전체로 읽는다: 숫자가 든 옵션은 통과하고, 그 뒤에 글자를 붙인 오타는 걸린다(그 아래 명령의 도움말에서 찾는다)."""
    fake = tmp_path / "planted.md"
    fake.write_text("`PY -m ozl.syuka score events P --from-v3 vidTEST0001 --from-v3_typo x --replace.typo`\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "DOCS", [fake])
    found = doc_flags()
    assert ("ozl.syuka", "score", "events", "--from-v3") in found
    assert ("ozl.syuka", "score", "events", "--from-v3_typo") in found
    assert ("ozl.syuka", "score", "events", "--replace.typo") in found
    events_help = help_text("ozl.syuka", "score", "events")
    assert re.search(r"(?<![\w-])--from-v3(?![\w-])", events_help)
    assert not re.search(r"(?<![\w-])--from-v3_typo(?![\w-])", events_help)
    assert not re.search(r"(?<![\w-])--replace\.typo(?![\w-])", events_help)


def test_command_checks_catch_planted_errors():
    """검사가 잡는지(음성 대조): 없는 하위 명령, 없는 옵션, 없는 파일을 지어낸 문장에 심는다."""
    planted = "`PY -m ozl.issues publish-now <번호>` 와 `PY -m ozl.ops queue drop`, `src/ozl/nope.py`, `make/99_none.md`"
    cmds = [(m.group(1), m.group(2), m.group(3) or "") for m in CMD.finditer(planted)]
    assert cmds == [("ozl.issues", "publish-now", ""), ("ozl.ops", "queue", "drop")]
    assert "publish-now" not in choices(help_text("ozl.issues"))
    assert "drop" not in choices(help_text("ozl.ops", "queue"))
    assert "--no-such-option" not in help_text("ozl.ops", "queue")
    assert [m.group(1) for m in PATH.finditer(planted)] == ["src/ozl/nope.py"] and not (ROOT / "src/ozl/nope.py").exists()
    assert [m.group(1) for m in LOCAL.finditer(planted)] == ["make/99_none.md"]


def test_help_never_creates_the_probe_root():
    assert not PROBE.exists()


@pytest.mark.parametrize("doc", DOCS, ids=rel)
def test_referenced_files_exist(doc):
    body = text(doc)
    missing = []
    for m in PATH.finditer(body):
        ref = m.group(1).rstrip(".")
        if not (ROOT / ref).exists():
            missing.append(ref)
    base = skill_root(doc)
    for m in LOCAL.finditer(body):
        if not ((base / m.group(1)).exists() or (doc.parent / m.group(1)).exists()):
            missing.append(m.group(1))
    for m in SIBLING.finditer(body):
        if not list(base.rglob(m.group(1))):
            missing.append(m.group(1))
    assert not missing, f"{rel(doc)}: 없는 파일을 가리킨다 {sorted(set(missing))}"


def first_table(body: str) -> list[list[str]]:
    """첫 `## ` 제목 앞에 나오는 첫 표의 줄(머리 줄 포함, 구분 줄 제외)."""
    head = body.split("\n## ", 1)[0]
    rows, started = [], False
    for line in head.splitlines():
        if line.startswith("|"):
            started = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
        elif started:
            break
    return rows


@pytest.mark.parametrize("skill", sorted(BRANCHES))
def test_skill_head_table_has_four_items_per_branch(skill):
    rows = first_table(text(SKILLS / skill / "SKILL.md"))
    assert rows, "첫머리에 표가 없다"
    header, body = rows[0], rows[1:]
    for col in COLUMNS:
        assert col in header, f"첫머리 표에 '{col}' 칸이 없다"
    for branch in BRANCHES[skill]:
        hit = [r for r in body if r[0].startswith(f"`{branch}")]
        assert len(hit) == 1, f"{branch} 줄이 {len(hit)}개"
        cells = dict(zip(header, hit[0]))
        for col in COLUMNS:
            assert len(cells.get(col, "")) >= 2, f"{branch}: '{col}' 칸이 비었다"
    assert len(body) == len(BRANCHES[skill]), "표의 갈래 수가 정해 둔 것과 다르다"


@pytest.mark.parametrize("doc", DOCS, ids=rel)
def test_approval_commands_only_appear_with_a_prohibition(doc):
    bad = [line.strip()[:120] for line in text(doc).splitlines()
           if FORBIDDEN_CMD.search(line) and not any(w in line for w in NEGATION)]
    assert not bad, f"{rel(doc)}: 승인, 내림, 공개용 내보내기 명령이 금지 문장 없이 나온다 {bad}"


def test_prohibition_check_catches_a_planted_line():
    assert FORBIDDEN_CMD.search("끝나면 `python -m ozl.issues approve <번호>` 를 돌린다")
    assert FORBIDDEN_CMD.search("`export --public` 로 내보낸다") and FORBIDDEN_CMD.search("`withdraw` 한다")
    assert not FORBIDDEN_CMD.search("승인은 사용자가 운영 화면 `/approve` 에서 한다")
    assert not FORBIDDEN_CMD.search("`approval.json` 은 손으로 쓰지 않는 파일이다")


@pytest.mark.parametrize("doc", DOCS, ids=rel)
def test_no_scheduled_run_premise(doc):
    body = text(doc)
    hit = [w for w in SCHEDULED if w in body]
    assert not hit, f"{rel(doc)}: 정해진 때마다 도는 실행을 전제로 한 말이 남았다 {hit}"


def test_ozl_skill_says_manual_only_and_where_approval_happens():
    body = text(SKILLS / "ozl" / "SKILL.md")
    assert "사용자가 부를 때만 돈다" in body and "예약 실행은 두지 않는다" in body
    assert "수집을 돌리지 않는다" in body
    for doc in (SKILLS / "ozl" / "SKILL.md", SKILLS / "ozl" / "find" / "find.md"):
        assert re.search(r"승인은 사용자가 운영 화면 `/approve` 에서 한다", text(doc)), rel(doc)


def test_ozl_old_arguments_are_mapped():
    body = text(SKILLS / "ozl" / "SKILL.md")
    rows = {line.split("|")[1].strip(): line.split("|")[2].strip() for line in body.splitlines()
            if line.startswith("| `") and line.count("|") == 3}
    assert "`/ozl find`" in rows["`am`, `pm`, `weekly`"] and "보관" in rows["`am`, `pm`, `weekly`"]
    assert "/syuka deck" in rows["`pick <card_id>`, `build <card_id>`"]
    late = rows["`verify <claim_id…>`, `publish <card_id…>`"]
    assert "사용자가 그렇게 말했을 때만" in late and "agent/desk.md" in late


def test_ozl_make_keeps_its_steps_and_guards():
    body = text(SKILLS / "ozl" / "SKILL.md")
    heads = [l for l in body.splitlines() if l.startswith("## ") or l.startswith("### ")]
    order = ["## 공통", "## /ozl find", "## /ozl status", "## /ozl make", "## 0. 가드", "## 1. 회차의 짜임", "## 2. 돌리는 법",
             "## 3. 단계", "### 1) 대상 정하기", "### 2) 쓰기", "### 3) 재대조와 문장 대조", "### 4) 고치기", "### 5) 검토 묶음",
             "### 6) 다른 계열의 해석 점검", "### 7) 고침 회차", "### 8) 마무리"]
    at = [next((i for i, h in enumerate(heads) if h.startswith(o)), -1) for o in order]
    assert -1 not in at and at == sorted(at), dict(zip(order, at))
    for sentence in ("**승인(`approve`)과 공개용 내보내기(`export --public`)는 하지 않는다.** 내림(`withdraw`)도 하지 않는다.",
                     "대기열 파일(`ops/make_queue.json`)을 손으로 고치지 않는다.",
                     "사람에 관한 의혹, 선거 판세, 사생활이 중심인 소재는 만들지 않고 멈춤으로 둔다",
                     "작성자는 재대조 칸을 채우지 않고, 다른 프로세스(`claude -p`)나 에이전트를 띄워 스스로 검토하지 않는다.",
                     "6단계는 워크플로와 서브에이전트에 맡기지 않는다. 본 세션이 직접 한다."):
        assert sentence in body, sentence
    step1 = body.split("### 1) 대상 정하기", 1)[1].split("### 2) 쓰기", 1)[0]
    for word in ("대기열 번호", "화제 번호", "인자 없음", "queue list", "BV picks", "BV note --pick", 'BV note --add', "/ozl find"):
        assert word in step1, word
    step8 = body.split("### 8) 마무리", 1)[1]
    assert "queue set <job_id> --state 끝남" in step8 and "BV result <key> --state 끝남" in step8


def test_runner_guard_moved_to_its_own_doc():
    skill = text(SKILLS / "ozl" / "SKILL.md")
    runner = text(SKILLS / "ozl" / "make" / "runner.md")
    assert "## 실행기 설정 예시" not in skill and '"allowed_tools"' not in skill
    assert "`make/runner.md`" in skill and "실행기는 꺼져 있다" in skill
    for word in ("OZL_OPS_RUNNER=1", "Codex 를 부르지 않는다", "다른 계열의 해석 점검을 보내지 않는다", "--disallowedTools",
                 '"allowed_tools"', "꺼져 있다", "runner --once --dry-run"):
        assert word in runner, word


def test_draft_instruction_and_workflow_know_the_pick_record():
    draft = text(SKILLS / "ozl" / "make" / "01_draft.md")
    first = draft.split("\n## ", 1)[0]
    assert "고르기 기록" in first and "단서" in first
    chosen = next(l for l in draft.splitlines() if "`chosen_by`" in l)
    assert "대화에서 고른 건" in chosen and "'사람'" in chosen
    wf = text(SKILLS / "ozl" / "make" / "workflow_make.js")
    assert "brief(단서 파일: 조사 묶음이나 /ozl find 의 고르기 기록)" in wf
    assert "고르기 기록이면 picks 에서 이 대상의 줄만 읽는다" in wf


def test_helper_subcommands_and_flags_in_docs_exist():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ozl_skill_board_view_docs", SKILLS / "ozl" / "find" / "board_view.py")
    bv = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True       # 스킬 폴더에 __pycache__ 를 남기지 않는다
    try:
        spec.loader.exec_module(bv)
    finally:
        sys.dont_write_bytecode = keep
    used = set()
    for p in DOCS:
        if p.suffix == ".md":
            used.update(m.group(1) for m in HELPER.finditer(text(p)))
    assert {"note", "picks", "result"} <= used
    assert used <= set(bv.COMMANDS), f"문서가 적은 도우미 하위 명령이 없다: {sorted(used - set(bv.COMMANDS))}"
    env = dict(os.environ, OZL_DESK_ROOT=str(PROBE))
    helps = {sub: subprocess.run([sys.executable, str(SKILLS / "ozl" / "find" / "board_view.py"), *([sub] if sub else []), "--help"],
                                 cwd=ROOT, env=env, capture_output=True, text=True, timeout=120).stdout
             for sub in ("", "note", "picks", "result")}
    for sub, flags in {"": ("--board", "--top", "--category", "--match", "--all", "--json"),
                       "note": ("--pick", "--drop", "--add"), "picks": ("--json",), "result": ("--state", "--issue", "--note")}.items():
        for flag in flags:
            assert flag in helps[sub], f"board_view.py {sub} --help 에 {flag} 가 없다"


@pytest.mark.parametrize("name", ["workflow_make.js", "workflow_revise.js"])
def test_workflow_scripts_parse(name, tmp_path):
    """워크플로 스크립트는 맨 위에서 await 와 return 을 쓴다. 함수로 감싼 사본이 문법 검사를 통과하는지 본다."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 가 없다")
    src = text(SKILLS / "ozl" / "make" / name)
    assert src.startswith("export const meta = {")
    wrapped = ("const args = {}; const agent = async () => ({}); const phase = () => {}; const log = () => {};\n"
               + src.replace("export const meta", "const meta", 1).replace("\nconst A = args || {}", "\nasync function main() {\nconst A = args || {}", 1)
               + "\n}\n")
    assert "async function main() {" in wrapped
    f = tmp_path / (name.replace(".js", "") + "_wrapped.mjs")
    f.write_text(wrapped, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


# ── /syuka 스킬 ───────────────────────────────────────────────────────────────

def syuka(name: str) -> str:
    return text(SYUKA / name)


def front_matter(p: pathlib.Path) -> dict:
    import yaml
    body = text(p)
    assert body.startswith("---\n"), f"{rel(p)}: 머리말이 없다"
    return yaml.safe_load(body[4:body.index("\n---\n", 4)])


def test_syuka_docs_found():
    for need in SYUKA_DOCS:
        assert (SYUKA / need).is_file(), need
    names = {rel(p) for p in DOCS}
    assert {f".claude/skills/syuka/{n}" for n in SYUKA_DOCS} <= names


@pytest.mark.parametrize("skill,words", [("ozl", ("화제", "이슈 글", "/ozl find", "/ozl make", "/ozl status")),
                                         ("syuka", ("슈카", "슈카월드", "덱", "/syuka find", "/syuka deck", "/syuka ad"))])
def test_skill_front_matter_names_the_skill_and_its_words(skill, words):
    fm = front_matter(SKILLS / skill / "SKILL.md")
    assert set(fm) == {"name", "description"} and fm["name"] == skill
    assert re.fullmatch(r"[a-z0-9-]+", fm["name"]), "스킬 이름은 영문 소문자, 숫자, 하이픈만 쓴다"
    for w in words:
        assert w in fm["description"], f"{skill}: 설명 줄에 '{w}' 가 없다"
    assert "사용자가 부를 때만 돈다" in fm["description"]


def test_syuka_common_rules():
    body = syuka("SKILL.md")
    common = body.split("\n## 공통", 1)[1].split("\n## ", 1)[0]
    for sentence in ("전사 문장과 슬라이드 문구(문자 인식 결과)는 답, 카드, 기록, 사양, 메모 어디에도 옮기지 않는다.",
                     "다른 모델 계열에 보내는 것은 `PY -m ozl.render bundle <사양>` 이 만든 검토 묶음뿐이다",
                     "이슈 글의 승인은 사용자가 운영 화면 `/approve` 에서 한다",
                     "사용자가 그렇게 말했을 때만 하고, 이 스킬이 스스로 하지 않는다.",
                     "어느 단계도 사용자에게 원문 대조나 확인을 요청하지 않는다.",
                     "예약 작업이나 launchd 작업을 만들거나 켜지 않는다. 커밋과 푸시를 하지 않는다."):
        assert sentence in common, sentence
    for word in ("`PY -m ozl.research publish`", "`PY -m ozl.research human-verify`", "`tracks/syuka/decks/`"):
        assert word in common, word
    assert "사용자가 부를 때만 돈다" in body and "예약 실행은 두지 않는다" in body
    # 갈래마다 자기 지시서를 가리킨다
    for head, docs in (("## /syuka find", ("`find.md`",)), ("## /syuka deck", ("`deck/01_card.md`", "`find.md`", "`skills/ozl/SKILL.md`", "`agent/deck.md`")),
                       ("## /syuka ad", ("`ad.md`",))):
        part = body.split("\n" + head, 1)[1].split("\n## ", 1)[0]
        for d in docs:
            assert d in part, f"{head}: {d} 를 가리키지 않는다"


@pytest.mark.parametrize("name", SYUKA_DOCS)
def test_syuka_docs_have_no_external_model_route(name):
    body = syuka(name)
    hit = [w for w in EXTERNAL_CALLS if w in body]
    assert not hit, f"syuka/{name}: 외부 모델을 부르는 길의 이름이 있다 {hit}"
    assert "옮기지 않는다" in body, f"syuka/{name}: 전사 문장과 슬라이드 문구를 옮기지 않는다는 말이 없다"


@pytest.mark.parametrize("name", SYUKA_DOCS)
def test_syuka_docs_say_who_decides_publication(name):
    """스킬마다: 승인과 공개는 사용자가 한다(이슈 글은 운영 화면, 카드 발행과 덱 공개는 사용자가 말했을 때만)."""
    body = syuka(name)
    assert "사용자가 그렇게 말했을 때만" in body or "운영 화면 `/approve`" in body, f"syuka/{name}"


def test_syuka_find_orders_the_three_commands_and_states_coverage():
    body = syuka("find.md")
    order = ["-m ozl.syuka find-v3 <낱말>", "-m ozl.research.videos find --keyword <핵심어>", "-m ozl.research coverage <낱말…> --months <달> --fulltext"]
    at = [body.find(o) for o in order]
    assert -1 not in at and at == sorted(at), dict(zip(order, at))
    heads = [l for l in body.splitlines() if l.startswith("### ")]
    assert [h[:6] for h in heads] == ["### 1.", "### 2.", "### 3.", "### 4.", "### 5."]
    # 자료가 덮는 범위: 3판은 2025·2026년 전부와 2024년 일부
    assert "3판 자료는 2025년과 2026년 영상(본편과 생방송 전체)을 전부, 2024년 영상을 일부 덮는다." in body
    assert "자료가 덮는 범위" in body and "이 자료에서는 찾지 못했다" in body
    skill = syuka("SKILL.md")
    assert "3판 자료는 2025년과 2026년 영상 전부와 2024년 영상 일부만 덮는다." in skill
    # 낱말은 한 번에 하나(find-v3 는 인자 하나만 받는다)
    assert "word" in help_text("ozl.syuka", "find-v3") and "낱말은 한 번에 하나만 받는다" in body
    assert "기본 범위는 24개월이다" in body and "`--months 6`" in body


def test_syuka_find_summary_rules_and_overlap_verdicts():
    body = syuka("find.md")
    table = body.split("### 4. 영상별 표로 요약한다", 1)[1].split("### 5.", 1)[0]
    for cell in ("| 때 |", "| 영상 |", "| 무엇을 다뤘나 |", "| 그때의 수치와 기준 시점 |", "| 관계 |", "https://youtu.be/<video_id>", "자기 말로 60자 이내"):
        assert cell in table, cell
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from ozl.research import cards
    finally:
        sys.path.pop(0)
    assert len(cards.RELATIONS) == 5
    for r in cards.RELATIONS:
        assert f"`{r}`" in table, f"관계 '{r}' 가 요약 규칙에 없다"
    verdicts = body.split("### 5. 겹침을 판정한다", 1)[1].split("\n## ", 1)[0]
    rows = [l.split("|")[1].strip() for l in verdicts.splitlines() if l.startswith("| ") and not l.startswith("| 판정 |")]
    assert rows == ["같은 사건(방송 뒤 새 사실 없음)", "같은 사건(방송 뒤 새 전개)", "같은 흐름(사건은 다름)", "무관", "판정 못 함"], rows
    for word in ("중심 질문", "제목 낱말 일치만으로 판정하지 않는다", "판정을 누가 하는가", "다른 에이전트(읽기 전용)", "전사 문장 없이"):
        assert word in verdicts, word


def test_syuka_card_instruction_has_the_single_card_steps():
    body = syuka("deck/01_card.md")
    order = ["### 0-2. 민감 확인", "### 0-3. 겹침 확인", "### 1. 1차 출처 조사", "-m ozl.research ids --slot am -n 1",
             "skills/ozl/card_template.yaml", "skills/ozl/claim_template.yaml", "-m ozl.research validate --slot am",
             "### 4. 독립 검증", "-m ozl.research pick <card_id>", "## 넘어가기", "-m ozl.render progress <card_id> --start --by <이름>"]
    at = [body.find(o) for o in order]
    assert -1 not in at and at == sorted(at), dict(zip(order, at))
    sens = body.split("### 0-2. 민감 확인", 1)[1].split("### 0-3.", 1)[0]
    for word in ("`deck_blocked`", "`RED`", "만들지 않는다", "`src/ozl/research/sensitive.py`", "`YELLOW`"):
        assert word in sens, word
    assert "받지 못했으면 10분으로 잡고 사용자에게 그렇게 알린다" in body and "outline --minutes 10" in body
    assert "쓴 세션이 스스로 채점하지 않는다" in body and "**서브에이전트 도구가 없으면** 여기서 멈춘다" in body
    assert "`checks.recalculated`" in body        # 양식의 false 로 두면 등급 올리기에서 걸린다(시험 사본에서 걸린 곳)
    tail = body.split("## 넘어가기", 1)[1]
    assert "`skills/ozl/SKILL.md` 의 5절" in tail and "`agent/deck.md`" in tail and "옮겨 적지 않았다" in tail


def section5() -> str:
    body = text(OLD_DOC)
    return body[body.index(SECTION5):]


def test_syuka_docs_point_to_section5_instead_of_copying_it():
    long_lines = [l.strip() for l in section5().splitlines() if len(l.strip()) >= 60]
    assert len(long_lines) >= 10
    for name in SYUKA_DOCS:
        body = syuka(name)
        copied = [l[:60] for l in long_lines if l in body]
        assert not copied, f"syuka/{name}: 5절의 줄을 그대로 옮겼다 {copied}"


def sponsorship_code() -> dict | None:
    """덱 코드에 광고 칸 검사가 있으면 그 상수들, 없으면 None."""
    spec_py = ROOT / "src" / "ozl" / "render" / "spec.py"
    if "def sponsorship_errors" not in text(spec_py):
        return None
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from ozl.render import spec as S
    finally:
        sys.path.pop(0)
    return {"fields": S.SPONSOR_FIELDS, "kinds": S.SPONSOR_KINDS, "stage": S.SPONSOR_STAGE, "share": S.SPONSOR_MAX_SHARE, "key": S.SPONSOR}


def test_syuka_ad_inputs_table_checks_and_plan():
    body = syuka("ad.md")
    inputs = body.split("## 받는 것 (여섯)", 1)[1].split("\n## ", 1)[0]
    rows = [l.split("|")[1].strip() for l in inputs.splitlines() if l.startswith("| ") and not l.startswith("| 받는 것 |")]
    assert rows == ["카드 번호", "광고 종류", "광고주 이름", "광고주 제공 자료 폴더", "광고 구간의 위치와 길이", "표시 문구"], rows
    assert "`private/desk/sponsor/<card_id>/`" in inputs
    table = body.split("### 1. 광고주 자료 대조표", 1)[1].split("### 2.", 1)[0]
    cols = [l.split("|")[1].strip() for l in table.splitlines() if l.startswith("| ") and not l.startswith("| 칸 |")]
    assert cols == ["번호", "광고주 자료의 주장", "자료의 자리", "수치가 있는가", "찾은 원문", "기록 번호", "판정", "까닭"], cols
    assert "원문으로 받침 / 광고주 제공으로만 소개 / 쓰지 않음" in table
    for verdict in ("**원문으로 받침**", "**광고주 제공으로만 소개**", "**쓰지 않음**"):
        assert verdict in table, verdict
    sens = body.split("### 2. 민감 점검", 1)[1].split("### 3.", 1)[0]
    kinds = [l.split("|")[1].strip() for l in sens.splitlines() if l.startswith("| ") and not l.startswith("| 갈래 |")]
    assert [k.split("(")[0] for k in kinds] == ["정부와 공공기관 협업", "금융 상품", "건강 주장", "규제 산업"], kinds
    assert "1차 문서(법령, 고시, 심의 규정의 본문)를 먼저 읽는다" in sens and "멈춘 뒤" in sens
    plan = body.split("### 3. 광고 표시 계획", 1)[1].split("### 4.", 1)[0]
    for word in ("표시 문구", "첫 장과 끝 장", "말로 할 문장", "띠", "덱 밖에서 할 것", "확인하지 못한 것", "한글"):
        assert word in plan, word
    assert "광고주 자료만으로 수치를 쓰지 않는다." in body


def test_syuka_ad_matches_the_sponsorship_code_as_it_is_now():
    """광고 칸 검사가 코드에 있으면 그 칸을 쓰는 단계로, 없으면 '아직 없다'로 적혀 있어야 한다."""
    body = syuka("ad.md")
    code = sponsorship_code()
    missing = "광고 구간의 장을 검사하는 코드는 아직 없다"
    if code is None:
        assert missing in body and "대조표, 민감 점검, 표시 계획까지" in body
        return
    assert missing not in body
    step = body.split("### 4. 사양의 광고 칸", 1)[1].split("### 5.", 1)[0]
    assert f"`{code['key']}`" in step and f"`stage: {code['stage']}`" in step
    for f in code["fields"]:
        assert f"`{f}`" in step, f"광고 칸의 '{f}' 가 지시서에 없다"
    for k in code["kinds"]:
        assert k in step, k
    assert f"{round(code['share'] * 100)}%" in body
    assert "-m ozl.render check <사양>" in step and "`agent/deck.md` 의 「광고·협업 회차」" in step
    assert "sponsorship" in help_text("ozl.render", "check")


def heredocs(body: str) -> list[str]:
    return re.findall(r"<<'EOF'\n(.*?)\nEOF\n", body, flags=re.S)


@pytest.mark.parametrize("name", SYUKA_DOCS)
def test_syuka_python_snippets_compile(name):
    for i, code in enumerate(heredocs(syuka(name))):
        compile(code, f"syuka/{name}#{i}", "exec")


def test_syuka_sandbox_capture_snippet_runs_in_a_copy(tmp_path):
    """「시험 사본에서 돌릴 때」의 조각을 사본에서 실제로 돌린다. 원문은 지어낸 로컬 파일이고 웹 요청은 없다."""
    import yaml
    skill = syuka("SKILL.md")
    part = skill.split("\n## 시험 사본에서 돌릴 때", 1)[1]
    snippet = next(c for c in heredocs(part) if "capture_claim(" in c)
    assert "fetcher=local_fetch" in snippet and "assert C.ROOT ==" in snippet
    copy = tmp_path / "copy"
    shutil.copytree(ROOT / "src", copy / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    env = dict(os.environ, PYTHONPATH=str(copy / "src"), PYTHONDONTWRITEBYTECODE="1")
    env.pop("OZL_PRIVATE", None)
    env.pop("OZL_DESK_ROOT", None)
    guard = re.search(r'-c "(from ozl\.research import cards; print\(cards\.ROOT\))"', part).group(1)
    seen = subprocess.run([sys.executable, "-c", guard], cwd=copy, env=env, capture_output=True, text=True, timeout=120)
    assert seen.stdout.strip() == str(copy.resolve()), seen.stdout + seen.stderr      # 사본이 잡혔다
    cid = "2099-01-01-am-01-c1"
    url = "https://example.org/hanbit/press"
    doc = tmp_path / "press.html"
    # 사본 글이 80자(capture.MIN_TEXT)보다 짧으면 "프로그램 대조 불가"가 되므로 문장을 넉넉히 둔다
    doc.write_text("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>지어낸 보도자료</title></head><body>"
                   "<h1>한빛시 공유 자전거 이용 현황(지어낸 보도자료)</h1>"
                   "<p>한빛시 통계과는 2099년 3월 공유 자전거 이용 현황을 발표했다.</p>"
                   "<p>2099년 3월 한빛시 공유 자전거 대여 건수는 41만 2천 건으로 집계됐다.</p>"
                   "<p>한빛시는 이 수치가 잠정치이며 6월에 확정치를 낸다고 밝혔다.</p></body></html>", encoding="utf-8")
    claim = yaml.safe_load(text(ROOT / "skills" / "ozl" / "claim_template.yaml"))
    claim.update(claim_id=cid, card_id=cid[:-3], observed="2099년 3월 한빛시 공유 자전거 대여 건수는 41만 2천 건으로 집계됐다.")
    claim["source"]["url"] = url
    cpath = ozlpaths.under(copy / "private", "desk", "claims", "2099-01-01", f"{cid}.yaml")
    cpath.parent.mkdir(parents=True)
    cpath.write_text(yaml.safe_dump(claim, allow_unicode=True, sort_keys=False), encoding="utf-8")
    code = (snippet.replace("<사본의 절대 경로>", str(copy)).replace("<기록의 source.url>", url)
            .replace("<그 문서를 대신할 로컬 파일의 절대 경로>", str(doc)).replace("<기록 번호>", cid).replace("<쓴 쪽 이름>", "시험 작성자"))
    assert "<" not in re.sub(r"<<|<=|<module>", "", code.split("def local_fetch", 1)[0]), "채우지 않은 자리표시가 남았다"
    real = ozlpaths.real_at("desk", "captures", cid)
    before = real.exists()
    r = subprocess.run([sys.executable, "-"], input=code, cwd=copy, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split()[:2] == [cid, "찾음"], r.stdout
    got = yaml.safe_load(cpath.read_text(encoding="utf-8"))["verification"]
    assert got["match"]["found"] and got["capture"]["ok"] and got["author"]["by"] == "시험 작성자"
    assert (copy / got["capture"]["text_path"]).is_file() and (ozlpaths.under(copy / "private", "desk", "captures", cid, "source.html")).is_file()
    assert real.exists() == before, "실제 자료 루트에 사본이 쓰였다"
    # 표에 없는 주소는 받지 않고 멈춘다
    bad = subprocess.run([sys.executable, "-"], input=code.replace(f'"{url}":', '"https://example.org/other":'), cwd=copy, env=env,
                         capture_output=True, text=True, timeout=120)
    assert bad.returncode != 0 and "KeyError" in bad.stderr


# ── 옛 일일 데스크 문서(skills/ozl/SKILL.md)와 보관 파일 ──────────────────────

def old_head() -> str:
    body = text(OLD_DOC)
    return body[:body.index(SECTION5)]


def archive_file() -> pathlib.Path:
    found = sorted(ARCHIVE.glob("desk_routine_*.md"))
    assert len(found) == 1, f"보관 파일이 {len(found)}개"
    assert re.fullmatch(r"desk_routine_\d{8}_\d{6}\.md", found[0].name), found[0].name
    return found[0]


def test_old_desk_doc_head_has_no_scheduled_run_premise():
    head = old_head()
    assert not head.startswith("---") and "name: ozl" not in head, "스킬 머리말을 떼지 않았다"
    hit = [w for w in OLD_PREMISE if w in head]
    assert not hit, f"옛 문서의 머리에 예약 실행을 전제로 한 말이 남았다 {hit}"
    heads = [l for l in text(OLD_DOC).splitlines() if l.startswith("## ")]
    assert heads[0] == "## 옛 인자" and heads[1].startswith(SECTION5), heads      # 5절 앞의 절은 대응표 하나뿐이다
    for gone in ("## 0. 가드", "## 1. `am`", "## 2. (옛) `weekly`", "## 3. 사용자 명령", "## 4. 고장 났을 때"):
        assert gone not in head, gone
    assert "`~/OZL/.venv/bin/python`(아래 `PY`)" in head, "5절이 쓰는 PY 의 뜻이 머리에 없다"
    assert "사용자 결정(2026-11-15)" in head and "`.claude/skills/syuka/deck/01_card.md`" in head
    assert rel(archive_file()) in head


def test_old_desk_doc_keeps_one_table_of_old_arguments():
    head = old_head()
    part = head.split("\n## 옛 인자", 1)[1]
    rows = {l.split("|")[1].strip(): l.split("|", 2)[2] for l in part.splitlines() if l.startswith("| `")}
    assert list(rows) == ["`am`, `pm`, `weekly`", "`pick <card_id>`, `build <card_id>`", "`status`", "`verify <claim_id…>`", "`publish <card_id…>`"]
    assert "`/ozl find`" in rows["`am`, `pm`, `weekly`"] and "`/syuka deck`" in rows["`am`, `pm`, `weekly`"]
    assert "`/syuka deck <card_id>`" in rows["`pick <card_id>`, `build <card_id>`"]
    assert "`/ozl status`" in rows["`status`"]
    assert "사용자가 스스로" in rows["`verify <claim_id…>`"] and "모델이 스스로 부르지 않고" in rows["`verify <claim_id…>`"]
    assert "사용자가 공개하라고 했을 때만 한다" in rows["`publish <card_id…>`"] and "--refetch-check" in rows["`publish <card_id…>`"]
    assert len([l for l in head.splitlines() if l.startswith("|")]) == 7, "표는 한 장(머리 줄, 구분 줄, 다섯 줄)이다"


def test_old_desk_doc_head_commands_exist_in_help():
    head = old_head()
    cmds = sorted({(m.group(1), m.group(2)) for m in CMD.finditer(head)})
    assert ("ozl.research", "pick") in cmds and ("ozl.research", "publish") in cmds and ("ozl.research", "capture") in cmds
    for module, sub in cmds:
        assert sub in choices(help_text(module)) or re.search(rf"{re.escape(module)}\s+{re.escape(sub)}(?![\w-])", help_text(module)), f"{module} {sub}"
    for line in head.splitlines():
        for m in CMD.finditer(line):
            for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", line[m.end():].split("`", 1)[0]):
                assert flag in help_text(m.group(1), m.group(2)), f"{m.group(1)} {m.group(2)} {flag}"
    missing = [m.group(1) for m in PATH.finditer(head) if not (ROOT / m.group(1).rstrip(".")).exists()]
    assert not missing, missing


def test_archive_head_has_date_reason_and_where_things_moved():
    body = text(archive_file())
    head, original = body.split("\n## 옛 원문\n", 1)
    assert "보관한 날: 2026-11-15" in head and "까닭: 사용자 결정(2026-11-15)" in head and "## 옮긴 곳" in head
    for where in ("`.claude/skills/ozl/SKILL.md`", "`.claude/skills/syuka/SKILL.md`", "`.claude/skills/ozl/find/find.md`",
                  "`.claude/skills/syuka/find.md`", "`.claude/skills/syuka/deck/01_card.md`", "`skills/ozl/SKILL.md`"):
        assert where in head, where
    missing = [m.group(1) for m in PATH.finditer(head) if not (ROOT / m.group(1).rstrip(".")).exists()]
    assert not missing, missing
    assert "따라 하지 않는다" in head
    # 옛 0~4절은 그대로 보관돼 있고, 5절은 옮기지 않았다
    for kept in ("## 0. 가드 (예약 실행이면 가장 먼저)", "## 1. `am` — 소재 후보 0~3장(하루 한 번 아침)", "## 2. (옛) `weekly`", "## 3. 사용자 명령", "## 4. 고장 났을 때"):
        assert kept in original, kept
    assert SECTION5 not in body
    assert not body.startswith("---"), "보관 파일이 스킬 머리말로 시작하면 안 된다"


def test_section5_is_still_whole():
    """머리를 다시 쓰면서 5절이 잘리지 않았는지 본다. 5절의 내용은 덱 쪽이 고치므로 단계 수는 아래로만 본다."""
    s5 = section5()
    steps = [int(re.match(r"(\d+)\. \*\*", l).group(1)) for l in s5.splitlines() if re.match(r"\d+\. \*\*", l)]
    assert steps == list(range(len(steps))) and len(steps) >= 12, steps
    assert any(l.startswith("끝낼 기준") for l in s5.splitlines())
    assert "`PY -m ozl.render progress <card_id> --start --by <이름>`" in s5


# ── 지침과 공개 문서의 루틴 문장(CLAUDE.md, agent/desk.md, agent/issues.md, README.md, docs/how-it-works.md) ──
# 예약 루틴을 두지 않기로 한 뒤(사용자 결정 2026-11-15) 이 문서들이 스킬을 손으로 부르는 방식과 맞는지 본다.
# AGENTS.md 는 CLAUDE.md 를 가리키는 링크라 따로 보지 않는다(test_agents_md_is_the_guide).

GUIDE = ROOT / "CLAUDE.md"
DESK_RULES = ROOT / "agent" / "desk.md"
ISSUE_RULES = ROOT / "agent" / "issues.md"
README = ROOT / "README.md"
HOW = ROOT / "docs" / "how-it-works.md"
GUIDE_DOCS = (GUIDE, DESK_RULES, ISSUE_RULES, README, HOW, ROOT / "docs" / "tooling.md", ROOT / "agent" / "ops.md")
# 예약 루틴이 있던 때의 말. 지침과 공개 문서에 남아 있으면 안 된다
ROUTINE_ERA = SCHEDULED + ("예약 루틴과 모델이", "모델과 예약 실행은", "루틴을 돌릴 때는", "루틴 재가동", "루틴 프롬프트",
                           "예약 루틴을 붙일 때도", "루틴은 MCP", "멈춰 두었", "0~3장", "/ozl pick", "/ozl am", "오늘 할 일:")
SIX = ("/ozl find", "/ozl make", "/ozl status", "/syuka find", "/syuka deck", "/syuka ad")


def routine_era_words(body: str) -> list[str]:
    return [w for w in ROUTINE_ERA if w in body]


def line_with(body: str, *needles: str) -> str:
    hit = [l for l in body.splitlines() if all(n in l for n in needles)]
    assert len(hit) == 1, f"{needles}: {len(hit)}줄"
    return hit[0]


@pytest.mark.parametrize("doc", GUIDE_DOCS, ids=rel)
def test_guides_have_no_routine_era_words(doc):
    hit = routine_era_words(text(doc))
    assert not hit, f"{rel(doc)}: 예약 루틴이 있던 때의 말이 남았다 {hit}"


def test_agents_md_is_the_guide():
    """Codex 가 읽는 AGENTS.md 는 CLAUDE.md 와 같은 본문이어야 한다. 링크로 두었으므로 따로 고칠 것이 없다."""
    agents = ROOT / "AGENTS.md"
    assert agents.exists(), "AGENTS.md 가 없다"
    body = text(agents)
    # 링크를 지원하지 않는 곳에 받으면 가리키는 경로만 든 파일이 된다. 그 꼴도 받는다
    assert os.path.samefile(agents, GUIDE) or body == text(GUIDE) or body.strip() == "CLAUDE.md"


def test_routine_era_check_catches_planted_lines():
    assert routine_era_words("예약 루틴(`ozl-am`, `ozl-pm`)은 꺼져 있고 발굴은 하루 한 번 아침") == ["하루 한 번 아침", "ozl-am", "ozl-pm"]
    assert routine_era_words("예약 실행은 지난달부터 멈춰 두었고 후보를 한 번에 0~3장 고릅니다") == ["멈춰 두었", "0~3장"]
    assert routine_era_words("대화에서 `/ozl pick <card_id>` 로 통과시킵니다") == ["/ozl pick"]
    assert not routine_era_words("예약 루틴은 두지 않는다. 필요할 때 `/ozl find` 를 손으로 부른다. 매시 수집은 그대로 돈다")


def test_guide_says_no_routines_names_the_skills_and_keeps_the_hourly_collection():
    body = text(GUIDE)
    assert "ozl-am" not in body
    for cmd in SIX:
        assert f"`{cmd}`" in body, cmd
    rule = line_with(body, "예약 루틴은 두지 않는다(사용자 결정 2026-11-15)")
    assert "손으로 부른다" in rule
    assert "launchd `com.hyunbin.ozl-pulse`" in rule and "그대로 돈다" in rule and "끌지는 사용자가 정한다" in rule
    runner = line_with(body, "실행기(`python -m ozl.ops runner`)")
    assert "꺼져 있다" in runner and "Codex 호출 금지" in runner and "Opus 고정" in runner
    assert line_with(body, "지금 쌓인 일:").startswith("3. 지금 쌓인 일: `/ozl status`")
    assert "모델이 스스로 하지 않는다" in line_with(body, "ozl.research human-verify")
    assert "`/ozl find`" in line_with(body, "사용자의 일은 고르기(")
    n = len(body.splitlines())
    assert 54 <= n <= 66, f"CLAUDE.md {n}줄(60줄 안팎이어야 한다)"


def test_guide_table_points_to_the_skills_and_rule_files():
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in text(GUIDE).splitlines() if l.startswith("| ")]
    by = {r[0]: r for r in rows if len(r) == 3}
    issue = by["화제 고르기와 이슈 글 만들기(`/ozl find`, `/ozl make`)"]
    assert issue[1] == "`agent/issues.md`" and "`.claude/skills/ozl/SKILL.md`" in issue[2]
    syuka = next(r for k, r in by.items() if k.startswith("슈카 자료("))
    assert "`/syuka find`, `/syuka deck`, `/syuka ad`" in syuka[0] and syuka[1] == "`agent/deck.md`"
    assert "`.claude/skills/syuka/`" in syuka[2] and "`skills/ozl/SKILL.md` §5" in syuka[2]
    cards = by["소재 카드와 클레임(덱의 재료)"]
    assert cards[1] == "`agent/desk.md`" and "`.claude/skills/syuka/deck/01_card.md`" in cards[2]
    assert not [k for k in by if "일일 데스크" in k]
    for r in rows[1:]:
        first = re.match(r"`(agent/[\w.]+)`", r[1])
        assert first and (ROOT / first.group(1)).is_file(), r[1]


def test_guide_commit_and_push_rules():
    body = text(GUIDE)
    skills = line_with(body, "커밋과 푸시를 하지 않는다")
    assert "스킬(`/ozl`, `/syuka`)" in skills and "쓸 곳이 없다" in skills and "수동 승인" in skills
    push = line_with(body, "`scripts/push_delegated.sh` 로만")
    assert "사용자가 공개를 지시한 카드의 푸시" in push and "사용자가 푸시하라고 말한 뒤에만" in push
    bad = [l.strip()[:100] for l in body.splitlines() if FORBIDDEN_CMD.search(l) and not any(w in l for w in NEGATION)]
    assert not bad, f"CLAUDE.md: 승인, 내림, 공개용 내보내기 명령이 금지 문장 없이 나온다 {bad}"


@pytest.mark.parametrize("doc", (GUIDE, DESK_RULES, ISSUE_RULES), ids=rel)
def test_guide_commands_and_files_exist(doc):
    body = text(doc)
    for module, sub in sorted({(m.group(1), m.group(2)) for m in CMD.finditer(body)}):
        top = help_text(module)
        assert sub in choices(top) or re.search(rf"{re.escape(module)}\s+{re.escape(sub)}(?![\w-])", top), f"{rel(doc)}: {module} {sub}"
    missing = sorted({m.group(1).rstrip(".") for m in PATH.finditer(body) if not (ROOT / m.group(1).rstrip(".")).exists()})
    assert not missing, f"{rel(doc)}: 없는 파일을 가리킨다 {missing}"


def test_desk_rules_point_to_syuka_deck_and_section5():
    body = text(DESK_RULES)
    assert "하루 한 번 아침" not in body
    assert body.splitlines()[0].startswith("# 소재 카드와 클레임")
    proc = line_with(body, "절차의 정본 =")
    for need in ("`/syuka deck`", "`.claude/skills/syuka/deck/01_card.md`", "`skills/ozl/SKILL.md` 5절", "`/ozl find`",
                 "예약 루틴은 두지 않는다(사용자 결정 2026-11-15)", "`skills/ozl/archive/`", "따라 하지 않는다"):
        assert need in proc, need
    assert rel(archive_file()).startswith("skills/ozl/archive/")
    assert "`/ozl status`" in line_with(body, "쌓인 일:")
    assert "`/syuka deck`" in line_with(body, "사용자의 일은 소재 고르기와 공개 승인뿐이다")
    assert "모델이 스스로 올리지 않는다" in line_with(body, "`human-verify`(사람 육안 대조 기록)")
    notion = line_with(body, "Notion 커넥터")
    assert "사용자가 원할 때만" in notion and "스킬(`/ozl`, `/syuka`)은 Notion 에 올리지 않는다" in notion
    assert "보고서를 정해진 때마다 만들지 않는다" in line_with(body, "일일 보고서 =")


def test_issue_rules_name_both_ways_to_pick_and_no_schedule():
    body = text(ISSUE_RULES)
    proc = line_with(body, "- 절차:")
    for need in ("`/ozl find`", "`/ozl make`", "`/ozl status`", "`.claude/skills/ozl/find/find.md`", "사용자가 부를 때만 돈다"):
        assert need in proc, need
    ways = line_with(body, "고르는 길은 둘이다")
    assert "`/ozl find`" in ways and "`/pick`" in ways and "[만들기]" in ways and "`<자료 루트>/find/`" in ways
    assert body.rstrip().endswith("이 형식에 예약 실행을 붙이지 않는다.")


@pytest.mark.parametrize("doc", (README, HOW), ids=rel)
def test_public_docs_say_hourly_program_and_manual_commands(doc):
    """공개 문서: 수집은 매시 프로그램이 하고, 모델이 도는 예약 실행은 없으며, 명령은 손으로 부른다."""
    body = text(doc)
    assert "멈춰 두었" not in body
    sentences = [s for l in body.splitlines() for s in re.split(r"(?<=[다요]\.)\s+", l)]
    assert any("매시" in s and "프로그램" in s for s in sentences), "매시 수집을 프로그램이 한다는 문장이 없다"
    assert any("예약 실행은 두지 않습니다" in s for s in sentences)
    assert any("`/ozl find`" in s and ("불러" in s or "손으로" in s) for s in sentences), "손으로 부르는 명령을 적은 문장이 없다"
    assert "손으로" in body and "`/syuka deck`" in body
    assert "민감 표시" in body and "다루지 않을 소재 거르기" not in body


def test_readme_folder_table_has_both_skill_folders():
    body = text(README)
    old = line_with(body, "| `skills/ozl/` |")
    assert "완성 절차서" in old and "보관한" in old and "후보 발굴" not in old
    new = line_with(body, "| `.claude/skills/` |")
    assert "`/ozl`" in new and "`/syuka`" in new and "손으로 부르는" in new
    assert (ROOT / ".claude" / "skills" / "ozl").is_dir() and (ROOT / ".claude" / "skills" / "syuka").is_dir()


def test_how_it_works_has_two_ways_to_pick_and_current_state():
    body = text(HOW)
    pick = line_with(body, "1. **고르기 (직접)**")
    assert "고르는 길은 둘입니다" in pick and "`/ozl find`" in pick and "운영 화면" in pick and "매시 프로그램이 돌고" in pick
    make = line_with(body, "2. **만들기 (모델)**")
    assert "`/ozl find` 에서 고른 건" in make and "대기열" in make and "`/ozl make`" in make
    state = line_with(body, "지금 상태는 이렇습니다.")
    assert "모델이 도는 예약 실행은 두지 않습니다" in state and "매시 수집은 프로그램이 계속 돕니다" in state and "꺼져 있습니다" in state
    assert "모델은 이 둘을 스스로 하지 않습니다" in body
    assert "### 2. 후보 고르기 (고르기는 직접, 확인은 자동)" in body and "### 2. 후보 고르기 (자동)" not in body


# ── 따라가기(P4)에서 걸린 곳을 고친 문장이 남아 있는지 ─────────────────────────────

def test_ozl_skill_tells_how_to_run_in_a_sandbox_copy():
    """새 에이전트가 시험 사본에서 걸린 곳: 작업 폴더, 이미 들어 있는 자료 루트 변수, 합친 명령, 후보 판, 날짜."""
    body = text(SKILLS / "ozl" / "SKILL.md")
    common = body.split("## 공통", 1)[1].split("## /ozl find", 1)[0]
    assert "시험 사본(저장소를 복사한 폴더)에서 돌릴 때는 그 사본이 작업 폴더다" in common
    assert "`cd ~/OZL` 을 붙이지 않고" in common and "명령은 한 번에 하나씩 부른다" in common
    assert "세션의 환경에 그 변수가 이미 있으면(실행기, 시험 하네스) 명령 앞에 붙이지 않는다" in common
    assert "from ozl.issues import paths; print(paths.desk_root())" in common
    sandbox = body.split("**시험 루트에서 돌릴 때.**", 1)[1].split("## 0. 가드", 1)[0]
    for word in ("--board tests/fixtures/skills/board.json", "실제 오늘을 쓴다", "`read_at`", "`found: false`"):
        assert word in sandbox, word
    draft = text(SKILLS / "ozl" / "make" / "01_draft.md")
    assert "명령 앞에 붙이지 않는다(붙인 명령은 허용 패턴에 맞지 않아 거부된다)" in draft
    assert "작업 폴더의 `.py` 파일로 쓰고" in draft and "`started` 는 화제가 시작된 날" in draft


def test_ozl_status_names_the_desk_root_and_the_card_exception():
    body = text(SKILLS / "ozl" / "SKILL.md")
    status = body.split("## /ozl status", 1)[1].split("## /ozl make", 1)[0]
    assert "첫 줄에 지금의 자료 루트를 적는다" in status
    desk = ozlpaths.LAYOUT["desk"]                            # 문서에 적힌 위치가 정본 LAYOUT 과 같아야 한다
    assert f"`OZL_DESK_ROOT` 를 따르지 않고 저장소의 `private/{desk}/cards/` 를 읽는다" in status
    from ozl.research import cards
    assert cards.CARDS == ozlpaths.at("desk", "cards")       # 문서의 말대로 카드 폴더는 저장소 기준 고정이다


def test_ozl_step1_handles_a_given_title_and_a_stop_before_writing():
    body = text(SKILLS / "ozl" / "SKILL.md")
    step1 = body.split("### 1) 대상 정하기", 1)[1].split("### 2) 쓰기", 1)[0]
    assert "`BV --match <제목의 핵심 낱말>`" in step1 and "그 화제 번호로 `--pick` 한다" in step1
    assert "`대기` 나 `실행 중` 으로 있으면 그 줄을 쓴다" in step1
    assert "pathlib.Path('<작업 폴더>').mkdir(parents=True, exist_ok=True)" in step1
    assert "`BV result <key> --state 대기`" in step1 and "거부돼 슬러그를 바꾸어도 작업 폴더는 그대로 쓴다" in step1
    # 문서가 적은 상태 낱말이 두 도구의 실제 값과 맞는다
    common = body.split("## 공통", 1)[1].split("## /ozl find", 1)[0]
    from ozl.ops import queue
    shared = ("대기", "실행 중", "끝남", "멈춤", "취소")
    only_queue = ("실패", "시간 초과", "중단됨")
    assert set(queue.STATES) == set(shared) | set(only_queue)
    for w in shared + only_queue:
        assert f"`{w}`" in common, w
    out = subprocess.run([sys.executable, str(SKILLS / "ozl" / "find" / "board_view.py"), "result", "--help"],
                         capture_output=True, text=True, env=dict(os.environ, OZL_DESK_ROOT=str(PROBE))).stdout
    assert "{" + ",".join(shared) + "}" in out


def test_workflows_do_not_claim_the_default_desk_root():
    """자료 루트 인자를 받지 않은 워크플로가 '기본값(private/desk)이다'라고 단정하지 않는다(환경 변수가 이미 있을 수 있다)."""
    for name in ("workflow_make.js", "workflow_revise.js"):
        t = text(SKILLS / "ozl" / "make" / name)
        assert "자료 루트는 기본값(private/desk)이다" not in t, name
        assert "환경 변수 OZL_DESK_ROOT 가 있으면 그 값이고 없으면 private/desk 다" in t, name


def test_packet_instruction_warns_about_other_issues_in_the_preview():
    assert "미리보기 폴더에는 자료 루트의 다른 이슈도 함께 나온다. 이번 이슈의 파일만 읽는다." in text(SKILLS / "ozl" / "make" / "04_packet.md")


def test_review_prompts_carry_the_sentence_check_rule():
    """`CLAUDE.md` 는 대조를 맡길 때 「문장 대조의 기준」을 프롬프트에 그대로 적으라고 한다. 워크플로의 검토자 프롬프트와 길 안내가 그렇게 한다."""
    guide = text(ROOT / "CLAUDE.md").replace("`", "")
    for piece in ("화면 글과 말로 할 문장의 사실 주장은 그 쪽이 인용한 기록의 text·observed 로 받쳐져야 한다.",
                  "반론 칸(counter)에만 있는 내용은 화면에 쓰지 않고 노트에 둔다.",
                  '"보도에 없다" 같은 부재 주장은 "읽은 보도(매체 이름)에서 찾지 못했다"로 범위를 밝힌다.'):
        assert piece in guide, piece
        for name in ("workflow_make.js", "workflow_revise.js"):
            assert piece in text(SKILLS / "ozl" / "make" / name), (name, piece)
    assert "문장 대조 검토자의 프롬프트에는 `CLAUDE.md` 의 「문장 대조의 기준」 문장을 그대로 적는다" in text(SKILLS / "ozl" / "SKILL.md")


def test_review_and_fix_instructions_cover_the_second_round():
    review = text(SKILLS / "ozl" / "make" / "02_sentence_review.md")
    assert '"status 가 pending 이 아니다"로 돌아온다. 실패가 아니다.' in review
    from ozl.research import cards
    import inspect
    assert "status 가 pending 이 아니다" in inspect.getsource(cards.machine_check)      # 문서가 옮긴 문장이 코드의 문장이다
    fix = text(SKILLS / "ozl" / "make" / "03_fix.md")
    assert "문장 대조가 통과한 회차에서 함께 나온 사소한 지적은 여기서 고치지 않는다" in fix and "`06_revise.md`" in fix
    packet = text(SKILLS / "ozl" / "make" / "04_packet.md")
    assert "출처의 주소는 그대로 싣는다" in packet
    find = text(SKILLS / "ozl" / "find" / "find.md")
    assert "일부만 지금 만들라고 했으면 그 건만 만든다" in find


def test_find_instruction_agrees_with_the_skill_on_test_runs_and_extra_cases():
    """다시 따라가기에서 걸린 곳: find.md 의 시험 문장이 SKILL.md 와 달랐고, '정리 전'과 직접 넣은 제목의 견주기가 없었다."""
    find = text(SKILLS / "ozl" / "find" / "find.md")
    assert "시험이면 명령 앞에 `OZL_DESK_ROOT=<시험 루트>` 를 두고 `--board" not in find
    assert "세션의 환경에 `OZL_DESK_ROOT` 가 이미 있으면 명령 앞에 붙이지 않고" in find
    for word in ("'정리 전'", "같은 주체가 같은 때에 한 같은 일", "`BV --match <제목의 핵심 낱말>`", "합친 수다"):
        assert word in find, word
    helper = text(SKILLS / "ozl" / "find" / "board_view.py")
    assert 'TBD = "정리 전"' in helper and "고른 것 {len(picks)}건" in helper       # 문서가 옮긴 낱말이 도우미의 낱말이다
    skill = text(SKILLS / "ozl" / "SKILL.md")
    assert "`--note` 에 작업 폴더 이름을 적어 둔다" in skill and "그 변수를 따르고 `--desk-root <시험 루트>` 도 받는다" in skill


# ── /syuka 따라가기(P5)에서 걸린 곳을 고친 문장이 남아 있는지 ──────────────────────

def test_syuka_skill_tells_how_to_run_in_a_sandbox_copy():
    """P4 에서 /ozl 쪽에 걸린 것(작업 폴더, 이은 명령, 여러 줄 조각, 이미 든 환경 변수)을 /syuka 에도 적었다."""
    body = syuka("SKILL.md")
    common = body.split("\n## 공통", 1)[1].split("\n## ", 1)[0]
    assert "시험 사본(저장소를 복사한 폴더)에서 돌릴 때는 그 사본이 작업 폴더다" in common
    assert "`cd ~/OZL` 을 붙이지 않고" in common and "명령은 한 번에 하나씩 부른다" in common
    assert "여러 줄 조각은 `.py` 파일로 써서 `.venv/bin/python <파일>` 로 돌린다" in common
    sandbox = body.split("\n## 시험 사본에서 돌릴 때", 1)[1]
    for piece in ("tests/fixtures/skills/make_sandbox.py", "명령 앞에 붙이지 않고 `.venv/bin/python …` 그대로 부른다",
                  "`printenv` 같은 다른 명령으로 확인하지 않는다", "`--asof 2099-01-02T12:00`", "`kit/README.md` 의 표가 주소와 로컬 파일의 짝이다",
                  "번호(`ids`)의 날짜는 실제 오늘이다"):
        assert piece in sandbox, piece
    assert (ROOT / "tests" / "fixtures" / "skills" / "make_sandbox.py").is_file()
    assert "--asof" in help_text("ozl.research", "coverage")


def test_syuka_find_explains_what_the_three_commands_do_not_show():
    """새 에이전트가 찾기에서 걸린 곳: 낱말을 나누는 법, 전사 본문 기간의 뜻, 출력에 나오지 않는 영상, 관계의 방향."""
    body = syuka("find.md")
    for piece in ("본문을 `.py` 파일로 써서 `.venv/bin/python <파일>` 로 돌린다", "세션의 임시 폴더에 두고 저장소 안에 두지 않는다",
                  "곁가지로 나온 영상도 요지를 읽고 판단한다", "하나라도 나오면 걸린다", "띄어 쓴 한 낱말은 따옴표로 묶는다",
                  "`--months` 는 전사 본문을 훑는 기간일 뿐이다", "세 단계 가운데 하나에서만 찾고 \"겹침 없음\"으로 적지 않는다",
                  "보관한 옛 절차의 말이다", "제목에 낱말이 없으면 출력에 나오지 않는다", "관계는 새 소재에서 본 그 영상과의 사이다",
                  "\"없음(무관)\"이라고 적고 카드의 `coverage.videos` 에 넣지 않는다"):
        assert piece in body, piece
    # 문서가 옮긴 동작이 코드의 동작이다: 낱말은 하나라도 나오면 걸리고 띄어쓰기를 무시한다. 출력의 옛 말도 코드에 그대로 있다
    from ozl.research import coverage
    import inspect
    src = inspect.getsource(coverage)
    assert "sum(body.count(k) for k in kws)" in src and "절차서 §1 3단계" in src
    assert coverage._space_free("공유 자전거") == "공유자전거"


def test_syuka_deck_instruction_covers_what_the_walkthrough_tripped_on():
    """/syuka deck 을 끝까지 따라간 세션이 걸린 곳: 두 번의 대조, 사양에 적지 않는 것, 표의 칸과 단위, 재대조 옮기기, 이어 받기."""
    card = syuka("deck/01_card.md")
    for piece in ("이 독립 검증과 완성 절차 4단계의 재대조는 다른 일이고 둘 다 한다",
                  "**사양에 지난 방송을 적지 않는다.**", "\"실렸다\"가 나오면(종료 코드 1) 그 묶음을 어디에도 보내지 않는다",
                  ".venv/bin/python .claude/skills/syuka/deck/bundle_guard.py private/desk/builds/<card_id>/reviews/bundle_<타임코드>.md",
                  "그 장의 `conversions` 에 화면 표기(`shown`), 원문 표기(`source`), 기록 번호, 근거(`basis`",
                  "본 세션이 글자 그대로 `recheck` 칸에 옮긴다", "재대조 값을 본 뒤에 고쳤다는 것을",
                  "## 이어 받기", "이름은 앞 세션의 것을 그대로 쓴다", "`by` 칸에 있다", "임대를 여섯 시간 새로 늘린다",
                  "같은 카드 폴더에 `ad/` 가 있으면 광고 회차다"):
        assert piece in card, piece
    skill = syuka("SKILL.md")
    common = skill.split("\n## 공통", 1)[1].split("\n## ", 1)[0]
    assert "검토 묶음에는 사양의 장마다 적은 메모(`notes`)도 실린다" in common
    # 묶음을 보내기 전의 검사는 문장이 아니라 명령이다(읽기만 하는 도우미). 묶음 명령과 덱 검사 명령이 잡지 않는다는 것도 적는다
    assert "보내기 전에 `PY .claude/skills/syuka/deck/bundle_guard.py <묶음>` 을 돌린다" in common
    assert "종료 코드가 0 이 아니면 그 묶음을 보내지 않는다" in common and "직접 찾아본다" not in skill + card
    assert (SYUKA / "deck" / "bundle_guard.py").is_file()
    assert "\"전에 이 주제를 다룬 적이 있다\"는 한 마디는 말로 할 문장에 써도 된다" in common
    deck = skill.split("\n## /syuka deck", 1)[1].split("\n## ", 1)[0]
    assert "어느 검토가 끝났고 어느 것이 남았는지를 사용자에게 알린다" in deck and "`deck/01_card.md` 의 「이어 받기」" in deck
    sandbox = skill.split("\n## 시험 사본에서 돌릴 때", 1)[1]
    assert "\"라벨이 있는 편이 없다\"로 멈춘다" in sandbox and "`date +%Y%m%d_%H%M%S`" in sandbox
    # 문서가 옮긴 동작이 코드의 동작이다
    import inspect
    from ozl.render import bundle, progress
    assert "작성자 메모" in inspect.getsource(bundle) and "notes" in inspect.getsource(bundle)      # 메모가 묶음에 실린다
    assert progress.LEASE_HOURS == 6 and "다른 이름" in inspect.getsource(progress)                # 임대 여섯 시간, 다른 이름은 거부
    for flag in ("--resume", "--by", "--force", "--note"):
        assert flag in help_text("ozl.render", "progress")


def test_syuka_ad_instruction_covers_what_the_walkthrough_tripped_on():
    """/syuka ad 를 따라간 세션이 걸린 곳: 절차 문서와 어긋날 때, 맡을지 묻는 자리, 길이의 단위, 제휴 주장, 진행 기록, 순서."""
    ad = syuka("ad.md")
    for piece in ("절차 문서와 이 지시서가 어긋나면", "이 지시서와 `agent/deck.md` 와 코드를 따른다",
                  "길이는 장수로 받는다(검사가 장수를 센다)", "민감 점검(2단계)을 마친 뒤, 표시 계획을 쓰기 전에",
                  "사용자가 정한 것을 쓴다", "작업 기록이라 PDF 쌍을 만들지 않는다", "`--mark` 를 부르지 않고",
                  "제휴나 협약을 주장만 하는 것은 이 갈래가 아니다", "자료 이름은 보낸 곳, 무엇, 받은 날이 드러나게 적는다",
                  "출력의 \"본편 N장\"은 광고 장까지 센 수다", "사양을 이미 쓴 뒤에 불렸으면 기록 셋을 만들고",
                  "이 폴더를 빼지 않는다"):
        assert piece in ad, piece
    from ozl.render import spec
    assert spec.SPONSOR_MAX_SHARE == 0.20                                # 문서의 20% 가 코드의 값이다
    ignore = ROOT / "private" / ".gitignore"
    if ignore.is_file():                                                 # 비공개 사본이 있는 기기에서만: 문서의 말대로 광고주 자료 폴더는 백업에서 빠져 있지 않다
        assert "sponsor" not in ignore.read_text(encoding="utf-8")


def test_ozl_status_commands_leave_only_the_empty_lock_file(tmp_path):
    """/ozl status 는 "아무것도 바꾸지 않는다"고 적었다. 새 자료 루트에서 명령들을 돌린 뒤 남는 것은 빈 잠금 파일뿐이다."""
    status = text(SKILLS / "ozl" / "SKILL.md").split("\n## /ozl status", 1)[1].split("\n## ", 1)[0]
    assert "아무것도 바꾸지 않는다" in status and "`<자료 루트>/ops/.lock`" in status
    root = tmp_path / "desk"
    root.mkdir()
    env = dict(os.environ, OZL_DESK_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1")
    for argv in (["-m", "ozl.ops", "queue", "list"], ["-m", "ozl.issues", "status"],
                 [str(SKILLS / "ozl" / "find" / "board_view.py"), "picks"]):
        r = subprocess.run([sys.executable, *argv], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (argv, r.stderr)
    left = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    assert left <= {"ops/.lock"}, left
    assert all(p.stat().st_size == 0 for p in root.rglob("*") if p.is_file())


# ── 덱 검토 지시서 틀(skills/ozl/review/) ─────────────────────────────────
# 5절의 검토 셋이 쓰는 프롬프트다. 평가 기준의 항목을 빼먹지 않는지, 지금 절차에 없는 폴더를 가리키지 않는지,
# 지난 방송 이야기가 다른 모델 계열로 가는 글에 실릴 길이 없는지 본다.
REVIEW = ROOT / "skills" / "ozl" / "review"
REVIEW_TEMPLATES = ("sentence.md", "composition.md", "external_head.md")
PLACEHOLDER = re.compile(r"\{([A-Z][A-Z_]*)\}")
CRITERIA_DIR = ozlpaths.real_at("plan")                 # 평가 기준은 비공개 폴더에 있다(없는 기기에서는 그 시험만 건너뛴다)
CRITERIA_ITEM = re.compile(r"^\|\s*([나다])(\d+)\s*\|", re.M)


def review(name: str) -> str:
    return text(REVIEW / name)


def criteria_ranges(body: str) -> str:
    """평가 기준 글에서 나 절과 다 절의 항목 번호를 읽어 "나1~나N, 다1~다M" 으로."""
    top = {"나": 0, "다": 0}
    for sec, n in CRITERIA_ITEM.findall(body):
        top[sec] = max(top[sec], int(n))
    return f"나1~나{top['나']}, 다1~다{top['다']}"


def test_review_templates_and_readme_agree_on_placeholders():
    used = {name: set(PLACEHOLDER.findall(review(name))) for name in REVIEW_TEMPLATES}
    listed = set(PLACEHOLDER.findall(review("README.md")))
    assert set().union(*used.values()) == listed, (used, listed)
    assert "CRITERIA" in used["composition.md"] and "PRESS_DIR" in used["sentence.md"]
    assert used["external_head.md"] == {"ROUND", "PREV", "PRESS"}      # 밖으로 가는 머리말에는 저장소 경로를 넣는 자리가 없다


def test_composition_template_reads_every_item_of_the_criteria():
    body = review("composition.md")
    # 2026-11-15 확인에서 걸린 꼴: 번호 범위를 박아 두어 기준에 있는 나7, 다5 를 건너뛰었다
    assert "나1~나6" not in body and "다1~다4" not in body
    assert "`{CRITERIA}` 의 나(구성) 절과 다(화면) 절" in body and "완성본_평가기준_*" not in body
    assert "항목을 하나도 빼지 않고" in body and "충족으로 세지 않는다" in body
    assert "A. 기준 항목표(기준 파일의 나 절과 다 절 항목 전부: 충족/모자람/판정 못 함" in body
    for piece in ("지난 방송과 겹침(나7).", "카드 `coverage.videos` 의 영상마다 `relation` 과 `gist` 를 덱의 중심 질문과 견준다",
                  "\"겹침 판정 기록 없음\"으로 모자람이다",
                  "원본 비교표(기준에 다5 가 있을 때).", "장수(30분 환산), 장당 초, 장 모양 분포, 제목 끝맺음, 첫 세 장의 꼴",
                  "까닭을 찾지 못한 칸이 있으면 모자람이다", "\"비교표 없음\"으로 적고 충족으로 세지 않는다",
                  "`{BUILD}/원본_비교표_*.md`", "`private/desk/cards/{CARD}.yaml` 의 `coverage` 칸"):
        assert piece in body, piece
    assert "기준에 항목이 늘면 `composition.md` 의 할 일 1번에 적힌 번호 범위도 함께 고친다" in review("README.md")


def test_criteria_range_reader_counts_a_made_up_table():
    made_up = "## 나. 구성\n| 번호 | 기준 |\n|---|---|\n| 나1 | 지어낸 기준 |\n| 나8 | 지어낸 기준 |\n\n## 다. 화면\n| 다1 | 지어낸 기준 |\n| 다6 | 지어낸 기준 |\n"
    assert criteria_ranges(made_up) == "나1~나8, 다1~다6"


def test_composition_template_names_the_range_of_the_newest_criteria():
    """틀의 할 일 1번에 적힌 번호 범위가 가장 새 평가 기준의 항목과 같다. 기준에 항목이 늘었는데 틀이 그대로면 여기서 걸린다."""
    files = sorted(CRITERIA_DIR.glob("완성본_평가기준_*.md")) if CRITERIA_DIR.is_dir() else []
    if not files:
        pytest.skip("평가 기준 파일이 없는 환경")
    want = criteria_ranges(text(files[-1]))
    assert want != "나1~나0, 다1~다0", files[-1].name
    assert f"기준은 {want} 다" in review("composition.md"), (files[-1].name, want)


def test_past_broadcasts_stay_out_of_what_goes_to_another_model_family():
    comp, head, readme = review("composition.md"), review("external_head.md"), review("README.md")
    assert "- D. 지난 방송과 겹침(나7)의 근거" in comp and "지난 방송 이야기는 D 에만 둔다" in comp
    assert "A, B, C 에는 영상 번호, 영상 제목, 올린 날, 지난 방송이 한 말과 쓴 수치를 적지 마라" in comp
    assert "지난 방송의 문장과 슬라이드 문구는 옮겨 적지 마라" in comp
    for word in ("coverage", "나7", "지난 방송", "영상 번호", "겹침", "find-v3"):
        assert word not in head, word
    assert "`external_head.md` 에는 넣지 않는다" in readme and "구성·화면 평가의 D 절은 옮기지 않는다" in readme
    assert ".venv/bin/python .claude/skills/syuka/deck/bundle_guard.py <채운 머리말 파일> --card <card_id>" in readme
    assert "영상 전사·영상 목록은 다른 모델 계열에 넘기지 않는다" in readme
    card = syuka("deck/01_card.md")
    for piece in ("**검토 지시서를 채울 때.**", "`{PREV}` 와 `{PRESS}` 에는 D 절과 지난 방송을 가리키는 것을 옮기지 않는다",
                  "채운 머리말도 보내기 전에 위 검사에 `--card <card_id>` 를 붙여 돌린다", "받아 둔 것이 없으면 \"없음\"이라고 적는다"):
        assert piece in card, piece


def test_sentence_template_points_to_no_folder_the_procedure_does_not_make():
    body = review("sentence.md")
    # 옛 일일 데스크가 회차마다 만들던 폴더다. 지금 절차에는 만드는 단계가 없다
    assert "<날짜>_<회차>" not in body and "sources/" not in body and "manifest.json" not in body
    assert "`{PRESS_DIR}`" in body
    assert "통과로 치지 말고 판정 표에 심각도 '중간', 근거 \"기사 사본 없음(대조하지 못함)\"으로 올린다" in body
    assert "기사 주소를 직접 열어 대신하지 않는다" in body and "그중 대조하지 못함 N" in body
    assert "반론 칸(`counter`)에만 있는 내용은 화면에 쓰지 않고 notes 에 둔다" in body
    # 틀이 적은 기록과 사본의 자리가 코드가 쓰는 자리다
    from ozl.research import cards as C
    desk = ozlpaths.LAYOUT["desk"]                            # 문서·도움말의 위치 문구가 정본 LAYOUT 과 같아야 한다
    assert f"`private/{desk}/claims/<날짜>/<claim_id>.yaml`" in body and C.CLAIMS == ozlpaths.at("desk", "claims")
    assert f"`private/{desk}/captures/<claim_id>/`" in body and f"private/{desk}/captures" in help_text("ozl.research", "capture")
    assert "받아 둔 것이 없으면 줄을 지우지 말고 \"없음\"이라고 적는다" in review("README.md")


@pytest.mark.parametrize("name", REVIEW_TEMPLATES + ("README.md",))
def test_review_templates_point_to_existing_files_and_commands(name):
    body = review(name)
    missing = sorted({m.group(1).rstrip(".") for m in PATH.finditer(body) if not (ROOT / m.group(1).rstrip(".")).exists()})
    assert not missing, f"skills/ozl/review/{name}: 없는 파일을 가리킨다 {missing}"
    for m in CMD.finditer(body):
        module, sub = m.group(1), m.group(2)
        top = help_text(module)
        assert sub in choices(top) or re.search(rf"{re.escape(module)}\s+{re.escape(sub)}(?![\w-])", top), f"{name}: {module} {sub}"


def test_review_template_commands_are_collected():
    found = {(m.group(1), m.group(2)) for name in REVIEW_TEMPLATES + ("README.md",) for m in CMD.finditer(review(name))}
    assert ("ozl.syuka", "find-v3") in found and ("ozl.render", "bundle") in found


def test_section5_still_fills_the_templates_from_this_folder():
    """5절이 틀의 자리와 기준 파일을 정한다(틀의 `{CRITERIA}` 가 가리키는 문장). 5절이 바뀌면 틀의 안내도 함께 본다."""
    s5 = section5()
    assert "지시서는 `skills/ozl/review/` 의 틀에서 자리표시를 채워 만든다" in s5
    assert "평가 기준은 사양에 `style: syuka` 가 있으면" in s5 and "구성 평가 나·다 항목 모두 충족" in s5
    for name in REVIEW_TEMPLATES:
        assert f"`{name}`" in s5, name
