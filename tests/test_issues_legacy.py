"""옛 자료(카드 29장과 그 기록) 회귀 시험 — 실제 private/desk 를 읽기만 한다. 자료가 없는 기기에서는 건너뛴다.
발행 5장의 공개 판정 값은 private/out/night_20261114/baseline_publishable.json 과 대조한다(내용은 읽지 않고 번호·지문·참거짓만)."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.issues import gate, links  # noqa: E402
from ozl.research import cards  # noqa: E402
from ozl import paths as ozlpaths  # noqa: E402

BASELINE = ozlpaths.real_at("out", "night_20261114", "baseline_publishable.json")
PUBLISHED = {"2026-11-10-am-01", "2026-11-10-am-02", "2026-11-10-am-03", "2026-11-10-am-05", "2026-11-10-am-06"}

need_private = pytest.mark.skipif(not links.available(), reason="옛 자료(private/desk)가 이 기기에 없다")


@need_private
def test_counts_explained():
    c = links.counts()
    assert c["claims_files"] == c["claims_read"] + c["parked"]          # 운영으로 늘어도 이 관계는 남는다
    assert c["cards"] >= 29 and c["published_cards"] >= 5


@need_private
def test_published_cards_unchanged():
    if not BASELINE.is_file():
        pytest.skip("기준 파일이 없다")
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    for cid in PUBLISHED:
        card, claims = cards.load_card(cid), cards.claims_for(cid)
        assert cards.publishable(card, claims) is True
        assert base[cid]["publishable"] is True and cards.content_digest(card, claims) == base[cid]["digest"]
    for cid, row in base.items():
        if cards.card_path(cid).is_file():
            assert cards.publishable(cards.load_card(cid), cards.claims_for(cid)) == row["publishable"], cid


@need_private
def test_links_no_missing():
    r = links.check()
    assert not r["skipped"] and r["missing"] == [] and r["errors"] == []


@need_private
def test_gate_matches_cards():
    for card in cards.all_cards():
        cid = card["card_id"]
        assert gate.is_public("card", cid) == cards.publishable(card, cards.claims_for(cid))


def test_legacy_checks_run_on_real_data_in_subprocess():
    """가드(tests/conftest.py)가 비공개 뿌리를 임시 폴더로 돌리면 위 네 시험은 건너뛴다. 읽기만 하는 시험이므로 이 기기에 옛 자료가
    있으면 가드를 끈 하위 프로세스에서 같은 파일을 다시 돌려, 발행 5장의 승인 지문 대조가 기본 실행에서 빠지지 않게 한다."""
    import os
    import subprocess
    if os.environ.get("OZL_TEST_REAL_PRIVATE", "") == "1":
        pytest.skip("이미 실제 자료로 도는 중이다")
    real = ozlpaths.real_at("desk")
    if not ((real / "cards").is_dir() and (real / "claims").is_dir()):
        pytest.skip("옛 자료(private/desk)가 이 기기에 없다")
    env = {k: v for k, v in os.environ.items() if k not in ("OZL_PRIVATE", "OZL_DESK_ROOT")}
    env["OZL_TEST_REAL_PRIVATE"] = "1"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(pathlib.Path(__file__)),
                        "-k", "not in_subprocess"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    want = "4 passed" if BASELINE.is_file() else "3 passed"      # 기준 파일이 없으면 지문 대조 하나는 정상적으로 건너뛴다
    assert r.returncode == 0 and want in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
