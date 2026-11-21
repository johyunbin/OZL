# OZL 작업영역 지침 (길 안내와 공통 규칙 · 전역 지침은 도구마다 따로 읽힌다: Claude Code 는 `~/.claude/CLAUDE.md`, Codex 는 `~/.codex/AGENTS.md`, Antigravity 는 `~/.gemini/AGENTS.md`(정본 `~/.claude/ANTIGRAVITY.md`))

이름은 **OZL — 오늘의 즐길거리**. 문서 첫머리에 구호를 붙이지 않고, 무엇을 하는 곳인지 한두 문장으로 적는다(README 첫 문단이 기준).

이 문서는 길 안내와 어느 일에서든 지킬 규칙만 둔다. 일마다의 세부 규칙은 `agent/` 에 있다. **`agent/` 파일은 자동으로 읽히지 않는다. 아래 표에서 해당하는 일을 하기 전에 그 파일을 읽는다.** 어느 일에서든 지킬 무거운 규칙은 요지를 이 문서에 두고 세부는 `agent/` 에 둔다. 두 곳의 문장이 어긋나면 이 문서를 따르고 `agent/` 쪽을 고친다.

## 진입 순서
1. 이 문서 → `README.md` → `docs/how-it-works.md`(일의 흐름, 자동과 사람의 경계) → 하려는 일의 `agent/` 파일 → 그 일의 정본 문서(표의 끝 칸).
2. 지금 진행 중인 일과 사용자가 정할 것은 `private/records/plan/재정비_진행판_20261114.md` 에 있다. 사용자의 요청을 항목으로 만든 목록은 같은 폴더의 `요청_등록부_20261114.md`, 한 일의 기록은 `재정비_조치기록_20261114.md` 다. 사용자가 여는 결과물은 `결과물/`(비공개 폴더로 가는 링크)에 모은다. 앞선 계획 문서(`ozl_plan_20261109_164333.md`, `ozl_tidy_plan_20261110_164038.md`, `ozl_redesign_plan_20261113_014132.md`, `ozl_service_plan_20261114_022800.md`)는 `~/.claude/plans/archive/` 에 있다. 2026-11-14 의 서비스 기획안으로 만든 이슈 화면과 카드는 같은 날 사용자가 반려했다. 아래 표의 이슈 기록 절차(`/ozl make`)는 같은 날 정한 글 형식(읽는 글 `article.yaml` 과 뒤쪽 검증 기록, 명세 `private/records/plan/글형식_명세_20261114.md`)에 맞춰 고쳤다.
3. 지금 쌓인 일: `/ozl status`(만들기 대기열, 이슈 기록의 상태, 최근 고르기 기록, 옛 소재 카드 수를 모아 보인다). 명령으로 따로 볼 때는 `.venv/bin/python -m ozl.ops queue list`, `.venv/bin/python -m ozl.issues status`, `.venv/bin/python -m ozl.research status`.

| 하려는 일 | 먼저 읽을 파일 | 정본 |
|---|---|---|
| 화제 고르기와 이슈 글 만들기(`/ozl find`, `/ozl make`) | `agent/issues.md` | `docs/issue-brief.md`, `.claude/skills/ozl/SKILL.md`, `src/ozl/issues/` |
| 운영 화면, 화제 엔진, 매시 수집 | `agent/ops.md` | `src/ozl/ops/`, `src/ozl/signals/`, `src/ozl/pulse/` |
| 웹(`apps/web`)과 iOS 앱(`apps/ios`) | `agent/web.md` | `apps/web/README.md`, `apps/web/DESIGN.md` |
| 슈카 자료(영상 받기, 다글로 전사, Whisper, 슬라이드 분석)와 덱(`/syuka find`, `/syuka deck`, `/syuka ad`) | `agent/deck.md` | `.claude/skills/syuka/`, `skills/ozl/SKILL.md` §5, `src/ozl/render/` |
| 소재 카드와 클레임(덱의 재료) | `agent/desk.md` | `.claude/skills/syuka/deck/01_card.md`, `docs/methodology.md` |
| 공개, 커밋, 푸시, 백업 | `agent/publish.md` | `scripts/publish_gate.py`, `scripts/push_delegated.sh` |
| 공개 문서 쓰기(README, `docs/`, 웹 글) | `agent/publish.md` 의 「공개 문서 문체」 | `scripts/style_check.py` |

## 어느 일에서든 지키는 규칙

**공개와 비공개의 경계** (사용자 결정 2026-11-09, 세부는 `agent/publish.md`)
- 비공개(`private/`, gitignore): 원본 영상, 오디오, 전사 전문, 추출 프레임, **슬라이드 문구(문자 인식 결과)**, 원시 메타(API 정책), PPT 초안, 계획과 검토 원문, 실제 이슈 기록(`private/records/desk/issues/`). 전사 전문과 슬라이드 문구는 어떤 형태로도 공개하거나 제3자에게 공유하지 않는다(집계만). 사용자의 구독 모델 레인에 보내는 것은 2026-11-17 사용자 결정으로 허용한 예외다(아래 「모델과 자동 실행」). 코드와 테스트의 예시 문장도 지어낸 것만 쓴다.
- 공개 산출물은 **공개본 추출 게이트**(`scripts/publish_gate.py`)를 통과한 것만 커밋한다.
- 옛 소재 카드의 공개 여부를 묻는 코드는 `cards.publishable()` 하나만 쓴다(세부 `agent/desk.md`).
- `private/` 는 `scripts/backup_private.sh` 로만 비공개 원격에 올린다. 원문 사본(`private/records/desk/captures/` 와 이슈의 `captures/`)은 백업 밖이다(세부 `agent/publish.md`).

**사람이 하는 일과 하지 않는 일**
- 사용자의 일은 고르기(대화의 `/ozl find` 에서 고르기와 버리기와 직접 넣기, 운영 화면의 [만들기]와 [버리기], 덱으로 만들 소재 정하기, 옛 소재 카드의 통과와 폐기)와 공개 승인뿐이다. 그 사이의 검증과 완성은 시스템이 하고, 어느 단계도 사용자에게 원문 대조나 확인을 요청하지 않는다.
- 옛 소재 카드의 발행 승인(`python -m ozl.research publish`)과 사람 대조 기록(`python -m ozl.research human-verify`)은 **사용자가 그렇게 말했을 때만** 실행한다. 모델이 스스로 하지 않는다. `human-verify` 는 사용자가 스스로 대조했다고 말한 기록에만 쓴다.
- 이슈 기록의 승인(`python -m ozl.issues approve`), 내림(`withdraw`), 공개용 내보내기(`export --public`)는 **모델이 실행하지 않는다.** 사용자가 운영 화면 `/approve` 에서 한다(실행기 세션에서는 명령 자체가 막혀 있다). 시험 자료 루트의 지어낸 이슈로 하는 시험만 예외다.
- 모델 여럿이 합의했다거나 "맞다"고 서술한 것은 등급이나 판정을 올리지 않는다.

**문장 대조의 기준** (덱과 이슈 기록 공통. 이슈 기록의 판정과 문장 원칙은 `.claude/skills/ozl/make/principles.md`)
- 화면 글과 말로 할 문장의 사실 주장은 그 쪽이 인용한 기록의 `text`·`observed` 로 받쳐져야 한다. 반론 칸(`counter`)에만 있는 내용은 화면에 쓰지 않고 노트에 둔다. "보도에 없다" 같은 부재 주장은 "읽은 보도(매체 이름)에서 찾지 못했다"로 범위를 밝힌다. 대조를 맡길 때 이 기준을 프롬프트에 그대로 적는다(적지 않은 대조는 반론 칸을 근거로 인정하고 넘어갔다).

**커밋과 푸시** (세부는 `agent/publish.md`)
- 스킬(`/ozl`, `/syuka`)은 커밋과 푸시를 하지 않는다. 예약 루틴에 주었던 `daily/`, `docs/`, `claims/` 한정 자동 커밋과 푸시 위임은 루틴을 두지 않으므로 쓸 곳이 없다. 코드, 설정, `tracks/`, `src/` 는 수동 승인.
- 사용자가 공개를 지시한 카드의 푸시(`daily/`, `docs/`, `claims/`)는 **`scripts/push_delegated.sh` 로만** 한다. 코드와 설정 커밋은 **사용자가 푸시하라고 말한 뒤에만** `git push origin main` 으로 올린다.

**모델과 자동 실행**
- 예약 루틴은 두지 않는다(사용자 결정 2026-11-15). 필요할 때 스킬(`/ozl find`, `/ozl make`, `/ozl status`, `/syuka find`, `/syuka deck`, `/syuka ad`)을 손으로 부른다. 매시 수집(launchd `com.hyunbin.ozl-pulse`)은 그대로 돈다(모델을 부르지 않는다. 화제 발굴이 며칠 치 자료를 쓴다. 끌지는 사용자가 정한다).
- [만들기] 실행기(`python -m ozl.ops runner`)는 꺼져 있다. 켜는 것은 사용자가 정한다. 실행기가 띄우는 세션은 **Claude Opus 고정**(Fable 자동화 금지)이고, 실행기에서 **Codex 호출 금지**(Codex 는 사용자가 지시한 대화 세션에서만 쓴다).
- 다글로 제출(동시 1건, 간격 60초 이상, 일일 상한, 402와 429 에서 바로 중단), Whisper(`nice -n 19`, 1프로세스), yt-dlp(sleep 간격) 규칙은 `agent/deck.md` 의 「영상 자료 받기」에 있다. 전사나 영상을 받는 일이면 어느 작업에서든 먼저 읽는다.
- 외부 모델에 보내도 되는 것: 전사, 슬라이드 문구, 원문 사본 전체, 광고주 제공 자료는 읽기, 추출, 종합 목적이면 사용자의 구독 모델 레인(Codex, Gemini, ChatGPT)에 `~/.claude/scripts/offload.py` 로만 보낼 수 있다(사용자 결정 2026-11-17: 사적인 저장소와 자기 구독 레인 사이의 전달이고, 긴 원문을 Claude 가 직접 읽는 토큰을 줄이기 위해서다). 각 스킬이 정한 다른 계열 검증 단계의 창구에는 원자료를 보내지 않고, 그 단계가 외부 제공을 허용한 검토 묶음(예: 이슈 기록의 `packet_<꼬리>.md`, `agent/issues.md` 의 제한을 지킨 것)만 보낸다. 기준과 명령은 `~/.claude/knowledge/multimodel/offload.md` 이고, 맡기기 전에 `python3 ~/.claude/scripts/lane_budget.py` 로 주간 한도·리셋·초기화권을 본다. 오프로드 결과는 읽기와 1차 정리로만 쓰며 각 스킬의 검증 단계를 대신하지 않는다. 실행기(`OZL_OPS_RUNNER=1`)에서는 오프로드를 쓰지 않는다(위의 Codex 호출 금지 때문이다).
- 구독 레인 밖의 예외는 하나다. 매주 새 본편의 그림 종류 라벨은 슬라이드 대표 화면만 OpenAI API(gpt-6.1-terra)로 보내 붙인다(사용자 결정 2026-11-21, 주 약 500장에 약 0.5달러로 어림). 명령은 `python -m ozl.analyze.picture_label run --missing` 이고, 키는 환경 변수로만 넘기고 출력하지 않는다. 전사와 슬라이드 문구는 이 경로로 보내지 않는다. 이 명령은 새 편의 `slide_dense`, `slide_structure --only <편>`, `slide_db load --only <편>` 다음에 돈다.
- 외부 모델에 보내지 않는 것: 계정 정보, 일반인을 알아볼 수 있는 정보, 공개 제외로 정한 내용, 인증과 수집(스크래핑) 코드(다글로 인증은 `~/Trading` 모듈이 관리 — 호출만). 전역 cyber 가드와 같다. 외부 모델에 보내는 것과 공개물에 옮기는 것은 별개의 규칙이다: 전사 문장과 슬라이드 문구는 오프로드 결과에서 왔더라도 공개 산출물에 옮기지 않는다.

**파일**
- 매시 :03 ~ :08 에는 매시 수집(launchd `com.hyunbin.ozl-pulse`, 매시 5분)이 읽는 파일을 저장하지 않는다. 목록은 `agent/ops.md`.
- 카드 ID(`python -m ozl.research ids`)와 이슈, 근거, 주장의 번호(`python -m ozl.issues ids`)는 명령으로만 받는다. 발급 대장은 지운 번호도 다시 쓰지 않는다.
- 카드 YAML 에 새 칸을 더하지 않는다. 승인이 카드 내용 전체의 지문에 묶여 있어서 칸 하나만 더해도 발행한 카드의 승인이 풀린다. 필요한 값은 이미 있는 `topic`, `category`, `history` 에서 꺼낸다.
- 산출물 이름에는 타임코드 `_YYYYMMDD_HHMMSS` 를 붙이고 버전 넘버를 쓰지 않는다. 사용자 열람용 md 는 PDF 쌍(전역 규칙).

**공개 문서 문체의 요지** (전문은 `agent/publish.md`)
- 한 일을 적고 꾸미는 말을 뺀다. 구호, 이모지, 가운뎃점으로 명사를 길게 잇는 나열, 근거 없는 형용사를 쓰지 않는다.
- 구현된 것만 현재형으로 쓰고, 자동으로 한 일과 사람이 한 일을 섞지 않는다. 모델을 쓴 사실은 숨기지 않는다.
- 승인 전 카드나 이슈의 제목과 소재를 공개 문서에 적지 않는다(번호와 분야까지만).

**수익화**: SNS, 영상, 광고 수익화는 슈카 지원 맥락과 겹치므로 지원이 끝날 때까지 다루지 않는다.
