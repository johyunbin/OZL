# 소재 카드와 클레임 (덱의 재료, 옛 일일 데스크)

경제, 국제, 사회 뉴스에서 방송 소재를 골라 카드와 클레임(검증 기록)으로 적는 일의 규칙이다. 이슈 기록(`agent/issues.md`)과 따로 돈다. 공통 규칙은 `CLAUDE.md`, 덱은 `agent/deck.md`, 공개와 백업은 `agent/publish.md` 에 있다.

## 절차 (Phase 3 정본 · 2026-11-10)
- 절차의 정본 = `/syuka deck`(`.claude/skills/syuka/SKILL.md`. 소재 한 건을 카드와 클레임으로 적는 순서는 `.claude/skills/syuka/deck/01_card.md`)과 `skills/ozl/SKILL.md` 5절(덱 완성 절차). 화제 후보를 보고 고르는 일은 `/ozl find`(`.claude/skills/ozl/SKILL.md`)가 한다. 예약 루틴은 두지 않는다(사용자 결정 2026-11-15). 스킬은 사용자가 부를 때만 돈다. 정해진 때마다 돌던 옛 절차(`am`, `pm`, `weekly`)는 `skills/ozl/archive/` 에 보관했고 따라 하지 않는다. 옛 인자가 지금 가는 곳은 `skills/ozl/SKILL.md` 의 「옛 인자」 표에 있다. 그 절차의 규범이 이 문서다.
- 결정적 단계는 `python -m ozl.research …`(수집, 커버리지 대조, ID 발급, 검사, 렌더, Notion 속성, 원문 확보 `capture`, 기계 대조 `machine-verify`)와 `python -m ozl.render …`(덱 검사, 빌드, 검토 묶음 `bundle`, 진행 기록 `progress`)가 한다.
- 쌓인 일: `/ozl status`(옛 카드는 수만 한 줄로 보인다). 카드마다 보려면 `python -m ozl.research status`, 지난 카드를 표 한 장으로 보려면 `python -m ozl.research ledger`. 옛 카드의 '채택 대기'를 어떻게 할지는 사용자가 정한다.
- **사용자의 일은 소재 고르기와 공개 승인뿐이다.** `/syuka deck` 에 소재나 카드 번호를 주는 것이 통과다(검사와 독립 검증을 지난 카드는 스킬이 `pick` 으로 채택한다). 고른 뒤의 검증과 완성은 시스템이 하고, 어느 단계도 사용자에게 원문 대조나 확인을 요청하지 않는다(검증 시트는 할 일 목록이 아니라 기록이다). 사용자에게 묻는 것은 고르기에 관한 것뿐이다(지난 방송과 겹치는 소재나 민감 '주의' 소재를 그래도 만들지, 말할 시간).
- `human-verify`(사람 육안 대조 기록)와 `publish`(발행 승인)는 **사용자가 그렇게 말했을 때만** 실행한다. 모델이 스스로 올리지 않는다. 그렇다고 사용자에게 대조를 요청하지도 않는다 — `human-verify` 는 사용자가 스스로 대조했다고 말한 기록에만 쓴다.
- 카드 ID 는 `ids` 명령으로만 받는다(발급 대장 `private/desk/issued_ids.json` — 지운 번호도 재사용하지 않는다).
- 수치는 1차 출처를 직접 열어 본 것만 클레임으로 만들고, 작성한 세션과 다른 에이전트가 원문을 다시 열어 대조한다. 검색 요약만 본 값은 "확인 필요"로 리스크에 적는다.
- 피드와 발표 일정의 규칙은 `agent/ops.md` 의 「출처」에 있다.

## 검증 규칙 (정본 = `docs/methodology.md`)
- 모든 수치와 주장은 `claims/` YAML 레코드(출처 티어, checks, counter, human_verified, 새 기록은 기계 대조 묶음 `verification`).
- `verified` 의 표시는 둘이다(`cards.grade_label`·`badge_ko` 만 쓴다). **'확인'**(`GRADE_HUMAN`) = 원본성, 정확성, 해석 3차원 통과 + 사람이 원문과 눈으로 대조(`human_verified`). **「원문 일치」**(`GRADE_MACHINE`) = 사람 대조 없이 `machine_verify` 가 통과시킨 기록 — T1·T2 원문 사본을 프로그램이 받아 해시했고, `observed` 가 사본에 통째 대목으로 있으며, 쓴 쪽과 다른 재대조 에이전트가 같은 자리를 독립으로 찾았고, 맥락 칸이 맞는다. 카드 배지는 기록이 전부 사람 대조면 '확인', 기계 대조가 섞이면 「원문 일치」. 모델의 합의나 "맞다"는 서술은 등급을 올리지 않는다.
- 민감 소재: 전수 분석 전까지 임시 기준(국내 정당, 선거, 정치인 평가 제외 / 정책은 통계와 해외 비교로만 / 젠더, 종교, 지역 비하, 피해자 소재 제외 / 해외 정치, 지정학 허용).

## 카드와 공개 판정
- 카드와 클레임의 정본 = `private/desk/cards/<card_id>.yaml` · `private/desk/claims/<날짜>/…`(비공개). 정본은 `private/desk/` 의 카드와 클레임 파일 하나뿐이다. 공개 저장소, 사이트, Notion 은 거기서 한 방향으로 만든다. Notion 에서 거꾸로 받는 것은 `상태`뿐이다.
- 보고서는 두 벌 — **전체본** `private/daily/…`(모든 카드 · PDF 쌍)과 **발행본** `daily/…`(공개 · 공개 이력(승인, 철회)이 있는 회차에만 쓴다 — `report.keeps_public_page`. 승인된 카드만 전문, 승인 전 카드는 번호와 상태만).
- **공개 여부를 묻는 코드는 `cards.publishable()` 하나만 쓴다**: 승인이 참이고, 지금 클레임으로 다시 계산한 배지가 verified('확인', 「원문 일치」), 추정이며, 승인 때의 내용 지문이 지금과 같고, 「원문 일치」 기록은 저장한 사본으로 증거를 다시 검사해 맞을 때만 참. 승인 뒤에 카드나 클레임을 고치면 승인은 무효가 된다(다시 승인하거나 `withdraw`).
- 카드 YAML 에 새 칸을 더하지 않는 규칙은 `CLAUDE.md` 에 있다.

## Notion 미러 (소재 카드)
- 페이지 「OZL — 오늘의 즐길거리」 아래 DB 「OZL 소재 카드」(식별자와 속성 목록 = `private/notion.json`, 비공개). Notion 에 올리기와 상태 읽기는 사용자가 원할 때만 세션이 MCP(Notion 커넥터)로 한다(토큰 파일 없음. 속성은 `python -m ozl.research notion` 이 뽑는다). 스킬(`/ozl`, `/syuka`)은 Notion 에 올리지 않는다. Notion 은 `card_id`+`revision` 이벤트만 전달한다 — 카드의 정본은 `private/desk/cards/`, 공개분의 정본은 git 의 `daily/`·`claims/` 다. Notion 에서 사용자가 `상태`를 바꾸면 그것이 채택, 보류, 반려 결정이다.

## 파일 규약
- 일일 보고서 = 발행본 `daily/YYYY/MM/YYYY-MM-DD_{am,pm}.md`(공개. 공개 이력이 있는 회차만 — 없는 회차는 렌더가 쓰지 않고 남은 파일을 지운다)과 전체본 `private/daily/YYYY/MM/YYYY-MM-DD_{am,pm}.md`(비공개). 보고서를 정해진 때마다 만들지 않는다. 발행(`publish`)이 그 회차를 렌더하고, 전체본은 사용자가 원할 때 `python -m ozl.research render` 로 만든다. 주간 회차는 2026-11-13 에 멈췄다(주간 발행본을 쓰는 코드는 없다). 카드 ID 는 `YYYY-MM-DD-{am|pm|wk}-NN`(불변). 회차 칸은 번호의 한 부분으로 남아 있고 새 카드는 `am` 으로 받는다.
- 클레임 `claims/YYYY-MM-DD/<card_id>-cN.yaml`.
- 지난 카드를 찾는 길: 카드 원장 `private/desk/ledger.csv`(비공개. `python -m ozl.research ledger` 가 쓰고, 채택과 발행 시각은 카드의 `history` 에서 뽑는다)와 발행 카드 색인 `daily/index.json`(공개. 렌더가 함께 쓰고, `publishable()` 통과분만 싣는다). `scripts/build_site.py` 가 색인으로 사이트 「기록」 쪽을 만들고, 색인이 가리키는 카드 자리표가 발행본에 없으면 빌드를 실패시킨다. 카드 원본이 없는 기기에서는 색인을 다시 쓰지 않는다(예외로 멈춘다).
