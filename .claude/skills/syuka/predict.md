# /syuka predict — 토요일에 그 주 일요 생방송의 예측을 고정한다 (본 세션용)

일요 생방송이 다룰 이야기를 방송 전에 골라 한 파일로 고정하고 해시를 남긴다. 고정한 파일은 고치지 않는다. 월요일의 채점은 `score.md`(`/syuka score`)다. 계획의 정본은 `~/.claude/plans/system-reminder-you-are-unified-beacon.md` 의 6절 P1, 7절, 8절이다. 첫 실제 회차는 `private/data/derived/syuka/predictions/2026-11-22/`(손으로 고정한 판, 해시 `2d81feb0…5fc43`)이고, 같은 꼴로 한다.

자리표시: `PY` 는 `.venv/bin/python`(저장소에서 부른다). `<D>` 는 방송 날짜(`YYYY-MM-DD`), `<W>` 는 작업 폴더 `private/data/derived/syuka/predictions/<D>/`.

## 받는 것과 내는 것

- 받는 것: 방송 날짜(없으면 다음 일요일). 있으면 사용자가 꼭 넣거나 빼라고 한 이야기.
- 내는 것: `<W>/prediction_<타임코드>_fixed.json`(후보 15, 확신 3, 뼈대 3, 기준선 A·B), `<W>/HASH.txt` 한 줄, 장부 등록(`predictions`, `prediction_items`), 한 장 요약 PDF(`private/결과물/` 아래), 실행 기록 `<W>/RUNLOG.md`.
- 사용자가 하는 일: 해시 한 줄을 따로 보관하는 것뿐이다. 고르기는 사용자가 원할 때만 묻는다.

## 하지 않는 것

- 방송이 시작된 뒤에 고정하지 않는다. `predict fix` 는 방송 시각 뒤의 고정을 거부한다. 방송 뒤에 만든 것은 소급 시험이고 공식 기록에 넣지 않는다.
- 고정한 파일을 고치지 않는다. 고칠 일이 생기면 새 초안으로 `predict fix --revises <PID>` 를 다시 부른다(새 파일이 생기고 앞 파일은 그대로 남는다).
- 전사 문장을 후보, 관점, 뼈대에 옮기지 않는다. 최근 제목 목록은 공개 정보(영상 제목)다.
- 예약 작업을 만들지 않는다. 커밋과 푸시를 하지 않는다.
- 이 세션(후보를 고른 Claude)은 방송 뒤의 적중 판정에 끼지 않는다.

## 모델 배정

모델 이름을 이 문서에 적지 않는다. 단계마다 경로표를 불러 첫 줄(맨 위 레인)을 쓰고, 그 레인이 막히면 다음 줄로 내려간다. 고른 모델과 강도는 실행 기록에 적는다.

| 단계 | 부르는 경로표 |
|---|---|
| 후보 묶기, 상위 30건의 관점과 "왜 지금" | `python3 ~/.claude/scripts/lanes.py route --task extract --chars <입력 글자 수>` |
| 고정 전 반박 | `python3 ~/.claude/scripts/lanes.py route --task verify --author-family anthropic` 의 chatgpt 줄(계획 9절). 그 레인이 막히면 같은 경로표의 다른 비-Anthropic 줄 |
| 15건 선정, 확신 3건, 뼈대 3건 | 본 세션(Claude). 난도가 높다고 보면 `lanes.py route --task judge` 의 claude 줄을 따른다 |

- 외부 레인에는 `~/.claude/scripts/offload.py run` 으로만 보낸다(`--caller ozl:syuka-predict`). 보내는 것은 후보 목록(기사 제목과 엔진 수치), 최근 8주 영상 제목, 지시문뿐이다. 전사와 슬라이드 문구는 보내지 않는다.
- 맡기기 전에 `python3 ~/.claude/scripts/lane_budget.py` 로 한도를 본다. 시작할 때와 끝날 때 `get_usage` 값을 실행 기록에 적는다. 계획 8절대로, 이 회차가 Claude 주간 2%를 넘을 것 같으면 멈추고 사용자에게 알린다.

## 순서

### 1. 판 고정과 입력 만들기 (코드)

```bash
mkdir -p private/data/derived/syuka/predictions/<D>/input private/data/derived/syuka/predictions/<D>/work
```

```bash
.venv/bin/python -m ozl.signals board --out private/data/derived/syuka/predictions/<D>/input/board_<타임코드>.json
```

- 매시 :03~:08 에는 돌리지 않는다(`agent/ops.md`). 판은 운영 판을 덮지 않게 `--out` 으로 작업 폴더에 쓴다.
- 압축 후보 목록과 최근 8주 제목을 만든다: `PY -m ozl.syuka predict prepare <W>/input/board_<타임코드>.json --out <W>/input`(만들어지는 파일: `candidates_compact.json`, `recent_titles_8w.txt`). 이 명령이 아직 없으면 P0-가 의 같은 이름 파일 꼴을 따라 만든다.

### 2. 후보 묶기와 관점 (외부 레인)

- 계획 8절은 중복 묶기를 코드 몫으로 적었지만 지금 코드에는 이야기 묶기가 없어, P0-가 처럼 이 단계의 외부 레인이 묶음(`clusters`)까지 낸다. 기준선 A·B 는 그 묶음으로 중복을 지운다. 묶기를 코드로 옮기면 이 줄을 고친다.

- 지시문은 `private/data/derived/syuka/predictions/2026-11-22/input/prompt_codex_cluster.txt` 를 본으로 날짜, 판 번호, 건수만 바꿔 `<W>/input/prompt_codex_cluster.txt` 에 쓴다. 산출 꼴(`stories` 30건과 `clusters`)을 바꾸지 않는다.
- `python3 ~/.claude/scripts/offload.py run --task extract --caller ozl:syuka-predict --prompt-file <W>/input/prompt_codex_cluster.txt --in <W>/input/candidates_compact.json <W>/input/recent_titles_8w.txt --out <W>/work/codex_cluster.json --expect json`
- 결과의 근거 id 가 후보 목록에 있는지 코드로 확인한다(없는 id 를 쓴 이야기는 버린다).

### 3. 기준선 A·B (코드)

- `PY -m ozl.syuka predict baselines <W>/input/board_<타임코드>.json --clusters <W>/work/codex_cluster.json --out <W>/work/baselines.json`
- 규칙(바꾸지 않는다): A = 엔진 `story_rank` 오름차순(동률은 `score` 내림차순), 묶음으로 중복 제거, 상위 15 이야기. B = A 와 같되 분야가 경제·국제·과학기술이고 `deck_blocked` 가 거짓인 후보만.

### 4. 선정 (본 세션)

- `codex_cluster.json` 의 30건에서 15건을 고르고, 그중 확신 3건과 뼈대 3건(중심 질문, 단계 순서, 1차 자료의 자리)을 정한다. 고르는 기준은 채널의 소재 성격(경제·국제·기업·제도·이색 해외 소식), 시사성, 지난 방송과의 겹침(`후속` 은 살리고 `이미 다룸` 은 새 국면이 있을 때만)이다. 적합도 점수(`PY -m ozl.syuka hits --profile`)는 참고만 한다. 표본이 적은 동안은 순위를 그것으로 정하지 않는다.
- 초안은 P0-가 고정 파일과 같은 칸으로 `<W>/work/selection_draft.json` 에 쓴다: `schema`, `broadcast`(예: `"2026-11-29 (일) 20:20 KST 슈카월드 일요 생방송"`), `input`(판 파일과 해시, `calc_id`, `codex_cluster_sha256` 등), `picks`, `confident`, `skeletons`, `baselines`(A·B 와 `detail`), `scoring_rule`, `process`, `note`. `fixed_at` 은 비워 둔다(고정 명령이 채운다).

### 5. 고정 전 반박 (외부 레인, 한 번)

- 초안과 30건 목록만 보내 반박을 받는다(지시문 본: `private/data/derived/syuka/predictions/2026-11-22/work/prompt_rebut.txt`). `offload.py run --task verify --lane chatgpt --caller ozl:syuka-predict --author-family anthropic … --out <W>/work/rebut.json --expect json`.
- 받아들인 것과 받아들이지 않은 것을 까닭과 함께 초안의 `process.rebuttal_accepted`, `rebuttal_rejected` 에 적는다. 반박을 받지 못하면 그 사실을 `process` 에 적고 고정한다(방송 전 고정이 반박보다 먼저다).

### 6. 고정과 장부 등록 (코드)

```bash
.venv/bin/python -m ozl.syuka predict fix private/data/derived/syuka/predictions/<D>/work/selection_draft.json --date <D>
```

```bash
.venv/bin/python -m ozl.syuka predict verify
```

- `fix` 는 새 파일을 쓰고 읽기 전용으로 바꾼 뒤 `HASH.txt` 에 한 줄을 더하고 장부에 싣는다. 검사에 걸리면 파일을 쓰지 않으니 초안을 고쳐 다시 부른다.
- `verify` 가 모두 `일치` 여야 끝난다.

### 7. 사용자에게 보이기

- 한 장 요약(후보 15의 이름과 분야, 확신 3, 뼈대 3의 중심 질문, 기준선 A·B 의 이름, 해시 전체)을 md 와 PDF 쌍으로 `private/결과물/` 아래 새 번호 폴더에 둔다(`~/.claude/knowledge/md2pdf_authoring.md`). 첫 쪽을 그림으로 열어 확인한다.
- 사용자에게 해시 한 줄을 따로 보관해 달라고 그 자리에서 한 번 요청한다.
- `<W>/RUNLOG.md` 에 단계마다 시각, 모델과 강도, 입력 글자 수, 걸린 시간, 재시도, `get_usage` 앞뒤 값을 적는다. 다른 세션이 같은 한도를 쓰므로 한도 차이는 추정이라고 적는다.
