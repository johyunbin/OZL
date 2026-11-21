"""시험 공통 — 출처 대장(src/ozl/research/sources_ledger.yaml)을 기본으로 '모두 허용'으로 바꿔 끼운다.

기존 시험은 지어낸 피드·소스 id 로 수집과 점수를 돌린다. 실제 대장은 그 id 를 모르므로(→ 불명 → 막힘)
대장 판정과 무관한 시험이 실제 대장 내용에 기대어 깨지지 않게 한다.
대장 자체를 시험하는 모듈은 pytestmark = pytest.mark.real_ledger 를 두고, 지어낸 대장 파일을 ledger.PATH 에 끼워 쓴다.
표지는 등록해 두므로 --strict-markers 에서 오타가 나면 시험이 멈춘다(모듈 속성처럼 조용히 '모두 허용'으로 굴러가지 않는다).
"""
from __future__ import annotations

import os
import tempfile

# 운영 자료 쓰기 가드: 시험 모듈이 ozl 을 가져오기 전에 비공개 자료의 뿌리(ozl.paths.root)를 빈 임시 폴더로 돌린다.
# 모듈이 가져올 때 정하는 경로 상수도 이 폴더를 따르므로, 시험이 상수를 바꿔 끼우지 않은 곳에서도 운영 private/ 에 쓰지 않는다.
# 실제 자료를 읽는 시험을 이 기기에서 돌릴 때만 OZL_TEST_REAL_PRIVATE=1 로 끈다(쓰는 시험이 섞여 있으니 사본에서만).
if os.environ.get("OZL_TEST_REAL_PRIVATE", "") != "1":   # 원문이 정확히 "1" 일 때만 끈다
    os.environ["OZL_PRIVATE"] = tempfile.mkdtemp(prefix="ozl-test-private-")
    os.environ["OZL_UNDER_TEST"] = "1"   # 시험이 띄운 하위 프로세스도 시험임을 안다(scripts/publish_gate.py 의 사본 뿌리 차단을 비켜 간다)
    # 셸에서 물려받은 칸별 위치 변수가 운영 자료를 가리키면 가드를 건너뛴다 — 시험은 필요한 값을 monkeypatch 로 따로 준다
    for _k in ("OZL_DESK_ROOT", "OZL_PULSE_DB", "OZL_ENGINE_DB", "OZL_BOARD_OUT", "OZL_ENGINE_OVERRIDES", "OZL_WEB_OUT", "OZL_CARDS_OUT"):
        os.environ.pop(_k, None)

import pytest  # noqa: E402

from ozl.research import ledger  # noqa: E402


class _AllowAll(dict):
    def get(self, key, default=None):  # noqa: ARG002
        return {"collect": "허용", "score_use": "허용"}


def pytest_configure(config):
    config.addinivalue_line("markers", "real_ledger: 출처 대장을 '모두 허용'으로 바꿔 끼우지 않는다")


@pytest.fixture(autouse=True)
def _permissive_ledger(request, monkeypatch):
    if request.node.get_closest_marker("real_ledger"):
        return
    if hasattr(request.module, "REAL_LEDGER"):   # 옛 방식 — 표지로 바꾸라고 멈춘다
        raise RuntimeError(f"{request.module.__name__}: REAL_LEDGER 대신 pytestmark = pytest.mark.real_ledger 를 쓴다")
    monkeypatch.setattr(ledger, "load", lambda path=None: _AllowAll())


@pytest.fixture(autouse=True)
def _no_user_overrides(tmp_path_factory, monkeypatch):
    """시험은 실제 사용자 결정 파일(private/ops/ledger_overrides.yaml)을 읽지 않는다."""
    monkeypatch.setattr(ledger, "OVERRIDES_PATH", tmp_path_factory.getbasetemp() / "no_overrides.yaml")

