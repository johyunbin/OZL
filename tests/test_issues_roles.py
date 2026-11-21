"""가짜 전역 경로표로 CLI와 역할별 복구를 검사한다."""
import json
import subprocess

import pytest

from ozl.issues import roles
from ozl.issues.__main__ import main


@pytest.fixture
def lanes(tmp_path, monkeypatch):
    fake = tmp_path / "경로표.py"
    calls = tmp_path / "calls"
    monkeypatch.delenv("OZL_OPS_RUNNER", raising=False)
    monkeypatch.setenv("OZL_LANES_CMD", str(fake))
    fake.write_text(f"""import sys, os, json
from pathlib import Path
calls = Path({str(calls)!r})
args = sys.argv[1:]
with calls.open('a') as f:
    print(json.dumps(args), file=f)
task = args[args.index('--task') + 1]
model = 'opus' if task == 'implement' else 'sonnet'
effort = 'medium'
mode = os.environ.get('FAKE_MODE')
if mode == 'split' and len(calls.read_text().splitlines()) == 4:
    model = 'sonnet'
if mode == 'fix collision' and len(calls.read_text().splitlines()) == 3:
    model = 'sonnet'
if mode == 'collision' and task == 'read':
    model = 'opus'
if task == 'extract':
    if mode == 'bad model': model = 'haiku'
    if mode == 'bad effort': effort = 'ultra'
    if mode == 'missing': print('{{}}'); sys.exit(0)
    if mode == 'broken': print('not json'); sys.exit(0)
if mode == 'fail': sys.exit(5)
print(json.dumps(dict(lanes=dict(claude=dict(auto=dict(model=model, effort=effort))))))
""")
    return calls


def output(capsys, *args):
    assert main(["roles", "--json", *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_routes_and_budgets(lanes, capsys):
    result = output(capsys)
    assert result["source"] == "lanes" and not result["notes"]
    calls = [json.loads(line) for line in lanes.read_text().splitlines()]
    expected = [("implement", 2), ("read", 2), ("implement", 1), ("implement", 2), ("implement", 1), ("extract", 2)]
    for (name, row), (task, level), cmd in zip(result["roles"].items(), expected, calls, strict=True):
        assert row == dict(task=task, level=level, effort="medium", source="lanes", model=roles.DEFAULT_ROLES[name])
        assert cmd == ["route", "--task", task, "--level", str(level), *(["--with-budget"] if name != "review" else []), "--json"]


@pytest.mark.parametrize("mode", ["bad model", "bad effort", "missing", "broken"])
def test_only_bad_role_falls_back(mode, lanes, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", mode)
    r = output(capsys)
    assert r["source"] == "mixed" and len(r["notes"]) == 1 and "packet_check" in r["notes"][0]
    row = r["roles"]["packet_check"]
    assert row["model"] == "sonnet" and row["source"] == "default" and not row.get("effort")


@pytest.mark.parametrize("runner", [False, True])
def test_failure_or_runner_returns_session_defaults(runner, lanes, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "fail")
    monkeypatch.setenv("OZL_OPS_RUNNER", str(int(runner)))
    r = output(capsys)
    assert r["source"] == ("runner" if runner else "default")
    assert {k: v["model"] for k, v in r["roles"].items()} == roles.DEFAULT_ROLES
    assert not any(v.get("effort") for v in r["roles"].values())
    assert lanes.exists() != runner
    assert len(r["notes"]) == (0 if runner else 6)


@pytest.mark.parametrize("mode", ["collision", "split", "fix collision"])
def test_independent_review_even_when_writers_disagree(mode, lanes, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", mode)
    r = output(capsys)
    draft, fix, revise, review = (r["roles"][k] for k in ("draft", "fix", "revise", "review"))
    assert draft["model"] == fix["model"] == revise["model"] != review["model"] and r["notes"]
    assert review.get("effort") == ("medium" if mode == "collision" else None)


@pytest.mark.parametrize("original,review", [("Claude SONNET-4.5", "opus"), ("Claude OPUS 5.5", "sonnet")])
def test_saved_writer_is_not_reviewer(original, review, lanes, capsys):
    resolved = output(capsys, "--drafted-by", original)["roles"]
    assert resolved["review"]["model"] == review
    assert all(resolved[k]["model"] != review for k in ("draft", "fix", "revise"))


def test_runner_refuses_conflicting_saved_writer_without_routing(lanes, monkeypatch, capsys):
    monkeypatch.setenv("OZL_OPS_RUNNER", "1")
    assert main(["roles", "--json", "--drafted-by", "Claude Sonnet"]) == 2
    assert "독립된 검토 모델" in capsys.readouterr().err and not lanes.exists()


def test_timeout_falls_back(lanes, capsys, monkeypatch):
    def timeout(cmd, *, timeout, **kwargs):
        assert timeout == 30
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(subprocess, "run", timeout)
    assert output(capsys)["source"] == "default"
