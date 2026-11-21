"""한 이슈의 미리보기 본문과 판정에 쓴 공식 문서로 04_packet.md의 검토 묶음을 만든다."""
from __future__ import annotations

import re
import sys
import tempfile
from datetime import date
from pathlib import Path

from . import article, body, digest, evidence, ids, manifest, model, paths, rules
from .packet_guard import SourceLine, _checked_text

INTRO = """이 글은 떠도는 주장마다 판정과 근거를 붙인 이슈 기록의 초안이다.
판정은 확인, 일부 맞음, 사실과 다름, 확인 못 함 넷이다.
보도만으로는 '확인'을 붙이지 않는다."""

REQUEST = """# 3부 요청

아래 소제목 그대로 답하라.

## 판정이 근거를 넘어선 곳
주장마다: 근거가 실제로 말하는 것보다 판정이나 문장이 더 나간 대목. 글의 '어디까지 확인됐나' 묶음이 판정보다 세게 쓰인 곳도

## 다르게 읽힐 수 있는 문장
독자가 오해할 문장과 고칠 문장

## 빠진 반론과 맥락
이 글이 다루지 않은 중요한 반대 사실이나 조건

## 제목
제목이 근거를 넘어서는지, 더 정확한 제목 하나

## 틀렸을 가능성이 가장 큰 한 가지

근거 대목에 없는 사실을 지어내지 마라. 모르면 모른다고 적어라. 반드시 한글로 답하라.
맨 끝에 '최종 판단:' 한 줄을 적어라. 셋 가운데 하나다. '공개해도 된다'(고칠 것이 없다) / '사소한 것만 고치면 공개해도 된다'(표현을 다듬는 정도만 남았다. 무엇인지 위에 적어라) / '고쳐야 한다'(판정이 근거를 넘거나, 독자가 사실을 잘못 알게 되는 문제가 남았다)."""

STATUS = {"confirmed": "확인된 것", "reported": "보도로 전해진 것", "alleged": "의혹 단계인 것", "unknown": "아직 모르는 것"}


class PacketUnavailable(Exception):
    """미리보기나 공식 근거를 온전히 실을 수 없다(종료 코드 3)."""


def _section(title, rows):
    rows = [row for row in rows if row]
    return ["", f"### {title}", *rows] if rows else []


def _timeline(rows):
    for row in rows:
        label = row.get("label")
        if not label and row.get("date"):
            day = date.fromisoformat(str(row["date"]))
            label = f"{day.month}월 {day.day}일" + (" 예정" if row.get("planned") else "")
        yield label
        if row.get("new"):
            yield "새 소식"
        yield from row.get("items") or []


def _points(rows):
    for row in rows:
        yield row.get("head")
        yield row.get("text")


def _article_lines(a):
    lines = ["## 가. 이슈 글"]
    if not a:  # 글이 없는 예전 이슈에도 판정 상세는 있다.
        return lines
    for field in ("figure", "related_syuka"):
        if a.get(field):
            raise PacketUnavailable(f"이슈 글의 {field} 칸을 검토 묶음에 옮길 수 없다")
    lines += [str(a[k]) for k in ("category", "state", "started", "as_of") if a.get(k)]
    lines += [f"제목: {a.get('title') or ''}", a.get("dek") or ""]
    lines += _section("세 줄 요약", a.get("summary") or [])
    lines += _section("숫자", (" ".join(str(n[k]) for k in ("value", "unit", "label") if n.get(k) is not None)
                             for n in a.get("numbers") or []))
    lines += _section("무슨 일인가", (p.get("text") if isinstance(p, dict) else p for p in a.get("what") or []))
    why = a.get("why") or {}
    lines += _section("왜 커졌나", [why.get("lead"), *_points(why.get("points") or [])])
    news = a.get("news") or []
    lines += _section("새로 나온 소식", _timeline(news[:article.NEWS_MAX]))
    lines += _section("그 전에 있었던 일", _timeline(news[article.NEWS_MAX:] + (a.get("earlier") or [])))
    groups = a.get("status") or {}
    if any(groups.values()):
        lines += ["", "### 어디까지 확인됐나"]
        for key, label in STATUS.items():
            if groups.get(key):
                lines += [label, *groups[key]]
    views = []
    for v in a.get("views") or []:
        views.append(v.get("topic"))
        for side in v.get("sides") or []:
            views.extend([side.get("who"), side.get("text")])
    lines += _section("엇갈리는 시각", views)
    lines += _section("앞으로 볼 것", _points(a.get("next") or []))
    source_lines = []
    for s in sorted(a.get("sources") or [], key=lambda s: s["n"]):
        citation = ", ".join(str(s[k]) for k in ("publisher", "title", "date", "kind") if s.get(k))
        source_lines.append(SourceLine(f"[^{s['n']}] {citation}", s.get("url") or ""))
    lines += _section("출처", source_lines)
    lines += _section("고친 기록", (f"{c.get('at', '')} {c['what']}" for c in a.get("changes") or []))
    return lines


def _source_line(label, source):
    checked = re.sub(r"(?<=\d)T(?=\d\d:)", " ", source["checked_at"])
    caption = ", ".join(filter(None, (source["by"], source["title"], checked)))
    return SourceLine(f"{label}: {caption}", source["url"])


def _claim_lines(claim, heading):
    lines = ["", f"{heading}: {claim['gist']}", f"판정: {claim['verdict']}"]
    if claim["scope"]:
        lines.append(f"확인한 범위: {claim['scope']}")
    if claim.get("kind"):
        lines.append(f"주장의 종류: {claim['kind']}")
    basis = "관련해서 확인된 것" if claim["verdict"] == "확인 못 함" else "근거가 말하는 것"
    lines += [f"{basis}: {s}" for s in claim["basis"]]
    if claim.get("press_label") and not claim.get("evidence_label") and claim["verdict"] != "확인 못 함":
        lines.append("판정에 쓴 공식 근거 없음")
    for key, label in (("evidence_label", "근거의 종류"), ("press_label", "퍼진 곳"), ("searched", "찾아본 범위"),
                       ("not_found", "찾지 못한 것"), ("would_decide", "무엇이 나오면 판정할 수 있나"), ("party_position", "당사자 입장")):
        if claim.get(key):
            lines.append(f"{label}: {claim[key]}")
    lines += [f"판정하지 못한 까닭: {s}" for s in claim["reasons"]]
    for source in claim["sources"]:
        label = "참고한 보도"
        if source["kind"] in evidence.OFFICIAL:
            label = "살펴본 공식 문서" if claim["verdict"] == "확인 못 함" else "근거 문서"
        lines.append(_source_line(label, source))
    for h in claim.get("history", []):
        lines.append(f"판정 변경: {h['rev']}판 {h.get('at', '')} {h['from']} → {h['to']}. 까닭: {h.get('why', '')}")
    for part in claim.get("parts", []):
        lines += _claim_lines(part, "작은 주장 (핵심)" if part["core"] else "작은 주장")
    return lines


def _source_names(item):
    return ", ".join(s["by"] or s["title"] for s in item["sources"] if s["by"] or s["title"])


def _detail_lines(b):
    lines = ["## 나. 판정 상세", f"제목: {b['title']}", f"{b['rev']}판", f"무엇이 새로운가: {b['what_new']}", f"왜 중요한가: {b['why_matters']}"]
    lines += _section("지금까지 3줄", b["so_far"])
    facts = []
    for f in b["facts"]:
        facts.extend([("해석: " if f["type"] == "해석" else "") + f["text"], _source_names(f)])
    lines += _section("확인된 사실", facts)
    for group in b["verdicts"]["groups"]:
        if group["note"]:
            lines.append(f"{group['verdict']}: {group['note']}")
        for claim in group["claims"]:
            lines += _claim_lines(claim, "### 주장")
    flow = []
    for w in b["flow"]:
        reported = w["report_date"]
        when = w["event_date"]
        if reported and reported != when:
            when = f"{when} · {reported} 보도" if when else f"{reported} 보도 · 일어난 날은 확인하지 못함"
        flow.append(" ".join(filter(None, (when, w["kind"], w["what"]))))
        flow.append(_source_names(w))
    lines += _section("흐름", flow)
    lines += _section("입장", (" ".join(filter(None, (s["at"], s["who"], s["kind"], s["summary"], _source_names(s))))
                             for s in b["stances"]))
    lines += _section("남은 질문", (q["text"] for q in b["open_questions"]))
    lines += _section("그림", (g["caption"] for g in b["figures"]))
    if b["spillover"]["issues"]:
        raise PacketUnavailable("연관 이슈의 화면 제목을 이 이슈의 자료만으로 옮길 수 없다")
    lines += _section("번지는 곳", (f"{c['text']} {c['url']}".strip() for c in b["spillover"]["similar_cases"]))
    lines += _section("출처", (_source_line(s["kind"], s) for s in b["sources"]))
    lines += _section("이번 판에서 달라진 것", [b["rev_line"]])
    corrections = []
    for c in b["corrections"]:
        rev = f"{c['rev']}판" if c.get("rev") is not None else ""
        corrections.append(" ".join(filter(None, (rev, c["kind"], str(c["at"] or "")))))
        corrections.extend(f"{label}: {c[k]}" for k, label in (("before", "이전"), ("after", "고친 뒤"), ("why", "까닭"))
                           if c.get(k))
    lines += _section("정정과 판 기록", corrections)
    if trend := b.get("trend_now"):
        bars = trend["bars7"]
        peak = max(bars)
        scaled = [max(1, int(100 * v / peak + 0.5)) if v > 0 else 0 for v in bars]
        when = f"{trend['asof']} 기준 " if trend["asof"] else ""
        lines += _section("화제 추이", [f"{when}화제 점수: {trend['score']}",
                                   "최근 7일(가장 큰 날 100 기준): " + ", ".join(map(str, scaled))])
    lines += _section("키워드", b["keywords"])
    lines.append(b["ai_notice"])
    return lines


def _official_ids(issue, shown, evs):
    """판정이 직접 다룬 문서(확인 못 한 까닭 포함)와 바탕이 된 사실의 문서. 입장·흐름에만 쓰인 것은 뺀다."""
    cited = []
    facts = {f["id"]: f for f in issue.get("facts") or [] if rules.item_public(issue, f)}
    for claim in issue.get("claims") or []:
        if claim["id"] not in shown:
            continue
        for row in [claim, *(claim.get("parts") or [])]:
            cited.extend(link["id"] for link in row.get("evidence") or [] if isinstance(link, dict) and link.get("id"))
            for fid in row.get("basis_facts") or []:
                cited.extend(model.item_evidence_ids(facts.get(fid)))
    return [eid for eid in dict.fromkeys(cited) if evs.get(eid, {}).get("kind") in evidence.OFFICIAL]


def _doc_label(index):
    letters = "가나다라마바사아자차카타파하"
    label = ""
    while index:
        index, pos = divmod(index - 1, len(letters))
        label = letters[pos] + label
    return label


def _require_publishable(issue):
    pub = issue.get("publish")
    state = pub.get("state") if isinstance(pub, dict) else None
    if state != "게시 가능":
        raise PacketUnavailable(f"이슈 전체가 게시 가능이 아니다 (publish.state: {state})")


def render(issue, evs, parts12_only):
    _require_publishable(issue)
    errors = body.copy_errs_of(evs)
    man = manifest.load_manifest()
    entry = manifest.entry(man, "issue", issue["issue_id"], issue["revision"])
    approved = bool(entry) and entry.get("content_hash") == digest.content_hash(issue, evs)
    b = body.issue_body(issue, evs, copy_errs=errors, approved=approved,
                        first_rev=body.first_published(man, issue["issue_id"]))
    b["trend_now"] = model.clean_trend(issue.get("trend"))
    a = article.public_view(issue.get(model.ARTICLE_KEY))
    claims = [c for group in b["verdicts"]["groups"] for c in group["claims"]]
    shown = {c["id"] for c in claims}
    public_ids = {c["id"] for c in issue.get("claims") or [] if rules.item_public(issue, c)}
    detail = _detail_lines(b)
    written = sum(isinstance(row, str) and row.startswith("### 주장: ") for row in detail)
    if written != sum(body.verdict_summary(b).values()) or shown != public_ids:
        raise PacketUnavailable("미리보기의 판정 집계와 게시 가능한 주장 목록이 일치하지 않는다")
    lines = [INTRO, "", "# 1부 독자에게 보일 글", "", *_article_lines(a), "", *detail,
             "", "# 2부 판정에 쓴 공식 문서"]
    documents = {}
    footnotes = {s.get("url"): s for s in (a or {}).get("sources", [])}
    for eid in _official_ids(issue, shown, evs):
        ev = evs[eid]
        if errors[eid]:
            raise PacketUnavailable(f"{eid}: 판정에 쓴 공식 근거의 사본 대조 오류: " + "; ".join(errors[eid]))
        if not ev.get("observed"):
            raise PacketUnavailable(f"{eid}: 판정에 쓴 원문 대목이 없다")
        documents.setdefault(ev["source"]["url"], []).append(ev)
    for n, records in enumerate(documents.values(), 1):
        src = records[0]["source"]
        footnote = footnotes.get(src["url"], {})
        doc_date = src.get("date") or footnote.get("date") or f"열람일 {str(src.get('accessed') or '')[:10]}"
        title = src.get("title") or footnote.get("title") or "제목 미상"
        lines += ["", SourceLine(f"문서 {_doc_label(n)}. {src['publisher']}, {title}, {doc_date}", src["url"])]
        lines.extend(f"대목: {ev['observed']}" for ev in records)
    if not parts12_only:
        lines += ["", REQUEST]
    return _checked_text(lines, issue, evs, claims), len(claims), len(documents)


def add_parser(sub):
    c = sub.add_parser("packet", help="다른 계열 검토에 쓸 이슈 묶음")
    c.add_argument("issue")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--parts12-only", action="store_true")


def _write_packet(args):
    if not ids.issue_id_ok(args.issue):
        raise ValueError(f"이슈 번호 꼴이 아니다: {args.issue}")
    # 게시 가부는 issue.yaml에 있다. 제외된 이슈는 연결된 글이나 사본도 열지 않는다.
    issue = model.load_yaml(paths.issue_file(args.issue))
    _require_publishable(issue)
    if model.ARTICLE_KEY in issue:
        raise ValueError(f"issue.yaml 에 article 칸을 두지 않는다 — 글은 {model.ARTICLE_FILE} 에 쓴다")
    out = args.out.resolve()
    desk = paths.desk_root().resolve()
    if not paths.is_real_root() and not any(out.is_relative_to(p) for p in (desk, Path(tempfile.gettempdir()).resolve())):
        raise ValueError("시험 묶음은 자료 루트나 임시 폴더 안에만 쓴다")
    for root in (paths.issues_dir(), paths.real_root() / "issues"):
        if out.is_relative_to(root.resolve()) or (root.exists() and any(p.exists() and p.samefile(root) for p in out.parents)):
            raise ValueError("이슈 기록 폴더에는 묶음을 쓰지 않는다")
    if (a := article.load_article(args.issue)) is not None:
        issue[model.ARTICLE_KEY] = a
    text, claims, documents = render(issue, model.load_evidences(args.issue), args.parts12_only)
    paths.write_atomic(out, text)
    print(f"packet {args.out} 글자 {len(text)} 주장 {claims} 문서 {documents}")
    return 0


def command(args):
    try:
        return _write_packet(args)
    except PacketUnavailable as exc:
        print(f"packet: {exc}", file=sys.stderr)
        return 3
