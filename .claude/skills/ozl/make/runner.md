# 실행기에서 돌 때 — 가드와 설정 (`/ozl make` 의 딸린 문서)

실행기(`python -m ozl.ops runner`)는 운영 화면에서 [만들기]를 누른 건을 화면 없는 Claude Code 로 띄워 `/ozl make <job_id>` 를 돌리는 프로그램이다. **지금 꺼져 있다**(`<자료 루트>/ops/runner.json` 이 없거나 `enabled` 가 참이 아니면 아무것도 하지 않는다). 켤지는 사용자가 정한다. 이 문서는 실행기가 띄운 세션이 지킬 가드와, 켤 때의 설정 예시를 둔다. 대화 세션에서 `/ozl make` 를 부를 때는 읽지 않아도 된다.

## 가드

환경 변수 `OZL_OPS_RUNNER=1` 이면 실행기가 띄운 것이다. 이때는 아래를 지킨다(`PY` 는 `SKILL.md` 와 같이 `.venv/bin/python` 이다).

- **Codex 를 부르지 않는다.** `codex`, `codex_smart.sh`, `codex exec`, `mm_request.py --surface codex`, `multimodel_request` 도구 모두 금지다. 실행기는 `multimodel_request` MCP 도구를 통째로 막는다(인자로 표면만 거를 수 없다).
- **다른 계열의 해석 점검을 보내지 않는다**(6단계). 검토 묶음까지 만들고 이슈를 '검토 대기'로 둔 채 끝낸다.
- 실행기는 명령의 `--disallowedTools` 로 다음을 막는다: 승인 명령, 철회 명령, 공개 내보내기 명령, `ozl.ops token`, `private/ops/` 읽기, 발행 목록(`issues/manifest.json`) 직접 쓰기, 번호 대장 직접 쓰기, 고정 사본(`issues/*/revisions/`) 직접 쓰기, 운영 파일(`ops/`) 직접 쓰기, 옛 카드와 클레임(`cards/`, `claims/`) 직접 쓰기, `approval.json` 과 `make_queue.json` 을 이름으로 가리키는 명령(`src/ozl/ops/runner.py` 의 `DISALLOWED`, `DESK_BLOCK`). 막힌 것을 돌아가려 하지 않는다.
- 사용자에게 묻지 않는다. 막히면 `PY -m ozl.ops queue set <job_id> --state 멈춤 --note "<까닭 한 줄>"` 하고 끝낸다.
- 쓰기는 `OZL_DESK_ROOT` 아래만 한다(없으면 `private/desk`). 코드, 설정, 문서, 스킬은 고치지 않는다.
- 대상은 늘 대기열 번호다. 고르기 기록(`find/board_view.py`)은 쓰지 않는다.
- **역할의 모델은 기본 배정 그대로다.** 경로표(`lanes.py route`)를 부르지 않는다. `.venv/bin/python -m ozl.issues roles --json` 은 실행기에서 경로표를 읽지 않고 기본 배정(쓰기, 고치기, 묶음은 Opus, 문장 대조는 Sonnet, 강도는 세션 값)을 `source: runner` 로 내고, 1차 대조(`precheck`)는 `null` 로 낸다. 실행기 세션 자체는 `runner.json` 의 `model`(Opus) 고정이다(Fable 자동화 금지). 워크플로 인자 `offload`, `packet_mode`, `review_mode` 의 시험 길도 쓰지 않는다. `offload.py` 는 실행기의 거부 규칙(`src/ozl/ops/runner.py` 의 `OFFLOAD_RULES`)이 막는다.

`SKILL.md` 0절의 나머지 가드(승인, 내림, 공개용 내보내기를 하지 않는다. 대기열 파일을 손으로 고치지 않는다. 다루지 않는 소재. 작성자는 스스로 검토하지 않는다)는 실행기에서도 그대로다.

## 실행기에서 다른 것

- 화면 없는 세션이라 워크플로 도구가 거부된다(승인 창을 띄울 수 없다). 2~5단계를 서브에이전트로 차례로 돌린다. 지어낸 소재의 시험에서 실행기는 이 길로 쓰기, 문장 대조 두 번, 고치기, 검토 묶음까지 14분에 마쳤다.
- 서브에이전트 도구가 없으면 2단계를 시작하지 않고 `.venv/bin/python -m ozl.ops queue set <job_id> --state 멈춤 --note "서브에이전트 도구 없음"` 하고 끝낸다.
- 6단계(다른 계열의 해석 점검)와 8단계의 승인 화면 확인을 하지 않는다. 검토 묶음까지 만들고 '검토 대기'로 끝낸다.

## 설정 예시

`<자료 루트>/ops/runner.json`(기본은 꺼짐):

```json
{"enabled": true, "timeout_min": 90, "model": "opus", "permission_mode": "acceptEdits",
 "allowed_tools": ["Bash(.venv/bin/python *)", "Bash(curl -s http://127.0.0.1:8765/api/topic/*)", "Bash(date *)",
                   "Read", "Edit", "Write", "<서브에이전트 도구 이름>", "WebFetch"]}
```

- 실행기는 저장소(`~/OZL`)에서 띄워지고 `allowed_tools` 를 그대로 `--allowedTools` 로 넘긴다(`src/ozl/ops/runner.py` 의 `build_cmd`). 지시서의 명령은 `.venv/bin/python -m …` 말고도 `.venv/bin/python - <<'EOF'`(기록 쓰기, 맹검 목록 뽑기)와 `.venv/bin/python -c`(출처 대장 조회)를 쓰므로 `Bash(.venv/bin/python -m ozl.*)` 처럼 좁게 쓰면 첫 기록 쓰기에서 막힌다. 지시서의 조각에는 `cd` 를 붙이지 않았다(허용 패턴 `Bash(.venv/bin/python *)` 은 `.venv/bin/python` 으로 시작하는 명령만 받는다). 실행기에는 `rm`, `ls`, `mkdir` 허용이 없으므로 파일 지우기, 목록 보기, 폴더 만들기도 파이썬 조각 안에서 한다.
- 거부 규칙(`--disallowedTools`)이 허용보다 앞서므로 넓은 파이썬 허용이 승인과 공개 내보내기를 열지는 않는다. 다만 `runner.py` 머리말이 적었듯 이 규칙은 명령을 돌려 쓰면 빠져나갈 수 있고, 마지막 방어는 사람이 하는 승인이다.
- `<서브에이전트 도구 이름>` 은 실행 환경에서 확인해 적는다. 이 칸이 틀리면 `SKILL.md` 2절의 마지막 줄대로 멈춘다.
- `allowed_tools` 에 `multimodel_request` MCP 도구와 `mm_request.py` 를 넣지 않는다(실행기는 해석 점검을 보내지 않는다. MCP 도구는 넣어도 실행기가 뺀다). `WebFetch` 는 `robots.txt` 와 기사 열람에 쓴다.
- 헤드리스로 실제 한 건을 돌려 멈추는 곳은 아직 확인하지 않았다. 처음 켤 때 `PY -m ozl.ops runner --once --dry-run` 으로 명령을 보고, 한 건을 지켜본다. 문장 대조 서브에이전트가 작성자와 다른 모델(기본 배정에서는 Sonnet)을 받는지도 그때 확인한다.
