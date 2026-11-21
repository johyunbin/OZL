"""Workflow 도구 대신 Node의 async 함수에 같은 네 전역을 주어 실제 호출을 기록한다."""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / ".claude/skills/ozl/make"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node 없음")
WORKFLOWS = pytest.mark.parametrize("kind", ["make", "revise"])

HARNESS = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const calls = [];
let reviews = 0;
const agent = async (prompt, opts) => {
  calls.push({prompt, opts});
  if (Object.hasOwn(input.replies, opts.label)) {
    const reply = input.replies[opts.label];
    if (reply === '예외') throw Error('시험 시간 초과');
    return reply;
  }
  if (opts.label === '쓰기') return {issue_id: input.stop ? '' : input.args.issue, report: '초안', offload: '시험 사본 / 결과 파일 / 레인'};
  if (opts.label.startsWith('1차 대조 ')) {
    const reply = input.prechecks.shift();
    if (!reply) throw Error('예정하지 않은 1차 대조');
    return opts.schema || typeof reply === 'string' ? reply : JSON.stringify(reply);
  }
  if (opts.label.startsWith('1차 지적 고치기') && !opts.schema) return '1차 지적 전용 답';
  if (opts.label.startsWith('문장 대조')) {
    const bad = reviews++ < input.bad;
    return {blind_verdicts: [], findings: bad ? [{severity: '중요'}] : (input.minor ? [{severity: '사소'}] : []), verdict: bad ? '고쳐야 통과' : '통과'};
  }
  if (opts.schema?.properties.report) return {report: '작업만 보고', offload: opts.label + ' 사본 / 결과 파일 / 레인'};
  return '보고';
};
(async () => {
  try {
    const run = new Function('args', 'agent', 'phase', 'log', 'return (async () => {' + input.src + '\\n})()');
    const result = await run(input.args, agent, () => {}, () => {});
    console.log(JSON.stringify({result, calls}));
  } catch (err) { console.log(JSON.stringify({error: err.message, calls})); }
})();
"""


def run(kind, *, bad=1, stop=False, minor=False, prechecks=(), replies=None, **options):
    src = (FOLDER / f"workflow_{kind}.js").read_text().replace("export const meta =", "const meta =", 1)
    args = dict(title="시험", issue="i20990101-01", work="/tmp/work", list="고칠 목록", prior="앞선 답")
    args.update(options)
    payload = json.dumps(dict(src=src, args=args, bad=bad, stop=stop, prechecks=prechecks, minor=minor,
                              replies=replies or {}))
    p = subprocess.run([NODE, "-e", HARNESS], input=payload, text=True, capture_output=True, timeout=10, check=True)
    return json.loads(p.stdout)


def prompt_hash(calls):
    return hashlib.sha256("\0".join(c["prompt"] for c in calls).encode()).hexdigest()


@WORKFLOWS
def test_default_calls_prompts_and_schemas_unchanged(kind):
    # HEAD 4a0a93d의 두 스크립트를 위 하네스로 실행한 지문. opts는 스키마 전체와 호출 순서를 포함한다.
    original = {"make": "231f0911e8636486f8ead83fa01f8a1cf45a1ddf5a64a881a60072349e0c51b3",
                "revise": "0f06ea15ffd7209ed04d4dbe10bf44c952bce71fb2f8ef1ba286c9863ce1aee4"}
    original_opts = {"make": "b8db1fb3ba2af89cb68b9ed4081b31d904e163a525c5d0732aea8b49bc7431d6",
                     "revise": "71c6fb8cbbc33d667678d5db3e44284a3cf5f14d98302bacc711b922eab53e6a"}
    out = run(kind)
    assert out["result"]["review_mode"] == "claude" and out["result"]["precheck_rounds"] == 0
    assert out["result"]["precheck_log"] == []
    calls = out["calls"]
    assert calls == run(kind, offload=False)["calls"]
    assert prompt_hash(calls) == original[kind]
    opts_json = json.dumps([c["opts"] for c in calls], ensure_ascii=False, sort_keys=True)
    assert hashlib.sha256(opts_json.encode()).hexdigest() == original_opts[kind]
    assert [c["opts"]["model"] for c in calls] == ["opus", "sonnet", "opus", "sonnet", "opus"]
    assert all("effort" not in c["opts"] for c in calls)


@WORKFLOWS
def test_role_options_and_offload_are_scoped(kind):
    writer = "draft" if kind == "make" else "revise"
    roles = {k: dict(model=m, effort=e) for k, m, e in
             [(writer, "sonnet", "high"), ("review", "opus", "medium"), ("fix", "sonnet", "low"), ("packet", "sonnet", "max")]}
    out = run(kind, roles=roles, offload=True)
    assert out["result"]["roles_used"] == roles
    for call, role in zip(out["calls"], [writer, "review", "fix", "review", "packet"], strict=True):
        assert all(call["opts"][k] == v for k, v in roles[role].items())
        assert ("offload.py run" in call["prompt"]) == (role in (writer, "fix"))
    if kind == "make":
        schema = out["calls"][0]["opts"]["schema"]
        assert schema["properties"]["offload"]["type"] == "string" and "offload" not in schema["required"]


@WORKFLOWS
def test_same_reviewer_refused_before_first_call(kind):
    r = run(kind, roles={"review": {"model": "opus"}})
    assert "문장 대조 모델이 작성자와 같다: opus" in r["error"] and not r["calls"]


@WORKFLOWS
def test_fix_collision_refused_before_first_call(kind):
    r = run(kind, roles={"fix": {"model": "sonnet"}})
    assert not r["calls"] and "작성자와 같다: sonnet" in r["error"]


@WORKFLOWS
def test_saved_writer_collision_refused_before_first_call(kind):
    writer = "draft" if kind == "make" else "revise"
    roles = {writer: {"model": "sonnet"}, "fix": {"model": "sonnet"}, "review": {"model": "opus"}}
    r = run(kind, roles=roles, drafted_by="Claude OPUS-5.5")
    assert not r["calls"] and "작성자와 같다: opus" in r["error"]
    assert run(kind, roles=roles, drafted_by="Scopus")["result"]["sentence_ok"]


@WORKFLOWS
def test_saved_writer_model_tokens(kind):
    for name in ("claude_sonnet_4", "Claude/SONNET_v4a.5"):
        r = run(kind, drafted_by=name)
        assert not r["calls"] and "작성자와 같다: sonnet" in r["error"]
    # 한글도 토큰의 일부다. ASCII 낱말 경계만으로 sonnet을 떼어 내지 않는다.
    assert run(kind, drafted_by="작성sonnet_v4a")["result"]["sentence_ok"]


@WORKFLOWS
def test_offload_log_never_reaches_reviewers(kind):
    r = run(kind, offload=True)
    result = r["result"]
    initial = "시험" if kind == "make" else "고침 r2"
    assert result["offload_log"] == [initial + " 사본 / 결과 파일 / 레인", "고치기 1 사본 / 결과 파일 / 레인"]
    for c in r["calls"]:
        if c["opts"]["label"].startswith("문장 대조"):
            assert "사본 / 결과 파일 / 레인" not in c["prompt"]
            assert ("초안" if kind == "make" else "작업만 보고") in c["prompt"]
    assert "사본 / 결과 파일 / 레인" not in json.dumps({k: v for k, v in result.items() if k != "offload_log"}, ensure_ascii=False)


def test_stopped_offload_only_appears_in_log():
    result = run("make", stop=True, offload=True)["result"]
    assert result["offload_log"] == ["시험 사본 / 결과 파일 / 레인"] and result["draft"]["report"] == "초안"
    assert "offload" not in result["draft"]


@WORKFLOWS
@pytest.mark.parametrize(("limit", "effective"), [(0, 0), (1, 1), (4, 3), (1.5, 3), ("0", 3)])
def test_fix_round_limit(kind, limit, effective):
    r = run(kind, bad=5, max_fix=limit, roles={"fix": {"model": "fable"}, "review": {"model": "opus", "effort": "ultra"}})
    result = r["result"]
    assert result["fix_rounds"] == result["max_fix"] == effective
    assert sum(c["opts"]["phase"] == "고치기" for c in r["calls"]) == effective
    assert result["roles_used"]["review"] == {"model": "sonnet"} and not result["sentence_ok"]
    assert ("fix" in result["roles_used"]) == (effective > 0)
    assert "packet" not in result["roles_used"]


@WORKFLOWS
@pytest.mark.parametrize("prior", ["앞선 답", ""])
def test_code_packet_role_and_confirmation(kind, prior):
    r = run(kind, bad=0, packet_mode="code", prior=prior, desk_root="/tmp/시험")
    prompt = r["calls"][-1]["prompt"]
    confirm = kind == "revise" and bool(prior)
    assert ".venv/bin/python -m ozl.issues packet i20990101-01 --out /tmp/work/packet_" in prompt
    assert "OZL_DESK_ROOT=/tmp/시험 를 두고" in prompt or "OZL_DESK_ROOT=/tmp/시험 를 둔다" in prompt
    assert "종료 코드가 2" in prompt and ".hash" in prompt
    assert ("--parts12-only" in prompt) == confirm
    assert ("packet" if confirm else "packet_check") in r["result"]["roles_used"]
    assert r["result"]["packet_mode"] == "code" and r["result"]["fix_rounds"] == 0


def test_early_stop_reports_only_used_role():
    result = run("make", stop=True)["result"]
    assert result["roles_used"] == {"draft": {"model": "opus"}} and result["fix_rounds"] == 0


@WORKFLOWS
def test_meta_is_literal(kind):
    src = (FOLDER / f"workflow_{kind}.js").read_text()
    meta = re.match(r"\Aexport const meta = (\{.*?\n\})\n", src, re.S)[1]
    tokens = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", meta)
    assert not re.search(r"\$\{|[()`]|\bmodel\s*:", tokens)
    assert re.fullmatch(r"(?:[\s{},:\[\]']|name|description|phases|title|detail)+", tokens)


def checked(*severities, skipped=""):
    if skipped:
        return {"skipped": skipped}
    return {"verdict": "고쳐야 통과" if any(s != "사소" for s in severities) else "통과",
            "findings": [dict(severity=s, where="what_new", problem="1차 전용 지적",
                              evidence="시험 사본 대목", fix="범위를 좁힌다") for s in severities]}


@WORKFLOWS
def test_codex_first_two_stages_share_fix_budget(kind):
    out = run(kind, review_mode="codex_first", max_fix=2, prechecks=[checked("중요", "사소"), checked()],
              roles={"precheck": {"effort": "xhigh"}, "packet_check": {"model": "opus", "effort": "medium"}}, bad=2)
    result, calls = out["result"], out["calls"]
    labels = [c["opts"]["label"] for c in calls]
    assert labels[0] == ("쓰기" if kind == "make" else "고침 r2")
    assert labels[1:] == ["1차 대조 1", "1차 지적 고치기 1", "1차 대조 2", "문장 대조 1", "고치기 1", "문장 대조 2"]
    assert result["review_mode"] == "codex_first" and result["fix_rounds"] == result["max_fix"] == 2
    assert result["precheck_rounds"] == 2 and not result["sentence_ok"] and not result["packet"]
    tag = "r1" if kind == "make" else "r2"
    for i, expected in enumerate([2, 0], start=1):
        path = f"/tmp/work/precheck_{tag}_{i}.json"
        assert result["precheck_log"][i - 1] == dict(round=i, findings=expected, path=path)
        precheck = calls[1 if i == 1 else 3]
        assert precheck["opts"]["model"] == "opus" and precheck["opts"]["effort"] == "medium"
        assert "--lane codex --author-family anthropic --effort xhigh --caller ozl:make-precheck" in precheck["prompt"]
        assert "~/OZL/.claude/skills/ozl/make/07_precheck.md" in precheck["prompt"]
        assert path in precheck["prompt"]
    assert "03_fix.md" in calls[2]["prompt"] and "1차 전용 지적" in calls[2]["prompt"]
    for call in (calls[4], calls[6]):
        assert "02_sentence_review.md" in call["prompt"] and call["opts"]["model"] == "sonnet"
        assert all(s not in call["prompt"] for s in ("1차 전용 지적", "1차 지적 전용 답", "precheck_"))


@WORKFLOWS
@pytest.mark.parametrize("reply", [checked(), checked("사소"), checked(skipped="종료 코드 3"), checked(skipped="종료 코드 4")])
def test_clean_or_skipped_precheck_goes_straight_to_final_review(kind, reply):
    out = run(kind, review_mode="codex_first", prechecks=[reply], roles={"precheck": {"effort": "max"}}, bad=0, minor=True)
    calls, result = out["calls"], out["result"]
    assert [c["opts"]["label"] for c in calls[1:3]] == ["1차 대조 1", "문장 대조 1"]
    assert "--effort high " in calls[1]["prompt"]
    assert len(calls) == 4 and result["sentence_ok"] and result["packet"] and result["fix_rounds"] == 0
    assert result["precheck_rounds"] == 1
    row, = result["precheck_log"]
    if reply.get("skipped"):
        assert row["skipped"] == reply["skipped"] and row["path"] is None and row["findings"] is None
    else:
        assert row["path"] and row["findings"] == len(reply["findings"])


@WORKFLOWS
def test_exhausted_precheck_budget_still_runs_final_review(kind):
    out = run(kind, review_mode="codex_first", max_fix=1, prechecks=[checked("치명적")])
    assert [c["opts"]["label"] for c in out["calls"][1:]] == ["1차 대조 1", "1차 지적 고치기 1", "문장 대조 1"]
    assert out["result"]["fix_rounds"] == 1 and not out["result"]["sentence_ok"]


@WORKFLOWS
def test_runner_null_precheck_never_calls_offload(kind):
    out = run(kind, review_mode="codex_first", roles={"precheck": None})
    assert out["calls"] == run(kind)["calls"]
    assert out["result"]["precheck_rounds"] == 0 and out["result"]["review_mode"] == "claude"


@WORKFLOWS
@pytest.mark.parametrize(("fix_reply", "offload"), [(None, False), ("예외", False), ({}, True), (42, False)])
def test_failed_precheck_fix_still_runs_sonnet_once(kind, fix_reply, offload):
    out = run(kind, review_mode="codex_first", max_fix=2, offload=offload, prechecks=[checked("중요")],
              replies={"1차 지적 고치기 1": fix_reply, "문장 대조 1": None})
    assert [c["opts"]["label"] for c in out["calls"][1:]] == ["1차 대조 1", "1차 지적 고치기 1", "문장 대조 1"]
    assert out["calls"][-1]["opts"]["model"] == "sonnet"
    result = out["result"]
    assert result["fix_rounds"] == 1 and "실패" in result["fixLog"]
    assert not result["sentence_ok"] and not result["packet"]


@WORKFLOWS
def test_missing_writer_report_reviews_known_issue(kind):
    reply = {"issue_id": "i20990101-01"} if kind == "make" else {}
    label = "쓰기" if kind == "make" else "고침 r2"
    out = run(kind, offload=True, review_mode="codex_first", prechecks=[checked()],
              replies={label: reply, "문장 대조 1": None})
    assert [c["opts"]["label"] for c in out["calls"]] == [label, "1차 대조 1", "문장 대조 1"]
    assert out["calls"][-1]["opts"]["model"] == "sonnet"
    assert out["result"]["draft" if kind == "make" else "revise"] == ""
    assert not out["result"]["packet"]
    if kind == "make":
        stopped = run(kind, offload=True, review_mode="codex_first", replies={label: {}})
        assert len(stopped["calls"]) == 1 and not stopped["result"]["issue_id"]


@WORKFLOWS
@pytest.mark.parametrize("reply", [checked("알 수 없음"), {"findings": [None], "verdict": "통과"},
                                    {"findings": {}, "verdict": "통과"}, {"findings": [], "verdict": "기타"},
                                    {"findings": []}, {"verdict": "통과"}, "깨진 JSON"])
def test_invalid_precheck_result_is_skipped(kind, reply):
    out = run(kind, review_mode="codex_first", prechecks=[reply], bad=0)
    row, = out["result"]["precheck_log"]
    assert row["skipped"] and row["findings"] is None and row["path"] is None
    assert out["result"]["fix_rounds"] == 0 and out["calls"][2]["opts"]["label"] == "문장 대조 1"


def test_precheck_sentence_criteria_match_claude():
    rules = (FOLDER.parents[3] / "CLAUDE.md").read_text()
    paragraph = rules.split("**문장 대조의 기준**", 1)[1].splitlines()[1].removeprefix("- ")
    criteria = paragraph.split(" 대조를 맡길 때", 1)[0]
    assert criteria in (FOLDER / "07_precheck.md").read_text().split("\n\n")


@WORKFLOWS
def test_short_precheck_json_passes(kind):
    raw = '{"findings":[],"verdict":"통과"}'
    out = run(kind, review_mode="codex_first", prechecks=[raw], bad=0)
    row, = out["result"]["precheck_log"]
    assert row["findings"] == 0 and row["path"] and "skipped" not in row
    assert out["calls"][2]["opts"]["label"] == "문장 대조 1"


@WORKFLOWS
def test_precheck_command_quotes_paths_and_respects_zero_fix_limit(kind, tmp_path):
    desk = tmp_path / "시험' 자료"
    issue = desk / "issues/i20990101-01"
    files = ["issue.yaml", "article.yaml", "evidence/e1.yaml", "captures/e1/text.txt"]
    for name in [*files, "captures/e1/source.html", "reviews/notes.md"]:
        p = issue / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("지어낸 시험 자료")
    (issue / "issue.yaml").write_text("issue_id: i20990101-01\npublish:\n  state: 게시 가능\nclaims: []\n")
    (issue / "article.yaml").write_text("title: 지어낸 글\n")
    work = str(tmp_path / "작업' 폴더")
    out = run(kind, review_mode="codex_first", max_fix=0, prechecks=[checked("중요")], desk_root=str(desk), work=work)
    assert [c["opts"]["label"] for c in out["calls"][1:]] == ["1차 대조 1", "문장 대조 1"]
    assert out["result"]["fix_rounds"] == 0
    prompt = out["calls"][1]["prompt"]
    script = re.search(r"^```sh\n(.*?)\n```$", prompt, re.M | re.S)[1]
    cmd = subprocess.run(["/bin/sh", "-c", script], cwd=FOLDER.parents[3], text=True, check=True,
                         capture_output=True, env=dict(os.environ, OZL_DESK_ROOT="", OZL_OPS_RUNNER="0"))
    tag = "r1" if kind == "make" else "r2"
    tool = str(Path("~/.claude/scripts/offload.py").expanduser())
    instructions = str(Path("~/OZL/.claude/skills/ozl/make/07_precheck.md").expanduser())
    paths = [tool, instructions, *(str(issue / name) for name in files), f"{work}/precheck_{tag}_1.json"]

    def quoted(value):
        return "'" + value.replace("'", "'\\''") + "'"

    assert script.startswith(f"env OZL_DESK_ROOT={quoted(str(desk))} '.venv/bin/python'")
    assert cmd.stdout.startswith(f"env OZL_DESK_ROOT={quoted(str(desk))} ")
    assert all(quoted(path) in cmd.stdout for path in paths)
    assert shlex.split(cmd.stdout) == [
        "env", f"OZL_DESK_ROOT={desk}", "python3", tool, "run", "--task", "verify", "--lane", "codex",
        "--author-family", "anthropic", "--effort", "high", "--caller", "ozl:make-precheck",
        "--prompt-file", instructions, "--in", *(str(issue / name) for name in files),
        "--out", f"{work}/precheck_{tag}_1.json", "--expect", "json", "--min-chars", "20"]


@WORKFLOWS
@pytest.mark.parametrize("hidden", ["claim", "issue"])
def test_precheck_refuses_issue_with_hidden_items(kind, tmp_path, hidden):
    """공개 제외·보류 항목이 있거나 이슈가 게시 가능이 아니면 1차 대조 명령을 만들지 않는다(CLAUDE.md 「외부 모델에 보내지 않는 것」)."""
    desk = tmp_path / "desk"
    issue = desk / "issues/i20990101-01"
    for name in ["issue.yaml", "article.yaml", "evidence/e1.yaml", "captures/e1/text.txt"]:
        p = issue / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("지어낸 시험 자료")
    state = "게시 가능" if hidden == "claim" else "보류"
    claims = "claims:\n- id: c1\n  gist: 지어낸 주장\n  publish: 공개 제외\n" if hidden == "claim" else "claims: []\n"
    (issue / "issue.yaml").write_text(f"issue_id: i20990101-01\npublish:\n  state: {state}\n" + claims)
    (issue / "article.yaml").write_text("title: 지어낸 글\n")
    out = run(kind, review_mode="codex_first", max_fix=0, prechecks=[checked()], desk_root=str(desk), work=str(tmp_path / "w"))
    script = re.search(r"^```sh\n(.*?)\n```$", out["calls"][1]["prompt"], re.M | re.S)[1]
    cmd = subprocess.run(["/bin/sh", "-c", script], cwd=FOLDER.parents[3], text=True, capture_output=True,
                         env=dict(os.environ, OZL_DESK_ROOT="", OZL_OPS_RUNNER="0"))
    assert cmd.returncode != 0 and "외부 모델에 보내지 않는 항목" in cmd.stderr and "offload.py" not in cmd.stdout


@WORKFLOWS
def test_default_prompts_unchanged_with_desk_root(kind):
    """desk_root 를 줘도 기본 경로의 ENV 문구는 7d53b69 와 같다(셸 인용은 1차 대조 명령에만 쓴다)."""
    out = run(kind, desk_root="/tmp/시험 자료")
    first = out["calls"][0]["prompt"]
    assert "앞에 OZL_DESK_ROOT=/tmp/시험 자료 를" in first and "env OZL_DESK_ROOT=" not in first


@WORKFLOWS
def test_precheck_allows_issue_without_hidden_items(kind, tmp_path):
    desk = tmp_path / "desk"
    issue = desk / "issues/i20990101-01"
    for name in ["issue.yaml", "article.yaml", "evidence/e1.yaml", "captures/e1/text.txt"]:
        p = issue / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("지어낸 시험 자료")
    (issue / "issue.yaml").write_text("issue_id: i20990101-01\npublish:\n  state: 게시 가능\nclaims:\n- id: c1\n  gist: 지어낸 주장\n  publish: 게시 가능\n")
    (issue / "article.yaml").write_text("title: 지어낸 글\n")
    out = run(kind, review_mode="codex_first", max_fix=0, prechecks=[checked()], desk_root=str(desk), work=str(tmp_path / "w"))
    script = re.search(r"^```sh\n(.*?)\n```$", out["calls"][1]["prompt"], re.M | re.S)[1]
    cmd = subprocess.run(["/bin/sh", "-c", script], cwd=FOLDER.parents[3], text=True, capture_output=True,
                         env=dict(os.environ, OZL_DESK_ROOT="", OZL_OPS_RUNNER="0"))
    assert cmd.returncode == 0 and "offload.py" in cmd.stdout
