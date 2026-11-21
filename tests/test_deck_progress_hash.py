"""진행 기록의 최종 사양 대조. 해시가 없는 회차는 이전 방식으로 완성한다."""
import hashlib
import json
from datetime import timedelta

import pytest
import yaml

from ozl.render import progress as P
from ozl.render.__main__ import main as render_main
from ozl.research import cards as C
from test_deck_visuals import CARD, desk  # noqa: F401


@pytest.fixture
def run(desk, tmp_path, monkeypatch):
    C.save_yaml(C.card_path(CARD), {"card_id": CARD, "titles": ["가상제분 소식"], "sources": []})
    monkeypatch.setattr(P, "spec_major", lambda _: [])
    P.start(CARD)
    for step in P.STEPS[:-1]:
        if step not in P.GATED:
            P.mark(CARD, step)
    spec = tmp_path / "deck.yaml"
    spec.write_text(f"card_id: {CARD}\ntitle: 가상제분\n")
    return spec


def passes(spec, steps=P.GATED):
    for step in steps:
        P.mark(CARD, step, spec=spec)


def finish(spec):
    return P.done(CARD, str(spec.parent), spec=spec)


def cli(*args):
    return render_main(["progress", CARD, *(str(s) for s in args)])


def test_changed_spec_requires_review_and_all_downstream_steps(run):
    passes(run)
    with pytest.raises(ValueError, match="--spec"):
        P.done(CARD, str(run.parent))
    run.write_text(f"card_id: {CARD}\ntitle: 바뀐 제목\n")
    with pytest.raises(ValueError, match="다시 돌 게이트: 검토 → 빌드 → 게이트 → 재확인"):
        finish(run)
    assert P.load(CARD)["status"] == P.IN_PROGRESS
    passes(run)
    assert finish(run)["status"] == P.DONE


def test_rerunning_build_or_gate_invalidates_later_passes_even_in_same_second(run, monkeypatch):
    t = P.now()
    monkeypatch.setattr(P, "now", lambda: t)
    passes(run)
    P.mark(CARD, "빌드", spec=run)
    with pytest.raises(ValueError, match="다시 돌 게이트: 게이트 → 재확인"):
        finish(run)
    P.mark(CARD, "게이트", spec=run)
    with pytest.raises(ValueError, match="다시 돌 게이트: 재확인"):
        finish(run)
    P.mark(CARD, "재확인", spec=run)
    assert finish(run)["status"] == P.DONE


def test_carry_cli_records_source_hash_reason_and_final_hash(run, capsys):
    passes(run)
    old = hashlib.sha256(run.read_bytes()).hexdigest()
    run.write_text(f"card_id: {CARD}\ntitle: 가상제분\n# 글 간격 수정\n")
    new = hashlib.sha256(run.read_bytes()).hexdigest()
    assert cli("--mark", "빌드", "--spec", run) == 0
    assert cli("--mark", "게이트", "--spec", run, "--carry", "검토", "--reason", "글 간격만 고쳤다") == 0
    rec = P.load(CARD)["steps"][-1]
    assert rec["carried"] == {"검토": old} and rec["carry_reason"] == "글 간격만 고쳤다"
    with pytest.raises(ValueError, match="다시 돌 게이트: 재확인"):
        finish(run)
    P.mark(CARD, "재확인", spec=run)
    capsys.readouterr()
    assert cli() == 0
    assert f"검토: {old[:10]} · 최종 사양과 같음" in capsys.readouterr().out
    assert cli("--spec", run) == 0
    assert f"검토: {old[:10]} · 최종 사양과 다름" in capsys.readouterr().out
    assert cli("--done", "--final", run.parent, "--spec", run) == 0
    out = capsys.readouterr().out
    assert f"검토: {old[:10]} · 최종 사양과 다름" in out
    for step in P.GATED[1:]:
        assert f"{step}: {new[:10]} · 최종 사양과 같음" in out
    assert P.load(CARD)["steps"][-1]["spec_sha256"] == new


def test_carry_refuses_blank_reason_wrong_step_or_no_clean_source(run):
    P.mark(CARD, "검토", spec=run, major=["설명이 비었다"])
    before = P.load(CARD)
    for reason in ("", "  "):
        with pytest.raises(ValueError, match="--reason"):
            P.mark(CARD, "게이트", spec=run, carry="검토", reason=reason)
    for step, carry in (("빌드", "검토"), ("게이트", "재확인")):
        with pytest.raises(ValueError, match="--carry"):
            P.mark(CARD, step, spec=run, carry=carry, reason="글 간격만 고쳤다")
    with pytest.raises(ValueError, match="큰 오류 없는 검토"):
        P.mark(CARD, "게이트", spec=run, carry="검토", reason="글 간격만 고쳤다")
    assert P.load(CARD) == before


def test_current_hash_needs_clean_review_even_after_clean_gate(run):
    P.mark(CARD, "검토", spec=run, major=["설명이 비었다"])
    passes(run, P.GATED[1:])
    with pytest.raises(ValueError, match="다시 돌 게이트: 검토"):
        finish(run)


def test_recheck_digest_must_match_current_card(run):
    passes(run)
    card = C.load_card(CARD)
    card["titles"] = ["가상제분의 새 소식"]
    C.save_yaml(C.card_path(CARD), card)
    with pytest.raises(ValueError, match="재확인 뒤에 카드나 기록이 바뀌었다"):
        finish(run)
    P.mark(CARD, "재확인", spec=run)
    assert finish(run)["status"] == P.DONE


def test_cannot_carry_a_previous_run_and_unhashed_run_keeps_old_behavior(run):
    passes(run)
    P.abandon(CARD)
    P.start(CARD)
    with pytest.raises(ValueError, match="이번 회차"):
        P.mark(CARD, "게이트", spec=run, carry="검토", reason="글 간격만 고쳤다")
    for step in P.STEPS[:-1]:
        P.mark(CARD, step, spec=run if step == "사양" else None)
    assert P.done(CARD, str(run.parent))["status"] == P.DONE


def test_force_can_finish_without_spec(run):
    P.mark(CARD, "검토", spec=run)
    assert P.done(CARD, str(run.parent), force=True)["status"] == P.DONE


def test_append_order_not_clock_order(run):
    t = P.now()
    for step, minute in zip(("검토", "게이트", "빌드", "재확인"), (0, 2, 1, 3)):
        P.mark(CARD, step, spec=run, at=t + timedelta(minutes=minute))
    with pytest.raises(ValueError, match="다시 돌 게이트: 게이트 → 재확인"):
        finish(run)
    P.mark(CARD, "게이트", spec=run, at=t)
    P.mark(CARD, "재확인", spec=run, at=t)
    assert finish(run)["status"] == P.DONE


def test_final_folder_requires_unanimous_root_copies_without_meta(run):
    passes(run)
    final = run.parent / "final"
    archive = final / "archive"
    archive.mkdir(parents=True)
    (archive / "copy.yaml").write_bytes(run.read_bytes())
    (final / "linked.yaml").symlink_to(run)
    with pytest.raises(ValueError, match="완성본 폴더"):
        P.done(CARD, str(final), spec=run)
    (final / "linked.yaml").unlink()
    (final / "copy.yaml").write_bytes(run.read_bytes())
    other = final / "second.yaml"
    other.write_bytes(run.read_bytes() + b"# different edition")
    with pytest.raises(ValueError, match="완성본 폴더"):
        P.done(CARD, str(final), spec=run)
    other.write_bytes(run.read_bytes())
    assert P.done(CARD, str(final), spec=run)["status"] == P.DONE


@pytest.mark.parametrize("bad", ["broken", "wrong_spec", "no_hash", "missing", "wrong_bytes", "draft", "no_mode",
                                 "nested", "absolute", "traversal", "linked_pptx", "linked_meta"])
def test_root_meta_is_authoritative_and_binds_local_pptx(run, bad):
    passes(run)
    final = run.parent / "final"
    final.mkdir()
    (final / "copy.yaml").write_bytes(run.read_bytes())
    pptx = final / "deck.pptx"
    pptx.write_bytes(b"test deck")
    meta = {"draft": False, "edition": None, "spec_sha256": hashlib.sha256(run.read_bytes()).hexdigest(), "pptx": pptx.name,
            "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest()}
    invalid = dict(meta)
    if bad == "draft":
        invalid["draft"] = True
    elif bad == "no_mode":
        del invalid["draft"]
    elif bad == "wrong_spec":
        invalid["spec_sha256"] = "0" * 64
    elif bad == "no_hash":
        del invalid["pptx_sha256"]
    elif bad == "missing":
        invalid["pptx"] = "other.pptx"
    elif bad == "wrong_bytes":
        invalid["pptx_sha256"] = "0" * 64
    elif bad == "nested":
        archive = final / "archive"
        archive.mkdir()
        (archive / pptx.name).write_bytes(pptx.read_bytes())
        invalid["pptx"] = "archive/" + pptx.name
    elif bad == "absolute":
        invalid["pptx"] = str(pptx)
    elif bad == "traversal":
        invalid["pptx"] = "../final/" + pptx.name
    elif bad == "linked_pptx":
        (final / "linked.pptx").symlink_to(pptx)
        invalid["pptx"] = "linked.pptx"
    path = final / "build_meta.json"
    if bad == "linked_meta":
        outside = run.with_name("outside.json")
        outside.write_text(json.dumps(meta))
        path.symlink_to(outside)
    else:
        path.write_text("{" if bad == "broken" else json.dumps(invalid))
    with pytest.raises(ValueError, match="완성본 폴더"):
        P.done(CARD, str(final), spec=run)
    assert P.load(CARD)["status"] == P.IN_PROGRESS
    path.unlink()
    path.write_text(json.dumps(meta))
    (final / "copy.yaml").write_bytes(b"# edition-specific copy")
    assert P.done(CARD, str(final), spec=run)["status"] == P.DONE


def test_failed_review_supersedes_pass_of_same_hash(run):
    P.mark(CARD, "검토", spec=run)
    P.mark(CARD, "검토", spec=run, major=["설명이 맞지 않는다"])
    passes(run, P.GATED[1:])
    with pytest.raises(ValueError, match="다시 돌 게이트: 검토"):
        finish(run)
    run.write_text(f"card_id: {CARD}\ntitle: 새 판")
    with pytest.raises(ValueError, match="큰 오류 없는 검토"):
        P.mark(CARD, "게이트", spec=run, carry="검토", reason="글 간격 수정")


def test_carried_source_latest_verdict_is_checked_again_at_done(run):
    P.mark(CARD, "검토", spec=run)
    new = run.with_name("new.yaml")
    new.write_text(f"card_id: {CARD}\ntitle: 새 판")
    P.mark(CARD, "빌드", spec=new)
    P.mark(CARD, "게이트", spec=new, carry="검토", reason="글 간격 수정")
    P.mark(CARD, "검토", spec=run, major=["설명이 맞지 않는다"])
    other = run.with_name("other.yaml")
    other.write_text(f"card_id: {CARD}\ntitle: 다른 판")
    P.mark(CARD, "검토", spec=other)  # 전체 회차의 마지막 major는 비었지만 원판의 실패는 남는다.
    P.mark(CARD, "재확인", spec=new)
    with pytest.raises(ValueError, match="다시 돌 게이트: 검토"):
        finish(new)


def test_only_the_ordered_last_gate_can_carry(run):
    P.mark(CARD, "검토", spec=run)
    run.write_text(f"card_id: {CARD}\ntitle: 새 판")
    P.mark(CARD, "게이트", spec=run, carry="검토", reason="글 간격 수정", major=["잘못 적은 값"])
    passes(run, P.GATED[1:])
    with pytest.raises(ValueError, match="다시 돌 게이트: 검토"):
        finish(run)


@pytest.mark.parametrize("location", ["claim_ids", "claim_ids_mapping", "conversions", "chart", "capture", "number_claims",
                                      "pair", "swap_set", "swap_slide"])
def test_recheck_hashes_canonical_bytes_for_every_citation(run, location):
    cid = "2099-01-03-am-02-c1"
    parts = {
        "claim_ids": {"claim_ids": [cid]}, "conversions": {"conversions": [{"claim_id": cid}]},
        "claim_ids_mapping": {"claim_ids": {cid: None}},
        "chart": {"chart": {"claims": [cid]}}, "capture": {"capture": cid},
        "number_claims": {"number_claims": [{"shown": "한 줌", "claim_id": cid}]},
        "pair": {"kind": "image_pair", "pair": [{"capture": cid}, {}]},
        "swap_set": {"swap": {"set": {"number_claims": [{"claim_id": cid}]}}},
        "swap_slide": {"swap": {"slide": {"pair": [{"chart": {"claims": [cid]}}]}}},
    }
    run.write_text(yaml.safe_dump({"card_id": CARD, "slides": [parts[location]]}))
    record = C.claim_path(cid)
    C.save_yaml(record, {"claim_id": cid, "observed": "가상 섬의 밀밭"})
    passes(run)
    record.write_bytes(record.read_bytes() + b"# note\n")
    with pytest.raises(ValueError, match="재확인 뒤에 카드나 기록이 바뀌었다"):
        finish(run)
    assert all(len(s["spec_digest"]) == 64 for s in P.run_steps(P.load(CARD)) if s.get("spec_sha256"))
    P.mark(CARD, "재확인", spec=run)
    assert finish(run)["status"] == P.DONE


def test_old_hashed_recheck_with_no_spec_digest(run):
    passes(run)
    st = P.load(CARD)
    st["steps"][-1].pop("spec_digest", None)
    P.save(CARD, st)
    with pytest.raises(ValueError, match="재확인"):
        finish(run)
    P.mark(CARD, "재확인", spec=run)
    assert finish(run)["status"] == P.DONE


@pytest.mark.parametrize("with_spec", [False, True])
def test_unhashed_done_keeps_legacy_behavior(run, with_spec):
    for step in P.GATED:
        P.mark(CARD, step)
    C.save_yaml(C.card_path(CARD), {"card_id": CARD, "titles": ["가상제분의 새 소식"]})
    final = run.parent / "legacy"
    final.mkdir()
    assert P.done(CARD, str(final), spec=run if with_spec else None)["status"] == P.DONE


@pytest.mark.parametrize("action", ["사양", *P.GATED, "산출"])
def test_spec_card_must_match_progress_card(run, action):
    before = P.load(CARD)
    run.write_text("card_id: 2099-01-03-am-02\ntitle: 이웃 방앗간\n")
    with pytest.raises(ValueError, match="card_id"):
        if action == "산출":
            P.done(CARD, str(run.parent), spec=run, force=True)
        else:
            P.mark(CARD, action, spec=run)
    assert P.load(CARD) == before
