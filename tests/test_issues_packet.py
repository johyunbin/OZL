"""지어낸 이슈의 검토 묶음: 미리보기와 같은 글, 공개 경계, 줄 단위 누출 진단."""
import json
import re

import pytest

from ozl.issues import article, ids, model, paths
from ozl.issues.__main__ import main
from test_issues_article import sample
from test_issues_check import I1, I2, desk  # noqa: F401


def packet(iid, out, *flags):
    return main(["packet", iid, "--out", str(out), *flags])


def test_article_and_verdict_text_match_preview(desk, capsys):
    a = sample()
    a["earlier"] = [{"label": "지난 겨울", "items": ["시가 안을 준비했다.[^1]"]}]
    a["views"] = [{"topic": "인상 폭", "sides": [{"who": "시", "text": "원안이 필요하다.[^1]"}]}]
    a["sources"][0]["url"] = "https://example.org/private/claude/i20990101-01-e1"
    a["sources"].reverse()
    model.save_yaml(article.article_file(I1), a)
    assert main(["export", "--preview", "--out", str(desk / "pv")]) == 0
    capsys.readouterr()
    preview = json.loads((desk / "pv/issues/hanbit-bus-fare-400.json").read_text())
    # 다른 이슈를 읽는다면 이 깨진 yaml 때문에 멈춘다.
    paths.issue_file(I2).write_text("[")
    out = desk / "make/packet.md"
    assert packet(I1, out) == 0
    text = out.read_text()
    assert capsys.readouterr().out.strip() == f"packet {out} 글자 {len(text)} 주장 5 문서 3"
    for _, wording, _ in article.texts(preview["article"]):
        assert wording in text
    for group in preview["verdicts"]["groups"]:
        for c in group["claims"]:
            for row in [c, *c["parts"]]:
                assert f"{row['gist']}\n판정: {row['verdict']}\n확인한 범위: {row['scope']}" in text
                assert all(f"근거가 말하는 것: {s}" in text for s in row["basis"])
    assert a["sources"][-1]["url"] in text
    assert text.index("[^1] 한빛시") < text.index("[^2] 한빛교통공사") < text.index("[^3] 가상일보")
    assert "400 원 올리겠다는 기본요금 폭" in text and "[^1]" in text
    assert all(f"문서 {n}." in text for n in "가나다")


def test_hidden_claims_reports_and_internal_fields_are_not_exported(desk, capsys):
    issue = model.load_issue(I2)
    issue["claims"][2]["basis_facts"] = ["f1"]
    model.save_issue(issue)
    assert main(["export", "--preview", "--out", str(desk / "pv")]) == 0
    preview = json.loads((desk / "pv/issues/nuri-battery-recall.json").read_text())
    before = {p: p.read_bytes() for p in paths.issues_dir().rglob("*") if p.is_file()}
    out = desk / "make/packet.md"
    assert packet(I2, out) == 0
    text = out.read_text()
    assert before == {p: p.read_bytes() for p in paths.issues_dir().rglob("*") if p.is_file()}
    assert "관련해서 확인된 것: " + issue["facts"][0]["text"] in text
    gists = [c["gist"] for g in preview["verdicts"]["groups"] for c in g["claims"]]
    assert re.findall(r"^### 주장: (.+)$", text, re.M) == gists and len(gists) == 4
    assert f"{issue['claims'][3]['gist']}\n판정: 확인 못 함" in text
    for c in issue["claims"][-2:]:
        assert c["gist"] not in text and c["would_decide"] not in text
    assert "공개 제외" not in text and "보류" not in text and "숨긴" not in text
    outside_urls = re.sub(r"https?://\S+", "", text)
    assert not re.search(r"i\d{8}-\d{2}|\b[cfp]\d+\b|private/|captures/|evidence/|claude|sonnet|opus|T[12]|agent-[ab]", outside_urls, re.I)
    doc_text = text.split("# 2부")[1].split("# 3부")[0]
    for ev in model.load_evidences(I2).values():
        if ev["kind"] == "보도":
            assert ev["source"]["url"] not in doc_text
    assert "문서 가." in doc_text
    heads = ["판정이 근거를 넘어선 곳", "다르게 읽힐 수 있는 문장", "빠진 반론과 맥락", "제목", "틀렸을 가능성이 가장 큰 한 가지"]
    assert re.findall(r"^## (.*)$", text.split("# 3부 요청")[1], re.M) == heads
    assert "맨 끝에 '최종 판단:' 한 줄" in text
    assert packet(I2, out, "--parts12-only") == 0
    assert out.read_text() == text.split("\n# 3부 요청")[0]


@pytest.mark.parametrize("token", ["i20990101-01", "i20990101-01-e3", "c1", "f2", "p2", "w1", "s1", "q1",
                                   "/Users/가상", "private/", "captures/",
                                   "evidence/", "ClAuDe", "Opus", "opus-5", "(Codex)", "Sonnet", "haiku", "FABLE", "GPT-4o", "gpt-5.5",
                                   "Gemini", "ChatGPT", "T1", "/tmp/work/packet.md", "~/자료", "(https://news.example/x).(Codex)",
                                   "https://news.example/x(y).(Codex)"])
def test_leak_refuses_output_with_matching_line(desk, capsys, token):
    issue = model.load_issue(I1)
    out = desk / "make/packet.md"
    assert packet(I1, out) == 0
    original = out.read_bytes()
    n = next(i for i, s in enumerate(original.decode().splitlines(), 1) if s.startswith("무엇이 새로운가:"))
    capsys.readouterr()
    issue["what_new"] = f"잘못 넣은 글 {token}이다."
    model.save_issue(issue)
    missing = desk / "없는 폴더/묶음"
    for dest in (out, missing):
        assert packet(I1, dest) == 2
        log = capsys.readouterr()
        assert not log.out and f"{n}: 무엇이 새로운가: {issue['what_new']}" in log.err.splitlines()
    assert not missing.parent.exists() and out.read_bytes() == original


@pytest.mark.parametrize("wording", ["S&P500", "G20", "Q1", "갤럭시 S25", "GPT 기반 서비스", "공개하지 않은 것은",
                                     "비공개 사건", "비공개 사건 3건", "숨긴 주장은 없다", "c99"])
def test_reader_terms_and_unused_ids_are_allowed(desk, wording):
    issue = model.load_issue(I1)
    issue["what_new"] = wording
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I1, out) == 0
    assert f"무엇이 새로운가: {wording}" in out.read_text().splitlines()


@pytest.mark.parametrize("other", [I2, "i20991231-03", "i20991231-03-e2", "i20990101-01-e99", f"{I2}-e1"])
def test_other_issue_id_is_rejected(desk, capsys, other):
    issue = model.load_issue(I1)
    issue["what_new"] = f"다른 이슈 {other}에서 다뤘다."
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I1, out) == 2 and not out.exists()
    assert issue["what_new"] in capsys.readouterr().err


def test_output_cannot_replace_issue_even_through_symlink(desk, capsys):
    link = desk / "make"
    link.symlink_to(paths.issue_dir(I2), target_is_directory=True)
    original = paths.issue_file(I2).read_bytes()
    assert packet(I1, link / "issue.yaml") == 2
    assert capsys.readouterr().err.strip() == "packet: 이슈 기록 폴더에는 묶음을 쓰지 않는다"
    assert paths.issue_file(I2).read_bytes() == original
    assert packet("../other", desk / "packet.md") == 2
    assert capsys.readouterr().err.strip() == "packet: 이슈 번호 꼴이 아니다: ../other"


def test_document_cited_only_by_part_basis_fact_is_included(desk):
    issue = model.load_issue(I1)
    part = issue["claims"][-1]["parts"][-1]
    part["evidence"] = []
    model.save_issue(issue)
    ev = model.load_evidences(I1)[f"{I1}-e3"]
    out = desk / "packet.md"
    assert packet(I1, out) == 0
    docs = out.read_text().split("# 2부")[1]
    assert ev["observed"] in docs and ev["source"]["url"] in docs


def test_same_url_groups_passages_in_first_citation_order(desk, capsys):
    issue = model.load_issue(I1)
    evs = model.load_evidences(I1)
    first, second, third = (evs[f"{I1}-e{n}"] for n in (2, 1, 3))
    # 마지막 주장에 첫 문서의 다른 대목을 인용한다. 다른 두 문서를 건너 다시 나온 주소다.
    extra = dict(first, evidence_id=ids.next_evidence_ids(I1)[0], observed="위원회는 한빛시의 2098년 결산을 검사했다.")
    extra["verification"]["recheck"]["located"] = extra["observed"]
    model.save_evidence(extra)
    issue["claims"][-1]["parts"][-1]["evidence"].append({"id": extra["evidence_id"]})
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I1, out) == 0
    docs = out.read_text().split("# 2부")[1].split("# 3부")[0]
    heads = re.findall(r"^문서 (.+)$", docs, re.M)
    assert len(heads) == 3
    for head, label, ev in zip(heads, "가나다", [first, second, third], strict=True):
        assert head.startswith(f"{label}. ") and head.endswith(ev["source"]["url"])
    assert re.findall(r"^대목: (.+)$", docs, re.M) == [ev["observed"] for ev in (first, extra, second, third)]
    assert docs.index(extra["observed"]) < docs.index("문서 나.")
    assert capsys.readouterr().out.strip().endswith("주장 5 문서 3")
    # 같은 주소여도 뒤쪽 대목의 사본 검사는 생략할 수 없다.
    extra["observed"] = "사본에는 없는 대목이다."
    model.save_evidence(extra)
    assert packet(I1, out) == 3
    assert f"{extra['evidence_id']}: 판정에 쓴 공식 근거의 사본 대조 오류" in capsys.readouterr().err


@pytest.mark.parametrize("state", ["공개 제외", "보류", None])
def test_whole_issue_must_be_publishable(desk, capsys, state):
    issue = model.load_issue(I1)
    issue["publish"]["state"] = state
    model.save_issue(issue)
    article.article_file(I1).write_text("[")
    paths.evidence_file(I1, f"{I1}-e1").write_text("[")
    out = desk / "새 폴더/packet.md"
    assert packet(I1, out) == 3
    assert "publish.state" in capsys.readouterr().err and not out.parent.exists()


def test_original_fixture_omits_hidden_claims_but_keeps_shared_wording(desk):
    issue = model.load_issue(I2)
    out = desk / "packet.md"
    assert packet(I2, out) == 0
    text = out.read_text()
    assert "판정하지 못한 까닭: 핵심 근거를 구하지 못함" in text
    assert "찾아본 범위: 누리전자 공시, 제품안전원 공고" in text
    for hidden in issue["claims"][-2:]:
        assert hidden["gist"] not in text and hidden["would_decide"] not in text


def test_public_sentences_and_short_labels_do_not_block_packet(desk):
    issue = model.load_issue(I2)
    hidden = issue["claims"][-1]
    hidden["not_found"] = issue["why_matters"].replace(" ", "").rstrip(".") + "!"
    hidden["basis_facts"] = [issue["facts"][0]["id"]]
    hidden["basis_label"] = hidden["spread"]["where"] = "회수"
    issue["stances"][0].update(who="회수", publish="보류")
    issue["figures"].append({"id": "g1", "alt": "회수", "publish": "공개 제외"})
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I2, out) == 0
    text = out.read_text()
    assert issue["why_matters"] in text and issue["facts"][0]["text"] in text
    assert hidden["gist"] not in text


@pytest.mark.parametrize(("group", "field", "wording"), [
    ("facts", "text", "서명을 지웠다."),
    ("claims", "gist", "도장을 바꿨다."),
    ("flow", "what", "열쇠를 넘겼다."),
    ("stances", "summary", "가상인 A씨가 회사 계약서를 외부에 넘겼다는 주장이 돌았다."),
    ("stances", "who", "가상시 계약서의 유출 경위를 조사하는 위원회"),
    ("open_questions", "text", "누가 옮겼나?"),
    ("figures", "caption", "찢긴 영수증."),
    ("figures", "alt", "계약서 뒷장에는 가상의 직원 이름과 서명이 있다."),
    ("claims", "basis_label", "이 라벨은 공개하지 않은 계약서에서만 사용한다."),
])
def test_article_rejects_wording_from_each_hidden_list(desk, capsys, group, field, wording):
    issue = model.load_issue(I2)
    issue[group].append({"id": f"{model.ITEM_LISTS[group]}99", field: wording, "publish": "공개 제외"})
    model.save_issue(issue)
    a = sample(I2, issue["slug"])
    a["dek"] = wording
    model.save_yaml(article.article_file(I2), a)
    out = desk / "packet.md"
    assert packet(I2, out) == 2 and not out.exists()
    assert re.search(rf"^\d+: {re.escape(wording)}$", capsys.readouterr().err, re.M)


@pytest.mark.parametrize("field", ["titles.candidates", "reason", "spread.where", "verdict_history", "party_position", "figures.alt"])
def test_unshown_field_does_not_exempt_hidden_gist(desk, capsys, field):
    issue = model.load_issue(I2)
    wording = issue["claims"][-1]["gist"]
    if field == "titles.candidates":
        issue["titles"]["candidates"].append({"text": wording})
    elif field == "spread.where":
        issue["claims"][0]["spread"]["where"] = wording
    elif field == "verdict_history":
        issue["claims"][0]["verdict_history"] = [{"why": wording}]
    elif field == "party_position":
        issue["claims"][0]["party_position"] = {"none": True, "text": wording}
    elif field == "figures.alt":
        issue["figures"].append({"id": "g1", "alt": wording, "publish": "게시 가능"})
    else:
        issue[field] = wording
    model.save_issue(issue)
    a = sample(I2, issue["slug"])
    a["dek"] = wording
    model.save_yaml(article.article_file(I2), a)
    out = desk / "packet.md"
    assert packet(I2, out) == 2 and not out.exists()
    assert re.search(rf"^\d+: {re.escape(wording)}$", capsys.readouterr().err, re.M)


@pytest.mark.parametrize("field", ["gist", "scope", "searched", "would_decide", "not_found", "reason", "part", "part_reason",
                                   "basis", "part_basis", "party_position", "history"])
def test_normalized_hidden_claim_detail_reports_packet_lines(desk, capsys, field):
    issue = model.load_issue(I2)
    hidden = issue["claims"][-1]
    wording = "비공개 계약에는 부속 문서가 있다."
    if field in ("basis", "part_basis"):
        # 공개 사실이면 허용된다. 숨긴 주장에만 딸린 비공개 사실을 글에 옮긴 경우다.
        issue["facts"].append(dict(issue["facts"][0], id="f9", text=wording, publish="보류"))
        if field == "basis":
            hidden["basis_facts"] = ["f9"]
        else:
            hidden["parts"] = [{"id": "p1", "basis_facts": ["f9"]}]
    elif field == "part":
        hidden["parts"] = [{"id": "p1", "scope": wording}]
    elif field == "part_reason":
        hidden["parts"] = [{"id": "p1", "unverified_reasons": [wording]}]
    elif field == "reason":
        hidden["unverified_reasons"] = [wording]
    elif field == "history":
        hidden["verdict_history"] = [{"why": wording}]
    elif field == "party_position":
        hidden[field] = {"text": wording}
    else:
        hidden[field] = "먼저 계약 날짜를 살폈다. " + wording
    model.save_issue(issue)
    a = sample(I2, issue["slug"])
    a["status"]["alleged"] = ["비공개 계[^1]약에는,\n부속문서가 있다!"]
    model.save_yaml(article.article_file(I2), a)
    out = desk / "packet.md"
    assert packet(I2, out) == 2 and not out.exists()
    err = capsys.readouterr().err
    first = re.search(r"^(\d+): 비공개 계\[\^1\]약에는,$", err, re.M)
    assert first and f"{int(first[1]) + 1}: 부속문서가 있다!" in err.splitlines()


@pytest.mark.parametrize("wording", ["다루지 않은 주장 2건", "숨긴 주장 2건", "숨긴 주장 두 건", "다루지 않은 항목 3개",
                                     "공개하지 않은 항목은 1건이다.", "항목 세 개를 숨겼다."])
def test_hidden_count_is_a_numbered_leak(desk, capsys, wording):
    issue = model.load_issue(I1)
    issue["what_new"] = wording
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I1, out) == 2 and not out.exists()
    assert re.search(rf"^\d+: 무엇이 새로운가: {wording}$", capsys.readouterr().err, re.M)


def test_scopus_and_only_the_url_are_exempt(desk, capsys):
    a = sample()
    a["dek"] = "Scopus 자료(https://example.org/private/opus)."
    a["sources"][0]["url"] = "https://example.org/archive/(Codex)/private/"
    model.save_yaml(article.article_file(I1), a)
    out = desk / "packet.md"
    assert packet(I1, out) == 0
    text = out.read_text()
    assert a["dek"] in text and a["sources"][0]["url"] in text
    a["sources"][0]["title"] = "공개 자료 (Codex)"
    model.save_yaml(article.article_file(I1), a)
    assert packet(I1, out) == 2 and out.read_text() == text
    assert "공개 자료 (Codex)" in capsys.readouterr().err


def test_cited_copy_error_blocks_packet(desk, capsys):
    ev = model.load_evidences(I1)[f"{I1}-e1"]
    ev["observed"] = "사본에 없는 가상의 대목."
    model.save_evidence(ev)
    out = desk / "packet.md"
    assert packet(I1, out) == 3 and not out.exists()
    assert f"{I1}-e1: 판정에 쓴 공식 근거의 사본 대조 오류" in capsys.readouterr().err


def test_preview_corrections_core_and_interpretation(desk):
    a = sample()
    a["changes"] = [{"at": "2099-01-04", "what": "일정을 바로잡았다."}]
    model.save_yaml(article.article_file(I1), a)
    issue = model.load_issue(I1)
    issue["corrections"] = [dict(rev=2, at="2099-01-04", kind="정정", before="금요일", after="토요일", why="공고 정정")]
    issue["facts"][0]["type"] = "해석"
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I1, out) == 0
    text = out.read_text()
    for expected in ("2099-01-04 일정을 바로잡았다.", "이전: 금요일", "고친 뒤: 토요일", "까닭: 공고 정정",
                     "해석: " + issue["facts"][0]["text"], "작은 주장 (핵심): " + issue["claims"][-1]["parts"][0]["gist"]):
        assert expected in text


def test_unrenderable_preview_field_stops_packet(desk, capsys):
    issue = model.load_issue(I1)
    issue["spillover"]["issues"] = [I2]
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I1, out) == 3 and not out.exists()
    assert "연관 이슈" in capsys.readouterr().err


def test_preview_cannot_silently_drop_unclassified_public_claim(desk, capsys):
    issue = model.load_issue(I1)
    issue["claims"][0]["verdict"] = "미분류"
    model.save_issue(issue)
    out = desk / "packet.md"
    assert packet(I1, out) == 3 and not out.exists()
    assert "주장 목록이 일치하지 않는다" in capsys.readouterr().err
