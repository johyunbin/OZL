"""Workflow 도구 대신 Node의 async 함수에 같은 네 전역을 주어 실제 호출을 기록한다."""
import hashlib
import json
import re
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
  if (opts.label === '쓰기') return {issue_id: input.stop ? '' : input.args.issue, report: '초안', offload: '시험 사본 / 결과 파일 / 레인'};
  if (opts.label.startsWith('문장 대조')) {
    const bad = reviews++ < input.bad;
    return {blind_verdicts: [], findings: bad ? [{severity: '중요'}] : [], verdict: bad ? '고쳐야 통과' : '통과'};
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


def run(kind, *, bad=1, stop=False, **options):
    src = (FOLDER / f"workflow_{kind}.js").read_text().replace("export const meta =", "const meta =", 1)
    args = dict(title="시험", issue="i20990101-01", work="/tmp/work", list="고칠 목록", prior="앞선 답")
    args.update(options)
    payload = json.dumps(dict(src=src, args=args, bad=bad, stop=stop))
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
    calls = run(kind)["calls"]
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
    assert "OZL_DESK_ROOT=/tmp/시험" in prompt and "종료 코드가 2" in prompt and ".hash" in prompt
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
