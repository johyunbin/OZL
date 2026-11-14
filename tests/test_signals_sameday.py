"""화제 엔진: 급상승어 잇기 완화, 같은 날 잇기, 민감 표시의 자리, 큰 이야기 순서(2026-11-15). 제목과 이름은 전부 지어낸 것."""
from ozl.signals import board, overrides, text, trends
from ozl.signals.link import Linker

import test_signals_kit as K

U, G = K.unit, K.groups
DAY = "2030-04-01"


def _tr(title, news="", traffic="2000+", day=DAY):
    return {"key": "Google Trends KR|" + title, "title": title, "lang": "ko", "day": day, "kind": "trend",
            "extra": {"trend_news": news, "traffic": traffic}}


def _side(*titles):
    arts = []
    for i, t in enumerate(titles):
        a = {"key": f"매체{i}|{t}", "title": t}
        a.update(text.analyze(t, "ko"))
        arts.append(a)
    return trends.side_of(arts)


# ── 급상승어 낱말 조건
def test_keyword_spacing_and_particles_are_ignored():
    side = _side("가람국 전문가들 \"나래기지 철수 수단으로 봐\"")
    t = _tr("나래 기지의 철수")
    assert trends.words_ok(t, side[0], side[2])
    assert trends.words_ok(t, side[0], side[2], strict=True)        # 띄어쓰기를 무시한 꼴은 strict 에서도 쓴다


def test_proper_nouns_all_other_words_half():
    assert "한빛전자" in text.analyze("한빛전자 배터리 공장", "ko")["entities"]
    side = _side("한빛전자, 가람시 배터리 증설 발표")
    assert trends.words_ok(_tr("한빛전자 배터리 공장"), side[0], side[2])                 # 이름 전부 + 나머지 1/2
    assert not trends.words_ok(_tr("한빛전자 배터리 공장"), side[0], side[2], strict=True)
    assert not trends.words_ok(_tr("두리항공 배터리 공장"), side[0], side[2])             # 이름이 빠지면 안 된다


def test_trend_news_condition_unchanged():
    side = _side("한빛전자, 가람시 배터리 증설 발표")
    assert trends.match(_tr("한빛전자 배터리", news="한빛전자 가람시 배터리 증설 발표"), side)[0]
    assert not trends.match(_tr("한빛전자 배터리", news="별솔게임즈 신작 출시 연기 공지"), side)[0]


def test_trend_matching_two_issues_goes_to_merge_hints():
    s1 = _side("한빛전자 가람시 배터리 공장 화재")
    s2 = _side("한빛전자 가람시 배터리 공장 화재 진화")
    t = _tr("한빛전자 공장 화재", news="한빛전자 가람시 배터리 공장 화재")
    multi = []
    got, un = trends.assign([t], {"t1": ("ko", s1), "t2": ("ko", s2)}, multi)
    assert got[t["key"]]["issue_id"] in ("t1", "t2") and not un
    assert [(x[0]["title"], x[1]) for x in multi] == [("한빛전자 공장 화재", ["t1", "t2"])]


# ── 같은 날 잇기
def _linker(rare=None, rare_term=None, trend_pair=None):
    return Linker({}, overrides.Overrides(), "2030-04-02T00:00:00+00:00", "step", 1, {}, None,
                  rare=rare, rare_term=rare_term, trend_pair=trend_pair)


def _day():
    a = G([U("윤새봄, 만취 운전 사고…가로등 들이받아", "매체A", "2030-04-01T03:00"),
           U("윤새봄 만취 운전 사고로 가로등 파손", "매체B", "2030-04-01T03:30")], DAY)
    b = G([U("윤새봄 운전 사고 여파에 출연 예능 줄편집", "매체C", "2030-04-01T09:00"),
           U("윤새봄 운전 사고 여파, 출연 예능 줄줄이 편집", "매체D", "2030-04-01T09:20")], DAY)
    return a, b


def test_names_used_are_entities():
    for t in ("윤새봄 운전 사고 여파에 출연 예능 줄편집", "윤새봄, 만취 운전 사고…가로등 들이받아"):
        assert "윤새봄" in text.analyze(t, "ko")["entities"]


def test_same_day_rare_name_and_two_event_words_join():
    a, b = _day()
    assert len(a) == 1 and len(b) == 1                       # 1단계에서는 두 그룹이다
    L = _linker(rare=lambda e, d: True)
    L.run_day(DAY, a + b)
    assert a[0]["issue_id"] == b[0]["issue_id"] == "t20300401-001"
    assert b[0]["link"]["rule"] == "같은 날 드문 고유명사"


def test_same_day_needs_rare_name():
    a, b = _day()
    L = _linker(rare=lambda e, d: False)
    L.run_day(DAY, a + b)
    assert a[0]["issue_id"] and b[0]["issue_id"] and a[0]["issue_id"] != b[0]["issue_id"]


def test_same_day_needs_two_shared_event_words():
    a, _ = _day()
    c = G([U("윤새봄 새 앨범 발표…팬들 환호", "매체C", "2030-04-01T09:00"),
           U("윤새봄 새 앨범 공개에 팬들 환호", "매체D", "2030-04-01T09:20")], DAY)
    L = _linker(rare=lambda e, d: True)
    L.run_day(DAY, a + c)
    assert len(c) == 1 and c[0]["issue_id"] and a[0]["issue_id"] != c[0]["issue_id"]   # 같은 인물의 다른 일


def test_same_day_trend_branch_respects_conflicting_names():
    """같은 급상승어에 맞아도 그룹과 이슈가 서로 다른 드문 이름을 가지면 잇지 않는다(회사마다의 평가 결과)."""
    a = G([U("한빛전자 ESG 평가 통합 A등급 획득", "매체A", "2030-04-01T03:00"),
           U("한빛전자, ESG 평가 통합 A등급", "매체B", "2030-04-01T03:30")], DAY)
    b = G([U("두리항공 ESG 평가 통합 A등급 5년 연속", "매체C", "2030-04-01T09:00"),
           U("두리항공, ESG 평가 5년 연속 통합 A등급", "매체D", "2030-04-01T09:20")], DAY)
    L = _linker(rare=lambda e, d: True, trend_pair=lambda g, keys, d, lang: [("평가", frozenset({"평가"}))])
    L.run_day(DAY, a + b)
    assert len(a) == len(b) == 1 and b[0]["issue_id"] and a[0]["issue_id"] != b[0]["issue_id"]


def test_same_day_trend_branch_joins_unnamed_titles():
    a = G([U("전국 항공기 운항 중단 지시…이륙 대기", "매체A", "2030-04-01T03:00"),
           U("전국 항공기 운항 중단…이륙 대기 지시", "매체B", "2030-04-01T03:10")], DAY)
    b = G([U("항공기 이륙 중단 해제…운항 재개", "매체C", "2030-04-01T09:00"),
           U("항공기 이륙 중단 해제, 운항 재개 시작", "매체D", "2030-04-01T09:20")], DAY)
    assert len(a) == len(b) == 1 and not any(g["ent_fam"] for g in a + b)
    L = _linker(rare=lambda e, d: True, trend_pair=lambda g, keys, d, lang: [("항공기", frozenset({"항공기"}))])
    L.run_day(DAY, a + b)
    assert a[0]["issue_id"] == b[0]["issue_id"]
    assert b[0]["link"]["rule"] == "같은 날 같은 급상승어"


def test_same_day_off_without_rare_index():
    a, b = _day()
    L = _linker()
    L.run_day(DAY, a + b)
    assert a[0]["issue_id"] and b[0]["issue_id"] and a[0]["issue_id"] != b[0]["issue_id"]


# ── board: 민감 표시의 자리, 큰 이야기 순서, 검색에서만 보이는 것
def _row(iid, title, level="GREEN", H=1.0, fams=(1, 2, 3), g=0.0, score_raw=40.0, day_n=3, v=0.5):
    base = {"issue_id": iid, "lang": "ko", "title": title, "day_n": day_n, "first_day": "2030-03-30",
            "status_line": f"{day_n}일째", "new_thing": "", "outlets_n": fams[-1], "articles_n": 5, "copies_n": 0,
            "indirect": None, "links": [], "prev_day": None,
            "story_in": {"H": H, "families_by_day": list(fams), "families_3d": sum(fams), "grade_max_3d": g},
            "_z": {"v": v, "v_prev": v, "vdays": 3, "ended": False}}
    return {"issue_id": iid, "detail": {"row": base, "active": True}, "score": int(score_raw), "score_raw": score_raw,
            "state": "정점", "v": v, "H": H, "B": 0.3, "P": 0.4, "D": 0.0, "A": fams[-1], "g": g, "w": None,
            "kinds_present": ["언론"], "kinds_ok": ["언론"], "missing": [], "category": "사회",
            "sensitivity": {"level": level, "reasons": ["가상 사유"] if level != "GREEN" else []}, "person": False}


def _meta(unmatched=()):
    return {"asof": "2030-04-01T09:05:00+09:00", "base_day": DAY, "partial": True, "decided_at": "x", "calc_id": 1,
            "mode": "step", "versions": {}, "basis": "", "sources": [], "missing": [], "unmatched": list(unmatched),
            "merge_hints": [], "failed_both": False}


def test_red_rows_stay_in_zones_with_sensitivity_and_deck_blocked():
    rows = [_row("t20300330-001", "가상 큰 사건 민감", level="RED", score_raw=90),
            _row("t20300330-002", "가상 보통 사건", score_raw=50)]
    b = board.build(_meta(), rows, {})
    red = next(c for c in b["candidates"] if c["issue_id"] == "t20300330-001")
    assert red["zone"] == "ongoing" and red["sensitivity"]["level"] == "RED" and red["deck_blocked"] is True
    assert b["zones"]["ongoing"]["rows"][0] == "t20300330-001"
    assert next(c for c in b["candidates"] if c["issue_id"] == "t20300330-002")["deck_blocked"] is False


def test_story_rank_uses_cumulative_heat_not_score():
    rows = [_row("t20300330-001", "가상 어제 큰 일", H=2.4, fams=(9, 8, 0), score_raw=30),    # 오늘 0곳이지만 사흘 동안 컸다
            _row("t20300330-002", "가상 오늘 작은 일", H=0.4, fams=(0, 0, 2), score_raw=45),
            _row("t20300330-003", "가상 검색 붙은 일", H=0.4, fams=(0, 0, 2), g=1.0, score_raw=20)]
    b = board.build(_meta(), rows, {})
    rank = {c["issue_id"]: c["story_rank"] for c in b["candidates"]}
    assert rank == {"t20300330-001": 1, "t20300330-003": 2, "t20300330-002": 3}
    top = next(c for c in b["candidates"] if c["issue_id"] == "t20300330-001")
    assert top["story"]["families_3d"] == 17 and top["story"]["families_by_day"] == [9, 8, 0]
    assert [c["score"] for c in b["candidates"]] == [45, 30, 20]       # 화제 점수는 그대로


def test_story_is_none_for_old_rows():
    r = _row("t20300330-001", "가상 옛 줄")
    del r["detail"]["row"]["story_in"]
    b = board.build(_meta(), [r], {})
    assert b["candidates"][0]["story"] is None and b["candidates"][0]["story_rank"] == 1


def test_searches_unmatched_keep_traffic_and_news_title():
    un = [{"keyword": "가상검색어", "grade": 0.55, "day": DAY, "lang": "ko", "traffic_raw": "1000+",
           "news_title": "가상 딸린 기사 제목"},
          {"keyword": "표기없는검색어", "grade": 0.4, "day": DAY, "lang": "ko", "traffic_raw": "", "news_title": ""},
          {"keyword": "foreign", "grade": 0.4, "day": DAY, "lang": "en", "traffic_raw": "100+", "news_title": "x"}]
    b = board.build(_meta(un), [_row("t20300330-001", "가상 일")], {})
    assert b["searches_unmatched"] == [{"keyword": "가상검색어", "grade": 0.55, "day": DAY, "traffic_raw": "1000+",
                                        "news_title": "가상 딸린 기사 제목"}]
    old = board.build(_meta([{"keyword": "옛검색어", "grade": 0.4, "day": DAY, "lang": "ko"}]), [], {})
    assert old["searches_unmatched"] == [{"keyword": "옛검색어", "grade": 0.4, "day": DAY}]


# ── 검토 지적(2026-11-15): 사슬로 합쳐짐, 다른 주체, 검색어 고르기, 후보 좁히기, 합친 이슈의 이력, 늦게 받은 기사, 반올림
def test_same_day_rare_name_needs_core_event_words_not_chained_ones():
    """같은 드문 인물의 A(운전, 사고)에 한 매체의 B(운전, 사고, 기부, 행사)가 붙어도, A 와 사건 낱말이 겹치지 않는
    C(기부, 행사)는 합치지 않는다. 한 매체 기사로 딸려 들어온 낱말은 이슈의 중심 낱말이 아니다."""
    a = G([U("윤새봄, 만취 운전 사고…가로등 들이받아", "매체A", "2030-04-01T03:00"),
           U("윤새봄 만취 운전 사고로 가로등 파손", "매체B", "2030-04-01T03:30")], DAY)
    b = G([U("윤새봄 운전 사고 뒤 기부 행사 불참", "매체C", "2030-04-01T06:00")], DAY)
    c = G([U("윤새봄, 연말 기부 행사서 1억 쾌척", "매체D", "2030-04-01T09:00"),
           U("윤새봄 연말 기부 행사 참석…1억 쾌척", "매체E", "2030-04-01T09:20")], DAY)
    assert len(a) == len(b) == len(c) == 1
    L = _linker(rare=lambda e, d: True)
    L.run_day(DAY, a + b + c)
    assert b[0]["issue_id"] == a[0]["issue_id"]                         # B 는 A 와 같은 일(운전, 사고)
    assert c[0]["issue_id"] and c[0]["issue_id"] != a[0]["issue_id"]    # C 는 같은 인물의 다른 일


def _esg(name, o1, o2, hour, tail="획득"):
    return G([U(f"{name} ESG 평가 통합 A등급 {tail}", o1, f"2030-04-01T{hour}:00"),
              U(f"{name}, ESG 평가 통합 A등급 {tail}", o2, f"2030-04-01T{hour}:30")], DAY)


def test_same_day_rare_words_branch_is_not_for_differently_named_subjects():
    """두 회사 이름이 드물지 않아도(앞 7일에 여러 매체에 나온 이름) 이름이 다른 두 주체는 드문 사건 낱말만으로 잇지 않는다.
    같은 급상승어가 양쪽에 맞아도 마찬가지다."""
    for pair in (None, lambda g, keys, d, lang: [("평가", frozenset({"평가"}))]):
        a, b = _esg("한빛전자", "매체A", "매체B", "03"), _esg("두리항공", "매체C", "매체D", "09", tail="5년 연속")
        L = _linker(rare=lambda e, d: False, rare_term=lambda t, d: True, trend_pair=pair)
        L.run_day(DAY, a + b)
        assert len(a) == len(b) == 1 and b[0]["issue_id"] and a[0]["issue_id"] != b[0]["issue_id"], pair


def test_same_day_rare_words_branch_keeps_unnamed_titles_and_the_same_name():
    """드문 사건 낱말 갈래가 원래 잇던 것은 그대로다: 이름 없는 제목끼리, 그리고 같은(드물지 않은) 이름을 가진 그룹."""
    a = G([U("전국 항공기 운항 중단 지시…이륙 대기", "매체A", "2030-04-01T03:00"),
           U("전국 항공기 운항 중단…이륙 대기 지시", "매체B", "2030-04-01T03:10")], DAY)
    b = G([U("항공기 이륙 중단 해제…운항 재개", "매체C", "2030-04-01T09:00"),
           U("항공기 이륙 중단 해제, 운항 재개 시작", "매체D", "2030-04-01T09:20")], DAY)
    L = _linker(rare=lambda e, d: True, rare_term=lambda t, d: True)
    L.run_day(DAY, a + b)
    assert a[0]["issue_id"] == b[0]["issue_id"] and b[0]["link"]["rule"] == "같은 날 드문 사건 낱말"
    a = _esg("한빛전자", "매체A", "매체B", "03")
    b = G([U("한빛전자 ESG 평가 등급 상향에 주가 강세", "매체C", "2030-04-01T09:00"),
           U("한빛전자, ESG 평가 등급 올라 주가 강세", "매체D", "2030-04-01T09:20")], DAY)
    L = _linker(rare=lambda e, d: False, rare_term=lambda t, d: True)
    L.run_day(DAY, a + b)
    assert len(b) == 1 and a[0]["issue_id"] == b[0]["issue_id"] and b[0]["link"]["rule"] == "같은 날 드문 사건 낱말"
    # 같은 주체를 줄여 부른 이름은 다른 주체가 아니다: 긴 이름이 짧은 이름으로 시작하고 꼬리가 법인·조직 접미('그룹')일 때만.
    # 꼬리가 업종 낱말인 포함('한빛'과 '한빛전자')은 다른 주체로 본다(2026-11-15 재확인 뒤. 아래 재확인 지적 시험)
    a = _esg("한빛그룹", "매체A", "매체B", "03")
    b = G([U("한빛 ESG 평가 등급 상향에 주가 강세", "매체C", "2030-04-01T09:00"),
           U("한빛, ESG 평가 등급 올라 주가 강세", "매체D", "2030-04-01T09:20")], DAY)
    assert set(b[0]["ent_fam"]) == {"한빛"} and set(a[0]["ent_fam"]) == {"한빛그룹"}
    L = _linker(rare=lambda e, d: False, rare_term=lambda t, d: True)
    L.run_day(DAY, a + b)
    assert len(b) == 1 and a[0]["issue_id"] == b[0]["issue_id"] and b[0]["link"]["rule"] == "같은 날 드문 사건 낱말"


def _kw(key, title):
    return {"key": key, "title": title, "lang": "ko", "day": DAY, "kind": "trend", "extra": {"trend_news": "", "traffic": "2000+"}}


def test_same_day_trend_branch_tries_every_keyword_that_fits_both_sides():
    """그룹과 이슈 양쪽에 맞는 검색어가 둘일 때, 키 순서로 앞선 검색어가 이슈의 중심 낱말 조건에서 떨어져도
    조건을 채우는 다른 검색어로 잇는다. 검색어의 순서가 결과를 바꾸지 않는다(trends.pair_rule 을 그대로 쓴다)."""
    for bad_key, good_key in (("검색어1", "검색어2"), ("검색어2", "검색어1")):
        ua = [U("전국 항공기 운항 중단 지시…이륙 대기", "매체A", "2030-04-01T03:00"),
              U("전국 항공기 운항 중단…이륙 대기 지시", "매체B", "2030-04-01T03:10")]
        ua1 = [U("항공기 관제 장애 원인 조사 착수", "매체E", "2030-04-01T05:00")]       # 한 매체: '관제'는 중심 낱말이 아니다
        ub = [U("항공기 이륙 중단 해제…관제 장애 복구", "매체C", "2030-04-01T09:00"),
              U("항공기 이륙 중단 해제, 관제 장애 복구 완료", "매체D", "2030-04-01T09:20")]
        a, a1, b = G(ua, DAY), G(ua1, DAY), G(ub, DAY)
        assert len(a) == len(a1) == len(b) == 1 and not any(g["ent_fam"] for g in a + a1 + b)
        tr = [_kw(bad_key, "항공기 관제"), _kw(good_key, "항공기 이륙")]
        L = _linker(rare=lambda e, d: True, trend_pair=trends.pair_rule(tr, {u["key"]: u for u in ua + ua1 + ub}))
        L.run_day(DAY, a)
        iid = a[0]["issue_id"]
        L._attach(iid, a1[0], DAY, {"rule": "시험"})
        L.run_day(DAY, b)
        assert b[0]["issue_id"] == iid, (bad_key, good_key)
        assert (b[0]["link"]["rule"], b[0]["link"]["keyword"]) == ("같은 날 같은 급상승어", "항공기 이륙")


W1 = ["감나무", "돌고래", "무지개", "바람개비", "솔방울", "종이학", "초승달", "코끼리", "하모니카", "나침반", "도토리", "라일락",
      "민들레", "보름달", "소나기", "아지랑이", "잠자리", "참나무", "카나리아", "타악기", "풍차", "해바라기", "고드름", "노을",
      "다람쥐", "모닥불", "반딧불", "산책로", "은행나무", "옹달샘"]
W2 = ["축제", "대회", "전시", "공연", "박람회", "경연", "시상식", "강연", "체험전", "발표회", "음악회", "사진전", "토론회", "장터",
      "운동회", "낭독회", "관찰", "달리기", "수영", "등산", "낚시", "요리", "바둑", "서예", "뜨개질", "도예", "목공", "원예", "합창", "연극"]


def test_trend_candidates_come_from_an_index_not_every_issue_of_the_day(monkeypatch):
    """그룹마다 자기 검색어에만 맞고 서로 겹치는 낱말이 없으면 같은 날 잇기 검사 횟수는 그룹 수를 넘지 않는다.
    검색어가 맞는 그룹마다 그날 이슈 전체를 다시 보면 그룹 수의 제곱이 된다(30개에 435번)."""
    units, gs, tr = [], [], []
    for i, (w1, w2) in enumerate(zip(W1, W2)):
        hh, mm = 3 + i // 6, (i % 6) * 10
        pair = [U(f"{w1} {w2}", "매체A", f"2030-04-01T{hh:02d}:{mm:02d}"),
                U(f"{w1} {w2} 소식", "매체B", f"2030-04-01T{hh:02d}:{mm + 5:02d}")]
        units += pair
        gs += G(pair, DAY)
        tr.append(_tr(f"{w1} {w2}"))
    n = len(W1)
    assert len(gs) == n and all(len(g["units"]) == 2 for g in gs)
    pr = trends.pair_rule(tr, {u["key"]: u for u in units})
    assert all(pr(g, None, DAY, "ko") for g in gs)                 # 그룹마다 맞는 검색어가 있다
    calls = []
    orig = Linker.same_day
    monkeypatch.setattr(Linker, "same_day", lambda self, iid, g, day: calls.append(iid) or orig(self, iid, g, day))
    L = _linker(rare=lambda e, d: True, rare_term=lambda t, d: True, trend_pair=pr)
    L.run_day(DAY, gs)
    assert len({g["issue_id"] for g in gs}) == n and all(g["issue_id"] for g in gs)
    assert len(calls) <= n


def test_trend_index_still_reaches_an_issue_without_shared_title_or_name():
    """역색인으로 좁혀도, 제목과 이름이 겹치지 않는 이슈가 같은 검색어에 맞으면 후보에 든다(급상승어 갈래가 본다)."""
    ua = [U("나래공항 활주로 전면 폐쇄", "매체A", "2030-04-01T03:00"), U("나래공항 활주로 전면 폐쇄 조치", "매체B", "2030-04-01T03:10")]
    ub = [U("발 묶인 승객 수천 명…활주로 폐쇄 여파 이틀째", "매체C", "2030-04-01T09:00"),
          U("발 묶인 승객 수천 명, 활주로 폐쇄 여파 이틀째 계속", "매체D", "2030-04-01T09:20")]
    a, b = G(ua, DAY), G(ub, DAY)
    assert len(a) == len(b) == 1
    L = _linker(rare=lambda e, d: True, trend_pair=trends.pair_rule([_tr("활주로 폐쇄")], {u["key"]: u for u in ua + ub}))
    L.run_day(DAY, a)
    assert a[0]["issue_id"] not in L.candidates(b[0], DAY)          # 잇기 후보(이름, 제목)에는 없다
    L.run_day(DAY, b)
    assert b[0]["issue_id"] == a[0]["issue_id"] and b[0]["link"]["rule"] == "같은 날 같은 급상승어"


def test_story_rank_sorts_on_the_unrounded_value():
    """두 줄의 이야기 값이 소수 여섯 자리에서 같아 보여도 순서는 반올림 전 값으로 정한다(화제 점수로 뒤집히지 않는다)."""
    rows = [_row("t20300330-001", "가상 조금 작은 일", H=1.000001, score_raw=50),
            _row("t20300330-002", "가상 조금 큰 일", H=1.000002, score_raw=40)]
    b = board.build(_meta(), rows, {})
    cs = {c["issue_id"]: c for c in b["candidates"]}
    assert cs["t20300330-001"]["story"]["value"] == cs["t20300330-002"]["story"]["value"]     # 보이는 값은 같다
    assert (cs["t20300330-002"]["story_rank"], cs["t20300330-001"]["story_rank"]) == (1, 2)
    assert not any(k.startswith("_") for c in b["candidates"] for k in c)                    # 정렬용 값은 판에 남기지 않는다


def test_story_counts_the_history_of_merged_issues(tmp_path):
    """사람 판단으로 합친 이슈의 사흘 규모와 급상승 등급에는 합쳐져 들어온 번호의 이력도 든다.
    같은 날 두 번호에 모두 나온 매체 계열(연합뉴스)은 한 번만 세고, 등급은 가장 큰 값이다."""
    from ozl.signals import engine, store
    A, d1, d2 = K.art, "2030-03-01", "2030-03-02"
    x = "한빛전자, 가람시에 반도체 신공장 짓는다"
    its = [A(x, "연합뉴스", f"{d1}T09:00"), A("가람시 한빛전자 신공장 유치 확정", "한국경제", f"{d1}T09:30"),
           A("한빛전자 가람시 신공장에 3조 투입", "매일경제", f"{d1}T10:00"),
           A("가람시, 한빛전자 반도체 공장 유치에 들썩", "서울경제", f"{d1}T10:30"),
           A("한빛전자 가람시 공장 착공 내년 상반기", "머니투데이", f"{d1}T11:00"),
           A("한빛전자 신공장", "구글 트렌드", f"{d1}T10:00", kind="trend", feed="trends_kr",
             url="https://trends.google.com/trending/rss?geo=KR", extra={"traffic": "2000+", "trend_news": x}),
           A("켐텍화학 덴포시 공장 폭발", "연합뉴스", f"{d1}T12:00"),
           A("덴포시 켐텍화학 공장 폭발 사고 수습", "조선일보", f"{d1}T12:20"),
           A("켐텍화학 덴포시 공장 폭발 원인 조사", "동아일보", f"{d2}T08:00"),
           A("덴포시, 켐텍화학 공장 폭발 피해 주민 지원", "경향신문", f"{d2}T08:30")]
    ov = tmp_path / "ov.yaml"
    ov.write_text(f'- {{at: "{d2}T10:00:00+09:00", by: 사용자, action: merge, keep: t20300301-002, '
                  'absorb: [t20300301-001], reason: 시험}\n', encoding="utf-8")
    runs = [K.kst(f"{d1}T13:05"), K.kst(f"{d1}T23:05"), K.kst(f"{d2}T09:05"), K.kst(f"{d2}T10:05")]
    pdb = K.make_pulse(tmp_path / "p.db", its, runs)
    con = store.connect(tmp_path / "e.db")
    for r in runs:
        out = engine.step(con, pdb, r, overrides_path=ov)
        if r == runs[2]:                                            # 합치기 전: 두 이슈가 따로다
            before = {c["issue_id"]: c["story"] for c in out["board"]["candidates"]}
    assert before["t20300301-001"]["families_by_day"] == [0, 5, 0] and before["t20300301-001"]["grade_max_3d"] == 0.7
    assert before["t20300301-002"]["families_by_day"] == [0, 2, 2] and before["t20300301-002"]["grade_max_3d"] == 0.0
    cs = {c["issue_id"]: c for c in out["board"]["candidates"]}
    assert sorted(cs) == ["t20300301-002"] and cs["t20300301-002"]["aliases"] == ["t20300301-001"]
    st = cs["t20300301-002"]["story"]
    assert st["families_by_day"] == [0, 6, 2] and st["families_3d"] == 8      # 첫날: 5곳 + 2곳 − 겹친 1곳
    assert st["grade_max_3d"] == 0.7


def test_rare_index_uses_only_items_received_by_the_days_final_time():
    """그 날의 희귀성 판정에는 그 날의 확정 시각(다음 날 12:00 KST)까지 받은 기사만 쓴다(묶기와 같은 상한)."""
    from ozl.signals import pipeline
    arts = [U("윤새봄 새 앨범 발표", "매체A", "2030-04-05T10:00"), U("윤새봄 팬미팅 일정 공개", "매체B", "2030-04-06T10:00"),
            U("윤새봄 예능 출연 확정", "매체C", "2030-04-07T20:00")]
    arts[2]["received_at"] = K.kst("2030-04-10T09:00")               # 4월 8일의 확정 시각(4월 9일 12:00) 뒤에 받았다
    rare = pipeline.rare_index(arts)
    assert rare("윤새봄", "2030-04-08") is True                      # 그때까지 받은 것으로는 매체 계열 2곳
    assert rare("윤새봄", "2030-04-11") is False                     # 받은 뒤의 날에는 3곳
    arts[2]["received_at"] = K.kst("2030-04-07T20:10")
    assert pipeline.rare_index(arts)("윤새봄", "2030-04-08") is False


def test_late_received_article_does_not_change_links_of_a_day_computed_late(tmp_path):
    """4월 8일을 뒤늦게(4월 10일에) 계산해도, 4월 8일의 확정 시각 뒤에 받은 앞 날짜 기사는 그날의 같은 날 잇기를 바꾸지 않는다."""
    from ozl.signals import pipeline, store
    A, d = K.art, "2030-04-08"
    asof = K.kst("2030-04-10T15:00")

    def joined(name, late_seen):
        its = [A("윤새봄 새 앨범 발표", "연합뉴스", "2030-04-05T10:00"), A("윤새봄 팬미팅 일정 공개", "한국경제", "2030-04-06T10:00"),
               A("윤새봄 예능 출연 확정", "매일경제", "2030-04-07T20:00", first_seen=late_seen),
               A("윤새봄, 만취 운전 사고…가로등 들이받아", "서울경제", f"{d}T03:00"),
               A("윤새봄 만취 운전 사고로 가로등 파손", "머니투데이", f"{d}T03:30"),
               A("윤새봄 운전 사고 여파에 출연 예능 줄편집", "조선일보", f"{d}T09:00"),
               A("윤새봄 운전 사고 여파, 출연 예능 줄줄이 편집", "동아일보", f"{d}T09:20")]
        pdb = K.make_pulse(tmp_path / f"p_{name}.db", its, [asof])
        res = pipeline.step(store.connect(tmp_path / f"e_{name}.db"), pdb, asof)
        assert d in res["finalized"]
        io = pipeline.issue_of(res)
        ids = [io.get(K.key_of(it)) for it in its[3:]]
        assert all(ids)
        return len(set(ids)) == 1

    assert joined("late", "2030-04-10T09:00") is True      # 확정 시각 뒤에 받은 기사: 그날에는 이름이 아직 드물었다
    assert joined("ontime", "2030-04-07T20:10") is False   # 제때 받았으면 이름이 드물지 않아 잇지 않는다


# ── 재확인 지적(2026-11-15): 매체 둘이 쓴 가운데 그룹의 사슬, 이름 포함 관계, 새 그룹에만 맞는 검색어의 후보
def test_same_day_two_outlet_middle_group_does_not_chain_another_event():
    """가운데 그룹 B(운전, 사고, 기부, 행사)를 매체 계열 2곳이 써도, 씨앗 A(운전, 사고)와 사건 낱말이 겹치지 않는
    C(기부, 행사)는 합치지 않는다. 이슈의 중심 사건 낱말은 그날 첫 그룹(씨앗)의 낱말뿐이다."""
    a = G([U("윤새봄, 만취 운전 사고…가로등 들이받아", "매체A", "2030-04-01T03:00"),
           U("윤새봄 만취 운전 사고로 가로등 파손", "매체B", "2030-04-01T03:30")], DAY)
    b = G([U("윤새봄 운전 사고 뒤 기부 행사 불참", "매체C", "2030-04-01T06:00"),
           U("윤새봄, 운전 사고 뒤 기부 행사 불참 통보", "매체F", "2030-04-01T06:20")], DAY)
    c = G([U("윤새봄, 연말 기부 행사서 1억 쾌척", "매체D", "2030-04-01T09:00"),
           U("윤새봄 연말 기부 행사 참석…1억 쾌척", "매체E", "2030-04-01T09:20")], DAY)
    d = G([U("윤새봄 운전 사고 여파에 출연 예능 줄편집", "매체G", "2030-04-01T11:00"),
           U("윤새봄 운전 사고 여파, 출연 예능 줄줄이 편집", "매체H", "2030-04-01T11:20")], DAY)
    assert len(a) == len(b) == len(c) == len(d) == 1 and b[0]["families"] == ["매체C", "매체F"]
    L = _linker(rare=lambda e, d: True)
    L.run_day(DAY, a + b + c + d)
    assert b[0]["issue_id"] == a[0]["issue_id"] and b[0]["link"]["rule"] == "같은 날 드문 고유명사"   # B 는 A 와 같은 일
    assert c[0]["issue_id"] and c[0]["issue_id"] != a[0]["issue_id"]                               # C 는 같은 인물의 다른 일
    assert d[0]["issue_id"] == a[0]["issue_id"] and d[0]["link"]["day_terms"] == ["사고", "운전"]    # 씨앗의 낱말로는 그대로 잇는다


def test_same_day_rare_words_branch_does_not_chain_through_a_two_outlet_group():
    """같은 사슬은 이름 없는 갈래(드문 사건 낱말)에도 있다: 활주로 폐쇄(A)에 '폐쇄에 환불 대란'(B, 매체 계열 2곳)이 붙어도,
    A 와 사건 낱말이 겹치지 않는 '공연 취소에 환불 대란'(C)은 B 가 딸고 온 낱말(환불, 대란)만으로 합치지 않는다."""
    a = G([U("폭우로 전국 활주로 전면 폐쇄 지시", "매체A", "2030-04-01T03:00"),
           U("폭우에 전국 활주로 전면 폐쇄 지시 내려져", "매체B", "2030-04-01T03:10")], DAY)
    b = G([U("전국 활주로 전면 폐쇄에 환불 대란", "매체C", "2030-04-01T06:00"),
           U("전국 활주로 전면 폐쇄로 환불 대란 조짐", "매체D", "2030-04-01T06:20")], DAY)
    c = G([U("공연 취소에 환불 대란", "매체E", "2030-04-01T09:00"),
           U("공연 취소로 환불 대란 조짐", "매체F", "2030-04-01T09:20")], DAY)
    assert len(a) == len(b) == len(c) == 1 and not any(g["ent_fam"] for g in a + b + c)
    L = _linker(rare=lambda e, d: True, rare_term=lambda t, d: True)
    L.run_day(DAY, a + b)
    assert b[0]["issue_id"] == a[0]["issue_id"] and b[0]["link"]["rule"] == "같은 날 드문 사건 낱말"
    assert a[0]["issue_id"] in L.candidates(c[0], DAY)                  # C 는 B 와 제목이 겹쳐 후보에는 든다
    L.run_day(DAY, c)
    assert c[0]["issue_id"] and c[0]["issue_id"] != a[0]["issue_id"]


def test_same_names_only_for_a_listed_organisation_tail():
    """이름 포함만으로 같은 주체로 보지 않는다. 같은 이름이거나, 긴 이름이 짧은 이름으로 시작하고 남는 꼬리가 정해진
    법인·조직 접미일 때만 같은 주체다."""
    from ozl.signals.link import _same_names
    assert _same_names({"한빛전자", "가람시"}, {"한빛전자"})
    assert _same_names({"한빛"}, {"한빛그룹"}) and _same_names({"한빛홀딩스"}, {"한빛"}) and _same_names({"한빛"}, {"한빛지주"})
    assert _same_names({"한빛전자"}, {"한빛전자 측"}) and _same_names({"한빛전자 본사"}, {"한빛전자"})
    assert not _same_names({"한빛전자"}, {"새한빛전자"})          # 앞에 글자가 붙은 이름은 다른 회사
    assert not _same_names({"한빛"}, {"한빛전자"})                # 꼬리가 업종 낱말이면 다른 회사
    assert not _same_names({"한빛전자"}, {"한빛전자서비스"})
    assert not _same_names({"한빛그룹"}, {"한빛홀딩스"})          # 어느 쪽도 다른 쪽으로 시작하지 않는다
    assert not _same_names({"레온"}, {"레온 쿠"})                 # 꼬리가 사람 이름의 나머지(낱말 분석이 이름을 다르게 자른 꼴)
    assert not _same_names({"한"}, {"한그룹"})                    # 한 글자 이름은 견주지 않는다
    assert not _same_names(set(), {"한빛"})


def _esg2(name, tail, o1, o2, hour):
    us = [U(f"{name} {tail}", o1, f"2030-04-01T{hour}:00"), U(f"{name}, {tail}", o2, f"2030-04-01T{hour}:30")]
    return us, G(us, DAY)


def test_same_day_branches_do_not_take_a_name_inside_a_longer_name_as_the_same_subject():
    """서로 다른 회사 '한빛전자'와 '새한빛전자'(둘 다 드물지 않은 이름)는 드문 사건 낱말로도, 양쪽에 맞는 급상승어로도
    잇지 않는다. 꼬리가 업종 낱말인 포함('한빛'과 '한빛전자')도 다른 주체다. trends.pair_rule 을 그대로 쓴다."""
    for short, long_ in (("한빛전자", "새한빛전자"), ("한빛", "한빛전자")):
        for with_trend in (False, True):
            ua, a = _esg2(short, "ESG 평가 최고등급 획득…친환경 투자 성과", "매체A", "매체B", "03")
            ub, b = _esg2(long_, "회계부정 여파로 신뢰 잃고 ESG 평가 강등", "매체C", "매체D", "09")
            assert len(a) == len(b) == 1 and set(a[0]["ent_fam"]) == {short} and set(b[0]["ent_fam"]) == {long_}
            pr = trends.pair_rule([_tr("ESG 평가")], {u["key"]: u for u in ua + ub})
            assert pr(a[0], None, DAY, "ko") and pr(b[0], None, DAY, "ko")              # 검색어는 양쪽에 맞는다
            L = _linker(rare=lambda e, d: False, rare_term=lambda t, d: True, trend_pair=pr if with_trend else None)
            L.run_day(DAY, a + b)
            assert b[0]["issue_id"] and a[0]["issue_id"] != b[0]["issue_id"], (short, long_, with_trend)


def test_trend_candidates_reach_an_issue_when_the_keyword_fits_only_the_new_group():
    """검색어가 새 그룹에만 맞아도(이슈 쪽 기사에는 맞지 않는다), 그 그룹은 제목과 이름이 겹치지 않는 그날 이슈를 드문 사건 낱말
    갈래로 만날 수 있어야 한다. 역색인을 쓰기 전(검색어가 맞는 그룹은 그날 이슈 전체를 본다)에는 이어지던 것이다."""
    ua = [U("폭우로 전국 활주로 전면 폐쇄 지시", "매체A", "2030-04-01T03:00"),
          U("폭우에 전국 활주로 전면 폐쇄 지시 내려져", "매체B", "2030-04-01T03:10")]
    ub = [U("발 묶인 승객 불편 가중…활주로 폐쇄 여파 이틀째", "매체C", "2030-04-01T09:00"),
          U("발 묶인 승객 불편 가중, 활주로 폐쇄 여파 이틀째 계속", "매체D", "2030-04-01T09:20")]
    a, b = G(ua, DAY), G(ub, DAY)
    assert len(a) == len(b) == 1 and not any(g["ent_fam"] for g in a + b)
    pr = trends.pair_rule([_tr("승객 불편")], {u["key"]: u for u in ua + ub})
    assert pr(b[0], None, DAY, "ko") and not pr(a[0], None, DAY, "ko")      # 검색어는 새 그룹에만 맞는다
    L = _linker(rare=lambda e, d: True, rare_term=lambda t, d: t in ("활주로", "폐쇄"), trend_pair=pr)
    L.run_day(DAY, a)
    assert a[0]["issue_id"] not in L.candidates(b[0], DAY)                  # 잇기 후보(이름, 제목)에는 없다
    L.run_day(DAY, b)
    assert b[0]["issue_id"] == a[0]["issue_id"]
    assert (b[0]["link"]["rule"], b[0]["link"]["rare_terms"]) == ("같은 날 드문 사건 낱말", ["폐쇄", "활주로"])


V1 = ["관람객", "입장권", "주차장", "숙박업소", "안내소", "화장실", "분수대"]
V2 = ["항의", "환불", "혼잡", "예약", "폐쇄", "수리", "가동"]
MIXED_KINDS = {0: "새그룹만", 1: "새그룹만", 2: "새그룹만", 4: "새그룹만", 7: "양쪽", 9: "양쪽", 10: "양쪽",
               12: "검색어없음", 13: "검색어없음", 14: "검색어없음", 15: "낱말하나", 16: "낱말하나", 17: "낱말하나"}


def _mixed_day():
    """지어낸 하루 43그룹: 바탕 그룹 26개, 그 뒤에 오는 그룹 13개, 이름 있는 그룹 4개. → (그룹, 검색어, 기사, 기대)
    뒤에 오는 그룹은 이름이 없고 바탕 그룹과 제목이 거의 겹치지 않는다(낱말 순서를 바꾸고 제목을 길게 했다).
      새그룹만:   검색어가 뒤 그룹에만 맞고 뒤 그룹이 바탕의 드문 낱말 둘을 가진다 → 바탕 이슈에 드문 사건 낱말로 붙는다.
      양쪽:       검색어가 바탕과 뒤 그룹 양쪽에 맞는다 → 같은 급상승어로 붙는다.
      검색어없음: 바탕의 드문 낱말 둘을 가졌지만 맞는 검색어가 없다 → 후보를 넓히지 않으므로 따로 남는다.
      낱말하나:   검색어가 뒤 그룹에 맞지만 바탕의 드문 낱말은 하나뿐이다 → 따로 남는다.
    기대: 뒤 그룹 번호 → (꼴, 바탕 그룹 번호, 바탕 이슈에 붙는가, 근거 규칙)."""
    units, gs, tr, want = [], [], [], {}

    def add(titles, hh, mm, outlets=("매체A", "매체B")):
        us = [U(t, o, f"2030-04-01T{hh:02d}:{mm + 5 * k:02d}") for k, (t, o) in enumerate(zip(titles, outlets))]
        g = G(us, DAY)
        assert len(g) == 1 and not g[0]["ent_fam"], titles
        units.extend(us)
        gs.extend(g)
        return g[0]

    vs = iter(zip(V1, V2))
    for n, i in enumerate([i for i in range(len(W1)) if i not in (3, 5, 6, 8)]):
        w1, w2 = W1[i], W2[i]
        kind = MIXED_KINDS.get(i)
        if kind is None:                                                    # 뒤 그룹이 없는 바탕은 낱말 분석을 가리지 않는다
            us = [U(f"{w1} {w2}", "매체A", f"2030-04-01T{3 + n // 6:02d}:{(n % 6) * 10:02d}"),
                  U(f"{w1} {w2} 소식", "매체B", f"2030-04-01T{3 + n // 6:02d}:{(n % 6) * 10 + 5:02d}")]
            units.extend(us)
            gs.extend(G(us, DAY))
            tr.append(_tr(f"{w1} {w2}"))
            continue
        base = add([f"{w1} {w2}", f"{w1} {w2} 소식"], 3 + n // 6, (n % 6) * 10)
        assert {w1, w2} <= set(base["term_fam"])
        hh, mm, out = 10 + n // 6, (n % 6) * 10, ("매체C", "매체D")
        if kind == "새그룹만":
            v1, v2 = next(vs)
            g = add([f"{v1} {v2} 속출…{w2} 앞둔 {w1} 여파 이틀째 이어져",
                     f"{v1} {v2} 속출, {w2} 앞둔 {w1} 여파 이틀째 이어져 우려"], hh, mm, out)
            tr.append(_tr(f"{v1} {v2}"))
            want[g["group_id"]] = (kind, base["group_id"], True, "같은 날 드문 사건 낱말")
        elif kind == "양쪽":
            g = add([f"우여곡절 끝에 {w2} 앞둔 {w1} 일정 재개 결정", f"우여곡절 끝에 {w2} 앞둔 {w1} 일정 재개 결정 소식"], hh, mm, out)
            tr.append(_tr(f"{w1} {w2}"))
            want[g["group_id"]] = (kind, base["group_id"], True, "같은 날 같은 급상승어")
        elif kind == "검색어없음":
            g = add([f"안전 문제 불거진 {w2} 앞둔 {w1} 일정 전면 재검토 착수",
                     f"안전 문제 불거진 {w2} 앞둔 {w1} 일정 전면 재검토 착수 방침"], hh, mm, out)
            want[g["group_id"]] = (kind, base["group_id"], False, "새 이슈")
        else:
            v1, v2 = next(vs)
            g = add([f"{v1} {v2} 속출…{w1} 여파 이틀째 이어져", f"{v1} {v2} 속출, {w1} 여파 이틀째 이어져 우려"], hh, mm, out)
            tr.append(_tr(f"{v1} {v2}"))
            want[g["group_id"]] = (kind, base["group_id"], False, "새 이슈")
        assert ({w1, w2} if kind != "낱말하나" else {w1}) == {w1, w2} & set(g["term_fam"]), g["title"]
    sa, sb = _day()                                                         # 같은 인물의 같은 일(드문 고유명사)
    ea, eb = _esg("한빛전자", "매체A", "매체B", "03"), _esg("두리항공", "매체C", "매체D", "09", tail="5년 연속")
    gs += sa + sb + ea + eb
    want[sb[0]["group_id"]] = ("이름", sa[0]["group_id"], True, "같은 날 드문 고유명사")
    want[eb[0]["group_id"]] = ("이름", ea[0]["group_id"], False, "새 이슈")
    return gs, tr, units, want


def _run_mixed(index: bool):
    gs, tr, units, want = _mixed_day()
    pr = trends.pair_rule(tr, {u["key"]: u for u in units})
    # seeds 가 없는 규칙을 주면 Linker 는 검색어가 맞는 그룹마다 그날 이슈 전체를 본다(전수 검사)
    pair = pr if index else (lambda g, keys, day, lang: pr(g, keys, day, lang))
    content = set(W1) | set(W2) | set(V1) | set(V2)                         # 드문 낱말은 지어낸 내용 낱말뿐이다(틀 낱말은 드물지 않다)
    L = _linker(rare=lambda e, d: True, rare_term=lambda t, d: t in content, trend_pair=pair)
    calls, cands = [], {}
    same_day, candidates = L.same_day, L.candidates
    L.same_day = lambda iid, g, day: calls.append(iid) or same_day(iid, g, day)
    L.candidates = lambda g, day: cands.setdefault(g["group_id"], candidates(g, day))
    L.run_day(DAY, gs)
    return {"gs": gs, "by_id": {g["group_id"]: g for g in gs}, "L": L, "calls": calls, "cands": cands, "want": want}


def test_trend_index_gives_the_same_links_as_scanning_every_issue_of_the_day():
    """같은 입력(지어낸 43그룹)에서 역색인으로 좁힌 후보와 그날 이슈 전체를 보는 전수 검사가 같은 결과를 낸다:
    그룹마다 붙은 이슈, 근거 규칙, 쓴 검색어, 드문 낱말, 합침 후보가 모두 같다. 역색인 쪽이 같은 날 잇기 검사를 덜 한다."""
    a, b = _run_mixed(index=True), _run_mixed(index=False)

    def links(r):
        return [(g["group_id"], g["issue_id"], (g["link"] or {}).get("rule"), (g["link"] or {}).get("keyword"),
                 (g["link"] or {}).get("rare_terms")) for g in r["gs"]]

    assert 30 <= len(a["gs"]) <= 50 and all(g["issue_id"] for g in a["gs"])
    assert links(a) == links(b)
    assert a["L"].merge_hints == b["L"].merge_hints
    for r in (b, a):                                                        # 전수 검사와 역색인 모두 기대한 대로 이었다
        for gid, (kind, base, joined, rule) in r["want"].items():
            g, base_issue = r["by_id"][gid], r["by_id"][base]["issue_id"]
            assert g["link"]["rule"] == rule, (kind, g["title"], g["link"])
            assert (g["issue_id"] == base_issue) is joined, (kind, g["title"])
            if kind in ("새그룹만", "검색어없음"):                           # 제목과 이름으로는 후보에 들지 않는 이슈다
                assert base_issue not in r["cands"][gid], (kind, g["title"])
    assert len(a["calls"]) < len(b["calls"])
