"""급상승 검색어를 이슈와 그룹에 잇기(§5-2). 검색어의 날짜는 오른 시각(published)의 KST 날짜이고, 같은 언어의 이슈에만 잇는다.

1. 낱말 조건. 둘 가운데 하나(2026-11-15 완화. 그 전에는 '검색어 낱말 전부가 이슈 쪽 낱말에 들어 있다' 하나였다):
   (가) 띄어쓰기와 조사를 무시한 꼴: 검색어의 공백을 뺀 꼴, 또는 어절마다 조사를 뗀 뒤 이은 꼴(3글자 이상)이 이슈 기사 제목의
        정규화한 꼴(글자와 숫자만) 하나에 들어 있다('주한 미군의 철수' → '주한미군철수').
   (나) 검색어의 고유명사(entities)는 전부, 나머지 낱말(terms)은 절반 이상(올림)이 이슈 쪽 낱말(d−1 ~ d 기사)에 들어 있다.
   검색어 낱말이 비어 있으면 (가)만 본다.
2. 딸린 기사가 있으면: 그 제목과 이슈 기사 제목 하나의 Dice ≥ 0.50, 또는 딸린 기사 낱말에서 검색어 낱말을 뺀 나머지가
   이슈 쪽과 2개 이상 겹친다. 딸린 기사 제목이 여럿이면(trend_news_all, 2026-11-15) 제목마다 이 조건을 보고 가장 좋은 것을 쓴다.
   검색어가 두 제목에 다 있다는 것만으로 조건을 낮추지 않는다(같은 회사나 같은 품목의 다른 소식이 이어진다. config.py 의 주석).
   같은 날 잇기의 급상승어 갈래(PairRule)는 그룹과 이슈가 같은 딸린 기사 제목에 함께 맞을 때만 근거로 쓴다(matched_news, same_news).
   서로 다른 딸린 기사에 하나씩 맞은 것은 같은 검색어를 쓰는 다른 일이다('운항 중단'에 딸린 통신망 마비 기사와 태풍 기사).
3. 딸린 기사가 없으면 검색어 낱말이 둘 이상.
여럿이 맞으면 (Dice, 겹친 수)가 큰 이슈 하나, 같으면 번호가 이른 쪽. 딸린 기사는 기사로 세지 않는다(§2-3).
"""
from __future__ import annotations

import functools
import math
import re

from ozl.signals import config, score, text


@functools.lru_cache(maxsize=4096)
def _words(title: str, lang: str) -> frozenset:
    r = text.analyze(title, lang)
    return frozenset(r["terms"]) | frozenset(r["entities"])


@functools.lru_cache(maxsize=4096)
def _kw_parts(title: str, lang: str) -> tuple[frozenset, frozenset, tuple]:
    """검색어 → (고유명사, 나머지 낱말, 띄어쓰기와 조사를 무시한 꼴들)."""
    r = text.analyze(title, lang)
    toks = [w for w in re.split(r"\s+", text.strip_head(title)) if w]
    forms = {text.norm_title(title)}
    if lang != "en":
        forms.add(text.norm_title("".join(text._strip_particle(w) for w in toks)))
    forms = tuple(sorted(f for f in forms if len(f) >= config.TREND_SQUASH_MIN))
    return frozenset(r["entities"]), frozenset(r["terms"]), forms


def kw_words(t: dict) -> frozenset:
    return _words(t["title"], t["lang"])


def words_ok(t: dict, words: frozenset, norms, strict: bool = False) -> bool:
    """낱말 조건(머리말 1). norms: 이슈 쪽 기사 제목의 정규화한 꼴 목록. strict 면 낱말 전부(2026-11-15 전의 규칙)."""
    ents, terms, forms = _kw_parts(t["title"], t["lang"])
    if forms and any(f in n for f in forms for n in norms):
        return True
    if not ents and not terms:
        return False
    if strict:
        return (ents | terms) <= words
    if not ents <= words:
        return False
    need = math.ceil(len(terms) * config.TREND_TERMS_SHARE)
    return len(terms & words) >= need


def news_title(t: dict) -> str:
    return str((t.get("extra") or {}).get("trend_news") or "").strip()


def news_titles(t: dict) -> list[str]:
    """딸린 기사 제목 전부. 수집기가 담은 trend_news_all(많아야 TREND_NEWS_MAX 개)이 있으면 그것, 없으면 trend_news 하나.
    2026-11-15 전에 받은 검색어와 본문을 읽지 못한 검색어에는 trend_news 만 있다."""
    raw = (t.get("extra") or {}).get("trend_news_all")
    out: list[str] = []
    if isinstance(raw, (list, tuple)):
        for x in raw:
            s = str(x or "").strip()
            if s and s not in out:
                out.append(s)
    if not out:
        one = news_title(t)
        return [one] if one else []
    return out[:config.TREND_NEWS_MAX]


def traffic(t: dict) -> str:
    return str((t.get("extra") or {}).get("traffic") or "")


def side_of(arts: list[dict]) -> tuple[frozenset, list, tuple]:
    """이슈(또는 그룹) 쪽: 기사들의 낱말 합, 제목 글자 묶음 목록, 정규화한 제목 목록."""
    words = set()
    tbs, norms = [], []
    for a in arts:
        words |= set(a.get("terms") or ()) | set(a.get("entities") or ())
        n = a.get("norm_title") or text.norm_title(a["title"])
        tbs.append((a["key"], text.bigrams(n)))
        norms.append(n)
    return frozenset(words), tbs, tuple(norms)


def _news_match(t: dict, nt: str, kw: frozenset, side: tuple) -> tuple[bool, float, int, str | None]:
    """딸린 기사 제목 하나의 조건(머리말 2). → (맞는가, Dice, 겹친 수, 맞은 기사 키)."""
    words, tbs = side[0], side[1]
    ntb = text.bigrams(text.norm_title(nt))
    best, key = 0.0, None
    for k, tb in tbs:
        dv = text.dice(ntb, tb)
        if dv > best:
            best, key = dv, k
    over = len((_words(nt, t["lang"]) - kw) & words)
    ok = best >= config.TREND_NEWS_DICE or over >= config.TREND_NEWS_OVERLAP
    return ok, best, over, key if best >= config.TREND_NEWS_DICE else None


def match(t: dict, side: tuple, strict: bool = False) -> tuple[bool, float, int, str | None]:
    """(맞는가, Dice, 겹친 수, 맞은 기사 키). strict 면 낱말 조건을 '전부 포함'으로 본다(같은 날 잇기의 급상승어 갈래).
    딸린 기사 제목이 여럿이면 제목마다 조건을 보고 (맞는가, Dice, 겹친 수)가 가장 큰 것을 쓴다(같으면 앞의 것)."""
    words = side[0]
    norms = side[2] if len(side) > 2 else tuple()
    kw = kw_words(t)
    if not words_ok(t, words, norms, strict):
        return False, 0.0, 0, None
    nts = news_titles(t)
    if not nts:
        return len(kw) >= config.TREND_MIN_WORDS, 0.0, 0, None
    best = None
    for nt in nts:
        r = _news_match(t, nt, kw, side)
        if best is None or r[:3] > best[:3]:
            best = r
    return best


def matched_news(t: dict, side: tuple, strict: bool = False) -> frozenset | None:
    """이 쪽이 검색어 t 에 맞으면 조건을 채운 딸린 기사 제목들(정규화한 꼴), 맞지 않으면 None.
    딸린 기사가 없는 검색어가 낱말만으로 맞으면 빈 묶음이다. 맞는가는 match 와 같다."""
    words = side[0]
    norms = side[2] if len(side) > 2 else tuple()
    if not words_ok(t, words, norms, strict):
        return None
    kw = kw_words(t)
    nts = news_titles(t)
    if not nts:
        return frozenset() if len(kw) >= config.TREND_MIN_WORDS else None
    return frozenset(text.norm_title(nt) for nt in nts if _news_match(t, nt, kw, side)[0]) or None


def same_news(a: frozenset, b: frozenset) -> bool:
    """두 쪽이 맞은 딸린 기사 제목(matched_news)에 같은 기사가 있는가. 정규화한 꼴(공백, 대소문자, 기호를 고르게 한 것)이 같은
    제목일 때만이다. 비슷한 제목(Dice)은 같은 기사로 보지 않는다: 원인이 다른 두 사건의 딸린 제목이 틀만 같아 Dice 0.52 였다.
    딸린 기사가 없는 검색어(양쪽 다 빈 묶음)는 낱말 조건만으로 본다."""
    if not a and not b:
        return True
    return bool(a & b)


def assign(trends_d: list[dict], sides: dict[str, tuple[str, tuple]], multi: list | None = None) -> tuple[dict, list]:
    """trends_d: 그날 검색어. sides: 이슈 → (언어, 쪽). → ({검색어 키: 이은 결과}, 맞지 않은 검색어 목록).
    multi 에 목록을 주면 둘 이상의 이슈에 맞은 검색어를 (검색어, [이슈 …]) 로 더한다(같은 일로 보고 합침 후보에 올린다)."""
    got, unmatched = {}, []
    for t in sorted(trends_d, key=lambda x: x["key"]):
        best = None
        hit = []
        for iid in sorted(sides):
            lang, side = sides[iid]
            if lang != t["lang"]:
                continue
            ok, dv, over, mk = match(t, side)
            if ok:
                hit.append(iid)
            if ok and (best is None or (dv, over) > best[0]):
                best = ((dv, over), iid, mk)
        if multi is not None and len(hit) >= 2:
            multi.append((t, hit))
        if best is None:
            unmatched.append(t)
        else:
            got[t["key"]] = {"issue_id": best[1], "trend_key": t["key"], "keyword": t["title"], "traffic_raw": traffic(t),
                             "grade": score.grade(traffic(t)), "matched_article": best[2], "dice": round(best[0][0], 6),
                             "overlap": best[0][1]}
    return got, unmatched


class PairRule:
    """같은 날 잇기의 급상승어 갈래(2026-11-15). 낱말 조건은 '전부 포함'(strict)으로 본다.

    rule(그룹, 이슈의 그날 기사 키, 날, 언어) → 그룹과 이슈 양쪽에 맞는 검색어 전부 [(검색어, 검색어 낱말) …](검색어 키 순, 없으면 빈 목록).
      딸린 기사 제목이 여럿인 검색어는 그룹과 이슈가 같은 딸린 기사에 함께 맞아야 한다(same_news). 각각 다른 딸린 기사에 맞은 것은
      같은 검색어를 쓰는 다른 일이라 돌려주지 않는다.
      이슈의 그날 기사 키에 None 을 주면 그룹 쪽만 본다. 여럿 가운데 어느 것을 쓸지는 부르는 쪽이 고른다(link.Linker.same_day 의
      중심 낱말 조건). 맨 앞 하나만 돌려주면 그것이 조건에서 떨어질 때 뒤의 맞는 검색어를 보지 못한다.
    rule.seeds(그룹, 날, 언어) → 그룹 쪽에 맞는 검색어가 맞을 수 있는 기사 키(낱말과 제목의 역색인에서). 어떤 이슈가 그 검색어에
      맞으려면 이 기사 가운데 하나를 가져야 한다. 급상승어 갈래만 보면 부르는 쪽은 그날 이슈 전체가 아니라 이 기사를 가진 이슈만
      보면 된다. 검색어를 요구하지 않는 갈래(드문 사건 낱말)의 후보는 이것으로 찾을 수 없다. 검색어가 새 그룹에만 맞으면 이 기사는
      그 그룹의 것뿐이다. 그 후보는 부르는 쪽이 따로 찾는다(link.Linker._with_trend_candidates 의 core_idx).
    그룹 쪽에 맞는 검색어는 그룹마다 한 번만 찾고, 이슈 쪽 기사 묶음의 분석(side_of)은 기사 구성이 같으면 다시 하지 않는다."""

    SIDE_KEEP = 4096      # 기억해 두는 이슈 쪽 분석 수(넘으면 비운다)

    def __init__(self, trends: list[dict], arts: dict):
        self.arts = arts
        self.by_day: dict[tuple, list] = {}
        for t in sorted(trends, key=lambda x: x["key"]):
            self.by_day.setdefault((t["day"], t["lang"]), []).append(t)
        self._group: dict[str, list] = {}           # 그룹 번호 → 그룹 쪽에 맞는 [(검색어, 맞은 딸린 기사 제목들)]
        self._side: dict[frozenset, tuple] = {}     # 기사 키 묶음 → side_of
        self._seed: dict[str, frozenset] = {}       # 검색어 키 → 그 검색어가 맞을 수 있는 기사 키
        self._idx: dict[str, tuple] = {}            # 언어 → (낱말 → 기사 키, [(기사 키, 정규화한 제목)])

    def _of_group(self, group: dict, day: str, lang: str) -> list[tuple]:
        ts = self.by_day.get((day, lang))
        if not ts:
            return []
        gid = group["group_id"]
        if gid not in self._group:
            side = side_of([self.arts[k] for k in [*group["units"], *(group.get("copies") or [])] if k in self.arts])
            hits = [(t, matched_news(t, side, strict=True)) for t in ts]
            self._group[gid] = [(t, h) for t, h in hits if h is not None]
        return self._group[gid]

    def _side_of(self, keys) -> tuple:
        fk = frozenset(keys)
        if fk not in self._side:
            if len(self._side) >= self.SIDE_KEEP:
                self._side.clear()
            self._side[fk] = side_of([self.arts[k] for k in sorted(fk) if k in self.arts])
        return self._side[fk]

    def __call__(self, group: dict, issue_keys, day: str, lang: str) -> list[tuple[str, frozenset]]:
        ts = self._of_group(group, day, lang)
        if ts and issue_keys is not None:
            side = self._side_of(issue_keys)
            both = []
            for t, gh in ts:
                ih = matched_news(t, side, strict=True)
                if ih is not None and same_news(gh, ih):
                    both.append((t, gh))
            ts = both
        return [(t["title"], kw_words(t)) for t, _ in ts]

    def _index(self, lang: str) -> tuple[dict, list]:
        if lang not in self._idx:
            words: dict[str, set] = {}
            norms = []
            for k, a in self.arts.items():
                if a.get("lang") != lang or a.get("kind") == "trend":
                    continue
                for w in [*(a.get("terms") or ()), *(a.get("entities") or ())]:
                    words.setdefault(w, set()).add(k)
                norms.append((k, a.get("norm_title") or text.norm_title(a["title"])))
            self._idx[lang] = (words, norms)
        return self._idx[lang]

    def _seed_keys(self, t: dict) -> frozenset:
        """검색어 t 의 낱말 조건(strict)을 채울 수 있는 기사: 제목에 검색어의 띄어쓰기 없는 꼴이 든 기사와, 검색어 낱말 가운데
        가장 드문 낱말을 가진 기사. 낱말 조건은 검색어 낱말 전부가 이슈 쪽에 있어야 하므로 한 낱말만 보아도 빠지는 이슈가 없다."""
        if t["key"] not in self._seed:
            words, norms = self._index(t["lang"])
            ents, terms, forms = _kw_parts(t["title"], t["lang"])
            keys = {k for k, n in norms if any(f in n for f in forms)} if forms else set()
            ws = ents | terms
            if ws:
                keys |= words.get(min(ws, key=lambda w: (len(words.get(w, ())), w)), set())
            self._seed[t["key"]] = frozenset(keys)
        return self._seed[t["key"]]

    def seeds(self, group: dict, day: str, lang: str) -> set:
        out: set = set()
        for t, _ in self._of_group(group, day, lang):
            out |= self._seed_keys(t)
        return out


def pair_rule(trends: list[dict], arts: dict) -> PairRule:
    """같은 날 잇기의 급상승어 갈래(PairRule)를 만든다. trends: 이번 단계에 쓰는 검색어, arts: 기사 키 → 기사."""
    return PairRule(trends, arts)


def group_hit(group: dict, trends: list[dict], arts: dict) -> bool:
    """계열 1곳 그룹의 새 이슈 조건(§4-2): 같은 날·같은 언어 검색어 가운데 이 그룹에 맞는 것이 있나."""
    ts = [t for t in trends if t["day"] == group["day"] and t["lang"] == group["lang"]]
    if not ts:
        return False
    side = side_of([arts[k] for k in [*group["units"], *(group.get("copies") or [])] if k in arts])
    return any(match(t, side)[0] for t in ts)
