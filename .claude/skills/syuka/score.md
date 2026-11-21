# /syuka score — 월요일에 지난 일요 생방송과 예측을 맞춰 본다 (본 세션용)

토요일에 고정한 예측(`/syuka predict`, `predict.md`)을 일요 생방송의 고유 사건과 짝지어 적중을 잰다. 재는 법의 정본은 `~/.claude/plans/system-reminder-you-are-unified-beacon.md` 7절이다. 코드는 `src/ozl/syuka/hits.py` 이고, 지어낸 입력의 시험과 11-15 소급 시험 자료로 경로를 확인했다.

자리표시: `PY` 는 `.venv/bin/python`. `<D>` 는 방송 날짜, `<W>` 는 `private/data/derived/syuka/predictions/<D>/`, `<S>` 는 `<W>/score/`, `<PID>` 는 `PY -m ozl.syuka predict list` 가 보여 주는 그 주의 예측 번호, `<LIVE>` 는 그 생방송의 영상 번호.

## 받는 것과 내는 것

- 받는 것: 방송 날짜(없으면 지난 일요일).
- 내는 것: 장부의 `broadcast_events`, `hit_judgments`, `weekly_metrics`, 적중 요약 한 장(md 와 PDF, `private/결과물/` 아래), 실행 기록 `<S>/RUNLOG.md`.
- 사용자가 하는 일: 없다. 결과를 읽는다.

## 지킬 것

- **판정에 끼지 않는다.** 후보를 고른 Claude(토요일 세션과 그 내용을 아는 이 세션)는 적중 판정을 하지 않는다. 판정은 두 다른 계열이 따로 하고, 갈리면 세 번째 계열이 중재한다. 이 세션은 명령을 부르고 결과를 장부에 싣기만 한다. 판정 결과를 손으로 고치지 않는다.
- **사건을 먼저 고정한다.** 사건 목록은 후보를 보지 않은 에이전트가 만든다. 사건 묶음을 고정한 뒤에 가림 묶음을 만든다. 사건을 다시 고정해야 하면 `--replace` 로 새 묶음을 만들고 판정을 처음부터 다시 받는다(앞 묶음과 판정은 장부에 남는다).
- **판정자에게는 사건 요약과 식별자만 준다.** 판정 레인에 보내는 것은 `score packet` 이 만든 `prompt_judge_*.txt`(같은 폴더의 `packet_*.json` 내용이 이미 들어 있다)와 `score finalize` 가 만든 `arbitrate_*.json`, `recheck_*.json` 뿐이다. 전사 원문, 영상 번호, 시각, 후보의 출처·순위·확신 여부·기준선 여부는 보내지 않는다. `score packet` 은 두 파일에 공개본 게이트(`scripts/publish_gate.py`)를 돌려, 전사와 겹치는 문구가 있으면 파일을 지우고 멈춘다. 그때는 사건 요약을 자기 말로 다시 쓰게 해 사건을 다시 고정한다.
- 전사 문장을 요약 PDF, 실행 기록, 장부의 사유 칸에 옮기지 않는다.
- 예약 작업을 만들지 않는다. 커밋과 푸시를 하지 않는다.

## 모델 배정

모델 이름을 이 문서에 적지 않는다. 단계마다 경로표를 불러 쓰고, 고른 모델과 강도를 실행 기록에 적는다.

| 단계 | 부르는 경로표 |
|---|---|
| 3판 토막과 사건 묶기(후보를 보지 않은 레인) | `python3 ~/.claude/scripts/lanes.py route --task read --chars <전사 글자 수>`(경로표에는 `longread` 가 없고 긴 읽기는 `read` 다) 의 맨 위 줄(외부 레인). 그 레인이 3판 검사를 통과하는 파일을 내지 못하면 같은 경로표의 claude 줄로 새 서브에이전트를 띄운다 |
| 가림 판정 둘 | `python3 ~/.claude/scripts/lanes.py route --task judge` 의 codex 줄과 gemini_web 줄 |
| 갈린 건의 중재 | 같은 경로표의 chatgpt 줄 |

- 경로표의 `--task`(judge, read)는 레인과 강도를 고르는 이름이고, `offload.py run` 의 `--task` 는 맡기는 일의 꼴이다. 판정과 중재는 `offload.py run --task verify`, 3판 추출과 사건 묶기는 `offload.py run --task longread`(구조가 필요하므로 `--expect json`)로 보낸다. 어느 쪽이든 `--caller ozl:syuka-score --lane <경로표가 고른 레인> --effort <강도>` 를 붙인다.
- 시작과 끝의 `get_usage` 값, `lane_budget.py` 의 한도를 실행 기록에 적는다. 계획 8절대로 채점 회차가 Claude 주간 2%를 넘을 것 같으면(특히 3판 추출을 Claude 서브에이전트로 넘길 때) 멈추고 사용자에게 알린다.

## 순서

### 0. 전사와 목록 확인

- 생방송 전사가 Trading 내보내기에 들어왔는지 본다. 목록을 갱신한다: `PY -m ozl.syuka catalog`(갱신 전에 `private/data/derived/syuka/syuka.db` 를 같은 폴더에 `syuka.db.bak_<타임코드>` 로 복사한다).
- `<LIVE>` 를 찾는다: `videos` 표에서 종류가 '생방송 전체'이고 올린 날이 `<D>` 인 영상. 전사가 없으면 채점하지 않는다. 실행 기록에 "판정 불가(전사 없음)"와 그 주 본편 제목으로 확인한 소재 목록만 적고 끝낸다.
- 생방송과 주중 본편의 대응표를 갱신한다: `PY -m ozl.analyze.catalog livemap`, 그다음 `PY -m ozl.analyze.live_align`. 결과가 0행이면 두 명령은 기존 파일을 그대로 두고 종료 코드 1로 멈춘다. 그때는 대응표 갱신 없이 다음 단계로 간다.

### 1. 3판 토막과 고유 사건 (후보를 보지 않은 레인)

- 작업 폴더는 예측 폴더와 따로 둔다: `<B>` = `private/data/derived/syuka/broadcasts/<D>/`. 사건을 만드는 레인에는 예측 파일, 후보 목록, `private/data/derived/syuka/predictions/` 아래 무엇도, 이 문서도 넘기지 않는다. 서브에이전트로 띄울 때는 "`private/data/derived/syuka/predictions/` 를 읽지 않는다, `<B>` 에만 쓴다"를 지시문 첫 줄에 적는다.
- 넘기는 것은 3판 지침(`private/data/derived/syuka/extract_guide_v3.md`), `PY -m ozl.syuka mark-v3 <LIVE>` 로 찍은 전사(`<B>/marked_<LIVE>.txt`), 그리고 아래 두 가지 산출 요청뿐이다. 외부 레인이 긴 전사를 한 번에 받지 못하면 6만 자 아래 조각으로 나눠 보내고, 조각의 토막 합치기도 같은 레인에 맡긴다.
  1. 3판 파일 `<B>/v3/<LIVE>.json`(지침의 꼴 그대로).
  2. 고유 사건 묶기 `<B>/grouping.json`: `{"merge": [[3,4], …], "minor": [7, …], "why": "한두 문장"}`. 같은 사건을 이어서 다룬 토막은 묶고, 몇 분 안 되는 짧은 언급은 minor 로 둔다.
- `PY -m ozl.syuka validate-v3 <B>/v3/<LIVE>.json` 이 통과할 때까지 같은 레인에게 오류 줄만 돌려주어 고치게 한다(두 번 돌려도 걸리면 경로표의 claude 줄로 넘긴다). 통과하면 `PY -m ozl.syuka load-v3 <B>/v3`.
- 사건을 고정한다. `grouping.json` 의 값을 그대로 옮긴다(이 세션이 바꾸지 않는다):

```bash
.venv/bin/python -m ozl.syuka score events <PID> --from-v3 <LIVE> --merge 3,4 --minor 7
```

- `score events` 는 그때의 3판 원본을 장부에 따로 보존한다(`load-v3` 가 나중에 같은 영상의 토막을 바꿔도 판정 장부의 사건은 그대로다).
- 3판 경로가 두 레인 모두에서 막히면 11-15 소급 시험의 방식으로 대신한다: 경로표 `--task longread` 의 외부 레인에 전사를 6만 자 아래 조각으로 나눠 사건 요약을 받고, 조각 경계의 병합도 같은 외부 레인에 맡긴 뒤(`private/data/derived/syuka/retro/2026-11-15/work/prompt_events_*.txt`, `prompt_events_merge.txt` 가 본), `score events <PID> --from-json <B>/events_merged.json`. 이 세션이 사건을 합치거나 고치지 않는다. 어느 길로 했는지 실행 기록에 적는다.

### 2. 가림 묶음과 두 판정

```bash
.venv/bin/python -m ozl.syuka score packet <PID> --out private/data/derived/syuka/predictions/<D>/score --clusters private/data/derived/syuka/predictions/<D>/work/codex_cluster.json
```

- 두 판정자에게 같은 `prompt_judge_<PID>_<ES>.txt` 하나만 따로 보낸다(`offload.py run --task verify --lane <레인> --prompt-file <S>/prompt_judge_<PID>_<ES>.txt --out … --expect json`, `--in` 은 주지 않는다). 서로의 답을 보여 주지 않는다. 답은 `<S>/judge_codex.json`, `<S>/judge_gemini.json` 에 받는다(`--expect json`).
- 장부에 싣는다:

```bash
.venv/bin/python -m ozl.syuka score judge <PID> --judge codex private/data/derived/syuka/predictions/<D>/score/judge_codex.json
```

```bash
.venv/bin/python -m ozl.syuka score judge <PID> --judge gemini private/data/derived/syuka/predictions/<D>/score/judge_gemini.json
```

- 검사에 걸리면(빠진 후보, 없는 사건 번호) 그 판정자에게 오류 줄만 돌려주고 다시 받는다. 다시 받은 횟수를 기록한다.

### 3. 확정과 중재

```bash
.venv/bin/python -m ozl.syuka score finalize <PID> --out private/data/derived/syuka/predictions/<D>/score
```

- 종료 코드 2 는 두 판정이 갈렸다는 뜻이다. 만들어진 `arbitrate_<PID>_<ES>.json` 만 중재 레인에 보내 갈린 건마다 하나의 판정을 받고(`<S>/judge_chatgpt.json`), `score judge <PID> --judge chatgpt …` 뒤에 `finalize` 를 다시 부른다.
- 중재를 그날 받지 못하면 `finalize --provisional` 로 속보판을 남기고(갈린 건은 0으로 센다), 중재를 받은 뒤 다시 확정한다.
- 두 판정이 모두 적중이라고 한 건의 재확인 표본은 `finalize --out` 이 코드로 하나 골라 `recheck_<PID>_<ES>.json`(중재 묶음과 같은 가림 꼴)으로 쓴다. 이 세션이 고르지 않는다. 그 파일만 중재 레인에 보내고, 결과는 실행 기록에만 적고 장부의 판정을 바꾸지 않는다(판정자가 둘 다 너그러운지 보는 표본이다).

### 4. 결과 보기와 요약

```bash
.venv/bin/python -m ozl.syuka hits <PID>
```

- 요약 한 장(md 와 PDF, `private/결과물/` 아래 새 번호 폴더, 첫 쪽 그림 확인)에 넣는 것: 사건 표(번호, 갈래, 분, 사건 이름, 후보·기준선 A·B 의 적중을 '같은 사건'과 '인접(0.5)'으로 나눠), 지표(같은 사건 건수와 인접 건수를 따로 적은 재현율, 확신 3건 정밀도, 기준선과의 건수 차와 배수, 시사·중간·상시별 분자와 분모, 주중 본편 부가 지표), 판정 일치율과 중재 건, 놓친 사건이 후보 풀에 있었는지(후보 목록의 제목 낱말 검색이라고 밝힌다).
- 사건 이름은 장부의 요약이고 전사 문장이 아니다. 그래도 요약에 옮길 때는 자기 말로 줄인다.
- 소급 시험(`kind=retro`)의 결과는 같은 표에 섞지 않는다. `hits` 는 소급 시험을 `--include-retro` 일 때만 따로 묶어 보인다.
- 통계 단위는 방송이다. 몇 주가 쌓이기 전에는 방송별 결과를 그대로 보이고 평균으로 결론을 내지 않는다.
- **관점 일치.** 뼈대 3건 가운데 적중한 이야기만 본다. 그 뼈대의 중심 질문과 짝지어진 사건의 요약만 중재 레인에 보내 같은 질문을 다뤘는지(같음, 일부, 다름)를 받고, "적중한 뼈대 n건 가운데 평가 가능 m건"과 함께 요약에 적는다. 이 판정도 이 세션이 하지 않는다. 적중한 뼈대가 없으면 "평가 없음"으로 적는다.
