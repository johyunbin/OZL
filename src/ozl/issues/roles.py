"""워크플로 역할마다 전역 경로표를 조회하고, 쓸 수 없는 줄만 기본값으로 돌린다."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import subprocess

from . import paths, reviews

# 역할: (작업, 난도, 예산 반영 여부)
ROLE_TABLE = {
    "draft": ("implement", 2, True),
    "review": ("read", 2, False),
    "fix": ("implement", 1, True),
    "revise": ("implement", 2, True),
    "packet": ("implement", 1, True),
    "packet_check": ("extract", 2, True),
}
DEFAULT_ROLES = {
    "draft": "opus", "review": "sonnet", "fix": "opus",
    "revise": "opus", "packet": "opus", "packet_check": "sonnet",
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _route(task, level, budget):
    override = os.environ.get("OZL_LANES_CMD")
    script = Path(override or "~/.claude/scripts/lanes.py").expanduser().absolute()
    cmd = [str(script)] if override and os.access(script, os.X_OK) else ["python3", str(script)]
    cmd.extend(["route", "--task", task, "--level", str(level)])
    if budget:
        cmd.append("--with-budget")
    result = subprocess.run([*cmd, "--json"], capture_output=True, text=True, timeout=30, check=True)
    lane = json.loads(result.stdout)["lanes"]["claude"]["auto"]
    model, effort = lane["model"], lane["effort"]
    if model not in ("opus", "sonnet"):
        raise ValueError(f"허용 밖 모델: {model}")
    if effort not in EFFORTS:
        raise ValueError(f"허용 밖 effort: {effort}")
    return model, effort


def resolve_roles(drafted_by=""):
    runner = paths.in_runner()
    roles, notes = {}, []
    for role, (task, level, budget) in ROLE_TABLE.items():
        row = {"task": task, "level": level, "model": DEFAULT_ROLES[role], "source": "runner" if runner else "default"}
        roles[role] = row
        if not runner:
            try:
                model, effort = _route(task, level, budget)
                row.update(model=model, effort=effort, source="lanes")
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
                notes.append(f"{role}: 경로표를 쓸 수 없어 기본값 사용 ({exc})")

    authors = ("draft", "fix", "revise")
    writers = {reviews.model_key(roles[role]["model"]) for role in authors}
    original = set(re.findall(r"\b(?:opus|sonnet)\b", reviews.model_key(drafted_by), re.ASCII))
    review = roles["review"]
    if review["model"] in writers | original:
        if runner or len(original) == 2:
            raise ValueError("저장된 작성자와 독립된 검토 모델을 배정할 수 없다")
        other = "opus" if review["model"] == "sonnet" else "sonnet"
        notes.append("review: 작성자와 같은 모델이라 독립 검토 모델로 조정")
        if other not in writers | original:
            review.update(model=other, source="default")
        else:
            # 작성자가 두 모델에 걸치면 셋을 통일한다. 저장된 작성자만은 바꿀 수 없다.
            writer = next(iter(original), DEFAULT_ROLES["draft"])
            for role in authors:
                roles[role].update(model=writer, source="default")
                roles[role].pop("effort", None)
            review.update(model="sonnet" if writer == "opus" else "opus", source="default")
            review.pop("effort", None)

    sources = {row["source"] for row in roles.values()}
    return {"source": sources.pop() if len(sources) == 1 else "mixed", "roles": roles, "notes": notes}


def add_parser(sub):
    c = sub.add_parser("roles", help="워크플로 역할별 모델과 추론 강도")
    c.add_argument("--drafted-by", default="", help="이슈에 저장된 production.drafted_by")
    c.add_argument("--json", action="store_true")


def command(args):
    result = resolve_roles(args.drafted_by)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for role, row in result["roles"].items():
            print(f'{role}: {row["model"]} / {row.get("effort", "세션 값")} ({row["task"]} L{row["level"]}, {row["source"]})')
        for note in result["notes"]:
            print(note)
    return 0
