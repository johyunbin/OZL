"""급상승 검색어를 이슈와 그룹에 잇기(§5-2). 검색어의 날짜는 오른 시각(published)의 KST 날짜이고, 같은 언어의 이슈에만 잇는다.

1. 낱말 조건. 둘 가운데 하나(2026-11-15 완화. 그 전에는 '검색어 낱말 전부가 이슈 쪽 낱말에 들어 있다' 하나였다):
   (가) 띄어쓰기와 조사를 무시한 꼴: 검색어의 공백을 뺀 꼴, 또는 어절마다 조사를 뗀 뒤 이은 꼴(3글자 이상)이 이슈 기사 제목의
        정규화한 꼴(글자와 숫자만) 하나에 들어 있다('주한 미군의 철수' → '주한미군철수').
   (나) 검색어의 고유명사(entities)는 전부, 나머지 낱말(terms)은 절반 이상(올림)이 이슈 쪽 낱말(d−1 ~ d 기사)에 들어 있다.
   검색어 낱말이 비어 있으면 (가)만 본다.
2. 딸린 기사(trend_news)가 있으면: 그 제목과 이슈 기사 제목 하나의 Dice ≥ 0.50, 또는 딸린 기사 낱말에서 검색어 낱말을 뺀 나머지가
   이슈 쪽과 2개 이상 겹친다.
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


def match(t: dict, side: tuple, strict: bool = False) -> tuple[bool, float, int, str | None]:
    """(맞는가, Dice, 겹친 수, 맞은 기사 키). strict 면 낱말 조건을 '전부 포함'으로 본다(같은 날 잇기의 급상승어 갈래)."""
    words, tbs = side[0], side[1]
    norms = side[2] if len(side) > 2 else tuple()
    kw = kw_words(t)
    if not words_ok(t, words, norms, strict):
        return False, 0.0, 0, None
    nt = news_title(t)
    if nt:
        ntb = text.bigrams(text.norm_title(nt))
        best, key = 0.0, None
        for k, tb in tbs:
            dv = text.dice(ntb, tb)
            if dv > best:
                best, key = dv, k
        over = len((_words(nt, t["lang"]) - kw) & words)
        ok = best >= config.TREND_NEWS_DICE or over >= config.TREND_NEWS_OVERLAP
        return ok, best, over, key if best >= config.TREND_NEWS_DICE else None
    return len(kw) >= config.TREND_MIN_WORDS, 0.0, 0, None


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
        self._group: dict[str, list] = {}           # 그룹 번호 → 그룹 쪽에 맞는 검색어
        self._side: dict[frozenset, tuple] = {}     # 기사 키 묶음 → side_of
        self._seed: dict[str, frozenset] = {}       # 검색어 키 → 그 검색어가 맞을 수 있는 기사 키
        self._idx: dict[str, tuple] = {}            # 언어 → (낱말 → 기사 키, [(기사 키, 정규화한 제목)])

    def _of_group(self, group: dict, day: str, lang: str) -> list[dict]:
        ts = self.by_day.get((day, lang))
        if not ts:
            return []
        gid = group["group_id"]
        if gid not in self._group:
            side = side_of([self.arts[k] for k in [*group["units"], *(group.get("copies") or [])] if k in self.arts])
            self._group[gid] = [t for t in ts if match(t, side, strict=True)[0]]
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
            ts = [t for t in ts if match(t, side, strict=True)[0]]
        return [(t["title"], kw_words(t)) for t in ts]

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
        for t in self._of_group(group, day, lang):
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
