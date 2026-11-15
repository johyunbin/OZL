# 운영 화면, 화제 엔진, 매시 수집

후보를 모으고 점수를 매기는 매시 수집, 그 결과로 후보 목록을 만드는 화제 엔진, 사용자가 고르고 승인하는 운영 화면의 규칙이다. 공통 규칙은 `CLAUDE.md` 에 있다.

## 지금 도는 것과 꺼진 것
- 돈다: 매시 수집 launchd `com.hyunbin.ozl-pulse`(매시 5분, `scripts/pulse_run.sh` 가 `python -m ozl.pulse run` 뒤에 `python -m ozl.signals run` 을 부른다. 모델 호출 없음)와 운영 서버 launchd `com.hyunbin.ozl-pulse-web`(`127.0.0.1:8765`).
- 두지 않는다: 모델이 도는 예약 루틴(사용자 결정 2026-11-15). 고르기와 만들기는 사용자가 `/ozl find`, `/ozl make` 를 손으로 부를 때만 돈다. 고르는 길은 둘이다(대화의 `/ozl find`, 운영 화면 `/pick` 의 [만들기]).
- 다른 예약 실행(Trading 의 것, `multi-model`, 그 밖의 `com.hyunbin.*`)은 건드리지 않는다.

## 수집이 읽는 파일의 저장 금지 시간
매시 :03 ~ :08 에는 아래 파일을 저장하지 않는다(반쯤 쓴 파일을 수집이 읽지 않게).
- 코드: `src/ozl/pulse/`, `src/ozl/signals/`, `src/ozl/research/`(수집이 부르는 모듈), `scripts/pulse_run.sh`
- 설정과 자료: `src/ozl/research/feeds.yaml`, `calendar.yaml`, `sources_ledger.yaml`, `src/ozl/signals/data/`
- 수집 자료: `private/pulse/` 아래 DB 와 출력(`pulse.db`, `engine.db`, `out/`)

## 운영 화면 (`src/ozl/ops/`)
- `python -m ozl.ops serve` 가 고르기(`/pick`), 게시 승인(`/approve`), 미리보기(`/preview/`), 운영 첫 화면(`/ops`)과 iOS 앱이 쓰는 옛 주소(`/`, `/deck`, `/api/*`)를 낸다. 서버는 `127.0.0.1`(또는 `::1`)에만 묶이고, 이 기기 밖에서는 `tailscale serve` 를 거쳐 닿는다. 사설망 이름은 문서에 적지 않는다.
- 운영 서버는 launchd 환경에서 돈다(PATH 가 터미널과 다르다). 서버가 부르는 바깥 도구는 PATH 에만 기대지 않게 짠다(`capture.find_pdftotext()` 가 그 예다). 이슈를 '게시 대기'로 올린 뒤에는 `/approve` 를 열어 그 건의 "점검" 줄을 본다. 터미널의 검사 통과가 승인 화면의 통과를 뜻하지 않는다. 코드를 고친 뒤에는 서버를 다시 띄워야 화면에 반영된다(`launchctl kickstart -k gui/$(id -u)/com.hyunbin.ozl-pulse-web`).
- 쓰기 요청(POST)은 로그인(토큰), Host와 Origin 검사, 요청 토큰, 본문 크기와 종류 검사를 모두 통과해야 한다. 이 기기 주소가 아닌 이름으로 들어온 읽기도 로그인이 필요하다. 설계와 남은 위험은 `private/plan/ops_spec_20261114.md` 3절, 9절, 16절, 코드가 생긴 뒤에는 코드가 정본이다.
- 로그인 토큰은 `private/ops/token` 에 있다. `python -m ozl.ops token --show` 만 토큰을 찍는다. 토큰을 문서, 로그, 외부 모델, 커밋에 넣지 않는다.
- 만들기 대기열(`<자료 루트>/ops/make_queue.json`)은 손으로 고치지 않는다. 늘 `python -m ozl.ops queue list|show|set` 으로 읽고 바꾼다(서버와 같은 잠금을 쓴다).
- 실행기 `python -m ozl.ops runner --once [--dry-run]` 는 대기열에서 한 건을 꺼내 화면 없는 Claude Code(Opus)로 `/ozl make` 를 띄운다. 설정 `<자료 루트>/ops/runner.json` 이 없거나 `enabled` 가 참이 아니면 돌지 않는다. 켜는 것은 사용자가 정한다. 처음 켤 때는 `--dry-run` 으로 명령을 보고 한 건을 지켜본다.
- 실행기가 띄운 세션은 Codex 를 부르지 않고, 승인, 철회, 공개 내보내기, `ozl.ops token`, `private/ops/` 읽기, 발행 목록과 번호 대장과 고정 사본과 운영 파일의 직접 쓰기가 막혀 있다. 막힌 것을 돌아가지 않는다.

## 화제 엔진 (`src/ozl/signals/`)
- 명령: `python -m ozl.signals run [--asof] [--out]`(밀린 매시 수집 시각을 따라잡아 계산하고 `board.json` 을 쓴다), `replay --from --to [--db] [--step runs|daily] [--reset]`(기간을 처음부터 다시 계산), `board`(계산 없이 `board.json` 만 다시 쓴다), `explain <이슈 번호>`(점수 내역).
- 수집 DB(`private/pulse/pulse.db`)는 읽기만 한다. 엔진이 쓰는 저장소는 `private/pulse/engine.db` 하나이고, 후보 목록은 `private/pulse/out/board.json` 이다.
- `replay` 는 기본으로 새 파일에 쓴다. 라이브 `engine.db` 를 바꾸려면 `--db private/pulse/engine.db --reset` 을 함께 줘야 하고, 그때 같은 폴더에 백업이 남는다.
- 점수는 후보의 순서를 정하는 데만 쓴다. 사실 여부와는 상관이 없다.
- `replay` 를 사본에 돌릴 때는 `--out` 으로 다른 경로를 준다. 주지 않으면 라이브 `board.json` 을 덮어쓴다.
- 같은 날 잇기(2026-11-15, `link.Linker.same_day`): 같은 날 한 일이 여러 이슈로 갈라지는 것을 줄인다. 이슈의 그날 중심 낱말(중심 고유명사는 매체 계열 2곳 이상이 쓴 이름과 첫 그룹의 이름, 중심 사건 낱말은 첫 그룹의 낱말뿐)과 견주어 (가) 드문 고유명사 + 사건 낱말 2개, (다) 같은 급상승어(낱말 전부 포함), (나) 드문 사건 낱말 2개(그룹에 드문 고유명사가 없을 때) 가운데 하나를 넘으면 잇는다. 드물다 = 앞 7일 동안 그 낱말이 나온 매체 계열 2곳 이하. 값은 `config.py` 의 `LINK_SAME_DAY*`, `LINK_RARE_*`.
  - 사건 낱말은 세 갈래 모두 그날 첫 그룹(씨앗)의 낱말과만 견준다. 뒤에 붙은 그룹의 낱말까지 견주면, 그 그룹을 매체 한 곳이 썼든 여러 곳이 썼든 딸려 들어온 낱말로 다른 일이 사슬처럼 이어진다. 그래서 씨앗과 사건 낱말 둘을 함께 갖지 않는 후속 기사는 같은 날 잇기로 붙지 않는다.
  - (나)와 (다)는 이름이 있는 서로 다른 주체에는 쓰지 않는다(그룹에 고유명사가 있고 이슈에 중심 고유명사가 있는데 그룹의 이름이 이슈의 그날 기사에 없을 때). 이름이 드문가와 따로 본다. 같은 주체로 보는 것은 같은 이름과, 긴 이름이 짧은 이름으로 시작하고 남는 꼬리가 `config.LINK_SAME_SUBJECT_TAILS` 의 법인·조직 접미(그룹, 홀딩스, 지주, 본사, 측, 쪽)인 이름뿐이다. 한 이름이 다른 이름에 들어 있다는 것만으로는 같은 주체가 아니다(앞에 글자가 붙은 이름, 꼬리가 업종 낱말인 이름은 다른 회사로 본다). 낱말 분석이 인물 이름을 다르게 자른 기사('이름'과 '이름 성')는 이 규칙으로 붙지 않는다.
  - (다)에서 그룹과 이슈 양쪽에 맞는 검색어가 여럿이면 그 가운데 조건을 채우는 것을 쓴다.
  - 그룹에 맞는 검색어가 하나라도 있으면 그 그룹은 제목과 이름이 겹치지 않는 그날 이슈도 같은 날 잇기로 만날 수 있다. 기준은 그날 이슈 전체를 보는 전수 검사이고, 실제로는 색인으로 같은 결과를 낸다: (다)의 후보는 그 검색어가 맞을 수 있는 기사를 가진 이슈(`trends.PairRule.seeds`, `Linker.key_issue`), (나)의 후보는 그룹의 드문 사건 낱말 둘 이상을 씨앗 낱말로 가진 이슈(`Linker.core_idx`)다. 검색어가 새 그룹에만 맞을 때도 (나)의 후보는 빠지지 않는다. 두 길의 결과가 같은지는 `tests/test_signals_sameday.py` 의 `test_trend_index_gives_the_same_links_as_scanning_every_issue_of_the_day` 가 본다.
  - 드문가의 판정에는 그 날의 확정 시각(다음 날 12:00)까지 받은 기사만 쓴다(`pipeline.rare_index`). 지난 날짜를 뒤늦게 계산해도 결과가 같다.
- 급상승어 잇기는 고유명사는 전부, 나머지 낱말은 절반 이상, 또는 띄어쓰기와 조사를 무시한 꼴이 기사 제목에 들어 있으면 낱말 조건을 채운다. 딸린 기사 조건은 그대로다. 같은 날 한 검색어가 두 이슈 이상에 맞으면 `merge_hints` 에 남는다.
- 민감 높음(RED)도 두 구역과 목록에 남는다. 줄에 `sensitivity` 와 `deck_blocked` 가 붙는다. 덱 선택을 막는 화면은 아직 없다(다음 묶음).
- `board.json` 후보의 `story`, `story_rank` 는 화제 점수와 따로 둔 '큰 이야기' 순서다(H 누적, 사흘 매체 계열 합, 사흘 급상승어 등급). 점수식은 바꾸지 않았다. 사람 판단으로 합친 이슈는 합쳐져 들어온 번호의 지난 줄도 넣어 센다(같은 날 같은 매체 계열은 한 번, 등급은 가장 큰 값). 순서는 반올림 전 값으로 정하고 판에는 소수 여섯 자리로 싣는다. `searches_unmatched` 에는 이어지지 않은 한국어 급상승어 가운데 검색량 표기가 있는 것이 딸린 기사 제목과 함께 들어 있다.
- 실제 자료 정답과 측정: `private/pulse/gold/real_pairs_*.yaml`, `private/pulse/gold/measure_real.py`(pairs, trends, story, find).

## 출처
- 피드 = `src/ozl/research/feeds.yaml`, 발표 일정 = `calendar.yaml`. 일정은 **공식 일정 페이지를 직접 열어 확인한 날짜만** 적는다(35일 지나면 재확인 표시가 뜬다).
- 매시 수집은 피드를 호스트별 줄로 나눠 서로 다른 호스트는 동시에, 같은 호스트 안에서는 차례로 2초 간격(앞 응답이 끝난 뒤부터)으로 부른다(`pulse.snapshot.fetch_all`, `HOST_GAP`). 피드 하나에 매시 한 번이고 재시도는 없다. 일일 데스크의 소재 후보 수집(`research.collect.collect`)도 같은 함수로 받는다(같은 줄, 같은 간격). 새 피드를 켜면 매시 요청 수와 가장 많은 호스트의 피드 수를 재서 적는다(2026-11-15 기준 82회, 연합뉴스 9개).
- 출처마다 수집과 점수 사용의 허용 여부는 출처 대장 `src/ozl/research/sources_ledger.yaml` 에 적고, 수집 코드는 대장에서 허용이 아닌 곳에 요청하지 않는다.
- `docs/sources.md` 는 `scripts/build_sources.py` 로 만든다. 피드, 일정, 출처 대장을 고치면 다시 돌린다. 쓰지 않는 도구와 소스는 적지 않는다.
