"""2단계: 그룹을 이슈에 잇기(§4-2), 이슈 번호 발급과 재식별(§4-3), 사람의 합치기·가르기 판단(§4-4).

DB 를 모른다. pipeline.py 가 engine.db 에서 읽은 번호 대장·확정 그룹·직전 단계 구성원을 넣고, 결과(그룹의 이슈, 새 번호,
별칭, 이력)를 받아 저장한다.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from ozl.signals import config, text
from ozl.signals.overrides import Overrides, load as apply_overrides  # noqa: F401  (설계의 apply_overrides)


@dataclass
class Issue:
    issue_id: str
    lang: str
    first_day: str
    minted_at: str
    minted_calc: int | None
    seed_key: str
    title: str
    status: str = "active"          # active | absorbed(잠정 묶음 흡수) | vanished(사라짐)
    split_of: str | None = None
    override_sig: str | None = None


def temp_id(seed_key: str) -> str:
    return "임시-" + hashlib.sha1(seed_key.encode()).hexdigest()[:8]


def _gbig(g: dict) -> frozenset:
    """그룹 씨앗 제목의 글자 두 개 묶음. LINK_S_WITHOUT_NAMES 가 켜져 있으면 그룹의 고유명사를 지운 제목으로 잰다."""
    if "_gtb" not in g:
        t = g["title"]
        if config.LINK_S_WITHOUT_NAMES:
            for e in sorted(g["ent_fam"], key=len, reverse=True):
                t = t.replace(e, " ")
        g["_gtb"] = text.bigrams(text.norm_title(t))
    return g["_gtb"]


def _empty_prof():
    # titles: [(그룹 시각, 씨앗 키, 제목 묶음)], seed: (그룹 시각, 씨앗 키, 고유명사) 가운데 가장 이른 것.
    # 그룹이 들어온 차례와 무관하게 같은 프로필이 나오도록 시각으로 정렬해 쓴다.
    return {"ent": defaultdict(set), "term": defaultdict(set), "titles": [], "seed": None}


def _gkey(g: dict) -> tuple:
    return (g.get("first_at") or "", g.get("seed") or "")


def _same_subject(x: str, y: str) -> bool:
    """두 이름이 같은 주체를 가리키는가. 같은 이름이거나, 긴 이름이 짧은 이름으로 시작하고 남는 꼬리가 법인·조직을 나타내는
    정해진 접미(config.LINK_SAME_SUBJECT_TAILS)일 때만이다('한빛'과 '한빛그룹').
    한 이름이 다른 이름에 들어 있다는 것만으로는 같다고 보지 않는다. 앞에 글자가 붙은 이름('한빛전자'와 '새한빛전자'),
    꼬리가 업종 낱말인 이름('한빛'과 '한빛전자')은 다른 주체다. 한 글자 이름은 이렇게 견주지 않는다."""
    if x == y:
        return True
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    return len(short) >= 2 and long_.startswith(short) and long_[len(short):].strip() in config.LINK_SAME_SUBJECT_TAILS


def _same_names(a: set, b: set) -> bool:
    """두 이름 묶음에 같은 주체의 이름이 있는가(_same_subject)."""
    if a & b:
        return True
    return any(_same_subject(x, y) for x in a for y in b)


@dataclass
class Linker:
    registry: dict[str, Issue]
    overrides: Overrides
    asof_iso: str
    mode: str = "step"                       # step | view
    calc_id: int | None = None
    prev_members: dict[str, set] = field(default_factory=dict)   # 직전 단계: 이슈 → 첫날 구성원(사본 포함)
    trend_hit: object = None                 # (그룹) → bool. 계열 1곳 그룹의 새 이슈 조건(§5-2). 없으면 거짓
    rare: object = None                      # (고유명사, 날) → bool. 같은 날 잇기의 '드문 고유명사'. 없으면 같은 날 규칙을 쓰지 않는다
    rare_term: object = None                 # (사건 낱말, 날) → bool. 같은 날 잇기의 '드문 사건 낱말'. 없으면 그 갈래를 쓰지 않는다
    # (그룹, 이슈의 그날 기사 키, 날, 언어) → 둘 모두에 맞는 검색어 [(검색어, 낱말) …](trends.pair_rule).
    # .seeds(그룹, 날, 언어) 가 있으면 그 기사 키를 가진 이슈를 잇기 후보에 더한다(_with_trend_candidates)
    trend_pair: object = None
    history: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    merge_hints: list = field(default_factory=list)
    minted: list = field(default_factory=list)

    def __post_init__(self):
        self.prof: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_empty_prof))
        self.claimed: set[str] = set()
        self.members_now: dict[str, set] = defaultdict(set)      # 이번 단계: 이슈 → 모든 날의 구성원
        self.first_members: dict[str, set] = defaultdict(set)    # 이번 단계: 이슈 → 첫날 구성원
        self.split_ids: dict[str, str] = {}
        self.ent_idx: dict[str, set] = defaultdict(set)
        self.tb_idx: dict[str, list] = defaultdict(list)
        self.title_owner: list = []
        self.temp_lang: dict[str, str] = {}
        self.day_keys: dict[tuple, set] = defaultdict(set)       # (이슈, 날) → 이번 단계에 그 날 붙은 기사 키
        self.key_issue: dict[tuple, str] = {}                    # (날, 기사 키) → 그 날 그 기사가 붙은 이슈(day_keys 의 역색인)
        self.core_idx: dict[tuple, set] = defaultdict(set)       # (날, 사건 낱말) → 그 낱말이 그 날 씨앗 그룹에 있던 이슈
        self._pc: dict = {}
        self._mint_splits()

    # ── 번호
    def _next_id(self, day: str) -> str:
        pre = "t" + day.replace("-", "") + "-"
        n = max([int(i[len(pre):]) for i in self.registry if i.startswith(pre) and i[len(pre):].isdigit()] or [0])
        return f"{pre}{n + 1:03d}"

    def _hist(self, iid: str, kind: str, detail: dict):
        self.history.append({"issue_id": iid, "at": self.asof_iso, "kind": kind, "detail": detail})

    def _mint(self, day: str, lang: str, seed: str, title: str, **kw) -> str:
        if self.mode != "step":
            return temp_id(seed)
        iid = self._next_id(day)
        self.registry[iid] = Issue(iid, lang, day, self.asof_iso, self.calc_id, seed, title, **kw)
        self.minted.append(iid)
        self._hist(iid, "발급", {"seed": seed, "day": day})
        return iid

    def _mint_splits(self):
        for sp in self.overrides.splits:
            have = [i for i, rec in self.registry.items() if rec.override_sig == sp["sig"]]
            if have:
                self.split_ids[sp["sig"]] = have[0]
                continue
            src = self.registry.get(self.overrides.resolve(sp["issue"], sp["day"]))
            if self.mode != "step" or src is None:
                self.split_ids[sp["sig"]] = "임시-split-" + sp["sig"][:8]
                continue
            iid = self._mint(sp["day"], src.lang, "", src.title, split_of=src.issue_id, override_sig=sp["sig"])
            self.split_ids[sp["sig"]] = iid
            self._hist(iid, "갈라짐", {"from": src.issue_id, "at": sp["at"], "reason": sp.get("reason", "")})
            self._hist(src.issue_id, "갈라짐", {"to": iid, "at": sp["at"], "reason": sp.get("reason", "")})

    # ── 프로필
    def add_group(self, iid: str, g: dict) -> None:
        p = self.prof[iid][g["day"]]
        for e, fams in g["ent_fam"].items():
            p["ent"][e].update(fams)
            self.ent_idx[e].add(iid)
        for t, fams in g["term_fam"].items():
            p["term"][t].update(fams)
        tb = _gbig(g)
        p["titles"].append((*_gkey(g), tb))
        tid = len(self.title_owner)
        self.title_owner.append((iid, tb))
        for bg in tb:
            self.tb_idx[bg].append(tid)
        if p["seed"] is None or _gkey(g) < p["seed"][:2]:
            p["seed"] = (*_gkey(g), set(g["ent_fam"]))
            p["seed_terms"] = set(g["term_fam"])
            for t in p["seed_terms"]:        # 씨앗이 더 이른 그룹으로 바뀌어도 앞의 낱말은 남는다(후보만 넓다. 판정은 same_day)
                self.core_idx[(g["day"], t)].add(iid)
        if iid.startswith("임시-"):
            self.temp_lang[iid] = g["lang"]
        keys = set(g["units"]) | set(g.get("copies") or ())
        self.day_keys[(iid, g["day"])] |= keys
        for k in keys:
            self.key_issue[(g["day"], k)] = iid
        for k in [k for k in self._pc if k[0] in (iid, self.overrides.resolve(iid, g["day"]))]:
            del self._pc[k]

    def _sources(self, iid: str, day: str) -> list[str]:
        """이 날 iid 로 계산되는 이슈들(합치기 판단으로 흡수된 번호 포함)."""
        out = [iid]
        for m in self.overrides.merges:
            if m["day"] <= day:
                out += [j for j in m["absorb"] if j not in out and self.overrides.resolve(j, day) == iid]
        return out

    def profile(self, iid: str, day: str) -> dict | None:
        key = (iid, day)
        if key not in self._pc:
            self._pc[key] = self._profile(iid, day)
        return self._pc[key]

    def _profile(self, iid: str, day: str) -> dict | None:
        days: dict[str, list[dict]] = defaultdict(list)
        first_days = set()
        for j in self._sources(iid, day):
            for d, p in self.prof.get(j, {}).items():
                if d <= day:
                    days[d].append(p)
            if j in self.registry:
                first_days.add(self.registry[j].first_day)
            elif j.startswith("임시-"):
                first_days.add(day)
        past = sorted(d for d in days if d < day)
        if not past and day not in days:
            return None
        last = past[-1] if past else day
        if config.day_diff(day, last) > config.DORMANT_KEEP_DAYS:
            return None
        gap = 0 if day in days else config.day_diff(day, last)
        lo = config.day_add(last, -(config.LINK_WINDOW_DAYS - 1))
        win = [d for d in past if d >= lo] + ([day] if day in days else [])
        ent, term, titles, seeds = defaultdict(set), defaultdict(set), [], set()
        for d in win:
            for p in days[d]:
                for e, f in p["ent"].items():
                    ent[e] |= f
                for t, f in p["term"].items():
                    term[t] |= f
                titles.extend((d, *t) for t in p["titles"])
                if d in first_days and p["seed"] and p["seed"][2]:
                    seeds |= p["seed"][2]
        n = config.LINK_MIN_FAMILIES
        return {"ent": {e for e, f in ent.items() if len(f) >= n} | seeds,
                "term": {t for t, f in term.items() if len(f) >= n},
                "titles": [t[3] for t in sorted(titles, key=lambda t: t[:3])][-config.LINK_TITLES:], "gap": gap}

    @staticmethod
    def match(g: dict, prof: dict) -> tuple[bool, int, int, float]:
        """(잇는가, Ee, Et, S*)."""
        Ee = len(set(g["ent_fam"]) & prof["ent"])
        Et = len(set(g["term_fam"]) & prof["term"])
        gt = _gbig(g)
        S = max([text.dice(gt, t) for t in prof["titles"]] or [0.0])
        if prof["gap"] <= config.LINK_GAP_DAYS:
            ok = ((Ee >= 2 and (Et >= 1 or S >= config.LINK_NEAR_E2_S)) or (Ee >= 1 and S >= config.LINK_NEAR_E1_S)
                  or S >= config.LINK_TITLE_ONLY)
        else:
            ok = (Ee >= 2 and Et >= 2 and S >= config.LINK_FAR_S) or S >= config.LINK_TITLE_ONLY
        return ok, Ee, Et, S

    def same_day(self, iid: str, g: dict, day: str) -> dict | None:
        """같은 날 잇기(2026-11-15): 이슈의 그날 그룹과 둘 가운데 하나를 함께 가지면 같은 일로 본다.
        이슈 쪽의 '중심 낱말':
          중심 고유명사 = 그날 그 이슈 기사에서 LINK_SAME_DAY_CORE_FAMILIES 곳 이상의 매체 계열에 나온 이름과 그날 첫 그룹(씨앗)의 이름.
          중심 사건 낱말 = 그날 첫 그룹(씨앗)의 사건 낱말뿐이다. 매체 계열 여러 곳이 쓴 낱말까지 넣으면, 가운데 그룹이 딸고 들어온
            낱말(같은 인물의 다른 일)로 씨앗과 이을 근거가 없는 다른 일이 사슬처럼 이어진다.
        (가) 이슈의 중심 고유명사 가운데 드문 것 하나 이상 + 이슈의 중심 사건 낱말 LINK_SAME_DAY_TERMS 개 이상.
        (나) 이슈의 중심 사건 낱말 가운데 드문 것 LINK_SAME_DAY_RARE_TERMS 개 이상(고유명사 없이 띄어쓰기만 다른 제목 — '美전역'/'美 전역' — 을 위해).
             그룹에 드문 고유명사가 하나라도 있으면 쓰지 않는다.
        (다) 그날의 같은 급상승어 하나가 그룹과 이슈의 그날 기사 양쪽에 맞고(낱말은 전부 포함, 딸린 기사 조건 그대로),
             검색어 낱말이 모두 이슈의 중심 낱말이며, 그룹이 이슈의 중심 사건 낱말을 LINK_SAME_DAY_TERMS 개 이상 가진다.
             양쪽에 맞는 검색어가 여럿이면 그 가운데 이 조건을 채우는 것을 쓴다.
             그룹과 이슈가 서로 다른 드문 고유명사를 가지면(주어가 다른 같은 꼴 기사 — 회사마다의 평가 결과) 쓰지 않는다.
        (나)와 (다)는 이름이 있는 서로 다른 주체에는 쓰지 않는다: 그룹에 고유명사가 있고 이슈에 중심 고유명사가 있는데
             그룹의 이름이 이슈의 그날 기사 어디에도 없을 때. 이름이 드문가와는 따로 본다. 같은 주체로 보는 것은 같은 이름과,
             긴 이름이 짧은 이름으로 시작하고 꼬리가 정해진 법인·조직 접미인 이름뿐이다(_same_names. 포함 관계만으로는 아니다).
        사건 낱말은 세 갈래 모두 이슈의 중심 사건 낱말(씨앗 그룹의 낱말)과 견준다. 그날 붙은 그룹의 낱말 전부도, 매체 계열 여러 곳이
             쓴 낱말도 아니다.
        여럿이 맞으면 (가) > (다) > (나) 순이다(근거의 prio 3, 2, 1).
        드물다 = 그 앞 LINK_RARE_DAYS 일 동안 그 낱말이 나온 언론 매체 계열이 LINK_RARE_PRIOR_FAMILIES 곳 이하(self.rare, self.rare_term).
        넓은 이름은 낱말 분석에서 이미 terms 로 옮겨지고, 직함은 사건 낱말이 아니다(ROLE_WORDS_NOT_TERMS)."""
        if self.rare is None or not config.LINK_SAME_DAY:
            return None
        ents, core_e, core_t = set(), set(), set()
        n = config.LINK_SAME_DAY_CORE_FAMILIES
        for j in self._sources(iid, day):
            p = self.prof.get(j, {}).get(day)
            if p:
                ents |= set(p["ent"])
                core_e |= {e for e, f in p["ent"].items() if len(f) >= n} | set((p["seed"] or (None, None, set()))[2])
                core_t |= set(p.get("seed_terms") or ())
        g_ents = set(g["ent_fam"])
        rare_own = sorted(e for e in g_ents if self.rare(e, day))
        rare = [e for e in rare_own if e in core_e]
        # 사건 낱말은 세 갈래 모두 씨앗 그룹의 낱말과만 견준다. 뒤에 붙은 그룹의 낱말까지 견주면(한 매체든 여러 매체든)
        # 그 그룹이 딸고 들어온 낱말(같은 인물의 다른 일)만으로 다음 그룹이 사슬처럼 이어진다.
        shared = sorted(set(g["term_fam"]) & core_t)
        enough = len(shared) >= config.LINK_SAME_DAY_TERMS
        if rare and enough:
            return {"rule": "같은 날 드문 고유명사", "prio": 3, "rare": rare, "day_terms": shared}
        # 이름이 있는 서로 다른 주체: 그룹에 고유명사가 있고 이슈에 중심 고유명사가 있는데 그룹의 이름이 이슈의 그날 기사 어디에도
        # 없다. 이름이 드문가와 따로 본다(앞 7일에 여러 매체에 나온 회사 둘의 같은 꼴 기사 — 회사마다의 평가 결과).
        other_subject = bool(g_ents) and bool(core_e) and not _same_names(g_ents, ents)
        if self.trend_pair is not None and config.LINK_SAME_DAY_TREND and enough and not other_subject:
            conflict = bool(rare_own) and not (set(rare_own) & ents) and bool({e for e in core_e if self.rare(e, day)})
            keys = set()
            if not conflict:
                for j in self._sources(iid, day):
                    keys |= self.day_keys.get((j, day), set())
            # 양쪽에 맞는 검색어가 여럿이면 검색어 낱말이 모두 이슈의 중심 낱말인 것을 고른다(키 순으로 첫째).
            hit = next((h for h in (self.trend_pair(g, keys, day, g["lang"]) if keys else ())
                        if h[1] <= (core_e | core_t)), None)
            if hit:
                return {"rule": "같은 날 같은 급상승어", "prio": 2, "keyword": hit[0], "day_terms": shared}
        # (나)는 그룹에 드문 고유명사가 있으면 쓰지 않는다: 이름이 붙은 다른 일(배우의 사고 CCTV)이
        # 낱말만 겹치는 이슈(같은 날 다른 뺑소니)로 가는 것을 막는다. 이름이 있는 서로 다른 주체에도 쓰지 않는다.
        if self.rare_term is not None and not rare_own and not other_subject:
            rt = [t for t in shared if self.rare_term(t, day)]
            if len(rt) >= config.LINK_SAME_DAY_RARE_TERMS:
                return {"rule": "같은 날 드문 사건 낱말", "prio": 1, "rare_terms": rt, "day_terms": shared}
        return None

    def _with_trend_candidates(self, g: dict, day: str) -> list[str]:
        """잇기 후보(candidates) + 그룹에 맞는 급상승어가 하나라도 있으면 같은 날 잇기가 볼 그날의 같은 언어 이슈.
        같은 날 잇기는 고유명사나 제목이 겹치지 않는 같은 일(띄어쓰기만 다른 제목)을 잇는 것이라 candidates 의 거르기를 넘을 수 있어야 한다.
        기준은 전수 검사다: 그룹에 맞는 검색어가 있으면 그날 그룹이 붙은 이슈 전부를 본다(trend_pair 에 seeds 가 없을 때 이렇게 한다).
        seeds 가 있으면 그 전부를 다시 보지 않고 same_day 가 이을 수 있는 이슈만 색인으로 찾는다. 결과는 전수 검사와 같아야 한다:
          (가) 드문 고유명사 갈래는 이름이 겹쳐야 하므로 candidates 에 이미 있다.
          (다) 같은 급상승어 갈래는 그 검색어가 맞을 수 있는 기사를 그날 가진 이슈(trend_pair.seeds → key_issue).
          (나) 드문 사건 낱말 갈래는 검색어를 요구하지 않는다. 그룹의 드문 사건 낱말을 그날 중심 사건 낱말(씨앗 그룹의 낱말)로
               LINK_SAME_DAY_RARE_TERMS 개 이상 가진 이슈(core_idx). 검색어가 새 그룹에만 맞을 때도 이 이슈를 놓치지 않는다."""
        out = self.candidates(g, day)
        if self.trend_pair is None or not config.LINK_SAME_DAY_TREND or not self.trend_pair(g, None, day, g["lang"]):
            return out
        seeds = getattr(self.trend_pair, "seeds", None)
        if seeds is None:
            extra = {self.overrides.resolve(i, day) for (i, d) in self.day_keys if d == day}
        else:
            extra = set()
            for k in seeds(g, day, g["lang"]):
                i = self.key_issue.get((day, k))
                if i is not None:
                    extra.add(self.overrides.resolve(i, day))
            if self.rare_term is not None:
                n: dict[str, int] = defaultdict(int)
                for t in g["term_fam"]:
                    if self.rare_term(t, day):
                        for i in {self.overrides.resolve(j, day) for j in self.core_idx.get((day, t), ())}:
                            n[i] += 1
                extra |= {i for i, c in n.items() if c >= config.LINK_SAME_DAY_RARE_TERMS}
        have = set(out)
        return out + sorted(i for i in extra if i not in have and self._ok_issue(i, g["lang"], day))

    def _same_day_over_reid(self, g: dict, day: str, reid_id: str, keys: set) -> tuple[str, dict] | None:
        """재식별로 잠정 번호를 받을 그룹이, 같은 날 이미 다른 이슈에 붙은 그룹과 같은 날 잇기 조건을 넘으면 (그 이슈, 근거)."""
        if self.rare is None or not config.LINK_SAME_DAY:
            return None
        blocked = set()
        for own in self._prev_owner(keys) | {reid_id}:
            blocked |= self.overrides.blocked_with(own)
        best = None
        for iid in self._with_trend_candidates(g, day):
            if iid == reid_id or iid in blocked or iid.startswith("임시-"):
                continue
            if not any(self.prof.get(j, {}).get(day) for j in self._sources(iid, day)):
                continue
            sd = self.same_day(iid, g, day)
            if sd and (best is None or (sd["prio"], len(sd["day_terms"])) > (best[1]["prio"], len(best[1]["day_terms"]))):
                best = (iid, sd)
        return best

    # ── 하루 처리
    def _ok_issue(self, iid: str, lang: str, day: str) -> bool:
        if iid.startswith("임시-"):
            return self.temp_lang.get(iid) == lang
        rec = self.registry.get(iid)
        return bool(rec and rec.lang == lang and rec.status == "active" and rec.first_day <= day
                    and self.overrides.resolve(iid, day) == iid)

    def candidates(self, g: dict, day: str) -> list[str]:
        """잇는 조건을 넘을 수 있는 이슈만(고유명사 하나 이상 겹침 또는 제목 Dice 0.30 이상 — 모든 조건이 둘 중 하나를 요구한다)."""
        raw = set()
        for e in g["ent_fam"]:
            raw |= self.ent_idx.get(e, set())
        gt = _gbig(g)
        cnt: dict[int, int] = defaultdict(int)
        for bg in gt:
            for tid in self.tb_idx.get(bg, ()):
                cnt[tid] += 1
        floor = min(config.LINK_NEAR_E2_S, config.LINK_FAR_S)
        for tid, c in cnt.items():
            iid, tb = self.title_owner[tid]
            if 2 * c / (len(tb) + len(gt)) >= floor:
                raw.add(iid)
        out = {self.overrides.resolve(i, day) for i in raw}
        return sorted(i for i in out if self._ok_issue(i, g["lang"], day))

    def _prev_owner(self, keys: set) -> set[str]:
        return {iid for iid, mem in self.prev_members.items() if mem & keys}

    def run_day(self, day: str, groups: list[dict]) -> list[dict]:
        """그날 그룹을 첫 단위 시각순으로 잇는다. 각 그룹에 'issue_id'(없으면 None)와 'link'(점수 근거)를 붙인다.

        번호 재식별을 잇기보다 먼저 한다(§4-3): 새 이슈 조건을 넘는 그룹 전체와 그날 발급된 번호 사이의 겹침을 먼저
        재고, 겹침이 큰 쌍부터 일대일로 번호를 정한다. 남은 그룹만 잇기와 새 번호 발급으로 넘어간다."""
        gs = sorted(groups, key=lambda x: (x["first_at"], x["seed"]))
        for g in gs:
            g["issue_id"], g["link"] = None, None
        reid = self._reid_all(day, gs)
        for g in gs:
            keys = set(g["units"]) | set(g.get("copies") or ())
            forced = self._forced(g, day)
            if forced:
                self._attach(forced, g, day, {"rule": "사람 판단(갈라짐)"})
                continue
            if g["group_id"] in reid:
                iid, why = reid[g["group_id"]]
                tgt = self._same_day_over_reid(g, day, iid, keys)
                if tgt:
                    # 같은 날 앞선 그룹이 붙은 다른 이슈와 같은 일이다(같은 날 잇기). 재식별한 잠정 번호는 놓아 두고
                    # 단계 끝(finish)에서 구성원이 옮겨 간 쪽으로 흡수(별칭)되게 한다.
                    self.claimed.discard(iid)
                    self._attach(tgt[0], g, day, {**tgt[1], "instead_of": iid})
                    continue
                self._attach(iid, g, day, why)
                continue
            blocked = set()
            for own in self._prev_owner(keys):
                blocked |= self.overrides.blocked_with(own)
            scored = []
            for iid in self._with_trend_candidates(g, day):
                if iid in blocked:
                    continue
                prof = self.profile(iid, day)
                if prof is None:
                    continue
                ok, Ee, Et, S = self.match(g, prof)
                why = {"Ee": Ee, "Et": Et, "S": round(S, 6), "gap": prof["gap"],
                       "ents": sorted(set(g["ent_fam"]) & prof["ent"]), "terms": sorted(set(g["term_fam"]) & prof["term"])}
                if not ok and prof["gap"] == 0:
                    sd = self.same_day(iid, g, day)
                    if sd:
                        ok = True
                        why.update(sd)
                if ok:
                    # 설계의 잇기 조건을 넘은 것이 같은 날 규칙보다 앞서고, 같은 날 규칙끼리는 (가) > (다) > (나).
                    scored.append(((why.get("prio", 9), Ee + Et, S), iid, why))
            keep = set(self._prefer_split_children([s[1] for s in scored], day))
            scored = [s for s in scored if s[1] in keep]
            self._hints(g, [s[1] for s in scored])
            best = None
            for s in sorted(scored, key=lambda s: s[1]):     # 같으면 번호가 이른 쪽
                if best is None or s[0] > best[0]:
                    best = s
            if best:
                self._attach(best[1], g, day, best[2])
                continue
            if self.new_issue_ok(g):
                iid = self._mint(day, g["lang"], g["seed"], g["title"])
                self.claimed.add(iid)
                self._attach(iid, g, day, {"rule": "새 이슈"})
        return groups

    def _reid_key(self, rec: Issue, g: dict, day: str, keys: set):
        """재식별 조건(직전 구성원과 겹친 수 ÷ 작은 쪽 ≥ 0.5, 또는 씨앗 기사 포함)을 넘으면 (겹친 수, 비율, 씨앗 포함), 아니면 None."""
        if rec.first_day != day or rec.lang != g["lang"] or rec.status != "active" or rec.issue_id in self.claimed:
            return None
        if rec.split_of:
            return None
        prev = self.prev_members.get(rec.issue_id) or set()
        seed_in = rec.seed_key in keys
        if not prev and not seed_in:
            return None
        ov = len(prev & keys)
        ratio = ov / min(len(prev), len(keys)) if prev else 0.0
        if ratio >= config.REID_OVERLAP or seed_in:
            return (ov, ratio, seed_in)
        return None

    def _reid_all(self, day: str, gs: list[dict]) -> dict[str, tuple[str, dict]]:
        """그날 새 이슈 조건을 넘는 그룹(사람 판단으로 떼어 낸 것 제외)과 그날 발급된 번호의 겹침을 모두 재고,
        (겹친 수, 비율, 씨앗 포함)이 큰 쌍부터 일대일로 정한다. 같으면 앞선 그룹, 이른 번호. → {그룹 번호: (이슈, 근거)}"""
        today = {iid: rec for iid, rec in self.registry.items() if rec.first_day == day}
        if not today:
            return {}
        by_key: dict[str, set] = defaultdict(set)
        for iid, rec in today.items():
            for k in self.prev_members.get(iid) or ():
                by_key[k].add(iid)
            by_key[rec.seed_key].add(iid)
        pairs = []
        for gi, g in enumerate(gs):
            if self._forced(g, day) or not self.new_issue_ok(g):
                continue
            keys = set(g["units"]) | set(g.get("copies") or ())
            cand = set().union(*(by_key.get(k, set()) for k in keys)) if keys else set()
            for iid in sorted(cand):
                k = self._reid_key(today[iid], g, day, keys)
                if k is not None:
                    pairs.append(((-k[0], -k[1], not k[2], gi, iid), g, iid, k))
        out: dict[str, tuple[str, dict]] = {}
        used: set[str] = set()
        for _, g, iid, k in sorted(pairs, key=lambda x: x[0]):
            if g["group_id"] in out or iid in used:
                continue
            used.add(iid)
            tgt = self.overrides.resolve(iid, day)
            self.claimed.add(tgt)
            out[g["group_id"]] = (tgt, {"rule": "재식별", "from": iid, "overlap": k[0], "ratio": round(k[1], 6),
                                        "seed": k[2]})
        return out

    def new_issue_ok(self, g: dict) -> bool:
        nf = len(g["families"])
        if nf >= 2:
            return True
        return nf == 1 and (g["has_official"] or bool(self.trend_hit and self.trend_hit(g)))

    def _attach(self, iid: str, g: dict, day: str, why: dict) -> None:
        g["issue_id"], g["link"] = iid, why
        self.add_group(iid, g)
        keys = set(g["units"]) | set(g.get("copies") or ())
        self.members_now[iid] |= keys
        rec = self.registry.get(iid)
        if rec and rec.first_day == day:
            self.first_members[iid] |= keys

    def _forced(self, g: dict, day: str) -> str | None:
        keys = set(g["units"]) | set(g.get("copies") or ())
        for sp in self.overrides.splits:
            if sp["day"] <= day and (g["group_id"] in sp["groups"] or keys & sp["items"]):
                return self.split_ids.get(sp["sig"])
        return None

    def _prefer_split_children(self, ok: list[str], day: str) -> list[str]:
        """원래 이슈와 갈라져 나온 이슈가 함께 맞으면 갈라져 나온 쪽만 남긴다."""
        drop = set()
        for sp in self.overrides.splits:
            child = self.split_ids.get(sp["sig"])
            parent = self.overrides.resolve(sp["issue"], day)
            if child in ok and parent in ok:
                drop.add(parent)
        return [i for i in ok if i not in drop]

    def _hints(self, g: dict, ok: list[str]) -> None:
        for i in range(len(ok)):
            for j in range(i + 1, len(ok)):
                a, b = ok[i], ok[j]
                if b in self.overrides.blocked_with(a):
                    continue
                ta = self.registry[a].title if a in self.registry else ""
                tb = self.registry[b].title if b in self.registry else ""
                if text.dice(text.norm_title(ta), text.norm_title(tb)) >= config.MERGE_HINT_DICE:
                    self.merge_hints.append({"issues": [a, b], "why": f"그룹 {g['group_id']} 가 두 이슈 모두에 맞음"})

    def _reidentify(self, g: dict, day: str, keys: set) -> str | None:
        """그룹 하나만 볼 때: 그날 발급된 번호 가운데 재식별 조건을 넘는 것 중 (겹친 수, 비율, 씨앗 포함)이 가장 큰 번호.
        run_day 는 그날 그룹 전체를 함께 보는 _reid_all 을 쓴다."""
        best = None
        for iid, rec in sorted(self.registry.items()):
            k = self._reid_key(rec, g, day, keys)
            if k is not None and (best is None or k > best[0]):
                best = (k, iid)
        if best is None:
            return None
        return self.overrides.resolve(best[1], day)

    # ── 단계 끝
    def finish(self, days_done: set[str]) -> None:
        """이번 단계에서 다시 묶은 날에 첫날이 있던 번호 가운데 다시 잡히지 않은 것: 흡수(별칭) 또는 사라짐(잠정)."""
        if self.mode != "step":
            return
        for iid, rec in sorted(self.registry.items()):
            if rec.status != "active" or rec.first_day not in days_done or rec.split_of:
                continue
            if iid in self.claimed or iid in self.members_now:
                continue
            if self.overrides.resolve(iid, max(days_done)) != iid:
                continue          # 사람의 합치기 판단으로 다른 번호에 들어간 것(별칭은 판단이 남긴다)
            prev = self.prev_members.get(iid) or set()
            where = defaultdict(int)
            for other, mem in self.members_now.items():
                if other != iid:
                    where[other] = len(prev & mem)
            tgt = max(sorted(where), key=lambda k: where[k], default=None)
            if prev and tgt and not tgt.startswith("임시-") and where[tgt] / len(prev) >= config.REID_OVERLAP:
                rec.status = "absorbed"
                self.aliases.append({"old_id": iid, "new_id": tgt, "at": self.asof_iso, "reason": "잠정 묶음 흡수"})
                self._hist(iid, "흡수", {"into": tgt})
            else:
                rec.status = "vanished"
                self._hist(iid, "사라짐(잠정)", {})
