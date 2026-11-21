"""스킬 따라가기용 지어낸 자료 묶음(tests/fixtures/skills/)과 시험 사본 만들기(make_sandbox.py).

자료는 공개 저장소에 들어가므로 전부 지어낸 것이어야 한다. 사본은 임시 폴더에 만들고, 실제 자료(private/)에는 쓰지 않는다.
"""
import importlib.util
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from ozl.syuka import schema_v3
from ozl import paths as ozlpaths  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FX = REPO / "tests" / "fixtures" / "skills"
KIT = FX / "kit"
ROW = re.compile(r"^\|\s*`(https://[^`]+)`\s*\|\s*`([^`]+)`\s*\|")
FILE_ROW = re.compile(r"^\|\s*`((?!https:)[^`]+\.(?:md|html))`\s*\|")
# 실제 기관과 서비스의 이름이 섞이지 않았는지 보는 작은 목록(전부를 잡지는 못한다. 지어낸 이름만 쓴다는 규칙의 안전망이다)
REAL_NAMES = ("한국은행", "금융감독원", "금융위원회", "서울", "따릉이", "국토교통부", "기획재정부", "슈카월드")


def _load_maker():
    spec = importlib.util.spec_from_file_location("make_sandbox", FX / "make_sandbox.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _kit_table():
    out = []
    for line in (KIT / "README.md").read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def test_kit_readme_lists_every_document_with_an_example_address():
    table = _kit_table()
    assert len(table) == 9                                   # 사건 7(공식 3, 설명자료 1, 기사 요지 3), 덱 소재 2
    for url, rel in table:
        assert re.match(r"https://[a-z0-9.-]+\.example/", url), url   # 실제로 열리지 않는 주소
        assert (KIT / rel).is_file(), rel
    listed = {rel for _, rel in table} | {m.group(1) for line in (KIT / "README.md").read_text(encoding="utf-8").splitlines()
                                          if (m := FILE_ROW.match(line))}
    on_disk = {str(p.relative_to(KIT)) for p in KIT.rglob("*") if p.is_file() and p.suffix in (".html", ".md") and p.name != "README.md"}
    assert on_disk == listed                                 # 안내에 없는 문서도, 없는 파일을 가리키는 줄도 없다


def test_kit_has_the_planned_pieces():
    ev = KIT / "event_garam"
    assert len(list(ev.glob("official_*.html"))) == 3 and len(list(ev.glob("followup_*.html"))) == 1
    assert len(list(ev.glob("news_*.md"))) == 3
    assert len(list((KIT / "deck_bike").glob("official_*.html"))) == 2
    assert (KIT / "sponsor" / "sponsor_brief.md").is_file()
    hosts = {re.match(r"https://([^/]+)/", u).group(1) for u, _ in _kit_table()}
    assert hosts == {p.stem for p in (KIT / "robots").glob("*.txt")}   # 사이트마다 robots.txt 사본


@pytest.mark.parametrize("p", sorted(KIT.rglob("*.html")), ids=lambda p: p.name)
def test_official_copies_are_marked_fabricated_and_long_enough(p):
    html = p.read_text(encoding="utf-8")
    body = _text(html)
    assert "지어낸 문서" in body
    assert len(body) >= 300                                  # 원문 대조는 80자보다 짧은 글을 프로그램으로 맞추지 못한다
    assert "<title>" in html and 'charset="utf-8"' in html


def test_news_gists_are_gists_not_article_bodies():
    for p in sorted((KIT / "event_garam").glob("news_*.md")):
        t = p.read_text(encoding="utf-8")
        assert "기사 본문이 아니다" in t and "https://news.example/" in t
        assert all(k in t for k in ("- 매체:", "- 제목:", "- 날짜:", "- 주소:"))


def test_fixture_texts_use_no_real_names():
    for p in sorted(FX.rglob("*")):
        if p.is_file() and p.suffix in (".html", ".md", ".json", ".csv"):
            t = p.read_text(encoding="utf-8")
            hit = [n for n in REAL_NAMES if n in t]
            assert not hit, f"{p.relative_to(FX)}: {hit}"


def test_event_numbers_agree_across_the_kit():
    """문서끼리 수치가 맞아야 따라가기의 판정이 자료 탓에 흔들리지 않는다."""
    notice = _text((KIT / "event_garam" / "official_1_notice.html").read_text(encoding="utf-8"))
    table = (KIT / "event_garam" / "official_2_rate_table.html").read_text(encoding="utf-8")
    cells = re.findall(r"<tr><td>(\d+)개월</td><td>([\d.]+)%</td><td>([\d.]+)%</td><td>([\d.]+)%포인트</td></tr>", table)
    assert [c[0] for c in cells] == ["6", "12", "24", "36"]
    for _, before, after, cut in cells:
        assert round(float(before) - float(after), 1) == float(cut)
    assert "연 3.2%에서 연 2.9%로" in notice and dict((c[0], c[3]) for c in cells) == {"6": "0.2", "12": "0.3", "24": "0.3", "36": "0.3"}
    stats = (KIT / "deck_bike" / "official_2_stats.html").read_text(encoding="utf-8")
    rows = [[int(x.replace(",", "")) for x in r] for r in re.findall(
        r"<tr><td>(\d{4})</td><td>([\d,]+)</td><td>([\d,]+)</td><td>([\d,]+)</td><td>(\d+)</td><td>(\d+)</td><td>(\d+)</td></tr>", stats)]
    assert len(rows) == 5 and all(cost - income == loss for *_, income, cost, loss in rows)
    press = _text((KIT / "deck_bike" / "official_1_press.html").read_text(encoding="utf-8"))
    assert "1,240만 건" in press and "22.8%" in press and round((1240 / 1010 - 1) * 100, 1) == 22.8


def test_syuka_fixtures_pass_the_v3_schema():
    videos = json.loads((FX / "syuka_v3" / "videos.json").read_text(encoding="utf-8"))["videos"]
    up = {v["video_id"]: v["upload_at"] for v in videos}
    docs = sorted((FX / "syuka_v3").glob("fake*.json"))
    assert len(docs) == 5 and {p.stem for p in docs} == set(up)
    from ozl.research import cards
    # 카드의 coverage.videos 에 관계를 붙이려면 영상 번호가 유튜브 번호 꼴(11자)이어야 한다(cards.YT_ID)
    assert all(cards.YT_ID.fullmatch(v) for v in up), sorted(up)
    for p in docs:
        d = json.loads(p.read_text(encoding="utf-8"))
        assert schema_v3.validate_file(d, None, up[d["video_id"]]) == [], p.name
        assert "지어낸 영상" in next(v["title"] for v in videos if v["video_id"] == d["video_id"])


def test_syuka_meta_fixtures_match_the_v3_fixtures():
    """지어낸 영상 목록, 주제 태그, 전사가 3판 자료의 같은 다섯 편을 가리키고, 전사는 지어낸 것이라고 적혀 있다."""
    import csv
    from ozl.research import cards, videos as V
    meta = FX / "syuka_meta"
    listed = {v["video_id"]: v for v in json.loads((FX / "syuka_v3" / "videos.json").read_text(encoding="utf-8"))["videos"]}
    with (meta / "catalog_syukaworld.csv").open(encoding="utf-8") as f:
        cat = list(csv.DictReader(f))
    assert {r["video_id"] for r in cat} == set(listed)
    for r in cat:
        assert r["title"] == listed[r["video_id"]]["title"] and r["published_kst"][:10] == listed[r["video_id"]]["upload_at"][:10]
    with (meta / "video_tags_syukaworld.csv").open(encoding="utf-8") as f:
        rd = csv.DictReader(f)
        assert rd.fieldnames == V.COLS
        tags = list(rd)
    assert {r["video_id"] for r in tags} == set(listed)
    for r in tags:
        assert r["category"] in cards.CATEGORIES and r["category2"] in ("", *cards.CATEGORIES)
        assert 1 <= len(r["keywords"].split("|")) <= V.MAX_KEYWORDS and len(r["gist"]) <= V.GIST_MAX
    docs = sorted((meta / "transcripts").glob("*.json"))
    assert {p.stem for p in docs} == {"fakeSYK0001", "fakeSYK0002", "fakeSYK0005"}
    for p in docs:
        d = json.loads(p.read_text(encoding="utf-8"))
        assert "지어낸 방송의 지어낸 말" in d["text"] and "지어낸 전사" in d["note"] and d["exported_at"] < "2099-01-02"
    with (meta / "transcripts_index.csv").open(encoding="utf-8") as f:
        idx = {r["video_id"]: r for r in csv.DictReader(f)}
    assert set(idx) == set(listed) and idx["fakeSYK0005"]["is_live_full"] == "1"
    assert {v for v, r in idx.items() if r["has_transcript"] == "1"} == {p.stem for p in docs}


@pytest.mark.skipif(not (REPO / ".venv").is_dir(), reason="저장소의 가상 환경이 있어야 시험 사본을 만든다(CI 에는 없다)")
def test_make_sandbox_builds_a_copy_that_runs_its_own_code(tmp_path):
    m = _load_maker()
    real_db = ozlpaths.real_at("syuka", "syuka.db")
    before = real_db.stat().st_mtime_ns if real_db.exists() else None
    box = m.build(tmp_path / "사본", git=False)
    for rel in ("src/ozl/issues/paths.py", "tracks", "skills/ozl/SKILL.md", ".claude/skills/ozl/SKILL.md", "agent/issues.md",
                "CLAUDE.md", "README.md", "docs/how-it-works.md", "tests/fixtures/issues/i20990101-01/issue.yaml", "private/live/pulse/out/board.json",
                "private/test_desk/issues/i20990101-02/issue.yaml", "kit/README.md", "kit/event_garam/official_1_notice.html",
                "private/data/derived/syuka/syuka.db", "private/data/raw/meta/catalog_syukaworld.csv", "private/data/raw/meta/video_tags_syukaworld.csv",
                "private/data/raw/transcripts/trading_export/index.csv", "private/data/raw/transcripts/trading_export/syuka/fakeSYK0002.json"):
        assert (box / rel).exists(), rel
    assert (box / ".venv").is_symlink() and not (box / ".git").exists()
    assert not (ozlpaths.under(box / "private", "desk")).exists()                    # 실제 자료 루트 자리는 비워 둔다
    assert (ozlpaths.under(box / "private", "decks", "drafts")).is_dir()            # 덱 빌드가 산출 폴더를 만들 자리
    assert not list(box.rglob("__pycache__"))
    con = sqlite3.connect(ozlpaths.under(box / "private", "syuka", "syuka.db"))
    try:
        assert con.execute("SELECT COUNT(*) FROM v3_videos").fetchone()[0] == 5
        assert con.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 5
        assert con.execute("SELECT COUNT(*) FROM v3_segments").fetchone()[0] == 7
    finally:
        con.close()
    env = m.sandbox_env(box)
    py = str(box / ".venv" / "bin" / "python")
    r = subprocess.run([py, "-c", "from ozl.research import cards; from ozl.issues import paths; print(cards.ROOT); print(paths.desk_root())"],
                       cwd=box, env=env, capture_output=True, text=True, check=True)
    root, desk = r.stdout.split()
    assert Path(root).resolve() == box and Path(desk) == box / "private" / "test_desk"
    r = subprocess.run([py, ".claude/skills/ozl/find/board_view.py", "--top", "3"], cwd=box, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "t20990101-002" in r.stdout and "i20990101-01" in r.stdout
    r = subprocess.run([py, "-m", "ozl.syuka", "find-v3", "자전거"], cwd=box, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "fakeSYK0002" in r.stdout
    # 주제 태그와 전사 본문 찾기도 사본의 지어낸 자료로 돈다(전사 본문은 지어낸 날짜에 맞춘 --asof 로)
    r = subprocess.run([py, "-m", "ozl.research.videos", "find", "--keyword", "공유 자전거"], cwd=box, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "fakeSYK0002" in r.stdout and "중심 1편" in r.stdout
    r = subprocess.run([py, "-m", "ozl.research", "coverage", "자전거", "--months", "6", "--fulltext", "--asof", "2099-01-02T12:00"],
                       cwd=box, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "fakeSYK0001" in r.stdout and "본문 1회" in r.stdout      # 스쳐 말한 영상
    assert "fakeSYK0002" not in r.stdout and "fakeSYK0003" in r.stdout                    # 26주 밖의 영상, 전사 없는 최근 영상
    r = subprocess.run([py, "-m", "ozl.research", "coverage", "자전거", "--months", "24", "--fulltext", "--asof", "2099-01-02T12:00"],
                       cwd=box, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "fakeSYK0002" in r.stdout and "전사 3편 훑음" in r.stdout
    if before is not None:
        assert real_db.stat().st_mtime_ns == before                   # 실제 슈카 DB 는 건드리지 않는다


def test_make_sandbox_refuses_bad_targets(tmp_path):
    m = _load_maker()
    full = tmp_path / "찬폴더"
    full.mkdir()
    (full / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(m.Stop):
        m.build(full, git=False)
    with pytest.raises(m.Stop):
        m.build(REPO, git=False)
    with pytest.raises(m.Stop):
        m.build(REPO.parent, git=False)


@pytest.mark.skipif(not (REPO / ".venv").is_dir(), reason="저장소의 가상 환경이 있어야 시험 사본을 만든다(CI 에는 없다)")
def test_make_sandbox_stops_when_root_is_not_the_copy(tmp_path, monkeypatch):
    """사본의 코드가 아니라 다른 저장소의 코드가 잡히면 종료 코드 3 으로 멈춘다."""
    m = _load_maker()
    real_run = subprocess.run

    def fake(cmd, *a, **kw):
        if isinstance(cmd, list) and len(cmd) == 3 and "cards.ROOT" in cmd[2]:
            return subprocess.CompletedProcess(cmd, 0, stdout="/지어낸/다른/저장소\n", stderr="")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(m.subprocess, "run", fake)
    with pytest.raises(m.Stop) as e:
        m.build(tmp_path / "사본", git=False)
    assert e.value.code == 3
