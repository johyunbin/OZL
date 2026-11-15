"""경로, 환경 변수, 임계값 상수, 사전 판 해시. 숫자 임계값은 이 파일에만 둔다(설계 문서와 같은 값)."""
from __future__ import annotations

import hashlib
import os
import pathlib
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
KST = timezone(timedelta(hours=9))
UTC = timezone.utc

DATA_FILES = ("stop_terms.txt", "broad_entities.yaml", "en_common.txt",
              "categories.yaml", "indirect.yaml", "outlet_family.yaml", "not_entities.txt", "seo_nouns.txt")
# 낱말 분석 규칙의 판(text.py 의 코드가 같은 제목에서 다른 낱말을 내게 바뀌면 올린다). dict_version() 에 들어가므로
# 올리면 저장된 분석을 다시 한다. 2 = 두 어절 별칭 붙임에서 붙인 꼴 전체의 조사를 뗀 꼴도 본다(2026-11-15).
TEXT_RULES_VER = "2"

# ── 중복 제거(§2)
COPY_TITLE_DICE = 0.90          # (가) 제목 Dice
COPY_TITLE_HOURS = 12           # (가) 발행 시각 차
COPY_SUMMARY_DICE = 0.75        # (나) 요약 Dice
COPY_SUMMARY_TITLE_DICE = 0.40  # (나) 제목 Dice
COPY_SUMMARY_HOURS = 24         # (나) 발행 시각 차
COPY_SUMMARY_MINLEN = 40        # (나) 두 요약 모두 이 길이 이상
SUMMARY_HEAD = 150              # 요약 비교에 쓰는 앞부분 길이
OLD_ITEM_HOURS = 72             # 발행 시각이 받은 시각보다 이만큼 넘게 앞서면 옛 항목

# ── 1단계 그룹(§4-1)
G_E2_S = 0.30     # E ≥ 2 이고 S ≥ 이 값
G_E1_S = 0.53     # E ≥ 1 이고 S ≥ 이 값(설계 0.55 → 2026-11-14 실제 표본 100쌍 반영)
G_E0_S = 0.63     # S ≥ 이 값 이고 T ≤ G_E0_T(설계 0.65 → 같은 까닭)
G_E0_T = 24

# ── 2단계 이슈 잇기(§4-2)
LINK_GAP_DAYS = 3        # 이 날 수 이하면 가까운 이슈
LINK_WINDOW_DAYS = 7     # 프로필을 만드는 기간
LINK_TITLES = 20         # 프로필에 두는 그룹 대표 제목 수
LINK_MIN_FAMILIES = 2    # 프로필 낱말이 나와야 하는 계열 수
LINK_NEAR_E2_S = 0.30    # gap ≤ 3: Ee ≥ 2 이고 (Et ≥ 1 또는 S* ≥ 이 값)
LINK_NEAR_E1_S = 0.55    # gap ≤ 3: Ee ≥ 1 이고 S* ≥ 이 값
LINK_TITLE_ONLY = 0.80   # 어느 gap 이든 S* ≥ 이 값
LINK_FAR_S = 0.30        # gap > 3: Ee ≥ 2, Et ≥ 2, S* ≥ 이 값
DORMANT_KEEP_DAYS = 90   # 휴면 이슈도 이 날 수 안이면 잇기 대상
MERGE_HINT_DICE = 0.5    # 두 이슈 대표 제목 Dice 가 이 값 이상이면 merge_hints
REID_OVERLAP = 0.5       # 재식별: 직전 단계 구성원과 겹친 수 ÷ 작은 쪽 크기
# 같은 날 잇기(2026-11-15): 같은 날 한 일이 여러 이슈로 갈라지던 것(배우 음주운전 5갈래, 미국 이륙 중단 2갈래)을 줄인다.
# 세 갈래(link.Linker.same_day): 이슈의 중심 고유명사 가운데 드문 것 + 사건 낱말 LINK_SAME_DAY_TERMS 개, 중심 사건 낱말 가운데
# 드문 것 LINK_SAME_DAY_RARE_TERMS 개, 같은 급상승어. 처음(사건 낱말 1개, 중심 조건 없음)에는 잘못 이음이 많아 이렇게 좁혔다.
# 드문 고유명사 = 그 앞 LINK_RARE_DAYS 일 동안 그 이름이 나온 언론 매체 계열이 LINK_RARE_PRIOR_FAMILIES 곳 이하.
LINK_SAME_DAY = True
LINK_SAME_DAY_TERMS = 2
LINK_SAME_DAY_CORE_FAMILIES = 2  # 이슈의 '중심 고유명사' = 그날 이 수 이상의 매체 계열에 나온 이름(과 씨앗 그룹의 이름). 중심 사건 낱말은 씨앗 그룹의 낱말뿐이다
LINK_SAME_DAY_TREND = True      # 그날의 같은 급상승어 하나가 그룹과 이슈 양쪽에 맞으면 잇는 갈래
LINK_SAME_DAY_RARE_TERMS = 2     # 고유명사 없이 드문 사건 낱말만으로 잇는 갈래(띄어쓰기만 다른 제목 — 美전역/美 전역)
LINK_RARE_DAYS = 7
LINK_RARE_PRIOR_FAMILIES = 2
# 같은 날 잇기에서 두 이름을 같은 주체로 보는 좁은 경우(link._same_subject): 긴 이름이 짧은 이름으로 시작하고 남는 꼬리가 아래의
# 법인·조직 접미일 때('한빛'과 '한빛그룹'). 한 이름이 다른 이름에 들어 있다는 것만으로는 같은 주체가 아니다. 앞에 글자가 붙은
# 이름('새한빛전자')이나 꼬리가 업종 낱말인 이름('한빛전자')은 다른 회사일 수 있다. 실제 자료(11-11 ~ 11-14)에서 포함 관계에
# 기대어 이어지던 것은 2건이고 둘 다 낱말 분석이 인물 이름을 다르게 자른 꼴이라 이 목록으로는 잇지 않는다.
LINK_SAME_SUBJECT_TAILS = ("그룹", "홀딩스", "지주", "본사", "측", "쪽")
# 쉼표 주어 막는 조건(2026-11-15, link._comma_subject): 그룹 씨앗 제목이 'X, …' 꼴(첫 어절 바로 뒤 쉼표)인데 X 가 그룹의
# 고유명사로 잡히지 않았고(낱말 분석이 회사 이름을 일반 낱말로 본 경우), 이슈에 그날 중심 고유명사가 있으며, X 가 이슈의 그날
# 이름과 사건 낱말 어디에도 없으면 같은 날 잇기의 (나)와 (다)를 쓰지 않는다. 회사마다 내는 같은 꼴 기사(평가 등급 발표)가
# 이름 없는 그룹이라는 까닭으로 다른 회사의 이슈에 붙던 것을 막는다. 잇는 조건은 넓히지 않는다.
LINK_SAME_DAY_COMMA_SUBJECT = True
# 쉼표 주어로 치지 않는 낱말: 기관이나 역할을 가리키는 일반 낱말. '경찰, …' 과 '소속사, …' 는 같은 사건을 서로 다른 쪽에서 다룬
# 기사라서 쉼표 앞이 다르다는 것으로 가르지 않는다. 회사나 사람의 이름은 넣지 않는다(같은 성격의 낱말만 더한다).
LINK_COMMA_SUBJECT_SKIP = ("경찰", "검찰", "법원", "재판부", "정부", "당국", "금융당국", "국회", "여당", "야당", "여야", "대통령실",
                           "소속사", "구단", "협회", "노조", "유족", "측근", "업계", "전문가", "누리꾼")

# ── 묶기 보정 둘(2026-11-14 부터 기본 켜짐)
# 설계 그대로는 묶기 정답 60쌍에서 '같은 인물의 다른 사건'을 13쌍 합쳐 기준(잘못 합침 3쌍 이하)에 못 미쳤다.
# 사흘 안 규칙에서 직함이 사건 낱말로, 이름이 제목 유사도로 들어가 같은 사람의 다른 일이 이어졌기 때문이다.
# 켜면: 2단계 S* 를 두 제목에서 그룹의 고유명사를 지운 뒤 재고, 직함(대표·사장·회장…)을 사건 낱말(terms)에서 뺀다.
# 둘 다 끄면 설계 그대로다(tests/test_signals_gold.py 가 끈 재생의 결과를 기록해 둔다).
LINK_S_WITHOUT_NAMES = True
ROLE_WORDS_NOT_TERMS = True
ROLE_WORDS = ("씨", "회장", "부회장", "대표", "사장", "장관", "의원", "지사", "총장", "위원장", "감독", "선수", "배우", "가수",
              "교수", "대통령", "총리", "행장", "군수", "구청장", "셰프")

# ── 점수(§5 · 계획 5-2 표). 처음 30일은 고정한다.
C_NEWS, C_SEARCH, C_WIKI = 0.60, 0.25, 0.15   # v 의 비중(언론 L(A), 검색 g, 위키 w)
L_BASE = 31                    # L(A) = min(1, ln(1+A)/ln 31)
H_DECAY = 0.7                  # H(d) = 0.7 H(d−1) + v(d)
H_SCREEN = 2.5                 # 화면용 min(1, H/2.5)
W_H, W_B, W_P, W_D = 0.40, 0.25, 0.15, 0.20
V_ACTIVE = 0.1                 # P·두 구역·휴면에서 "v 가 0.1 이상인 날"
P_DAYS = 7                     # P = min(날 수, 7) / 7
# P 의 날 수를 세는 기간: 최근 7일 [d−6, d](설계 §5-1). 계획 5-2 표의 식은 기간을 말하지 않는다.
# None 이면 첫날부터 센다(누적 — 17일째 조용한 이슈가 16점을 받는다. 2026-11-14 Codex 검토 반영으로 7 로 바꿈).
P_WINDOW_DAYS: int | None = 7
D_WINDOW_DAYS = 7              # D 는 [d−6, d] 에 처음 생긴 f, e 만(설계 §5-4 · 계획은 기간을 말하지 않음)
D_FOLLOWUP_W, D_DIV = 2, 10    # D = min(1, (2f + e) / 10)
GRADE_STEPS = ((500, 0.40), (1_000, 0.55), (5_000, 0.70), (20_000, 0.85))   # n < 경계 → 등급
GRADE_TOP = 1.00
GRADE_UNKNOWN = 0.40           # 표기 없음·못 읽음

# ── 수집 상태(§5-3)
STALE_HOURS = 6                # 마지막 성공이 이보다 오래면 오래됨

# ── 급상승 검색어 잇기(§5-2)
TREND_NEWS_DICE = 0.50
TREND_NEWS_OVERLAP = 2
TREND_MIN_WORDS = 2            # trend_news 가 없으면 검색어 낱말이 이 수 이상
# 2026-11-15 완화(11-14 KR 급상승어 129개 가운데 6개만 이어졌다): 낱말 조건을 '전부'에서 '고유명사는 전부, 나머지는 이 비율 이상'으로,
# 그리고 띄어쓰기와 조사를 무시한 꼴이 기사 제목에 들어 있으면 낱말 조건을 채운 것으로 본다(이 글자 수 이상인 꼴만).
TREND_TERMS_SHARE = 0.5
TREND_SQUASH_MIN = 3
# 2026-11-15 딸린 기사: 수집기가 급상승어마다 딸린 기사 제목을 전부 담는다(extra 의 trend_news_all, 많아야 TREND_NEWS_MAX 개).
# 잇기는 제목마다 위 조건(Dice TREND_NEWS_DICE 이상 또는 겹침 TREND_NEWS_OVERLAP 개)을 보고 가장 좋은 것을 쓴다. 조건 값은 그대로다.
# 검색어가 딸린 기사 제목과 이슈 기사 제목 양쪽에 있으면 겹침 1개로도 잇는 보완은 넣지 않았다. 사본 재생(11-11 ~ 11-15)에서
# 새로 이어진 6건 가운데 3건이 다른 일이었다(같은 회사의 다른 소식, 같은 품목의 다른 나라 가격, 프로그램 이름만 같은 기사).
TREND_NEWS_MAX = 5

# ── 후속 사건·새 인물(§5-4)
FOLLOWUP_DICE = 0.50
FOLLOWUP_FAMILIES = 3
NEW_TERM_FAMILIES = 2
NEW_ENTITY_FAMILIES = 2

# ── 상태(§6-1)
STATE_NEW_V = 0.3
STATE_PEAK = 0.9
STATE_COOL = 0.7
RISE_LOW, RISE_HIGH, RISE_LOW_DAYS = 0.3, 0.5, 3
DORMANT_DAYS = 7

# ── 큰 이야기 순서(2026-11-15 · 화제 점수와 따로 둔다. 점수식은 처음 30일 고정이라 바꾸지 않는다)
# story = 0.3 min(1, H/2.5) + 0.5 min(1, ln(1+F3)/ln 31) + 0.2 G3
# 비중은 사본 재생의 11-13 ~ 11-15 01:05 판에서 0.5/0.3/0.2 와 견주어, 매체 계열이 많은 이야기가 위로 오는 쪽으로 정했다.
# F3 = 그날과 앞 이틀의 매체 계열 수(날마다 A) 합, G3 = 같은 사흘 동안 이은 급상승어 등급의 최댓값(없으면 0).
STORY_W_H, STORY_W_F, STORY_W_G = 0.3, 0.5, 0.2
STORY_DAYS = 3

# ── 두 구역(§6-2)
ZONE_NEW_MAX, ZONE_ONGOING_MAX = 4, 6
ZONE_V = 0.1

# ── 계산 범위
QUIET_STOP_DAYS = 14           # 마지막 기사 뒤 이 날 수가 지나면 날짜별 줄을 더 쓰지 않는다(다시 붙으면 H 를 0.7^gap 로 이어 받음)
PROVISIONAL_KEEP_DAYS = 90     # 잠정 행 보관 기간(확정 행은 남긴다)

# ── 날짜 확정(§7-2)
FINAL_HOUR_NEXT_DAY = 12  # d 다음날 12:00 KST


def paths(pulse_db: str | None = None, engine_db: str | None = None, out: str | None = None) -> dict[str, pathlib.Path]:
    """인자 > 환경 변수 > 기본값."""
    def pick(arg, env, default):
        v = arg or os.environ.get(env) or default
        return pathlib.Path(v)
    pulse_dir = ROOT / "private" / "pulse"
    return {
        "pulse_db": pick(pulse_db, "OZL_PULSE_DB", pulse_dir / "pulse.db"),
        "engine_db": pick(engine_db, "OZL_ENGINE_DB", pulse_dir / "engine.db"),
        "board": pick(out, "OZL_BOARD_OUT", pulse_dir / "out" / "board.json"),
        "overrides": pathlib.Path(os.environ.get("OZL_ENGINE_OVERRIDES") or pulse_dir / "engine_overrides.yaml"),
        "lock": pick(out, "OZL_BOARD_OUT", pulse_dir / "out" / "board.json").parent / "engine.lock",
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: pathlib.Path) -> str:
    """파일 sha256 앞 12자. 없으면 '없음'."""
    try:
        return _sha(path.read_bytes())[:12]
    except OSError:
        return "없음"


def dict_version() -> str:
    """별칭 사전 + 자료 파일 8개 + kiwipiepy 판 + 직함 규칙 + 낱말 규칙 판(TEXT_RULES_VER)의 sha256 앞 12자.
    바뀌면 낱말 분석을 다시 한다."""
    from ozl.research import videos
    import kiwipiepy
    h = hashlib.sha256()
    for p in [videos.KEYWORDS, *(DATA / f for f in DATA_FILES)]:
        h.update(p.name.encode())
        h.update(p.read_bytes() if p.exists() else b"")
    h.update(("kiwipiepy=" + kiwipiepy.__version__).encode())
    h.update(f"roles={ROLE_WORDS_NOT_TERMS}".encode())
    h.update(f"text={TEXT_RULES_VER}".encode())
    return h.hexdigest()[:12]


# ── 시각
def parse_ts(s: str | None) -> datetime | None:
    """ISO 문자열 → 시간대가 붙은 datetime(UTC). 시간대가 없으면 UTC 로 본다."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def iso_utc(d: datetime) -> str:
    return d.astimezone(UTC).isoformat()


def kst_day(d: datetime) -> str:
    return d.astimezone(KST).date().isoformat()


def t_final(day: str) -> datetime:
    """날짜 d 의 확정 시각 = d 다음날 12:00 KST."""
    d = date.fromisoformat(day) + timedelta(days=1)
    return datetime(d.year, d.month, d.day, FINAL_HOUR_NEXT_DAY, tzinfo=KST).astimezone(UTC)


def day_add(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def day_diff(a: str, b: str) -> int:
    """a − b (날 수)."""
    return (date.fromisoformat(a) - date.fromisoformat(b)).days
