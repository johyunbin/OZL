"""검토 묶음의 숨김 문장과 내부 표기 누출을 검사한다."""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from . import article, model, rules

# 본문에서는 짝이 맞는 괄호까지만 주소다. 닫는 괄호 뒤의 문장부호와 다음 말은 검사한다.
URL = re.compile(r"""
    https?://
    (?:
        (?!(?<=\))[.,;:!?。…])
        (?: [^\s<>()"'`\[\]] | \([^\s<>()"'`]*\) | \[[\da-f:.]+\] )
    )+
""", re.I | re.X)
SOURCE_URL = re.compile(r"""https?://[^\s<>"`]+""", re.I)
LEAK = re.compile(r"/Users/|private/|captures/|evidence/|~/|(?<!\S)/[^/\s]+/"
                  r"|(?a:\b(?:claude|opus|sonnet|haiku|fable|codex|gemini|chatgpt|gpt-[0-9][a-z0-9]*)\b)"
                  r"|(?<![a-z0-9])T[1-5](?![a-z0-9])", re.I)
# 근거 번호는 통째로 읽어 이슈 번호와 구별한다. 이슈 번호와 근거 번호는 어느 이슈 것이든 막는다. Q1(분기)과 q1(질문 번호)도 다르다.
ID_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:(?P<evidence>i[0-9]{8}-[0-9]{2}-e[0-9]+)"
                      r"|(?P<issue>i[0-9]{8}-[0-9]{2})|[a-z][0-9]+)(?![A-Za-z0-9])")
ITEM_COUNT = r"(?:주장|항목)(?:의?건수)?(?:은|는|이|가|을|를)?(?:\d+|한|두|세|네|다섯|여섯|[일이삼사오육칠팔구십]+)(?:건|개)"
HIDDEN_COUNT = re.compile(r"(?:다루지않[은는]|숨긴|숨겨진|공개하지않[은는]|비공개|공개제외|보류한)" + ITEM_COUNT
                          + "|" + ITEM_COUNT + r"(?:은|는|을|를)?(?:숨겼|보류|비공개|공개하지않|다루지않)")


@dataclass(frozen=True)
class SourceLine:
    caption: str
    url: str


def _normalized(text):
    return "".join(ch for ch in article.plain(text).casefold() if ch.isalnum())


# reader_items 가운데 판정 상세에 그대로 쓰는 항목 칸. 조건부 입장·이력은 화면용 값으로 따로 대조한다.
DETAIL_FIELDS = {
    "facts": {"text"}, "flow": {"what"}, "stances": {"who", "summary"},
    "open_questions": {"text"}, "figures": {"caption"}, "corrections": {"before", "after", "why"},
    "spillover": {"text"}, "claims": {"gist", "scope", "searched", "not_found", "would_decide", "basis_label"},
}


def _hidden_sentences(issue, shown_claims):
    hidden, public = set(), set()

    def add(target, wording, min_length=1):
        for sentence in article.sentences(wording):
            normalized = _normalized(sentence)
            if len(normalized) >= min_length:
                target.add(normalized)

    label_fields = (".scope", ".searched", ".basis_label", ".spread.where", ".who", ".alt")
    for path, wording, _, item in model.reader_items(issue):
        group = path.partition(".")[0]
        if group in model.ITEM_LISTS and not rules.item_public(issue, item):
            add(hidden, wording, 12 if path.endswith(label_fields) else 1)
        elif (path in ("titles.chosen", "what_new", "why_matters", "rev_line") or group == "so_far"
              or path.rpartition(".")[2] in DETAIL_FIELDS.get(group, ())):
            add(public, wording)

    # 당사자 입장과 판정 이력은 같은 공개 주장 안에서도 실제로 화면에 뽑힌 값만 쓴다.
    for claim in shown_claims:
        add(public, claim["party_position"])
        for change in claim["history"]:
            add(public, change.get("why") or "")
    for claim in issue.get("claims") or []:
        target = public if rules.item_public(issue, claim) else hidden
        for row in [claim, *(claim.get("parts") or [])]:
            for reason in row.get("unverified_reasons") or []:
                add(target, reason)
    return hidden - public


def _checked_text(rows, issue, evs, shown_claims):
    record_ids = set(evs)
    for group in (*model.ITEM_LISTS, "reviews"):
        record_ids.update(row["id"] for row in issue.get(group) or [] if row.get("id"))
    for claim in issue.get("claims") or []:
        record_ids.update(part["id"] for part in claim.get("parts") or [] if part.get("id"))
    lines, hits = [], set()
    for row in rows:
        if isinstance(row, SourceLine):
            value = row.caption
            check = row.caption
            if row.url:
                value += ", " + row.url
                if not SOURCE_URL.fullmatch(row.url):
                    check = value
        else:
            value = check = row
        for offset, line in enumerate(check.split("\n")):
            prose = URL.sub(" ", line)
            if LEAK.search(prose) or any(m["issue"] or m["evidence"] or m[0] in record_ids for m in ID_TOKEN.finditer(prose)):
                hits.add(len(lines) + offset)
        lines.extend(value.split("\n"))

    # 줄바꿈도 공백이다. 정규화 위치를 실제 출력 줄로 돌려 겹친 모든 줄을 알린다.
    offsets, normalized = [], []
    size = 0
    for line in lines:
        offsets.append(size)
        normalized.append(_normalized(line))
        size += len(normalized[-1])
    joined = "".join(normalized)

    def mark(start, end):
        hits.update(range(bisect_right(offsets, start) - 1, bisect_right(offsets, end - 1)))

    for match in HIDDEN_COUNT.finditer(joined):
        mark(*match.span())
    for sentence in _hidden_sentences(issue, shown_claims):
        start = joined.find(sentence)
        while start != -1:
            mark(start, start + len(sentence))
            start = joined.find(sentence, start + 1)
    if hits:
        raise ValueError("\n" + "\n".join(f"{i + 1}: {lines[i]}" for i in sorted(hits)))
    return "\n".join(lines) + "\n"
