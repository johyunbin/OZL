"""원문 화면 갈무리 — 공식 문서와 통계 화면을 그림으로 찍고 그림 검수 대장 칸 초안을 낸다.

    python -m ozl.render shot <url> --out <png> [--width 1280 --height 900] [--clip x,y,w,h] [--scale 2]
    python -m ozl.render shot --pdf <저장된 PDF 사본> --page <쪽> --source-url <원문 주소> --out <png> [--dpi 150] [--band 위,아래]

웹 화면(shot):
  1. 페이지를 단계마다 받는다(fetch_chain). 한 단계 = 그 호스트의 robots.txt 확인 → 같은 호스트 MIN_GAP 초 간격 → 요청 한 번.
     - robots.txt 는 urllib.robotparser 로 읽는다(사용자 에이전트 이름 UA_TOKEN). 한 실행 안에서 같은 호스트의 규칙은 한 번만 받는다.
       404·410 이면 막는 규칙이 없는 것으로, 401·403 이면 전부 막힌 것으로 본다(robotparser 와 같은 뜻).
       그 밖의 오류(5xx · 연결 실패)면 규칙을 확인하지 못했으므로 멈춘다. robots.txt 자체의 30x 는 다섯 번까지 따라간다.
     - 요청은 리다이렉트를 자동으로 따라가지 않는다(_NoRedirect). 30x 응답이면 Location 을 다음 단계의 주소로 삼고,
       본문의 <meta http-equiv="refresh">(META_REFRESH_MAX_DELAY 초 이하, 주석과 <noscript> 안의 것은 빼고)도 한 단계로 센다.
       단계는 MAX_HOPS 까지다.
     - 넘어갈 호스트의 robots.txt 가 그 경로를 막으면 그 주소를 받지 않고 멈춘다(넘어간 곳의 페이지 요청 0번).
       넘어갈 주소가 http(s) 가 아니거나 로그인 주소이거나, MAX_HOPS 단계를 넘겨도 넘어가라고 하면 멈춘다.
     - 호스트별 마지막 요청 시각을 HOST_LOG 에 적어 명령을 여러 번 불러도 간격을 지킨다.
  2. 단계마다 차단 응답(401 · 403 · 429 · 451 · 503 등), 로그인 화면(비밀번호 칸 · 로그인 주소), CAPTCHA 흔적이 있는지 본다.
     있으면 멈추고 그렇게 적는다(우회하지 않는다).
  3. 마지막 주소를 Chrome headless 로, 매번 새 임시 사용자 폴더로 띄워 찍는다(사용자 프로필과 쿠키를 쓰지 않고, 로그인하지 않는다).
  4. --clip x,y,w,h 를 주면 찍은 화면에서 그 범위(CSS 픽셀, 창 왼쪽 위가 0,0)만 남긴다. 찍는 범위를 고른 것이라 as_is 는 참 그대로다.
     --scale N(1~4)은 화면 배율이다(Chrome --force-device-scale-factor). 창과 범위는 CSS 픽셀 그대로이고 그림 픽셀만 N 배가 된다 —
     작은 그래프 글자를 큰 자리에 놓을 때 흐려지지 않게 쓴다. 1 이 아니면 shot_log.scale 에 적는다.
  5. PNG 옆에 같은 이름의 .yaml 로 대장 칸 초안(종류 '원문 화면 갈무리', 해시, 받은 시각, 주소, 단계 기록 shot_log.hops, 창 크기와 범위)을 쓴다.
     권리자, 라이선스, 상업적 이용, 변경, 내용 점검은 비워 둔다 — 사람이나 에이전트가 기관의 이용 조건을 읽고 채운다(비면 엄격 모드 실패).
PDF(--pdf): 저장된 사본에서 pdftoppm 으로 한 쪽을 그림으로 만든다. 웹을 다시 열지 않는다.
  --band 위,아래 를 주면 쪽 높이의 그 비율 구간(0~1, 예: 0.2,0.55)만 남긴다. 구간은 shot_log.band 에 적는다.

못 하는 것(한계):
  - 스크립트가 일으키는 이동(location 바꾸기 등)은 미리 알 수 없다. Chrome 이 마지막 주소를 연 뒤 스크립트로 다른 호스트에 넘어가면
    그 호스트의 robots.txt 는 보지 못한다. 찍힌 화면이 요청한 곳과 다르면 그 그림을 쓰지 않는다(사람이나 에이전트가 그림을 본다).
  - Chrome 이 화면을 그리며 받는 딸린 자원(그림, 글꼴, 스크립트)의 호스트는 robots.txt 를 보지 않는다(보통의 브라우저와 같다).
  - --clip 은 창 안의 범위만 고른다. 창보다 긴 화면은 --height 를 늘려 찍은 뒤 범위를 준다.

종료 코드: 0 찍음 · 3 멈춤(robots · 차단 · 로그인 · CAPTCHA · 넘어갈 수 없는 주소 · 단계 초과 · 빈 화면) · 2 사용법 · 1 그 밖의 오류.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit
from ozl import paths as ozlpaths

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHROME = pathlib.Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
UA_TOKEN = "ozl-shot"
USER_AGENT = f"Mozilla/5.0 (compatible; {UA_TOKEN}/1.0)"   # 사용자 이름·주소를 넣지 않는다
MIN_GAP = 2.0
HOST_LOG = ozlpaths.at("decks", "shots", "host_times.json")
TIMEOUT = 20
CHROME_TIMEOUT = 120               # Chrome 한 번이 화면을 찍는 데 주는 시간(초) — 넘으면 오류로 끝낸다
BLOCK_STATUS = {401: "인증 요구", 403: "접근 거부", 407: "프록시 인증 요구", 429: "요청이 너무 잦다", 451: "법적 사유로 막음", 503: "서비스 불가(차단일 수 있다)"}
CAPTCHA = re.compile(r"captcha|g-recaptcha|hcaptcha|cf-chl|challenge-platform|turnstile|보안\s*문자|자동\s*입력\s*방지", re.IGNORECASE)
PASSWORD = re.compile(r"<input[^>]+type\s*=\s*[\"']?password", re.IGNORECASE)
LOGIN_PATH = re.compile(r"/(login|signin|sign-in|sso|auth)(/|\.|$|\?)", re.IGNORECASE)
KIND = "원문 화면 갈무리"
MAX_HOPS = 5                       # 한 번의 shot 이 페이지를 요청하는 단계 수의 상한(처음 주소 포함)
REDIRECT_STATUS = (301, 302, 303, 307, 308)
META_REFRESH = re.compile(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[\"']?[^>]*>", re.IGNORECASE)
META_CONTENT = re.compile(r"content\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.IGNORECASE)
META_REFRESH_MAX_DELAY = 10.0      # 이보다 늦게 넘어가는 meta refresh 는 단계로 세지 않는다(Chrome 이 찍기 전에 넘어가지 않는다)
NOT_RENDERED = re.compile(r"<!--.*?-->|<noscript\b.*?</noscript\s*>", re.IGNORECASE | re.DOTALL)   # 스크립트를 켠 브라우저가 따르지 않는 자리


class Stop(Exception):
    """찍지 않고 멈춘다(robots · 차단 · 로그인 · CAPTCHA · 넘어갈 수 없는 주소 · 단계 초과 · 빈 화면). 까닭은 str(e).
    페이지를 받다가 멈췄으면 hops 에 그때까지의 단계 기록이 있다(fetch_chain)."""
    hops: list = []
    robots: dict | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """30x 를 따라가지 않는다 — 넘어갈 주소는 fetch_chain 이 그 호스트의 robots.txt 를 본 뒤에 직접 요청한다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(req, timeout):
    return _OPENER.open(req, timeout=timeout)


def _get(url: str, opener, limit: int = 2_000_000) -> tuple[int, str, str, str]:
    """(상태 코드, 응답 주소, 글, Location 머리). 30x · 4xx · 5xx 도 상태 코드로 돌려준다(기본 요청기는 30x 를 따라가지 않는다)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.5"})
    try:
        r = opener(req, TIMEOUT)
    except urllib.error.HTTPError as e:
        body = e.read(limit) if hasattr(e, "read") else b""
        loc = (e.headers.get("Location") or "") if getattr(e, "headers", None) is not None else ""
        return e.code, url, body.decode("utf-8", "replace"), loc.strip()
    try:
        status = getattr(r, "status", 200)
        final = r.geturl() if hasattr(r, "geturl") else url
        body = r.read(limit)
    finally:
        r.close()
    return status, final, body.decode("utf-8", "replace"), ""


class HostClock:
    """같은 호스트 요청 사이 MIN_GAP 초. 마지막 요청 시각은 파일(path)에도 적어 명령 사이에서도 지킨다."""

    def __init__(self, path: pathlib.Path | None = HOST_LOG, sleep=time.sleep, clock=time.time, gap: float = MIN_GAP):
        self.path, self.sleep, self.clock, self.gap = path, sleep, clock, gap
        self.last: dict[str, float] = {}
        if path is not None and path.is_file():
            try:
                self.last = {k: float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
            except (ValueError, OSError):
                self.last = {}

    def wait(self, host: str) -> float:
        now = self.clock()
        need = self.last.get(host, -1e18) + self.gap - now
        if need > 0:
            self.sleep(need)
        return max(need, 0.0)

    def mark(self, host: str) -> None:
        self.last[host] = self.clock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.last, ensure_ascii=False), encoding="utf-8")


def robots_url(url: str) -> str:
    u = urlsplit(url)
    return urlunsplit((u.scheme, u.netloc, "/robots.txt", "", ""))


def _robots_fetch(ru: str, opener, clock: HostClock) -> tuple[int, str]:
    """robots.txt 를 받는다 — (상태 코드, 글). robots.txt 자체의 30x 는 MAX_HOPS 번까지 따라간다(요청마다 그 호스트의 간격을 지킨다).
    끝까지 30x 면 그 상태 코드를 그대로 돌려준다(robots_allows 가 '확인하지 못함'으로 멈춘다)."""
    url, status, text = ru, 0, ""
    for _ in range(MAX_HOPS):
        host = urlsplit(url).hostname or ""
        clock.wait(host)
        try:
            status, _, text, loc = _get(url, opener, 500_000)
        finally:
            clock.mark(host)
        nxt = urljoin(url, loc) if status in REDIRECT_STATUS and loc else ""
        if not nxt.startswith(("https://", "http://")):
            break
        url = nxt
    return status, text


def robots_allows(url: str, opener, clock: HostClock, log, cache: dict | None = None) -> dict:
    """robots.txt 를 받아 이 주소를 받아도 되는지 — {robots_url, status, allowed, rule, cached}. 확인하지 못하면 Stop.
    cache(실행 하나의 기억)를 주면 같은 호스트(scheme://netloc)의 규칙은 한 번만 받고, 다음부터는 받아 둔 규칙으로 경로만 다시 본다.
    막혔으면 Stop(x.robots 에 이 기록)."""
    ru = robots_url(url)
    cached = cache is not None and ru in cache
    if cached:
        status, text = cache[ru]
    else:
        try:
            status, text = _robots_fetch(ru, opener, clock)
        except Exception as e:  # noqa: BLE001 — 연결 실패는 규칙을 확인하지 못한 것
            raise Stop(f"robots.txt 를 받지 못했다({type(e).__name__}: {e}) — 규칙을 확인하지 못해 멈춘다: {ru}") from e
        if cache is not None:
            cache[ru] = (status, text)
    rp = urllib.robotparser.RobotFileParser()
    if status in (401, 403):
        allowed, rule = False, f"robots.txt {status} — 전부 막힌 것으로 본다"
    elif status in (404, 410):
        allowed, rule = True, f"robots.txt {status} — 막는 규칙이 없다"
    elif 200 <= status < 300:
        rp.parse(text.splitlines())
        allowed = rp.can_fetch(UA_TOKEN, url)
        rule = f"robots.txt {status} — {UA_TOKEN} 에게 {'허용' if allowed else '막힘'}"
    else:
        log(f"[robots] {ru} {status} — 확인하지 못함")
        raise Stop(f"robots.txt 가 {status} 이다 — 규칙을 확인하지 못해 멈춘다: {ru}")
    log(f"[robots] {ru} · {rule} · 대상 {urlsplit(url).path or '/'}" + (" · 이 실행에서 받아 둔 규칙" if cached else ""))
    rec = {"robots_url": ru, "status": status, "allowed": allowed, "rule": rule, "cached": cached}
    if not allowed:
        x = Stop(f"robots.txt 가 이 경로를 막는다({rule}): {url}")
        x.robots = rec
        raise x
    return rec


def meta_refresh_target(html: str) -> str:
    """본문의 <meta http-equiv="refresh" content="초; url=주소"> 가 가리키는 주소(없거나 META_REFRESH_MAX_DELAY 보다 늦으면 빈 문자열).
    주소 없이 초만 적은 것(제자리 새로 고침)은 넘어가는 것이 아니다. 주석과 <noscript> 안의 것은 세지 않는다
    (Chrome 은 스크립트를 켜고 찍으므로 그 자리의 meta 를 따르지 않는다)."""
    for m in META_REFRESH.finditer(NOT_RENDERED.sub(" ", html or "")):
        c = META_CONTENT.search(m.group(0))
        if not c:
            continue
        content = next((g for g in c.groups() if g is not None), "").strip()
        head, sep, tail = content.partition(";")
        if not sep:
            head, sep, tail = content.partition(",")
        try:
            delay = float(head.strip() or 0)
        except ValueError:
            continue
        target = re.sub(r"^\s*url\s*=\s*", "", tail, flags=re.IGNORECASE).strip().strip("'\"").strip()
        if sep and target and delay <= META_REFRESH_MAX_DELAY:
            return target
    return ""


def fetch_chain(url: str, opener=_open, clock: HostClock | None = None, log=print) -> dict:
    """페이지를 단계마다 받는다 — {final_url, status, html, hops}. 한 단계 = 그 호스트의 robots.txt 확인 → 간격 → 요청 한 번.
    30x 의 Location 과 본문의 meta refresh 는 다음 단계의 주소다(MAX_HOPS 단계까지). 넘어갈 호스트의 robots.txt 가 막으면
    그 주소를 요청하지 않고 Stop. hops 의 한 줄 = {n, url, via, robots, waited, status, next, next_via}(멈춘 단계는 stopped 에 까닭).
    Chrome 은 띄우지 않는다."""
    clock = clock or HostClock(HOST_LOG)
    hops: list[dict] = []
    cache: dict = {}

    def stop(msg: str, hop: dict | None = None):
        if hop is not None:
            hop["stopped"] = msg
        x = Stop(msg)
        x.hops = hops
        return x

    cur, via = url, "요청한 주소"
    for n in range(1, MAX_HOPS + 1):
        hop = {"n": n, "url": cur, "via": via}
        hops.append(hop)
        try:
            hop["robots"] = robots_allows(cur, opener, clock, log, cache)
        except Stop as x:
            hop["robots"], hop["stopped"] = x.robots, str(x)
            x.hops = hops
            raise
        host = urlsplit(cur).hostname or ""
        hop["waited"] = round(clock.wait(host), 1)
        try:
            status, got, html, loc = _get(cur, opener)
        finally:
            clock.mark(host)
        hop["status"] = status
        log(f"[page] {cur} · 응답 {status} · {n}단계({via}) · 앞서 {hop['waited']:.1f}초 기다림")
        if status in REDIRECT_STATUS:
            if not loc:
                raise stop(f"응답 {status} 에 넘어갈 주소(Location)가 없다 — 멈춘다: {cur}", hop)
            nxt, how = urljoin(cur, loc), f"응답 {status} 의 Location"
        elif 300 <= status < 400:
            raise stop(f"응답 {status} — 넘어갈 곳을 알 수 없는 응답이다. 멈춘다: {cur}", hop)
        else:
            why = block_reason(status, got, html)
            if why:
                raise stop(f"{why} — 찍지 않고 멈춘다: {cur}", hop)
            target = meta_refresh_target(html)
            nxt, how = (urljoin(cur, target), "meta refresh") if target else ("", "")
            if not nxt or nxt == cur:
                return {"final_url": got if got.startswith(("https://", "http://")) else cur, "status": status, "html": html, "hops": hops}
        if not nxt.startswith(("https://", "http://")):
            raise stop(f"넘어갈 주소가 http(s) 가 아니다({how}): {nxt[:120]}", hop)
        if LOGIN_PATH.search(urlsplit(nxt).path or ""):
            raise stop(f"로그인 주소로 넘어가라는 응답이다({how}) — 받지 않고 멈춘다: {nxt}", hop)
        hop["next"], hop["next_via"] = nxt, how
        log(f"[hop] {n}단계 → {nxt} · {how}")
        cur, via = nxt, how
    raise stop(f"{MAX_HOPS}단계를 받고도 또 넘어가라고 한다 — 멈춘다(마지막으로 가리킨 주소는 받지 않았다): {cur}", hops[-1])


def block_reason(status: int, final_url: str, html: str) -> str:
    """차단 응답 · 로그인 화면 · CAPTCHA 흔적이면 까닭, 아니면 빈 문자열."""
    if status in BLOCK_STATUS:
        return f"응답 {status}({BLOCK_STATUS[status]})"
    if status >= 400:
        return f"응답 {status}"
    if LOGIN_PATH.search(urlsplit(final_url).path or ""):
        return f"로그인 주소로 넘어갔다({final_url})"
    if PASSWORD.search(html):
        return "비밀번호 칸이 있는 화면이다(로그인 화면)"
    m = CAPTCHA.search(html)
    if m:
        return f"CAPTCHA 흔적이 있다('{m.group(0)}')"
    return ""


def chrome_cmd(url: str, out: pathlib.Path, width: int, height: int, profile: pathlib.Path, chrome: pathlib.Path = CHROME,
               scale: float = 1.0) -> list[str]:
    extra = [f"--force-device-scale-factor={scale:g}"] if scale != 1 else []
    return [str(chrome), "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-sync", "--disable-background-networking", "--disable-component-update", "--disable-gpu", "--hide-scrollbars",
            "--mute-audio", f"--user-agent={USER_AGENT}", f"--window-size={width},{height}", "--virtual-time-budget=8000",
            *extra, f"--screenshot={out}", url]


def chrome_shot(url: str, out: pathlib.Path, width: int, height: int, run=subprocess.run, chrome: pathlib.Path = CHROME,
                scale: float = 1.0) -> None:
    """새 임시 사용자 폴더로 headless Chrome 을 띄워 찍는다. 폴더는 찍은 뒤 지운다.
    그림을 남기지 않았거나, 비정상 종료했거나(종료 코드가 0 이 아니다), CHROME_TIMEOUT 초 안에 끝나지 않으면 RuntimeError
    (명령은 '[shot] 오류'와 종료 코드 1 로 끝난다). 실패한 실행이 쓰다 만 그림은 지운다 — 남겨 두면 다음 실행이 '출력 파일이 이미 있다'로 멈춘다.
    부르기 전부터 있던 파일은 지우지 않는다(이 실행이 쓴 것이 아니다)."""
    if run is subprocess.run and not chrome.exists():
        raise RuntimeError(f"Chrome 이 없다: {chrome}")
    was_there = out.exists()

    def drop_leftover() -> str:
        if was_there or not out.exists():
            return ""
        out.unlink()
        return " — 쓰다 만 그림은 지웠다"
    with tempfile.TemporaryDirectory(prefix="ozl-shot-") as prof:
        try:
            r = run(chrome_cmd(url, out, width, height, pathlib.Path(prof), chrome, scale), capture_output=True, text=True, timeout=CHROME_TIMEOUT)
        except subprocess.TimeoutExpired as x:
            raise RuntimeError(f"Chrome 이 {CHROME_TIMEOUT}초 안에 끝나지 않았다 — 그림을 쓰지 않는다{drop_leftover()}: {url}") from x
        except BaseException:   # 중단(Ctrl-C)이나 그 밖의 오류로 나가는 길에서도 쓰다 만 그림을 남기지 않는다
            drop_leftover()
            raise
    code, err = getattr(r, "returncode", 0), (getattr(r, "stderr", "") or "")[-300:]
    if not out.is_file():
        raise RuntimeError(f"Chrome 이 그림을 남기지 않았다(종료 {code}): {err}")
    if code != 0:
        raise RuntimeError(f"Chrome 이 비정상 종료했다(종료 {code}) — 그림을 쓰지 않는다{drop_leftover()}: {err}")


def blank_image(png: pathlib.Path) -> bool:
    from PIL import Image
    with Image.open(png) as g:
        lo, hi = g.convert("L").getextrema()
    return hi - lo < 8


def _rel(p: pathlib.Path) -> str:
    p = p.resolve()
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def entry_draft(png: pathlib.Path, source_url: str, origin: str, log: dict) -> dict:
    """그림 검수 대장 칸 초안. 권리·라이선스·점검 칸은 비워 둔다(기관 이용 조건을 읽고 채운다 — 비면 엄격 모드 실패)."""
    from ozl.render import pictures as PIC
    host = urlsplit(source_url).hostname or ""
    return {"id": "p?", "path": _rel(png), "kind": KIND, "source_url": source_url, "origin": origin,
            "rights_holder": "", "license": "", "commercial_ok": None, "modify_ok": None, "attribution": host,
            "reverse_search": {"did": "해당 없음 — 원 게시처 화면을 직접 찍었다", "result": "원 게시처 자체다"},
            "synthetic_check": "직접 찍은 화면이다 — 덧칠·합성 없음", "content_check": "",
            "checked_at": log.get("fetched_at", ""), "as_is": True, "map": None, "sha256": PIC.file_sha256(png), "shot_log": log}


def write_draft(png: pathlib.Path, entry: dict) -> pathlib.Path:
    import yaml
    y = png.with_suffix(".yaml")
    y.write_text("# 그림 검수 대장 칸 초안(shots.py) — 빈 칸을 채우고 id 를 정해 사양 pictures: 에 옮긴다\n"
                 + yaml.safe_dump([entry], allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    return y


def parse_clip(text: str) -> tuple[int, int, int, int]:
    """'x,y,w,h'(CSS 픽셀) → 네 정수. 꼴이 틀리면 ValueError."""
    parts = [x.strip() for x in str(text).split(",")]
    if len(parts) != 4 or not all(x.isdigit() for x in parts):
        raise ValueError(f"--clip 은 x,y,w,h 네 정수(CSS 픽셀)다: {text}")
    x, y, w, h = (int(v) for v in parts)
    if w <= 0 or h <= 0:
        raise ValueError(f"--clip 의 폭과 높이는 0 보다 커야 한다: {text}")
    return x, y, w, h


def parse_band(text: str) -> tuple[float, float]:
    """'위,아래'(쪽 높이의 비율 0~1) → 두 실수. 꼴이 틀리면 ValueError."""
    parts = [x.strip() for x in str(text).split(",")]
    try:
        top, bottom = (float(v) for v in parts)
    except ValueError:
        raise ValueError(f"--band 는 위,아래 두 비율(0~1)이다: {text}") from None
    if not 0.0 <= top < bottom <= 1.0:
        raise ValueError(f"--band 는 0 <= 위 < 아래 <= 1 이어야 한다: {text}")
    return top, bottom


def _crop_file(png: pathlib.Path, box: tuple[int, int, int, int]) -> tuple[int, int]:
    """그림 파일을 box(왼쪽, 위, 오른쪽, 아래 — 그림 픽셀)만 남기고 다시 쓴다. 남은 크기를 돌려준다."""
    from PIL import Image
    with Image.open(png) as g:
        part = g.crop(box)
        part.load()
    part.save(png)
    return part.size


def _image_size(png: pathlib.Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(png) as g:
        return g.size


def shot(url: str, out: pathlib.Path, width: int = 1280, height: int = 900, opener=_open, clock: HostClock | None = None,
         run=subprocess.run, log=print, chrome: pathlib.Path = CHROME, clip: tuple[int, int, int, int] | None = None,
         scale: float = 1.0) -> dict:
    """웹 화면을 찍고 대장 칸 초안(dict)을 돌려준다. 멈출 까닭이 있으면 Stop(Chrome 을 띄우지 않는다).
    페이지는 fetch_chain 이 단계마다 받는다(robots.txt → 간격 → 요청, 30x 와 meta refresh 는 다음 단계). clip = 찍은 화면에서 남길 범위(x, y, w, h — CSS 픽셀)."""
    if not url.startswith(("https://", "http://")):
        raise Stop(f"주소가 아니다: {url}")
    out = pathlib.Path(out)
    if out.exists():
        raise Stop(f"출력 파일이 이미 있다 — 덮어쓰지 않는다: {out}")
    if not 1 <= scale <= 4:
        raise ValueError(f"--scale 는 1~4 다: {scale:g}")
    if clip is not None:
        x, y, w, h = clip
        if min(x, y) < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError(f"--clip {x},{y},{w},{h} 가 창({width}x{height}) 밖이다 — 창 안의 범위만 고른다(긴 화면은 --height 를 늘린다)")
    clock = clock or HostClock(HOST_LOG)   # 모듈 값을 부를 때 읽는다(시험이 바꿀 수 있게)
    got = fetch_chain(url, opener, clock, log)
    final, status, hops = got["final_url"], got["status"], got["hops"]
    host = urlsplit(final).hostname or ""
    out.parent.mkdir(parents=True, exist_ok=True)
    clock.wait(host)
    try:
        chrome_shot(final, out, width, height, run=run, chrome=chrome, scale=scale)
    finally:
        clock.mark(host)   # Chrome 이 실패해도(그림 없음 · 시간 초과) 그 호스트에 요청은 나갔다 — 다음 요청이 간격을 지키게 적는다
    size = _image_size(out)
    if clip is not None:
        k = size[0] / width if width else 1.0   # 화면 배율(보통 1, --scale 이면 그 값) — 그림 픽셀로 바꿔 자른다
        x, y, w, h = clip
        size = _crop_file(out, (round(x * k), round(y * k), min(round((x + w) * k), size[0]), min(round((y + h) * k), size[1])))
    if blank_image(out):
        raise Stop(f"찍은 화면이 비었다(한 가지 색) — 대장에 올리지 않는다: {out}")
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    meta = {"fetched_at": at, "requested_url": url, "final_url": final, "http_status": status, "robots": dict(hops[0]["robots"]), "hops": hops,
            "browser": "Chrome headless, 새 임시 사용자 폴더, 로그인 없음", "window": f"{width}x{height}",
            **({"clip": list(clip)} if clip is not None else {}), **({"scale": scale} if scale != 1 else {}), "image": f"{size[0]}x{size[1]}"}
    log(f"[shot] {out} · 창 {width}x{height}" + (f" · 범위 {','.join(map(str, clip))}" if clip is not None else "")
        + (f" · 배율 {scale:g}" if scale != 1 else "") + f" · 그림 {size[0]}x{size[1]} · {at}")
    return entry_draft(out, final, f"{host} 화면을 headless Chrome 으로 찍었다({at[:10]}, 로그인 없음)", meta)


def pdf_page(pdf: pathlib.Path, page: int, out: pathlib.Path, source_url: str, dpi: int = 150, log=print,
             band: tuple[float, float] | None = None) -> dict:
    """저장된 PDF 사본의 한 쪽을 그림으로(pdftoppm -singlefile). 웹을 다시 열지 않는다.
    band = 남길 구간(위, 아래 — 쪽 높이의 비율 0~1). 쪽 전체 폭에서 그 높이 구간만 남긴다."""
    pdf, out = pathlib.Path(pdf), pathlib.Path(out)
    if not pdf.is_file():
        raise Stop(f"PDF 사본이 없다: {pdf}")
    if out.exists():
        raise Stop(f"출력 파일이 이미 있다 — 덮어쓰지 않는다: {out}")
    if not source_url.startswith(("https://", "http://")):
        raise Stop(f"--source-url 이 원문 주소가 아니다: {source_url}")
    if band is not None and not 0.0 <= band[0] < band[1] <= 1.0:
        raise ValueError(f"--band 는 0 <= 위 < 아래 <= 1 이어야 한다: {band}")
    tool = shutil.which("pdftoppm")
    if not tool:
        raise RuntimeError("pdftoppm 이 없다")
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([tool, "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile", str(pdf), str(out.with_suffix(""))],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"pdftoppm 실패(종료 {r.returncode}): {r.stderr[-300:]}")
    from ozl.render import pictures as PIC
    page_px = _image_size(out)
    size = page_px
    if band is not None:
        size = _crop_file(out, (0, round(page_px[1] * band[0]), page_px[0], round(page_px[1] * band[1])))
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    meta = {"fetched_at": at, "pdf_copy": _rel(pdf), "pdf_sha256": PIC.file_sha256(pdf), "page": page, "dpi": dpi, "web": "다시 열지 않음",
            "page_px": f"{page_px[0]}x{page_px[1]}", **({"band": [band[0], band[1]]} if band is not None else {}), "image": f"{size[0]}x{size[1]}"}
    log(f"[pdf] {pdf} {page}쪽 → {out} ({dpi}dpi" + (f", 구간 {band[0]:g}~{band[1]:g}" if band is not None else "") + f", 그림 {size[0]}x{size[1]})")
    return entry_draft(out, source_url, f"저장된 PDF 사본의 {page}쪽을 pdftoppm 으로 그렸다"
                       + (f"(쪽 높이의 {band[0]:g}~{band[1]:g} 구간)" if band is not None else ""), meta)


def main(argv: list[str]) -> int:
    opts = {"--out": None, "--width": "1280", "--height": "900", "--pdf": None, "--page": "1", "--source-url": None, "--dpi": "150",
            "--clip": None, "--band": None, "--scale": None}
    pos = []
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a in opts:
            opts[a] = next(it, None)
            if opts[a] is None:
                print(f"[shot] {a} 에 값이 없다")
                return 2
        elif a.startswith("--"):
            print(f"[shot] 모르는 옵션 {a}")
            return 2
        else:
            pos.append(a)
    if not opts["--out"] or (not opts["--pdf"] and len(pos) != 1) or (opts["--pdf"] and (pos or not opts["--source-url"])):
        print(__doc__)
        return 2
    if ((opts["--clip"] or opts["--scale"] is not None) and opts["--pdf"]) or (opts["--band"] and not opts["--pdf"]):
        print("[shot] --clip 과 --scale 은 웹 화면에, --band 는 --pdf 에 쓴다")
        return 2
    try:
        clip = parse_clip(opts["--clip"]) if opts["--clip"] else None
        band = parse_band(opts["--band"]) if opts["--band"] else None
        scale = float(opts["--scale"]) if opts["--scale"] is not None else 1.0
        if not 1 <= scale <= 4:
            raise ValueError(f"--scale 는 1~4 다: {opts['--scale']}")
    except ValueError as x:
        print(f"[shot] {x}")
        return 2
    try:
        if opts["--pdf"]:
            e = pdf_page(pathlib.Path(opts["--pdf"]), int(opts["--page"]), pathlib.Path(opts["--out"]), opts["--source-url"], int(opts["--dpi"]), band=band)
        else:
            e = shot(pos[0], pathlib.Path(opts["--out"]), int(opts["--width"]), int(opts["--height"]), clip=clip, scale=scale)
    except Stop as x:
        print(f"[shot] 멈춤: {x}")
        return 3
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as x:   # 바깥 도구(Chrome · pdftoppm)의 시간 초과도 여기서 끝낸다
        print(f"[shot] 오류: {x}")
        return 1
    y = write_draft(pathlib.Path(opts["--out"]), e)
    print(f"[shot] 대장 칸 초안: {y} · sha256 {e['sha256'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
