"""python -m ozl.render check <사양.yaml> [--draft] [--claims-dir <경로>]… [--edition 비공개판|바꾼판]
python -m ozl.render build <사양.yaml> [--draft] [--claims-dir <경로>]… [--no-export] [--edition 비공개판|바꾼판]
python -m ozl.render bundle <사양.yaml> [--out <md>]          # 검토 묶음(ozl.render.bundle)
python -m ozl.render progress <card_id> [--start|--resume|--mark 단계|--done --final 폴더|--abandon]   # 진행 기록(ozl.render.progress)
python -m ozl.render refresh-candidates [<card_id>…] [--since YYYY-MM-DD] [--all] [--json] [--db <engine.db>]   # 덱 갱신 후보
python -m ozl.render norms [--out <폴더>]                   # 원본 방송 슬라이드 집계(ozl.render.norms)
python -m ozl.render compare <사양.yaml 또는 산출 폴더> [--video <영상 id>] [--out <폴더>] [--edition 비공개판|바꾼판]   # 원본 비교표(ozl.render.compare)
python -m ozl.render outline --minutes <분>                # style: syuka 덱의 목표 장수와 종류별 배분(ozl.render.style)
python -m ozl.render samples [--out <폴더>] [--no-export]   # 종류별 견본집(ozl.render.style) — 광고 구간 두 장(지어낸 광고주) 포함
python -m ozl.render potx [--out <폴더>] [--no-export]      # 렌더러 좌표로 레이아웃 12개가 든 정식 템플릿(.potx)과 확인용 pptx·PDF(ozl.render.potx)
python -m ozl.render shot <url> --out <png> [--width 1280 --height 900] [--clip x,y,w,h]   # 원문 화면 갈무리와 대장 칸 초안(ozl.render.shots)
                                                           # 단계마다 robots.txt 먼저, 리다이렉트는 따라가기 전에 넘어갈 호스트의 robots.txt 를 본다
python -m ozl.render shot --pdf <사본> --page <쪽> --source-url <원문 주소> --out <png> [--dpi 150] [--band 위,아래]
python -m ozl.render origin <덱 그림> <원 게시처에서 받은 파일> --url <주소>   # origin_check 칸 초안(지각 해시 거리와 구역 차이)
python -m ozl.render origin --survey <원본> <사본…> [--json <파일>]          # 사본마다 두 값을 잰 표(상한을 다시 정할 때)
python -m ozl.render public-check <산출 폴더 · 파일 하나(pptx · pdf · png · jpg · zip · tar)>   # 비공개 판의 것이면 종료 코드 1(문서 속성, 공개_가부.json, 등록 대장의 해시).
                                                           # 끝까지 보지 못한 파일도 1('검사 불가'). 등록 대장이 없으면 알림 줄을 낸다
                                                           # 폴더에서 보지 못한 것(읽지 못한 하위 폴더, 폴더 링크, 깨진 링크)도 1 — 링크는 따라가지 않는다
python -m ozl.render register-private [<폴더 또는 덱 파일>…] [--dry-run]   # 이미 만든 비공개 판을 등록 대장에 채운다(인자가 없으면 private/decks 아래)
                                                           # 보지 못한 폴더나 링크가 있으면 '검사 불가' 줄과 종료 코드 1(그 아래는 등록에서 빠졌다)

--draft        아직 '확인'(사람 대조)도 「원문 일치」(프로그램 대조 + 독립 재대조)도 아닌 기록·대기 폴더 기록도 인용 허용.
               해당 쪽에 [검증 대기] 딱지, 산출물 이름에 _draft. 완성본은 엄격 모드(--draft 없이)로만 만든다.
--claims-dir   카드 기록 폴더(private/desk/claims) 말고 기록을 더 찾을 폴더(예: private/desk/staging/<card_id>/). 초안 모드에서만 쓸 수 있다.
--edition      막는 그림(판정 '비공개 판에서만' 또는 권리 확인 대기)이 든 사양에서 한 판만 다룬다. 주지 않으면 엄격 모드는 두 판을 함께 검사하고
               같은 타임코드의 폴더 둘(<card>_<ts>_비공개판, _바꾼판)로 만든다. 비공개판만 다룰 때는 장의 swap 이 덜 쓰였어도 된다.
               초안 모드는 판을 가르지 않는다(바꾼 판의 초안은 --draft --edition 바꾼판).
사양의 칸     style: syuka 사양은 화면 수치 뒤에 링크 번호가 붙는다. 분모 꼴(1인당, 100명당)과 차례 꼴(제2, 3번째, 2차)에는 붙이지 않고,
               한 쪽에서 같은 표기와 같은 번호는 처음 자리에만 붙인다. 차트 그림 안의 '출처:' 줄은 그리지 않는다(환산식이 있으면 그 줄만).
               capture_full 은 capture 대신 원문 화면 갈무리 종류의 picture 도 받는다. 그림이 자리 넓이의 절반을 못 채우거나 갈무리 글자가
               7pt 아래로 찍히면(대장 줄의 shot_log 로 어림) check 가 경고한다.
               광고 회차는 사양 맨 위에 sponsorship: {kind: 유료 광고|협찬|협업, sponsor, label, whole, materials} 를 두고 구간의 장에 stage: 광고 를 쓴다.
               check 가 표시 문구와 구간의 짜임을 보고, build 가 구간의 장마다 오른쪽 위에 띠를 그린다.
--clip         (shot) 찍은 화면에서 남길 범위. CSS 픽셀, 창 왼쪽 위가 0,0 이다. 창 밖의 범위는 받지 않는다(긴 화면은 --height 를 늘린다).
--band         (shot --pdf) 남길 높이 구간. 쪽 높이의 비율 둘(0~1, 예: 0.2,0.55). 범위와 구간은 대장 칸 초안의 shot_log 에 적힌다.
"""
from __future__ import annotations

import pathlib
import sys

from ozl.render import build as B
from ozl.render import spec as S
from ozl.research import cards as C


def _opts(argv: list[str]) -> tuple[list[str], bool, bool, list[str], str | None]:
    pos, draft, export, dirs, edition = [], False, True, [], None
    it = iter(argv)
    for a in it:
        if a == "--draft":
            draft = True
        elif a == "--no-export":
            export = False
        elif a == "--edition":
            from ozl.render import pictures as PIC
            edition = next(it, None)
            if edition not in PIC.EDITIONS:
                raise SystemExit(f"--edition 뒤에 판 이름이 있어야 한다({' | '.join(PIC.EDITIONS)})")
        elif a == "--claims-dir":
            d = next(it, None)
            if d is None:
                raise SystemExit("--claims-dir 뒤에 경로가 있어야 한다")
            if not pathlib.Path(d).is_dir():
                raise SystemExit(f"--claims-dir {d} 는 폴더가 아니다")
            dirs.append(d)
        elif a.startswith("--"):
            raise SystemExit(f"모르는 옵션 {a}")
        else:
            pos.append(a)
    return pos, draft, export, dirs, edition


def main(argv: list[str]) -> int:
    if argv and argv[0] == "refresh-candidates":
        from ozl.render import refresh
        return refresh.main(argv[1:])
    if argv and argv[0] in ("bundle", "progress", "norms", "compare", "potx"):   # 하위 명령은 각 모듈이 인자를 읽는다(_opts 는 사양 파일 명령 전용)
        from importlib import import_module
        return import_module(f"ozl.render.{argv[0]}").main(argv[1:])
    if argv and argv[0] in ("outline", "samples"):   # style: syuka 덱의 장 배분과 견본집(ozl.render.style)
        from ozl.render import style as ST
        return ST.main(argv)
    if argv and argv[0] == "shot":   # 원문 화면 갈무리(ozl.render.shots)
        from ozl.render import shots as SH
        return SH.main(argv[1:])
    if argv and argv[0] in ("public-check", "origin", "register-private"):   # 공개 가부 확인, 원출처 대조 칸 초안, 등록 대장 채우기(ozl.render.pictures)
        from ozl.render import pictures as PIC
        return {"public-check": PIC.public_check_main, "origin": PIC.origin_main, "register-private": PIC.register_main}[argv[0]](argv[1:])
    if any(a in ("-h", "--help") for a in argv):   # 사양 파일을 읽기 전에 끝낸다
        print(__doc__)
        return 0
    pos, draft, export, dirs, edition = _opts(argv)
    if len(pos) < 2 or pos[0] not in ("check", "build"):
        print(__doc__)
        return 2
    path = pathlib.Path(pos[1])
    if not path.is_file():
        print(f"[{pos[0]}] 사양 파일이 없다: {path}", file=sys.stderr)
        return 1
    try:
        sp = S.load_spec(path)
    except Exception as e:  # noqa: BLE001 — YAML 문법 오류 등은 한 줄로
        print(f"[{pos[0]}] 사양을 읽지 못했다({type(e).__name__}): {str(e).splitlines()[0] if str(e) else ''}", file=sys.stderr)
        return 1
    if not isinstance(sp, dict):
        print(f"[{pos[0]}] 사양 최상위가 사전(mapping)이 아니다: {path}", file=sys.stderr)
        return 1
    if pos[0] == "check":
        if not draft:   # build 와 같게 — 엄격 모드는 밈을 빼고 검사하고, 뺀 것을 알린다
            from ozl.render import pictures as PIC
            sp, dropped = PIC.drop_memes(sp)
            for d in dropped:
                print("[밈 제외]", d)
        cid = sp.get("card_id")
        card = None
        if cid and C.CARD_ID.match(str(cid)):
            if not C.card_path(str(cid)).exists():
                print(f"[check] 카드 {cid} 를 찾지 못했다")
                return 1
            card = C.load_card(str(cid))
        claims, staged = S.load_claims(S.cited_ids(sp), dirs)
        eds = S.check_editions(sp, claims, S.load_template(), card, B.layout_problems, draft=draft, staged=staged, appendix_fn=B.appendix_problems,
                               edition=edition)
        for ed in eds:   # 판을 가르지 않는 사양은 한 번 — 줄 머리가 지금까지와 같다([경고] · [실패] · [check]). 두 판이면 줄 머리에 판 이름을 붙인다
            rep = ed.report
            tag = f"·{ed.name}" if ed.name else ""
            for w in rep.warnings:
                print(f"[경고{tag}]", w)
            for e in rep.errors:
                print(f"[실패{tag}]", e)
            print(f"[면제한 식별자{tag}]", ", ".join(rep.exempt_idents) if rep.exempt_idents else "없음")
            n = len(ed.spec.get("slides") or [])
            extra = f" · [검증 대기] {len(rep.pending)}장({', '.join(map(str, rep.pending))})" if draft else ""
            print(f"[check{tag}] {'통과' if rep.ok else '실패'}{' (초안 모드)' if draft else ''} · 본편 {n}장 · 실패 {len(rep.errors)} · 경고 {len(rep.warnings)}{extra}")
            for m in rep.metrics:   # template: v1 사양의 지표(실패·경고 수에 넣지 않는다). 옛 사양은 빈 목록이라 출력이 그대로다
                print(f"[v1{tag}]", m)
        return 0 if all(ed.report.ok for ed in eds) else 1
    try:
        info = B.build(path, export=export, draft=draft, claims_dirs=dirs, edition=edition)
    except SystemExit as e:
        print(f"[build] {e}", file=sys.stderr)
        return 1
    if "editions" in info:   # 두 판(또는 --edition 으로 고른 한 판) — 판마다 출력 칸을 찍는다
        for name, one in info["editions"].items():
            for k, v in one.items():
                print(f"[{name}] {k}: {v}")
    else:
        for k, v in info.items():
            if k != "dropped":
                print(f"{k}: {v}")
    for d in info.get("dropped") or []:
        print("[밈 제외]", d)
    cid = str(sp.get("card_id", ""))
    if C.CARD_ID.match(cid):
        from ozl.render import progress as P   # 막지 않고 알리기만 한다(빌드는 한 편에 여러 번 부른다)
        st = P.load(cid)
        if st.get("status") == P.DONE and not draft:
            print(f"[진행 기록] 이 카드는 이미 완성본이 있다: {st.get('final', '')} — 다시 만드는 중이면 progress --start --force")
    if draft:
        first = next(iter(info["editions"].values())) if "editions" in info else info
        print(f"[검증 대기] 기록을 인용한 슬라이드: {first.get('pending_slides', 0)}장")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
