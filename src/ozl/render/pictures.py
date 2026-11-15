"""그림 검수 대장 — 덱에 넣는 그림 파일마다 남기는 검수 기록과 그 판정.

대장은 사양의 맨 위 `pictures:` 목록이다(사양 옆 파일이 아니다). 까닭:
  - 완성본 폴더에 사양 사본이 들어가고, 진행 기록(progress)과 검토 묶음(bundle)이 사양 sha256 하나로 판을 가린다.
    대장을 사양 안에 두면 그림 검수 기록이 같은 지문에 묶여, 검토한 판과 다른 대장으로 빌드하는 일이 생기지 않는다.
  - 검사(check)는 사양 사전 하나만 받는다. 옆 파일이면 사양 경로를 따로 알아야 하고, 옮기거나 복사할 때 짝이 끊긴다.

쪽에서는 `picture: <그림 번호>` 로 부른다(image_text · number · photo_caption 의 그림 자리, image_pair 의 각 자리).

칸(FIELDS — 하나라도 비면 그 그림은 엄격 모드에서 실패, 초안 모드에서는 [그림 대기]):
  id 그림 번호(p1, p2 …) · path 파일 경로(저장소 기준 상대 또는 절대) · kind 그림 종류(KIND_RULES 의 이름)
  source_url 출처 주소 · origin 원출처 · rights_holder 권리자 · license 라이선스
  commercial_ok 상업적 이용이 되는가(참/거짓) · modify_ok 변경이 되는가(참/거짓) · attribution 출처 표시 문구
  reverse_search 역검색 {did: 한 일, result: 결과} · synthetic_check 합성 여부 확인 · content_check 인물·로고·지도 점검
  checked_at 확인 시각(ISO) · as_is 원형 그대로 썼는가(참/거짓) · map 지도인가(참/거짓 — 모든 종류에서 답한다)
  sha256 검수한 파일의 해시(검사·빌드 때 다시 해시해 다르면 그 그림을 쓰지 않는다)
칸끼리: 라이선스에 NC 가 있으면 commercial_ok 가 거짓, ND 가 있으면 modify_ok 가 거짓이어야 한다. 점검 글·파일 이름·원출처·주소가
  지도를 가리키면 종류와 상관없이 map_check 를 요구한다. 그림 밑 표기의 수는 라이선스 판 번호·유형과 출처 주소·확인 시각의 연도만 받는다.
  파일 짧은 변은 MIN_SHORT_PX 이상.
조건 칸: edits(as_is 가 거짓이면 자르기·덧칠 내용) · map_check {east_sea: 참, dokdo: 참}(지도) ·
         permission(기업 뉴스룸 — 이용 조건에서 사용 허락을 확인한 기록) · meme_origin(밈의 유래)

판정(설계 5-7절 그림 종류 표를 그대로 옮겼다 — KIND_RULES):
  쓴다 / 원형 그대로만 / 허락 기록이 있을 때만 원형으로 / 연습용 판(초안 모드)에서만 / 비공개 판에서만(아래) / 쓰지 않는다.
  상업적 이용이 안 되는 그림은 비공개 판 전용 종류가 아니면 쓰지 않는다(우리 방침). 변경이 안 되는 그림을 고쳐 썼으면 실패다.
  밈은 엄격 모드에서 실패가 아니라 빠진다(drop_memes — 빌드 출력과 러닝시트에 뺀 것을 적는다).

2026-11-15 더한 것(라-2 · R-024 · R-025 · R-026 · R-245 · R-296):
  - 새 판정 PRIVATE_ONLY(비공개 판에서만). 엄격 모드 빌드는 되지만 그런 그림이 한 장이라도 든 덱은 공개 불가다(public_status · public-check 명령 ·
    pptx 문서 속성 keywords 의 PRIVATE_KEYWORD). 통신사·언론사 사진, 화제 그림, 공공누리 2·4유형, 비상업(NC) 라이선스 그림이 이 판정이다
    (사용자가 2026-11-14 21:42 에 "상업적으로 쓰지 않는 개인 작업"으로 정한 범위). 이 종류는 commercial_ok 가 거짓이어도 실패로 보지 않는다.
  - 원문 화면 갈무리(SCREEN — shots.py 로 공식 문서·통계 화면을 찍은 그림): 쓴다. 출처 주소의 기관 호스트(org_host)가 그 쪽이 인용한 기록의
    원문 주소 가운데 하나와 같아야 한다(spec.picture_errors 가 기록을 넘겨 screen_host_errors 를 부른다). 그림 밑 표기는 호스트만.
  - AI 개념도: generator(쓴 모델과 판) · prompt · generated_at 칸이 있어야 한다(concept · concept_check 는 아래 「그림 검수 보강」).
    파일이 아직 없으면 초안은 [그림 대기], 엄격은 실패.
  - origin_check(원출처 대조 — 보도 사진 · 밈 · 화제 그림 · 로고에 필수): {url: 원 게시처 주소, sha256: 원 게시처에서 다시 받은 파일의 해시,
    phash_distance: 덱에 넣은 파일과의 지각 해시(64비트 DCT 해시) 해밍 거리, local_diff: 구역 차이(아래 「그림 검수 보강」),
    checked_at, original_path(받은 파일 — 있으면 다시 잰다)}.
    거리가 PHASH_MAX 를 넘거나 구역 차이가 LOCAL_DIFF_MAX 를 넘으면 실패(잘리거나 덧칠된 사본을 막는다).
    두 값은 `python -m ozl.render origin <덱 그림> <받은 원본> --url <주소>` 로 잰다.
  - context_check(맥락 점검 — 밈 · 화제 그림 · 보도 사진에 필수): {spread: 어디서 퍼졌는가, mockery: 조롱이나 특정 집단 비하의 맥락,
    manipulation: 합성·조작 이력}. 판단은 에이전트가 적는다. 코드는 세 칸이 찼는지만 보고 내용이 맞는지는 판단하지 않는다.
  - 새 칸은 그 종류에서만 요구하므로 다른 종류의 옛 대장은 그대로 통과한다.

2026-11-15 두 판과 공개 차단(사용자 결정 나 · 라 — R-024 · R-245):
  - 막는 그림(edition_block — 판정 '비공개 판에서만'이거나 권리 확인 대기인 그림)이 든 사양은 두 판으로 나온다:
    EDITION_PRIVATE(비공개판 — 그 그림이 든 판)과 EDITION_SWAP(바꾼판 — 막는 그림이 든 장을 모두 바꾼 판).
    밈(연습용 판에서만)은 판을 가르지 않는다: 엄격 모드는 먼저 빼고(drop_memes) 초안 모드는 연습용 판 하나에만 남는다.
  - 사양의 장마다 swap 칸: {why: 한 줄 까닭, set: {칸: 값}} 은 그 장의 칸을 덮어쓰고(값이 null 이면 칸을 지운다),
    {why, slide: {…장 전체…}} 는 글과 도형으로 다시 짠 장으로 바꾼다(stage 는 원래 장과 같아야 한다). 코드는 문장을 짓지 않는다.
    strip_swaps(비공개판 사양) · apply_swaps(바꾼판 사양과 바꾼 장 목록) · swap_errors(규칙) · needs_two · plan_editions 가 다룬다.
    원래 사양은 고치지 않는다(drop_memes 와 같은 꼴).
  - 엄격 모드: 막는 그림이 든 장에 swap 이 없으면 실패. 바꾼 뒤에도 막는 그림이 남거나 회색 자리(image)로 바꾸면 실패. 막는 그림이 없는 장의 swap 도 실패.
    초안 모드는 판을 가르지 않는다(swap 은 모양만 보고 떼어 낸 연습용 판 하나 — 바꾼 판의 초안은 --edition 바꾼판 으로 본다).
  - 권리 확인 대기(결정 라): RIGHTS_PENDING_HOSTS 의 호스트(지금 korea.kr)를 찍은 원문 화면 갈무리와 rights_pending: "<까닭>" 칸을 적은 그림은
    판정은 그대로('쓴다')이고 공개만 막는다(public_block). 권리가 확실해지면 표의 그 줄(또는 칸)을 지우고 등록 대장에서 그 그림의 줄을 지운다(사람이 정한다).
  - 비공개 등록 대장(REGISTRY — private/decks/private_only_registry.jsonl): 빌드가 비공개판을 만들 때 막는 그림 파일과 그 판의 pptx · PDF ·
    막는 그림이 든 쪽의 PNG 의 sha256 을 한 줄씩 덧붙인다(그 밖의 쪽 PNG 는 바꾼판의 같은 쪽과 바이트가 같아 적지 않는다).
    막는 그림이 든 초안 모드의 연습용 판도 같은 방식으로 등록한다. public_check 가 pptx 문서 속성(keywords), 공개_가부.json(edition), pptx 안 미디어 해시, 파일 해시를 이 대장과 견준다
    — keywords 를 지운 사본도 그림 해시로 잡는다. 환경 변수 OZL_PRIVATE_REGISTRY 는 더 볼 대장을 더할 뿐이다(기본 대장은 늘 본다).
    파일 하나를 볼 때는 확장자가 아니라 파일 안을 본다(is_deck_file — zip 안에 프레젠테이션 부품이 있으면 덱이다). 이름을 .ppsx · .pptx.zip ·
    확장자 없는 이름으로 바꾼 사본도 덱으로 검사하고, 그 밖의 파일은 종류와 상관없이 파일 해시를 견준다.
    못 잡는 것: 그림을 다시 저장해 바이트가 달라진 사본(재압축 · 자르기), 화면을 찍은 그림. 해시가 같은 파일과 문서 속성이 남은 덱만 잡는다.

2026-11-15 재확인 뒤 고친 것(다른 계열 모델과 다른 검토자의 재확인 지적):
  - 묶음 안 보기(scan): zip · tar(압축된 것 포함) · 압축 한 겹(gz · bz2 · xz) 안의 파일마다 해시를 견주고, 안의 파일도 파일 안을 보고 가려
    덱이면 덱으로 연다(문서 속성, 안에 든 그림). 노트만 지워 바이트가 달라진 비공개 덱을 zip 에 넣어도 문서 속성으로 잡는다.
    겹친 묶음은 ARCHIVE_MAX_DEPTH 겹까지 풀어 본다. 그보다 깊은 묶음, 풀린 크기의 합이 ARCHIVE_MAX_BYTES 를 넘거나 항목 수가
    ARCHIVE_MAX_MEMBERS 를 넘는 묶음, 풀 수 없는 묶음(암호, 깨진 항목, 7z · rar 같은 풀 줄 모르는 형식)은 '검사 불가'(종료 1)다.
    묶음 목록에 나오지 않는 내용이 붙은 파일도 '검사 불가'다: zip 의 첫 항목 앞에 붙은 내용, tar 의 마지막 항목 뒤에 붙은 내용,
    압축 흐름(gz · bz2 · xz) 뒤에 붙은 풀리지 않는 내용. 0 으로 찬 구역으로 시작하는 파일은 tar 로 보지 않는다(tarfile 은 빈 tar 로 읽는다).
    메모리에서만 읽는다(디스크에 풀지 않고 항목 이름을 경로로 쓰지 않는다). tar 끝의 pptx 처럼 두 꼴로 읽히는 파일은 두 꼴을 다 본다.
  - 가리지 못한 파일은 '덱이 아님'이 아니다: is_deck_file 과 content_kind 는 가리지 못하면 Unscannable 을 낸다. public_check 는 예외 대신
    '검사 불가' 줄과 종료 코드 1 을 낸다(덱 꼴인데 열리지 않는 파일을 준 명령이 KeyError 로 끝나던 것).
  - 폴더 검사는 *.pptx · *.pdf · *_png/*.png 만이 아니라 폴더 안의 모든 파일을 하위 폴더까지 본다.
  - 등록 대장이 없거나 비면 해시를 견주지 못한다. 종료 코드는 그대로이고(다른 기기에는 대장이 늘 없다) 알림 줄(NOTICE)을 낸다.
  - `python -m ozl.render register-private` 가 이미 만들어진 비공개 판(문서 속성에 표시가 있는 덱)을 대장에 채운다(backfill_rows · register_main).
  - 여전히 못 잡는 것: 표지로 알아보지 못하는 묶음 형식(iso · dmg · cab, 기본값이 아닌 속성으로 만든 .lzma 등), 부호화한 파일(base64 등)이나 zip 이 아닌 방식으로 암호를 건 파일 안의 것,
    zip 의 덧글과 항목 사이 빈틈에 넣은 내용. 문서 속성과 그림을 모두 바꾼 덱(그림을 다시 저장하고 keywords 를 지운 것)도 못 잡는다.

2026-11-15 그림 검수 보강(사용자 결정 다 · R-024 · R-025 · R-245 · R-296):
  - 생성 그림은 개념도만 쓴다. AI 개념도 줄은 generator · prompt · generated_at 에 더해 concept: true 와
    concept_check: {people: false, real_place: false, photoreal: false, logo_text: false} 가 있어야 한다(사람, 실제 건물이나 장소,
    사진처럼 보이는 질감, 회사 로고나 글자가 그림에 없는가). 점검 칸은 그림을 연 사람이나 에이전트가 채운다 — 코드는 그림을 보지 않는다.
    프롬프트에 사실처럼 보이게 하라는 정해 둔 꼴(REALISM_FORMS — photorealistic · 실사풍 · 실제 사진처럼 등)이 있으면 실패다.
    이 낱말 검사는 그물일 뿐이다: 다른 말로 쓴 프롬프트는 못 잡고, 그림이 실제로 어떻게 나왔는지는 concept_check 를 채운 쪽이 본다.
  - hard_block: concept 가 참이 아니거나 concept_check 에 참이 있는 AI 개념도(개념도가 아닌 생성 그림), 다른 종류의 줄에
    generator · prompt · generated_at 을 적은 그림(종류를 바꿔 적은 생성 그림)은 초안 모드에서도 실패다([그림 대기]로 미루지 않는다 —
    spec.picture_errors). 기다려서 나아지는 것이 아니기 때문이다.
  - 대장 파일: json 의 생성 그림 행에 concept · prompt · generated_at · concept_check 를 싣고, md 에 「생성 그림」 절(모델, 만든 시각, 점검, 프롬프트 전문)을 둔다.
  - 구역 차이(local_diff): 두 그림을 회색조 256×256 으로 맞추고 16×16 구역마다 밝기 절대 차이의 평균을 내어 그 최댓값(0~255).
    지각 해시는 그림 전체의 큰 무늬만 보아 넓이 1~10% 의 덧칠을 통과시킨다(실측). 구역 차이는 한 구역만 바뀌어도 커진다.
    origin_check 에 local_diff 칸을 더했고 LOCAL_DIFF_MAX 를 넘으면 실패다. original_path 가 있으면 검사 때 두 값을 다시 잰다.
    local_diff 칸이 없는 옛 줄은 original_path 의 파일로 잰 값으로 판정하고, 잴 파일도 없으면 실패다.
    두 상한은 실측 표(ORIGIN_SURVEY_FILE)에서 정했다. 못 잡는 것: 바탕과 밝기가 비슷한 색의 덧칠(덧칠 상자 안 밝기 차이가 약 70 아래 —
    흰 문서 바탕의 흰 덧칠 포함), 밝기를 그대로 둔 색 바꿈(회색조), 밝기와 대비를 조금 고친 사본, 넓이 0.5% 보다 작은 덧칠(재지 않았다).
    자르거나 띠를 붙이거나 뒤집은 재게시 사본은 두 값 가운데 하나가 상한을 넘는다 — 원 게시처에서 받은 파일을 쓰라는 뜻이다.
  - `python -m ozl.render origin --survey <원본> <사본…>` 이 사본마다 두 값을 표로 찍는다(상한을 다시 정할 때 쓴다).

2026-11-15 이월된 고침과 자리에 놓인 크기의 경고(R-244 · R-262 · 이월 2~4):
  - 폴더 검사(walk_folder): 목록을 읽지 못한 하위 폴더, 폴더로 가는 링크, 깨진 링크, 상태를 읽지 못한 항목을 모아 돌려준다. public_check 와
    register-private 는 그 줄마다 '검사 불가'를 내고 종료 코드 1 이다(전에는 건너뛰고 통과했다 — 그 아래의 비공개 판을 보지 못한 채로).
    폴더 링크는 따라가지 않는다(폴더 밖을 훑게 되고 고리가 생길 수 있다). 링크만 모아 둔 폴더를 통째로 주면 '검사 불가'가 나온다 — 가리키는 폴더를 직접 준다.
  - 묶음 판별: tar 는 머리의 표지로 종류를 먼저 가려 'r:' 또는 'r:gz' · 'r:bz2' · 'r:xz' 로만 연다(_tar_mode). 'r:*' 는 0 으로 찬 파일을 xz 풀이로
    끝까지 읽었다(64MiB 에 5.45초 → 0.003초, 실측).
  - 적힌 크기 먼저: zip 항목의 file_size 와 tar 항목의 size 를 풀기 전에 남은 한도와 견줘, 넘으면 풀지 않고 '검사 불가'다(_Budget.need).
    실제로 푼 바이트를 세는 검사는 그대로 남아 있다(적힌 크기가 거짓일 수 있다). zip 의 항목 수는 항목을 읽기 전에 목록 길이로 한 번에 견준다.
    목록 자체는 zipfile 이 파일을 열 때 다 읽는다 — 목록을 읽기 전에 막지는 못한다(표준 모듈의 공개 함수로는 되지 않는다).
  - 풀 줄 모르는 형식에 ar('!<arch>')와 lzma-alone(.lzma — 표지가 없어 머리의 꼴을 보고 조금 풀어 본다, _lzma_alone)을 더했다.
    lzma-alone 은 압축 도구의 기본 속성값(0x5D)으로 만든 것만 잡는다.
  - registry_rows: 글자가 깨진 대장(UnicodeDecodeError)을 '읽지 못했다'로 돌려준다(전에는 예외로 죽었다).
  - placement_warnings: 그림 파일이 자리 넓이의 절반(style.PICTURE_FILL_MIN)을 채우지 못하면 경고(쪽 판정의 '빈칸'). 원문 화면 갈무리는
    대장 줄의 shot_log(창 폭 · 범위 · dpi · 그림 크기)로 본문 글자가 슬라이드에서 몇 pt 로 찍히는지 어림해(screen_readable_pt) style.SCREEN_MIN_PT
    아래면 경고한다. shot_log 가 없는 줄은 읽힘을 어림하지 않는다. 가정한 글자 크기와 기준은 style.py 에 있다.

못 하는 것: 칸이 채워졌는지, 칸끼리 맞는지만 본다. 역검색을 실제로 했는지, 라이선스 주장이 사실인지, 맥락 점검의 판단이 옳은지는 사람이 본다.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import pathlib
import re
import unicodedata
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[3]

PIC_ID = re.compile(r"^p\d{1,3}$")

# 판정 이름
USE = "쓴다"
AS_IS = "원형 그대로만"
PERMIT = "허락 기록이 있을 때만 원형으로"
DRAFT_ONLY = "연습용 판에서만"
PRIVATE_ONLY = "비공개 판에서만"
NEVER = "쓰지 않는다"
PRIVATE_KEYWORD = "ozl:private-only"   # 공개 불가 덱의 pptx 문서 속성 keywords 에 넣는 표시(public-check 가 읽는다)
# 원출처 대조의 두 상한 — 실측 표 ORIGIN_SURVEY_FILE(같은 이름의 .json 에 수) 에서 정했다. 다시 재면 값과 파일 이름을 함께 옮긴다
# (tests/test_deck_origin.py 가 둘이 같은지 본다). 2026-11-15 실측: 받아 둔 그림 4장의 가공 사본 296개와 실제 재게시 사본 1개.
#   구역 차이 — 재압축(품질 90~10)과 축소(75~25%) 사본의 최댓값 24.0, 축소 25% + 품질 30 사본 28.9, 실제 재게시 사본(정부 누리집의 작은 그림) 9.4.
#     가장자리 1% 자르기의 최솟값 39.1, 뚜렷한 덧칠(덧칠 상자 안 밝기 차이 100 이상)의 최솟값은 넓이 0.5% 에서 48.0, 넓이 1% 에서 86.9.
#     35 는 앞의 것보다 크고 뒤의 것보다 작다.
#   지각 해시 거리 — 재압축과 축소 사본의 최댓값 2(축소 25% + 품질 30 은 4). 뚜렷한 넓이 1% 덧칠은 2~22 라 거리만으로는 가르지 못한다.
#     거리는 큰 바뀜(좌우 뒤집기 30~32, 아래 띠, 넓은 자르기)을 잡는 둘째 기준으로 8 을 그대로 둔다(4 로 낮춰도 더 잡히는 사본은 216개 가운데 2개).
PHASH_MAX = 8        # origin_check 의 지각 해시 거리 상한(64비트 중) — 넘으면 잘리거나 덧칠된 사본으로 본다
LOCAL_DIFF_MAX = 35.0   # origin_check 의 구역 차이 상한(0~255) — 넘으면 한 곳이 덧칠되거나 잘리거나 바뀐 사본으로 본다
ORIGIN_SURVEY_FILE = "private/decks/규칙/왜곡사본_거리_실측_20261115_054129.md"
LOCAL_SIDE = 256     # 구역 차이를 잴 때 두 그림을 맞추는 한 변(픽셀)
LOCAL_ZONES = 16     # 한 변의 구역 수 — 구역 하나는 16×16 픽셀(그림 넓이의 약 0.4%)

# ── 두 판(2026-11-15 사용자 결정 나) ──
EDITION_PRIVATE = "비공개판"   # 막는 그림이 든 판 — 공개하지 않는다
EDITION_SWAP = "바꾼판"        # 막는 그림이 든 장을 모두 바꾼 판
EDITIONS = (EDITION_PRIVATE, EDITION_SWAP)
EDITION_KEY = {EDITION_PRIVATE: "private", EDITION_SWAP: "swap"}
EDITION_KEYWORD = "ozl:edition="   # pptx 문서 속성 keywords 의 판 표시 — 'ozl:edition=private' · 'ozl:edition=swap'
SWAP = "swap"                      # 사양의 장마다 두는 칸 — {why, set} 또는 {why, slide}
SWAP_KEYS = ("why", "set", "slide")
# 권리 확인 대기(결정 라) — 이 기관 호스트를 찍은 원문 화면 갈무리는 판정('쓴다')은 그대로 두고 공개만 막는다.
#   korea.kr(정책브리핑): 저작권정책이 사진과 일부 자료를 따로 협의하라고 적어, 화면 갈무리의 공개 이용 범위를 확인하지 못했다.
#   권리가 확실해지면 이 줄을 지운다(등록 대장의 그 그림 줄도 함께 지운다).
RIGHTS_PENDING_HOSTS = ("korea.kr",)
REGISTRY_NAME = "private_only_registry.jsonl"
REGISTRY = ROOT / "private" / "decks" / REGISTRY_NAME   # 비공개 등록 대장(막는 그림과 비공개판 산출물의 sha256)
REGISTRY_ENV = "OZL_PRIVATE_REGISTRY"   # 더 볼 등록 대장(경로 구분자로 여럿) — 더하기만 한다. 기본 대장을 빼지 못한다

AI_MARK = "AI 생성 이미지, 실제 장면 아님"
TRADEMARK_NOTE = "상표는 각 소유자의 것"
# 로고를 쓰려면 따로 허락을 요구하는 회사 — 이 권리자의 로고는 쓰지 않는다(설계 표의 예).
# 권리자 칸을 NFKC 정규화·casefold 한 뒤 낱말 경계로 견준다(logo_blocked): 'Apple Inc' · 'Apple Korea' · 전각 'Ａpple' 도 걸린다.
# 한글 항목은 낱말 앞머리로도 견준다('애플코리아').
LOGO_BLOCKED = ("Apple", "Apple Inc.", "애플")
MIN_SHORT_PX = 300   # 그림 파일 짧은 변의 최소 픽셀 — 이보다 작으면 슬라이드에서 뭉개진다


@dataclass(frozen=True)
class Rule:
    verdict: str
    note: str = ""
    as_is: bool = False        # 원형 그대로만(as_is 가 참이어야 한다)
    credit: bool = False       # 저작자와 라이선스 표기가 그림 밑에 찍혀야 한다(attribution 이 권리자를 담아야)
    permission: bool = False   # 이용 조건에서 사용 허락을 확인한 기록(permission 칸)
    map: bool = False          # 지도 — 동해·독도 표기 확인(map_check)
    mark: str = ""             # 그림 밑에 따로 찍는 표시
    warn: str = ""             # 쓸 수 있지만 알리는 말
    license_has: tuple = ()    # 라이선스 칸에 들어 있어야 할 표기(하나라도)
    license_not: tuple = ()    # 라이선스 칸에 있으면 안 되는 표기
    license_need: tuple = ()   # 라이선스 조건(license_conditions)에 있어야 할 것(NC 등)
    needs: tuple = ()          # 이 종류에서만 요구하는 칸(origin_check · context_check · AI_FIELDS)
    screen: bool = False       # 원문 화면 갈무리 — 기관 호스트 대조(screen_host_errors), 그림 밑 표기는 호스트만


ORIGIN = ("origin_check",)
CONTEXT = ("context_check",)
AI_KIND = "AI 개념도"
GENERATED_FIELDS = ("generator", "prompt", "generated_at")   # 생성 그림에만 적는 칸 — 다른 종류의 줄에 있으면 종류를 바꿔 적은 것이다
AI_FIELDS = GENERATED_FIELDS + ("concept", "concept_check")
# 개념도 점검(concept_check) — 그림에 이것이 있는가. 넷 다 거짓이어야 한다(그림을 연 쪽이 채운다).
CONCEPT_CHECKS = {"people": "사람", "real_place": "실제 건물이나 장소", "photoreal": "사진처럼 보이는 질감", "logo_text": "회사 로고나 글자"}
# 프롬프트에서 사실처럼 보이게 하라는 정해 둔 꼴. 그물일 뿐이다 — 다른 말로 쓴 프롬프트는 못 잡는다.
REALISM_FORMS = re.compile(
    r"photo[\s\-]?realis(?:tic|m)|photoreal\b|hyper[\s\-]?realis(?:tic|m)|ultra[\s\-]?realistic|realistic\s+photo(?:graph)?|"
    r"like\s+a\s+(?:real\s+)?photo(?:graph)?|lifelike|"
    r"실사\s?풍|실사\s?(?:처럼|같이|같은|느낌|스타일|화풍)|포토\s?리얼|극사실|(?:실제|진짜|뉴스|보도)\s?사진\s?(?:처럼|같이|같은|으로|풍)|"
    r"사진\s?처럼\s?(?:보이|사실)|실제\s?(?:장면|현장|상황)\s?(?:처럼|같이|같은)|사실적(?:인|으로|이게)", re.IGNORECASE)
_NEG_BEFORE = re.compile(r"\b(?:no|not|non|without|avoid|avoiding|never)\b[\s\-]*(?:\w+[\s\-]+){0,2}$|non-$", re.IGNORECASE)
_NEG_AFTER = re.compile(r"아닌|아니|없이|없는|없게|않|말고|말\s?것|마라|마세요|말아|금지|제외|피한|피해|피하|빼고|뺀|배제")
_CLAUSE_END = re.compile(r"[,.;:\n·/()]")
PRIVATE_NOTE = "상업적으로 쓰지 않는 개인 작업의 비공개 판에서만(2026-11-14 사용자 결정) — 이 그림이 든 덱은 공개하지 않는다"

KIND_RULES: dict[str, Rule] = {
    "직접 그린 도표": Rule(USE),
    "직접 그린 지도": Rule(USE, map=True),
    "원문 화면 갈무리": Rule(USE, "공식 문서·통계 화면을 찍은 그림 — 인용한 기록의 원문과 같은 기관 호스트, 그림 밑 표기는 호스트만", as_is=True, screen=True),
    "공공누리 1유형": Rule(USE, "저작자와 라이선스 표기", credit=True, license_has=("1유형",)),
    "CC BY": Rule(USE, "저작자와 라이선스 표기", credit=True, license_has=("CC BY",), license_not=("SA", "NC", "ND")),
    "CC BY-SA": Rule(AS_IS, "고쳐 쓰면 결과물에도 같은 라이선스를 붙여야 해서 원형 그대로만", as_is=True, credit=True, license_has=("BY-SA",),
                     license_not=("NC", "ND")),
    "공공누리 3유형": Rule(AS_IS, "변경 금지", as_is=True, credit=True, license_has=("3유형",)),
    "기업 뉴스룸": Rule(PERMIT, "그 뉴스룸의 이용 조건에서 사용 허락을 확인한 것만, 변형 없이", as_is=True, permission=True),
    "무료 스톡 인물 사진": Rule(USE, warn="무료 스톡의 인물 사진이다 — 부정적인 소재의 쪽에는 쓰지 않는다(쪽의 소재는 사람이 본다)"),
    "로고": Rule(AS_IS, "그 회사를 가리키는 자리에만 원형으로 작게", as_is=True, mark=TRADEMARK_NOTE, needs=ORIGIN),
    "AI 개념도": Rule(USE, "사람이 없는 개념도만", mark=AI_MARK, needs=AI_FIELDS),
    "밈": Rule(DRAFT_ONLY, "원출처와 라이선스가 확인된 것만, 연습용 판에서만", needs=ORIGIN + CONTEXT),
    "통신사·언론사 사진": Rule(PRIVATE_ONLY, "보도 사진 — " + PRIVATE_NOTE, as_is=True, credit=True, needs=ORIGIN + CONTEXT),
    "화제 그림": Rule(PRIVATE_ONLY, "널리 퍼진 그림(밈이 아닌 화제의 사진·그림) — " + PRIVATE_NOTE, as_is=True, credit=True, needs=ORIGIN + CONTEXT),
    "공공누리 2유형": Rule(PRIVATE_ONLY, "상업적 이용 금지 조건 — " + PRIVATE_NOTE, credit=True, license_has=("2유형",)),
    "공공누리 4유형": Rule(PRIVATE_ONLY, "상업적 이용과 변경 금지 조건 — " + PRIVATE_NOTE, as_is=True, credit=True, license_has=("4유형",)),
    "비상업(NC) 라이선스 그림": Rule(PRIVATE_ONLY, "CC BY-NC 계열 — " + PRIVATE_NOTE, credit=True, license_need=("NC",)),
    "방송 화면 캡처": Rule(NEVER, "우리 방침"),
    "실존 인물 AI 그림": Rule(NEVER),
    "사실처럼 보이는 AI 장면": Rule(NEVER),
}
SCREEN = "원문 화면 갈무리"
MEME = "밈"
MAP_KINDS = ("직접 그린 지도",)

FIELDS = {
    "id": "그림 번호", "path": "파일 경로", "kind": "그림 종류", "source_url": "출처 주소", "origin": "원출처", "rights_holder": "권리자",
    "license": "라이선스", "commercial_ok": "상업적 이용", "modify_ok": "변경", "attribution": "출처 표시 문구", "reverse_search": "역검색",
    "synthetic_check": "합성 여부 확인", "content_check": "인물·로고·지도 점검", "checked_at": "확인 시각", "as_is": "원형 그대로",
    "map": "지도인가", "sha256": "파일 해시",
}
BOOL_FIELDS = ("commercial_ok", "modify_ok", "as_is", "map")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

# 라이선스 조건 — 약자와 풀어 쓴 낱말(공백·하이픈을 뺀 대문자로 견준다)
LICENSE_WORDS = {
    "NC": ("NONCOMMERCIAL", "비영리", "영리금지"),
    "ND": ("NODERIVATIVES", "NODERIVS", "NODERIVATIVE", "변경금지"),
    "SA": ("SHAREALIKE", "동일조건"),
}
# 지도로 보이는 낱말 — '지도 아님' · '지도 없음' 처럼 부정이 바로 뒤에 붙으면 세지 않는다
MAP_HINT = re.compile(r"(지도|동해|독도)(?!\s*(?:아님|아니|없))|\bmaps?\b", re.IGNORECASE)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def name_in(name: str, text: str) -> bool:
    """이름이 글 안에 있는가 — 둘 다 _norm 으로 맞추고(전각 · 호환 글자) 대소문자를 가리지 않는다. 빈 이름은 거짓."""
    key = _norm(name).casefold()
    return bool(key) and key in _norm(text).casefold()


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", _norm(s))


def _hangul(w: str) -> bool:
    return any("가" <= ch <= "힣" for ch in w)


def logo_blocked(holder: str) -> str:
    """권리자 이름이 LOGO_BLOCKED 의 한 항목과 낱말 경계로 맞으면 그 항목, 아니면 빈 문자열.
    항목의 낱말들이 권리자 이름 안에 이어서 나오면 맞다(마지막 낱말이 한글이면 앞머리만 맞아도 된다)."""
    hw = _words(holder)
    for x in LOGO_BLOCKED:
        xw = _words(x)
        n = len(xw)
        if not n:
            continue
        for i in range(len(hw) - n + 1):
            head, last = hw[i:i + n - 1], hw[i + n - 1]
            if head == xw[:-1] and (last == xw[-1] or (_hangul(xw[-1]) and last.startswith(xw[-1]))):
                return x
    return ""


def license_conditions(lic: str) -> set[str]:
    """라이선스 글에 붙은 조건(NC · ND · SA) — 약자 낱말 또는 풀어 쓴 낱말."""
    up = _norm(lic).upper()
    toks = set(re.findall(r"[A-Z]+", up))
    flat = re.sub(r"[\s\-_·.]", "", up)
    return {k for k, words in LICENSE_WORDS.items() if k in toks or any(w.upper() in flat for w in words)}


def looks_like_map(e: dict) -> bool:
    """점검 글·파일 이름·원출처·출처 주소가 지도를 가리키는가('지도 아님' 같은 부정은 세지 않는다)."""
    texts = [_s(e.get("content_check")), _s(e.get("origin")), pathlib.Path(_s(e.get("path"))).stem, _s(e.get("source_url"))]
    return any(MAP_HINT.search(re.sub(r"[_\-]", " ", t)) for t in texts if t)


_LICENSE_NUM_OK = re.compile(r"\d+\.\d+|제?\s*\d\s*유형")


def credit_number_errors(e: dict) -> list[str]:
    """그림 밑 표기(출처 표시 문구·라이선스)에 실을 수 있는 수: 라이선스 판 번호(4.0)·공공누리 유형, 출처 표시 문구의 연도 가운데
    출처 주소에 있거나 확인 시각의 연도인 것. 그 밖의 수는 숫자 대조를 받지 않는 글에 수량을 싣는 길이라 실패다."""
    out = []
    lic = _s(e.get("license"))
    rest = _LICENSE_NUM_OK.sub(" ", unicodedata.normalize("NFKC", lic))
    if re.search(r"\d", rest):
        out.append(f"라이선스 '{lic}' 에 판 번호(4.0)·공공누리 유형 말고 다른 수가 있다")
    att = unicodedata.normalize("NFKC", _s(e.get("attribution")))
    ok_years = set(re.findall(r"(?<!\d)\d{4}(?!\d)", _s(e.get("source_url"))))
    ca = _s(e.get("checked_at"))[:4]
    if ca.isdigit():
        ok_years.add(ca)
    for tok in re.findall(r"\d[\d,.]*", att):
        if tok not in ok_years:
            out.append(f"출처 표시 문구 '{_s(e.get('attribution'))}' 의 수 '{tok}' — 출처 주소나 확인 시각의 연도만 적을 수 있다(그림 밑 표기는 숫자 대조를 받지 않는다)")
    return out
OWN_KINDS = ("직접 그린 도표", "직접 그린 지도")   # 출처 주소 칸에 주소 대신 자료 경로·설명을 적어도 된다


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def ledger(spec: dict) -> tuple[dict[str, dict], list[str]]:
    """사양의 pictures 목록 → ({그림 번호: 기록}, 모양 오류). 번호가 겹치거나 형식이 틀리면 오류."""
    raw = spec.get("pictures")
    if raw is None:
        return {}, []
    if not isinstance(raw, list):
        return {}, ["pictures 는 그림 검수 기록의 목록이어야 한다"]
    out: dict[str, dict] = {}
    errs = []
    for k, e in enumerate(raw):
        if not isinstance(e, dict):
            errs.append(f"pictures[{k}]: 사전(mapping)이어야 한다")
            continue
        pid = _s(e.get("id"))
        if not PIC_ID.match(pid):
            errs.append(f"pictures[{k}]: 그림 번호 '{pid}' 는 p1 · p2 … 꼴이어야 한다")
            continue
        if pid in out:
            errs.append(f"pictures[{k}]: 그림 번호 {pid} 가 겹친다")
            continue
        out[pid] = e
    return out, errs


def resolve_path(e: dict) -> pathlib.Path:
    p = pathlib.Path(_s(e.get("path")))
    return p if p.is_absolute() else ROOT / p


def is_meme(e: dict | None) -> bool:
    return bool(e) and _s(e.get("kind")) == MEME


def rule_of(e: dict) -> Rule | None:
    return KIND_RULES.get(_s(e.get("kind")))


def _checked_at_ok(v) -> bool:
    if isinstance(v, (dt.date, dt.datetime)):
        return True
    try:
        dt.datetime.fromisoformat(_s(v))
        return True
    except ValueError:
        return False


def judge(e: dict, draft: bool = False) -> tuple[str, list[str], list[str]]:
    """(판정, 이 그림을 쓰지 못하는 까닭, 경고). 까닭이 비어 있으면 이 모드에서 쓸 수 있다.
    판정은 종류 표의 이름(KIND_RULES)이고, 상업적 이용이 안 되면 종류와 상관없이 NEVER."""
    why: list[str] = []
    warns: list[str] = []
    kind = _s(e.get("kind"))
    rule = KIND_RULES.get(kind)
    for k, name in FIELDS.items():
        v = e.get(k)
        if k in BOOL_FIELDS:
            if not isinstance(v, bool):
                why.append(f"{name}({k}) 칸이 참/거짓으로 적혀 있지 않다")
        elif k == "reverse_search":
            if not (isinstance(v, dict) and _s(v.get("did")) and _s(v.get("result"))):
                why.append("역검색(reverse_search) 칸에 한 일(did)과 결과(result)가 둘 다 있어야 한다")
        elif not _s(v):
            why.append(f"{name}({k}) 칸이 비었다")
    if rule is None:
        return NEVER, why + [f"그림 종류 '{kind}' 는 종류 표에 없다({' · '.join(KIND_RULES)}) — 표에 없는 종류는 쓰지 않는다"], warns
    verdict = rule.verdict
    if e.get("commercial_ok") is False and rule.verdict != PRIVATE_ONLY:   # 비공개 판 전용 종류는 상업적 이용이 안 되는 것이 전제다
        verdict = NEVER
        why.append("상업적 이용이 안 되는 그림이다 — 우리 방침으로 쓰지 않는다")
    if rule.verdict == NEVER:
        why.append(f"'{kind}' 는 쓰지 않는다" + (f"({rule.note})" if rule.note else ""))
    if e.get("checked_at") not in (None, "") and not _checked_at_ok(e.get("checked_at")):
        why.append(f"확인 시각 '{_s(e.get('checked_at'))}' 를 시각으로 읽지 못했다(ISO 꼴: 2099-01-02T10:00:00+09:00)")
    url = _s(e.get("source_url"))
    if url and kind not in OWN_KINDS and not url.startswith(("https://", "http://")):
        why.append(f"출처 주소 '{url}' 가 주소가 아니다")
    if e.get("as_is") is False:
        if not _s(e.get("edits")):
            why.append("원형 그대로가 아니면(as_is: false) 자르기·덧칠 내용(edits)을 적어야 한다")
        if e.get("modify_ok") is False:
            why.append("변경이 안 되는 그림(modify_ok: false)을 고쳐 썼다(as_is: false)")
        if rule.as_is:
            why.append(f"'{kind}' 는 원형 그대로만 쓴다 — as_is: false 면 쓰지 않는다")
    lic = _s(e.get("license"))
    if lic and rule.license_has and not any(x.upper() in _norm(lic).upper() for x in rule.license_has):
        why.append(f"라이선스 '{lic}' 가 종류 '{kind}' 와 맞지 않는다({' 또는 '.join(rule.license_has)} 표기가 없다)")
    conds = license_conditions(lic)
    bad = [x for x in rule.license_not if x in conds]
    if bad:
        why.append(f"라이선스 '{lic}' 에 {bad} 조건이 붙어 있다 — 종류 '{kind}' 로 쓰지 않는다")
    miss = [x for x in rule.license_need if x not in conds]
    if lic and miss:
        why.append(f"라이선스 '{lic}' 에 {miss} 조건이 없다 — 종류 '{kind}' 가 아니다(조건 없는 CC BY 는 'CC BY' 로 적는다)")
    if rule.license_need and conds & {"ND", "SA"} and e.get("as_is") is not True:
        why.append(f"라이선스 '{lic}' 에 변경 금지(ND)나 동일 조건(SA)이 붙어 있다 — 원형 그대로(as_is: true)만 쓴다")
    for k in rule.needs:
        why += need_errors(e, k)
    if kind != AI_KIND:
        why += hard_block(e)   # 다른 종류의 줄에 적은 생성 그림 칸(종류를 바꿔 적은 생성 그림)
    # 칸끼리: 라이선스 조건과 참/거짓 칸이 어긋나면 어느 쪽이 맞는지 모른다 — 쓰지 않는다
    if "NC" in conds and e.get("commercial_ok") is True:
        why.append(f"라이선스 '{lic}' 에 비영리(NC) 조건이 있는데 상업적 이용(commercial_ok) 칸이 참이다 — 칸끼리 어긋난다")
    if "ND" in conds and e.get("modify_ok") is True:
        why.append(f"라이선스 '{lic}' 에 변경 금지(ND) 조건이 있는데 변경(modify_ok) 칸이 참이다 — 칸끼리 어긋난다")
    why += credit_number_errors(e)
    sha = _s(e.get("sha256")).lower()
    if sha and not SHA_RE.match(sha):
        why.append(f"파일 해시(sha256) '{_s(e.get('sha256'))}' 가 sha256 꼴(16진 64자)이 아니다")
    if rule.credit:
        holder = _s(e.get("rights_holder"))
        att = _s(e.get("attribution"))
        if att and holder and holder not in att:
            why.append(f"출처 표시 문구에 저작자(권리자 '{holder}')가 없다 — '{kind}' 는 저작자와 라이선스를 표기해야 한다")
    if rule.permission and not _s(e.get("permission")):
        why.append("기업 뉴스룸 그림은 그 뉴스룸의 이용 조건에서 사용 허락을 확인한 기록(permission)이 있어야 한다 — 찾지 못했으면 쓰지 않는다")
    if kind == "로고":
        hit = logo_blocked(_s(e.get("rights_holder")))
        if hit:
            verdict = NEVER
            why.append(f"권리자 '{_s(e.get('rights_holder'))}' 는 로고 사용에 따로 허락을 요구하는 회사다(LOGO_BLOCKED '{hit}') — 쓰지 않는다")
    if e.get("map") is False and (rule.map or looks_like_map(e)):
        why.append("지도인가(map) 칸이 거짓인데 " + ("종류가 지도다" if rule.map else "점검 글·파일 이름·원출처·주소가 지도를 가리킨다")
                   + " — 지도면 map: true 와 동해·독도 확인(map_check)을 적는다")
    if rule.map or e.get("map") is True or looks_like_map(e):
        mc = e.get("map_check")
        if not (isinstance(mc, dict) and mc.get("east_sea") is True and mc.get("dokdo") is True):
            why.append("지도는 동해와 독도 표기를 확인한 기록(map_check: {east_sea: true, dokdo: true})이 있어야 한다")
    if kind == MEME:
        if not _s(e.get("meme_origin")):
            why.append("밈은 유래(meme_origin)를 적어야 한다")
        if not draft:
            why.append("밈은 연습용 판(초안 모드)에서만 쓴다 — 엄격 모드는 빼고 만든다(drop_memes)")
    rp = e.get("rights_pending")
    if rp is not None and not (isinstance(rp, str) and rp.strip()):
        why.append("권리 확인 대기(rights_pending) 칸은 까닭을 적은 한 줄이어야 한다 — 대기가 아니면 칸을 두지 않는다")
    if rule.warn:
        warns.append(rule.warn)
    return verdict, why, warns


def rights_pending(e: dict) -> str:
    """권리 확인 대기인가 — 까닭(아니면 빈 문자열). 판정은 바꾸지 않고 공개만 막는다(결정 라 · public_block).
    rights_pending 칸에 까닭을 적었거나, 원문 화면 갈무리의 출처 주소가 RIGHTS_PENDING_HOSTS 의 기관 호스트일 때."""
    note = e.get("rights_pending")
    if isinstance(note, str) and note.strip():
        return note.strip()
    rule = rule_of(e)
    if rule is not None and rule.screen:
        host = org_host(_s(e.get("source_url")))
        if host in RIGHTS_PENDING_HOSTS:
            return f"{host} 화면 갈무리의 공개 이용 범위를 확인하지 못했다(pictures.RIGHTS_PENDING_HOSTS)"
    return ""


def _ts_ok(v) -> bool:
    return _present_s(v) and _checked_at_ok(v)


def _present_s(v) -> bool:
    return bool(_s(v))


def prompt_realism(prompt: str) -> str:
    """프롬프트에서 사실처럼 보이게 하라는 꼴(REALISM_FORMS)을 찾아 그 낱말을 돌려준다(없으면 빈 문자열).
    같은 마디 안에서 부정이 붙은 것은 세지 않는다: 영어는 앞의 no · not · non- · without · avoid, 한글은 뒤의 '아닌' · '없이' · '않' · '금지' 등
    ('not photorealistic' · '실사풍이 아닌' · '사진처럼 보이는 질감을 넣지 않는다'). 마디는 쉼표, 마침표, 줄바꿈에서 끊는다."""
    text = unicodedata.normalize("NFKC", _s(prompt))
    for m in REALISM_FORMS.finditer(text):
        before = _CLAUSE_END.split(text[:m.start()])[-1][-40:]
        after = _CLAUSE_END.split(text[m.end():])[0][:24]
        if _NEG_BEFORE.search(before) or _NEG_AFTER.search(after):
            continue
        return m.group(0)
    return ""


def _concept_errors(e: dict) -> tuple[list[str], list[str]]:
    """AI 개념도의 concept · concept_check — (개념도가 아니라는 까닭[초안 모드에서도 실패], 칸이 덜 찬 까닭[엄격 실패 · 초안은 그림 대기])."""
    hard: list[str] = []
    soft: list[str] = []
    c = e.get("concept")
    if c is not True:
        what = "칸이 없다" if c is None else "칸이 거짓이다" if c is False else f"칸이 참/거짓이 아니다('{_s(c)}')"
        hard.append(f"개념도 여부(concept) {what} — 생성 그림은 개념도만 쓴다(concept: true 가 아닌 생성 그림은 쓰지 않는다)")
    cc = e.get("concept_check")
    if not isinstance(cc, dict):
        soft.append("개념도 점검(concept_check: {" + ", ".join(CONCEPT_CHECKS) + "} — 넷 다 false)이 있어야 한다 — 그림을 연 쪽이 채운다(코드는 그림을 보지 않는다)")
        return hard, soft
    for k, name in CONCEPT_CHECKS.items():
        v = cc.get(k)
        if v is True:
            hard.append(f"개념도 점검(concept_check.{k} — {name})이 참이다 — 이것이 든 생성 그림은 개념도가 아니다. 쓰지 않는다")
        elif v is not False:
            soft.append(f"개념도 점검(concept_check.{k} — {name}) 칸이 참/거짓으로 적혀 있지 않다")
    return hard, soft


def hard_block(e: dict) -> list[str]:
    """초안 모드에서도 이 그림을 쓰지 못하는 까닭(사용자 결정 다 — 생성 그림은 개념도만). 비어 있으면 없다.
    - AI 개념도인데 concept 가 참이 아니거나 concept_check 에 참이 있다(개념도가 아닌 생성 그림).
    - 다른 종류의 줄에 generator · prompt · generated_at 이 있다(종류를 바꿔 적은 생성 그림).
    spec.picture_errors 가 초안 모드에서도 실패로 돌린다([그림 대기]로 미루지 않는다 — 기다려서 나아지는 것이 아니다)."""
    kind = _s(e.get("kind"))
    if kind == AI_KIND:
        return _concept_errors(e)[0]
    have = [k for k in GENERATED_FIELDS if _present_s(e.get(k))]
    if not have:
        return []
    rule = KIND_RULES.get(kind)
    if rule is not None and rule.verdict == NEVER:
        return [f"생성 그림 칸({' · '.join(have)})이 있는 '{kind}' 줄이다 — 생성 그림은 개념도('{AI_KIND}')만 쓴다"]
    return [f"생성 그림 칸({' · '.join(have)})이 '{kind}' 줄에 있다 — 생성 그림은 종류를 '{AI_KIND}' 로 적는다(다른 종류로 적은 생성 그림은 쓰지 않는다)"]


def need_errors(e: dict, k: str) -> list[str]:
    """종류마다 더 요구하는 칸(Rule.needs)의 검사 — origin_check · context_check · AI 개념도의 generator · prompt · generated_at · concept · concept_check."""
    kind = _s(e.get("kind"))
    if k == "origin_check":
        return origin_errors(e)
    if k == "context_check":
        cc = e.get("context_check")
        names = {"spread": "어디서 퍼졌는가", "mockery": "조롱이나 특정 집단 비하의 맥락", "manipulation": "합성·조작 이력"}
        if not isinstance(cc, dict):
            return [f"'{kind}' 는 맥락 점검(context_check: {{spread, mockery, manipulation}})이 있어야 한다 — 판단은 에이전트가 적는다"]
        return [f"맥락 점검(context_check.{x} — {n}) 칸이 비었다" for x, n in names.items() if not _s(cc.get(x))]
    if k == "generated_at":
        v = e.get(k)
        if not _present_s(v):
            return [f"'{kind}' 는 만든 시각(generated_at) 칸이 있어야 한다"]
        return [] if _checked_at_ok(v) else [f"만든 시각 '{_s(v)}' 를 시각으로 읽지 못했다(ISO 꼴)"]
    if k in ("generator", "prompt"):
        name = {"generator": "쓴 모델과 판(generator)", "prompt": "프롬프트(prompt)"}[k]
        if not _present_s(e.get(k)):
            return [f"'{kind}' 는 {name} 칸이 있어야 한다"]
        hit = prompt_realism(e.get(k)) if k == "prompt" else ""
        return [f"프롬프트(prompt)에 사실처럼 보이게 하라는 말('{hit}')이 있다 — 생성 그림은 개념도만 쓴다(사진처럼 보이는 생성 그림은 쓰지 않는다)"] if hit else []
    if k == "concept":
        return _concept_errors(e)[0][:1] if e.get("concept") is not True else []
    if k == "concept_check":
        hard, soft = _concept_errors(e)
        return [x for x in hard if "concept_check" in x] + soft
    return [f"모르는 요구 칸 {k}"]


def origin_errors(e: dict) -> list[str]:
    """원출처 대조(origin_check) — 원 게시처 주소, 그곳에서 다시 받은 파일의 sha256, 덱에 넣은 파일과의 지각 해시 거리.
    original_path 가 있고 두 파일이 다 있으면 해시와 거리를 다시 재서 적힌 값과 견준다."""
    kind = _s(e.get("kind"))
    oc = e.get("origin_check")
    if not isinstance(oc, dict):
        return [f"'{kind}' 는 원출처 대조(origin_check: {{url, sha256, phash_distance, checked_at}})가 있어야 한다 — 원 게시처에서 다시 받은 파일과 견준다"]
    out = []
    url = _s(oc.get("url"))
    if not url.startswith(("https://", "http://")):
        out.append("원출처 대조(origin_check.url)에 원 게시처 주소가 없다")
    sha = _s(oc.get("sha256")).lower()
    if not SHA_RE.match(sha):
        out.append("원출처 대조(origin_check.sha256)에 원 게시처에서 받은 파일의 sha256(16진 64자)이 없다")
    d = oc.get("phash_distance")
    if isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 64:
        out.append("원출처 대조(origin_check.phash_distance)에 지각 해시 거리(0~64 정수)가 없다 — `python -m ozl.render origin` 으로 잰다")
    elif d > PHASH_MAX:
        out.append(f"원 게시처 파일과 지각 해시 거리 {d} 가 상한 {PHASH_MAX} 를 넘는다 — 잘리거나 덧칠된 사본일 수 있어 쓰지 않는다")
    ld = oc.get("local_diff")
    if ld is not None:
        if isinstance(ld, bool) or not isinstance(ld, (int, float)) or not 0 <= ld <= 255:
            out.append("원출처 대조(origin_check.local_diff)에 구역 차이(0~255 수)가 없다 — `python -m ozl.render origin` 으로 잰다")
        elif ld > LOCAL_DIFF_MAX:
            out.append(f"원 게시처 파일과 구역 차이 {ld:g} 가 상한 {LOCAL_DIFF_MAX:g} 를 넘는다 — 한 곳이 덧칠되거나 바뀐 사본일 수 있어 쓰지 않는다")
    if not _ts_ok(oc.get("checked_at")):
        out.append("원출처 대조(origin_check.checked_at)에 받은 시각(ISO)이 없다")
    op = _s(oc.get("original_path"))
    if ld is None and not op:
        out.append("원출처 대조(origin_check.local_diff)에 구역 차이가 없다 — `python -m ozl.render origin` 으로 재서 적는다"
                   "(받은 파일을 original_path 에 두면 검사 때 다시 잰다)")
    if op and not out:
        orig = pathlib.Path(op) if pathlib.Path(op).is_absolute() else ROOT / op
        mine = resolve_path(e)
        if not orig.is_file():
            out.append(f"원출처 대조의 받은 파일이 없다: {orig}")
        elif mine.is_file():
            if file_sha256(orig) != sha:
                out.append("원출처 대조의 받은 파일 해시가 적힌 sha256 과 다르다")
            else:
                got = phash_distance(mine, orig)
                if got != d:
                    out.append(f"원출처 대조의 지각 해시 거리를 다시 재니 {got} 이다(적힌 값 {d})")
                got_ld = local_diff(mine, orig)
                if ld is None:
                    if got_ld > LOCAL_DIFF_MAX:   # 칸이 없는 옛 줄 — 받은 파일로 잰 값으로 판정한다
                        out.append(f"원 게시처 파일과 구역 차이를 재니 {got_ld:g} 로 상한 {LOCAL_DIFF_MAX:g} 를 넘는다 — 한 곳이 덧칠되거나 바뀐 사본일 수 있어 쓰지 않는다")
                elif round(float(ld), 1) != got_ld:
                    out.append(f"원출처 대조의 구역 차이를 다시 재니 {got_ld:g} 이다(적힌 값 {ld:g})")
    return out


def local_diff(a: pathlib.Path, b: pathlib.Path) -> float:
    """구역 차이 — 두 그림을 회색조 LOCAL_SIDE×LOCAL_SIDE 로 맞추고 LOCAL_ZONES×LOCAL_ZONES 구역마다 밝기 절대 차이의 평균을 내어
    그 최댓값을 돌려준다(0~255, 소수 한 자리). 같은 그림이면 0, 재압축과 축소는 작고, 한 구역이 덧칠되면 그 구역의 값이 그대로 드러난다."""
    import numpy as np
    from PIL import Image

    def arr(p):
        with Image.open(p) as g:
            return np.asarray(g.convert("L").resize((LOCAL_SIDE, LOCAL_SIDE), Image.LANCZOS), dtype=float)
    z = LOCAL_SIDE // LOCAL_ZONES
    d = np.abs(arr(a) - arr(b)).reshape(LOCAL_ZONES, z, LOCAL_ZONES, z).mean(axis=(1, 3))
    return round(float(d.max()), 1)


def origin_verdict(d: int, ld: float) -> str:
    """두 값의 판정 글 — '받는다' 또는 넘은 상한."""
    over = ([f"지각 해시 거리 {d} > {PHASH_MAX}"] if d > PHASH_MAX else []) + ([f"구역 차이 {ld:g} > {LOCAL_DIFF_MAX:g}"] if ld > LOCAL_DIFF_MAX else [])
    return "받는다" if not over else "넘는다(" + ", ".join(over) + ")"


def survey_rows(orig: pathlib.Path, copies: list[pathlib.Path]) -> list[dict]:
    """원본 한 장과 사본들의 두 값 — [{copy, size, phash_distance, local_diff, ok, verdict}]. 그림으로 읽지 못한 사본은 error 칸."""
    from PIL import Image
    rows = []
    for c in copies:
        c = pathlib.Path(c)
        try:
            with Image.open(c) as g:
                size = f"{g.size[0]}x{g.size[1]}"
            d, ld = phash_distance(c, orig), local_diff(c, orig)
        except Exception as x:  # noqa: BLE001 — 읽지 못한 사본은 한 줄로
            rows.append({"copy": c.name, "error": f"{type(x).__name__}"})
            continue
        rows.append({"copy": c.name, "size": size, "phash_distance": d, "local_diff": ld,
                     "ok": d <= PHASH_MAX and ld <= LOCAL_DIFF_MAX, "verdict": origin_verdict(d, ld)})
    return rows


def survey_md(orig: pathlib.Path, rows: list[dict]) -> str:
    lines = [f"원본 {pathlib.Path(orig).name} · 상한: 지각 해시 거리 {PHASH_MAX}, 구역 차이 {LOCAL_DIFF_MAX:g}", "",
             "| 사본 | 크기 | 지각 해시 거리 | 구역 차이 | 판정 |", "|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['copy']} | — | — | — | 읽지 못함({r['error']}) |")
        else:
            lines.append(f"| {r['copy']} | {r['size']} | {r['phash_distance']} | {r['local_diff']:g} | {r['verdict']} |")
    return "\n".join(lines)


def phash(path: pathlib.Path) -> int:
    """64비트 지각 해시(DCT) — 32×32 회색조로 줄이고 2차원 DCT 의 왼쪽 위 8×8(첫 칸 뺀 중앙값 기준)을 비트로 만든다."""
    import numpy as np
    from PIL import Image
    with Image.open(path) as g:
        a = np.asarray(g.convert("L").resize((32, 32), Image.LANCZOS), dtype=float)
    n = 32
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    d = (m @ a @ m.T)[:8, :8].flatten()
    med = np.median(d[1:])
    bits = 0
    for x in d:
        bits = (bits << 1) | int(x > med)
    return bits


def phash_distance(a: pathlib.Path, b: pathlib.Path) -> int:
    return bin(phash(a) ^ phash(b)).count("1")


# ── 원문 화면 갈무리의 기관 호스트 ──────────────────────────────────────────
_SECOND_LEVEL = {"go", "or", "re", "co", "ac", "ne", "pe", "kg", "ms", "es", "hs", "sc", "mil", "gov", "com", "org", "net", "edu"}


def org_host(url: str) -> str:
    """주소의 기관 호스트 — 'www.' · 'm.' 을 떼고, 국가 도메인의 2단계(go.kr · co.uk 등)면 끝 세 칸, 아니면 끝 두 칸."""
    from urllib.parse import urlsplit
    host = (urlsplit(_s(url)).hostname or "").lower().rstrip(".")
    parts = [x for x in host.split(".") if x]
    while len(parts) > 2 and parts[0] in ("www", "m"):
        parts = parts[1:]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def screen_host_errors(e: dict, claims: list[dict]) -> list[str]:
    """원문 화면 갈무리의 출처 주소가 그 쪽이 인용한 기록(claims) 가운데 하나의 원문 주소와 같은 기관 호스트인가."""
    mine = org_host(_s(e.get("source_url")))
    if not claims:
        return ["원문 화면 갈무리는 그 원문을 인용한 기록이 그 쪽 claim_ids 에 있어야 한다(기록의 원문 주소와 기관 호스트를 견준다)"]
    hosts = sorted({org_host(_s((c.get("source") or {}).get("url"))) for c in claims} - {""})
    if not mine or mine not in hosts:
        return [f"원문 화면 갈무리의 출처 주소 기관 호스트 '{mine}' 가 그 쪽이 인용한 기록의 원문 호스트({', '.join(hosts) or '없음'})와 다르다"]
    return []


def credit_lines(e: dict) -> list[str]:
    """그림 밑에 찍는 표기(위에서 아래로): 따로 찍는 표시(AI 표시·상표 고지) · '출처 표시 문구 · 라이선스'.
    숫자 대조에서 빼는 구조 글이다(원문 캡처의 호스트 줄과 같다)."""
    rule = rule_of(e)
    out = []
    if rule and rule.screen:   # 원문 화면 갈무리: 호스트만(capture 의 '원문: 호스트' 와 같은 자리)
        from urllib.parse import urlsplit
        host = (urlsplit(_s(e.get("source_url"))).hostname or "").lower()
        return [f"원문: {host}"] if host else []
    if rule and rule.mark == AI_MARK:
        out.append(AI_MARK)
    line = " · ".join(x for x in (_s(e.get("attribution")), _s(e.get("license"))) if x)
    if rule and rule.mark == TRADEMARK_NOTE:
        line = " · ".join(x for x in (line, TRADEMARK_NOTE) if x)
    if line:
        out.append(line)
    return out


def _wh(v) -> tuple[int, int] | None:
    """'900x1000' → (900, 1000). 읽지 못하면 None."""
    m = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*", _s(v))
    return (int(m.group(1)), int(m.group(2))) if m and int(m.group(1)) > 0 and int(m.group(2)) > 0 else None


def _pixel_size(e: dict) -> tuple[int, int] | None:
    """그림 파일의 (폭, 높이) 픽셀. 읽지 못하면 None(파일 검사 file_error 가 따로 실패시킨다)."""
    try:
        from PIL import Image
        with Image.open(resolve_path(e)) as g:
            pw, ph = g.size
    except Exception:  # noqa: BLE001
        return None
    return (pw, ph) if pw > 0 and ph > 0 else None


def placed_size(e: dict, slot_w: float, slot_h: float) -> tuple[float, float] | None:
    """그림 파일이 자리(in) 안에 비율을 지켜 놓일 때의 (폭, 높이) in — build.fit_inside 와 같은 계산. 파일을 읽지 못하면 None."""
    px = _pixel_size(e)
    if px is None or slot_w <= 0 or slot_h <= 0:
        return None
    k = min(slot_w / px[0], slot_h / px[1])
    return px[0] * k, px[1] * k


def screen_readable_pt(e: dict, placed_w: float) -> float | None:
    """원문 화면 갈무리의 본문 글자가 슬라이드에서 몇 pt 로 찍히는지 어림한 값. placed_w = 그림이 슬라이드에 놓인 폭(in).
    대장 줄의 shot_log(shots.py 가 적는다)로 잰다. 재지 못하면 None(shot_log 가 없는 줄, 원문 화면 갈무리가 아닌 줄, 칸을 읽지 못한 줄).
      - 웹 화면(window: '창 폭x높이' CSS 픽셀, clip: [x, y, w, h]): 그림의 폭이 CSS 픽셀로 얼마인가 = clip 의 w, 없으면 창 폭.
        본문 글자를 style.SCREEN_WEB_BODY_PX(CSS 픽셀)로 가정하면 슬라이드 위 크기 = 가정 px × 놓인 폭 ÷ 그 CSS 폭 × 72.
      - PDF 쪽(dpi, band 는 높이만 자르므로 폭은 쪽 전체): 본문 글자를 style.SCREEN_DOC_BODY_PT(pt)로 가정하면 그림 안에서 가정 pt ÷ 72 × dpi 픽셀,
        슬라이드 위 크기 = 가정 pt × dpi × 놓인 폭 ÷ 그림 폭(픽셀). 그림 폭은 shot_log.image(없으면 page_px, 그것도 없으면 그림 파일)에서 읽는다.
    어림이다: 실제 글자 크기는 화면마다 다르다(가정한 값과 기준은 style.py 에 있다)."""
    from ozl.render import style as ST
    rule = rule_of(e)
    log = e.get("shot_log")
    if rule is None or not rule.screen or not isinstance(log, dict) or placed_w <= 0:
        return None
    dpi = log.get("dpi")
    if isinstance(dpi, (int, float)) and not isinstance(dpi, bool) and dpi > 0:   # PDF 쪽을 그린 그림
        size = _wh(log.get("image")) or _wh(log.get("page_px")) or _pixel_size(e)
        if size is None:
            return None
        return ST.SCREEN_DOC_BODY_PT * dpi * placed_w / size[0]
    win = _wh(log.get("window"))
    if win is None:
        return None
    css_w = float(win[0])
    clip = log.get("clip")
    if isinstance(clip, (list, tuple)) and len(clip) == 4 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in clip) and clip[2] > 0:
        css_w = float(clip[2])
    return ST.SCREEN_WEB_BODY_PX * placed_w / css_w * 72


def placement_warnings(e: dict, slot_w: float, slot_h: float) -> list[str]:
    """그림 파일을 자리(in)에 놓았을 때의 경고 — 자리 넓이의 style.PICTURE_FILL_MIN 을 채우지 못한다(빈칸으로 센다),
    원문 화면 갈무리의 글자가 style.SCREEN_MIN_PT 아래로 찍힌다(screen_readable_pt)."""
    from ozl.render import style as ST
    got = placed_size(e, slot_w, slot_h)
    if got is None:
        return []
    w, h = got
    out = []
    fill = (w * h) / (slot_w * slot_h)
    if fill < ST.PICTURE_FILL_MIN:
        out.append(f"그림이 자리 넓이의 {fill * 100:.0f}% 만 채운다(자리 {slot_w:.2f}×{slot_h:.2f}in 에 그림 {w:.2f}×{h:.2f}in) — "
                   f"{ST.PICTURE_FILL_MIN * 100:.0f}% 를 채우지 못하면 빈칸으로 센다. 자리 모양에 맞게 찍거나 다른 종류의 장으로 옮긴다")
    pt = screen_readable_pt(e, w)
    if pt is not None and pt < ST.SCREEN_MIN_PT:
        out.append(f"갈무리 글자가 약 {pt:.1f}pt 로 찍힌다 — 찍는 범위를 좁히거나 넓은 자리를 쓴다(기준 {ST.SCREEN_MIN_PT:g}pt · 웹 본문 {ST.SCREEN_WEB_BODY_PX:g}px, "
                   f"문서 본문 {ST.SCREEN_DOC_BODY_PT:g}pt 로 어림)")
    return out


def file_error(e: dict) -> str:
    """그림 파일을 열 수 있는가. 빈 문자열이면 연다."""
    p = resolve_path(e)
    if not p.is_file():
        return f"그림 파일이 없다: {p}"
    try:
        from PIL import Image
        with Image.open(p) as g:
            size = g.size
            g.verify()
    except Exception as x:  # noqa: BLE001 — 그림으로 읽지 못하면 사유 한 줄
        return f"그림 파일을 그림으로 읽지 못했다({type(x).__name__}): {p}"
    if min(size) < MIN_SHORT_PX:
        return f"그림 파일이 너무 작다({size[0]}x{size[1]} — 짧은 변 {MIN_SHORT_PX}px 이상): {p}"
    want = _s(e.get("sha256")).lower()
    if want:
        got = file_sha256(p)
        if got != want:
            return f"그림 파일의 sha256 이 대장과 다르다(검수 뒤 파일이 바뀌었다 — 대장 {want[:12]}… · 지금 {got[:12]}…): {p}"
    return ""


def file_sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 밈 빼기(엄격 모드) ──────────────────────────────────────────────────────
DROPPED = "_dropped"   # image_pair 의 자리에서 밈을 뺐다는 표시(빌드가 그 자리를 비운다)


def drop_memes(spec: dict) -> tuple[dict, list[str]]:
    """엄격 모드(완성본·공개용)에서 밈 그림을 뺀 사양과, 뺀 것을 적은 글 목록. 원래 사양은 고치지 않는다.
    - photo_caption 쪽의 그림이 밈이면 쪽을 뺀다.
    - image_text · number 의 그림 자리가 밈이면 picture 칸을 지운다(그림 자리가 빈다).
    - image_pair 의 한 자리가 밈이면 그 자리를 비운다(DROPPED 표시 — 설명도 함께 뺀다). 두 자리가 다 밈이면 쪽을 뺀다.
    쪽 번호는 원래 사양 기준으로 적는다."""
    pics, _ = ledger(spec)
    sp = copy.deepcopy(spec)
    notes: list[str] = []
    keep = []
    for i, sl in enumerate(sp.get("slides") or [], 1):
        if not isinstance(sl, dict):
            keep.append(sl)
            continue
        kind = sl.get("kind")
        pid = _s(sl.get("picture"))
        if pid and is_meme(pics.get(pid)):
            if kind == "photo_caption":
                notes.append(f"{i}쪽(photo_caption): 밈 {pid} 을 뺐다 — 쪽을 뺐다")
                continue
            sl.pop("picture", None)
            notes.append(f"{i}쪽({kind}): 밈 {pid} 을 뺐다 — 그림 자리를 비웠다")
        if kind == "image_pair" and isinstance(sl.get("pair"), list):
            memes = [j for j, slot in enumerate(sl["pair"]) if isinstance(slot, dict) and is_meme(pics.get(_s(slot.get("picture"))))]
            if memes and len(memes) == len(sl["pair"]):
                # 두 자리가 다 밈이면 빈 두 칸짜리 장이 남는다 — photo_caption 처럼 쪽을 뺀다
                ids = " · ".join(_s(sl["pair"][j].get("picture")) for j in memes)
                notes.append(f"{i}쪽(image_pair): 두 자리가 다 밈({ids})이다 — 쪽을 뺐다")
                continue
            for j in memes:
                notes.append(f"{i}쪽(image_pair) {'왼' if j == 0 else '오른'}쪽 자리: 밈 {_s(sl['pair'][j].get('picture'))} 을 뺐다 — 그 자리를 비웠다")
                sl["pair"][j] = {DROPPED: "밈"}
        keep.append(sl)
    sp["slides"] = keep
    return sp, notes


def dropped_summary(notes: list[str]) -> str:
    """러닝시트·빌드 출력 한 줄: '밈 2장을 뺐다(엄격 모드) — …'."""
    if not notes:
        return ""
    return f"밈 {len(notes)}장을 뺐다(엄격 모드 — 완성본·공개용 판에는 밈을 넣지 않는다): " + " / ".join(notes)


# ── 공개 가부와 그림 검수 대장 파일(style: syuka 빌드가 덱과 함께 낸다) ─────────────────
PUBLIC_FILE = "공개_가부.json"


def _page(i: int, j: int) -> str:
    return str(i) if j < 0 else f"{i} {'왼' if j == 0 else '오른'}"


def used_pictures(spec: dict) -> dict[str, list[str]]:
    """{그림 번호: 쓴 쪽 목록}(처음 쓴 쪽 순서). 밈을 뺀 자리는 세지 않는다."""
    from ozl.render import spec as S
    out: dict[str, list[str]] = {}
    for i, sl in enumerate(spec.get("slides") or [], 1):
        if not isinstance(sl, dict):
            continue
        for j, v in S.slot_views(sl):
            pid = _s(v.get("picture"))
            if pid:
                out.setdefault(pid, []).append(_page(i, j))
    return out


def public_block(e: dict) -> str:
    """이 그림이 덱의 공개를 막는가 — 막으면 까닭, 아니면 빈 문자열. 비공개 판 전용과 연습용 판 전용(밈) 종류, 권리 확인 대기 그림이 막는다."""
    rule = rule_of(e)
    if rule is None:
        return f"종류 '{_s(e.get('kind'))}' 가 종류 표에 없다"
    if rule.verdict == PRIVATE_ONLY:
        return f"'{_s(e.get('kind'))}' 는 비공개 판에서만 쓴다"
    if rule.verdict == DRAFT_ONLY:
        return f"'{_s(e.get('kind'))}' 는 연습용 판에서만 쓴다"
    rp = rights_pending(e)
    if rp:
        return f"권리 확인 대기 — 비공개 판에서만 쓴다({rp})"
    return ""


# ── 두 판: swap 칸 ──────────────────────────────────────────────────────────
def edition_block(e: dict | None) -> str:
    """판을 가르게 하는 그림인가 — 판정 '비공개 판에서만'이거나 권리 확인 대기면 그 까닭, 아니면 빈 문자열.
    밈(연습용 판에서만)과 종류 표에 없는 그림은 아니다: 밈은 엄격 모드가 먼저 빼고, 표에 없는 종류는 검사가 실패시킨다."""
    if not e:
        return ""
    rule = rule_of(e)
    if rule is None or rule.verdict == DRAFT_ONLY:
        return ""
    return public_block(e)


def _slide_blocking(sl: dict, pics: dict[str, dict]) -> list[str]:
    """이 장에 든 막는 그림 — 'p1(통신사·언론사 사진)' 꼴(자리 순서, 겹치면 한 번)."""
    from ozl.render import spec as S
    out: list[str] = []
    for _, v in S.slot_views(sl):
        pid = _s(v.get("picture"))
        if pid and edition_block(pics.get(pid)):
            tag = f"{pid}({_s(pics[pid].get('kind'))})"
            if tag not in out:
                out.append(tag)
    return out


def has_swaps(spec: dict) -> bool:
    return any(isinstance(sl, dict) and SWAP in sl for sl in spec.get("slides") or [])


def needs_two(spec: dict) -> bool:
    """막는 그림(edition_block)이 한 장이라도 쓰였는가 — 그러면 엄격 모드의 check 와 build 가 두 판을 함께 다룬다."""
    pics, _ = ledger(spec)
    return any(isinstance(sl, dict) and _slide_blocking(sl, pics) for sl in spec.get("slides") or [])


def strip_swaps(spec: dict) -> dict:
    """비공개판 사양 — swap 칸을 뗀 사본. 원래 사양은 고치지 않는다."""
    sp = copy.deepcopy(spec)
    for sl in sp.get("slides") or []:
        if isinstance(sl, dict):
            sl.pop(SWAP, None)
    return sp


def _swap_shape_errors(i: int, sl: dict) -> list[str]:
    """swap 칸의 모양 — {why, set} 또는 {why, slide}."""
    sw = sl.get(SWAP)
    tag = f"{i}쪽: "
    if not isinstance(sw, dict):
        return [tag + "swap 은 {why, set 또는 slide} 사전이어야 한다"]
    out = []
    extra = [k for k in sw if k not in SWAP_KEYS]
    if extra:
        out.append(tag + f"swap 에 모르는 칸 {extra} 이 있다({' · '.join(SWAP_KEYS)} 만 쓴다)")
    if not (isinstance(sw.get("why"), str) and sw["why"].strip()):
        out.append(tag + "swap.why(바꾸는 까닭 한 줄)가 있어야 한다")
    has_set, has_slide = sw.get("set") is not None, sw.get("slide") is not None
    if has_set == has_slide:
        out.append(tag + "swap 에는 set(칸을 덮어쓴다)과 slide(장 전체를 다시 쓴다) 가운데 하나만 둔다")
        return out
    part = sw["set"] if has_set else sw["slide"]
    name = "set" if has_set else "slide"
    if not (isinstance(part, dict) and part):
        out.append(tag + f"swap.{name} 은 비지 않은 사전이어야 한다")
        return out
    if SWAP in part:
        out.append(tag + f"swap.{name} 안에 swap 을 다시 두지 않는다")
    if has_slide and _s(part.get("stage")) != _s(sl.get("stage")):
        out.append(tag + f"swap.slide 의 stage('{_s(part.get('stage'))}')는 원래 장('{_s(sl.get('stage'))}')과 같아야 한다 — 바꾼 판도 단계 순서가 같다")
    if has_set and "stage" in part and _s(part.get("stage")) != _s(sl.get("stage")):
        out.append(tag + "swap.set 으로 stage 를 바꾸지 않는다 — 바꾼 판도 단계 순서가 같다")
    return out


def _swapped(sl: dict) -> dict:
    """swap 을 적용한 장(swap 칸은 뗀다). 모양이 틀린 swap 은 적용하지 않고 떼기만 한다(오류는 swap_errors 가 낸다)."""
    sw = sl.get(SWAP)
    base = {k: copy.deepcopy(v) for k, v in sl.items() if k != SWAP}
    if not isinstance(sw, dict) or _swap_shape_errors(0, sl):
        return base
    if isinstance(sw.get("slide"), dict):
        return {k: copy.deepcopy(v) for k, v in sw["slide"].items() if k != SWAP}
    for k, v in sw["set"].items():
        if v is None:
            base.pop(k, None)
        else:
            base[k] = copy.deepcopy(v)
    return base


def _swap_result(after: dict, pics: dict[str, dict], rebuilt: bool) -> str:
    """바꾼 것 — 그림 번호와 종류 / 차트 / 원문 캡처 / 글과 도형으로 다시 짬."""
    from ozl.render import spec as S
    parts: list[str] = []
    for j, v in S.slot_views(after):
        where = (S.SLOT_NAME[j] + " ") if j >= 0 else ""
        what = S.visual_of(v)
        if what == "picture":
            pid = _s(v.get("picture"))
            parts.append(f"{where}{pid}({_s((pics.get(pid) or {}).get('kind'))})")
        elif what == "chart":
            parts.append(f"{where}차트")
        elif what == "capture":
            parts.append(f"{where}원문 캡처 {_s(v.get('capture')).rsplit('-', 1)[-1]}")
        elif what == "image":
            parts.append(f"{where}회색 자리")
    if rebuilt:
        return "글과 도형으로 다시 짬" + (f"({', '.join(parts)})" if parts else "")
    return ", ".join(parts) or "그림 없음(글만)"


def apply_swaps(spec: dict) -> tuple[dict, list[dict]]:
    """바꾼판 사양과 바꾼 장 목록. 원래 사양은 고치지 않는다.
    목록의 한 줄 = {page: 쪽, from: 원래 그림 번호와 종류, to: 바꾼 것, why: 까닭, mode: 'set' | 'slide'}. 모양이 틀린 swap 은 목록에 넣지 않는다."""
    pics, _ = ledger(spec)
    sp = copy.deepcopy(spec)
    rows: list[dict] = []
    out = []
    for i, sl in enumerate(sp.get("slides") or [], 1):
        if not (isinstance(sl, dict) and SWAP in sl):
            out.append(sl)
            continue
        after = _swapped(sl)
        if not _swap_shape_errors(i, sl):
            sw = sl[SWAP]
            rows.append({"page": i, "from": ", ".join(_slide_blocking(sl, pics)) or "(막는 그림 없음)",
                         "to": _swap_result(after, pics, isinstance(sw.get("slide"), dict)),
                         "why": sw["why"].strip(), "mode": "slide" if isinstance(sw.get("slide"), dict) else "set"})
        out.append(after)
    if "slides" in sp:
        sp["slides"] = out
    return sp, rows


def swap_errors(spec: dict, draft: bool = False, shape_only: bool = False) -> list[str]:
    """판 가르기 규칙의 실패 목록(쪽 번호는 넘겨받은 사양 기준 — 엄격 모드는 밈을 뺀 뒤의 쪽).
    늘 보는 것: swap 의 모양, 막는 그림이 없는 장의 swap, swap 을 적용한 뒤에도 남는 막는 그림.
    엄격 모드만: 막는 그림이 든 장에 swap 이 없다, swap 이 그림을 회색 자리(image)로 바꿨다.
    shape_only=True 면 모양만 본다(비공개판 하나만 다룰 때 — swap 이 덜 쓰였어도 그 판은 만들 수 있다)."""
    from ozl.render import spec as S
    pics, _ = ledger(spec)
    errs: list[str] = []
    for i, sl in enumerate(spec.get("slides") or [], 1):
        if not isinstance(sl, dict):
            continue
        block = _slide_blocking(sl, pics)
        if SWAP not in sl:
            if block and not draft and not shape_only:
                errs.append(f"{i}쪽: 막는 그림 {', '.join(block)}이 든 장에 swap 이 없다 — 바꾼 판에서 이 장을 무엇으로 바꿀지 적는다"
                            f"(swap: {{why, set 또는 slide}}). 비공개 판만 다루려면 --edition {EDITION_PRIVATE}")
            continue
        shape = _swap_shape_errors(i, sl)
        if shape:
            errs += shape
            continue
        if shape_only:
            continue
        if not block:
            errs.append(f"{i}쪽: 막는 그림이 없는 장에 swap 이 있다 — swap 은 판정 '{PRIVATE_ONLY}'이거나 권리 확인 대기인 그림이 든 장에만 둔다")
            continue
        after = _swapped(sl)
        left = _slide_blocking(after, pics)
        if left:
            errs.append(f"{i}쪽: swap 을 적용한 뒤에도 막는 그림 {', '.join(left)}이 남는다 — 바꾼 판에는 막는 그림을 두지 않는다")
        if not draft and any(S.visual_of(v) == "image" for _, v in S.slot_views(after)):
            errs.append(f"{i}쪽: swap 이 그림 자리를 회색 자리(image)로 바꿨다 — 바꾼 판에는 검수 대장의 그림, 차트, 원문 캡처를 넣거나 "
                        "글과 도형으로 다시 짠다(초안 모드는 통과)")
    return errs


def plan_editions(spec: dict, draft: bool = False, edition: str | None = None) -> tuple[list[str], list[tuple[str | None, dict, list[dict]]]]:
    """(판 가르기 실패, [(판 이름 | None, 그 판의 사양, 바꾼 장 목록)]). 판 이름 None = 판을 가르지 않는 한 판(지금까지의 동작 그대로).
    - 막는 그림도 swap 도 없는 사양: 한 판. 사양을 그대로 돌려준다.
    - 엄격 모드: 두 판(비공개판, 바꾼판). swap_errors 의 실패는 바꾼판을 만들 수 없다는 뜻이다.
    - 초안 모드: 판을 가르지 않는다. swap 은 모양만 보고 뗀다(연습용 판 하나 — 지금까지의 초안과 같다).
    - edition 을 주면 그 판 하나. 비공개판은 swap 의 모양만 보고(swap 이 덜 쓰였어도 만든다), 바꾼판은 swap_errors 전부를 본다.
      막는 그림도 swap 도 없는 사양에 edition 을 주면 실패(판 목록이 비어 있다)."""
    if edition is not None and edition not in EDITIONS:
        return [f"--edition '{edition}' 를 모른다({' · '.join(EDITIONS)})"], []
    two, sw = needs_two(spec), has_swaps(spec)
    if edition is None:
        if not two and not sw:
            return [], [(None, spec, [])]
        if draft:
            return swap_errors(spec, True, shape_only=True), [(None, strip_swaps(spec) if sw else spec, [])]
        swapped, rows = apply_swaps(spec)
        return swap_errors(spec, False), [(EDITION_PRIVATE, strip_swaps(spec), rows), (EDITION_SWAP, swapped, rows)]
    if not two and not sw:
        return [f"--edition {edition}: 이 사양에는 막는 그림도 swap 도 없다 — 판을 가르지 않는 사양이다(--edition 없이 돌린다)"], []
    swapped, rows = apply_swaps(spec)
    if edition == EDITION_PRIVATE:
        return swap_errors(spec, draft, shape_only=True), [(EDITION_PRIVATE, strip_swaps(spec), rows)]
    return swap_errors(spec, draft), [(EDITION_SWAP, swapped, rows)]


def used_in_any_edition(spec: dict) -> set[str]:
    """두 판을 합쳐 쓰인 그림 번호 — 한 판에서만 쓰는 그림을 '쓰지 않은 그림' 경고에서 빼는 데 쓴다."""
    return set(used_pictures(strip_swaps(spec))) | set(used_pictures(apply_swaps(spec)[0]))


def public_status(spec: dict) -> dict:
    """{public_ok, blocking: [{id, kind, pages, why}], pictures: 쓴 그림 수, rule}. 쓴 그림만 본다(대장에만 있는 그림은 덱에 없다)."""
    pics, _ = ledger(spec)
    blocking = []
    used = used_pictures(spec)
    for pid, pages in used.items():
        why = public_block(pics.get(pid) or {"kind": "(대장에 없음)"})
        if why:
            blocking.append({"id": pid, "kind": _s((pics.get(pid) or {}).get("kind")), "pages": pages, "why": why})
    return {"public_ok": not blocking, "blocking": blocking, "pictures": len(used),
            "rule": f"판정이 '{PRIVATE_ONLY}' 또는 '{DRAFT_ONLY}' 인 그림이 한 장이라도 든 덱은 공개하지 않는다(pictures.public_block)"}


def keywords_value(status: dict, edition: str | None = None) -> str:
    """pptx 문서 속성 keywords 에 넣는 글 — 공개 불가면 'ozl:private-only ozl:block=p3,p5', 공개 가능이면 빈 문자열.
    판을 가른 빌드는 끝에 판 표시를 붙인다: 비공개판 '… ozl:edition=private'(막는 그림 목록이 비어도 ozl:private-only 를 넣는다), 바꾼판 'ozl:edition=swap'."""
    parts: list[str] = []
    if not status.get("public_ok") or edition == EDITION_PRIVATE:
        ids = ",".join(b["id"] for b in status.get("blocking") or [])
        parts.append(f"{PRIVATE_KEYWORD} ozl:block={ids}" if ids or edition is None else PRIVATE_KEYWORD)
    if edition is not None:
        parts.append(EDITION_KEYWORD + EDITION_KEY[edition])
    return " ".join(parts)


def _check_text(e: dict, key: str) -> str:
    v = e.get(key)
    if not isinstance(v, dict):
        return ""
    if key == "origin_check":
        ld = v.get("local_diff")
        zone = f"구역 차이 {ld:g} (상한 {LOCAL_DIFF_MAX:g})" if isinstance(ld, (int, float)) and not isinstance(ld, bool) else "구역 차이는 검사 때 받은 파일로 잰다"
        return f"거리 {v.get('phash_distance')} (상한 {PHASH_MAX}) · {zone} · {_s(v.get('url'))} · {_s(v.get('checked_at'))}"
    return " / ".join(f"{k}: {_s(v.get(k))}" for k in ("spread", "mockery", "manipulation") if _s(v.get(k)))


def ledger_report(spec: dict, draft: bool = False) -> list[dict]:
    """그림 검수 대장 파일의 행 — 쓴 그림마다 번호, 쪽, 종류, 출처, 권리자, 라이선스, 판정, 원출처 대조, 맥락 점검, 공개 가부."""
    pics, _ = ledger(spec)
    rows = []
    for pid, pages in used_pictures(spec).items():
        e = pics.get(pid) or {}
        verdict, why, warns = judge(e, draft) if e else (NEVER, ["대장에 없다"], [])
        rows.append({"id": pid, "pages": pages, "kind": _s(e.get("kind")), "source_url": _s(e.get("source_url")), "origin": _s(e.get("origin")),
                     "rights_holder": _s(e.get("rights_holder")), "license": _s(e.get("license")), "verdict": verdict,
                     "problems": why, "warnings": warns, "sha256": _s(e.get("sha256")),
                     "origin_check": _check_text(e, "origin_check"), "context_check": _check_text(e, "context_check"),
                     "generator": _s(e.get("generator")), "public": "막음 — " + public_block(e) if public_block(e) else "공개 가능",
                     "checked_at": _s(e.get("checked_at"))})
        rp = rights_pending(e) if e else ""
        if rp:   # 권리 확인 대기인 그림에만 칸을 더한다(그 밖의 행은 지금까지와 같다)
            rows[-1]["rights_pending"] = rp
        if _s(e.get("kind")) == AI_KIND or any(_present_s(e.get(k)) for k in GENERATED_FIELDS):   # 생성 그림에만 칸을 더한다
            cc = e.get("concept_check")
            rows[-1].update({"concept": e.get("concept") if isinstance(e.get("concept"), bool) else None, "prompt": _s(e.get("prompt")),
                             "generated_at": _s(e.get("generated_at")),
                             "concept_check": {k: cc.get(k) for k in CONCEPT_CHECKS} if isinstance(cc, dict) else None})
    return rows


def generated_table(rows: list[dict]) -> list[str]:
    """그림 검수 대장의 「생성 그림」 절 — 번호, 쪽, 모델, 만든 시각, 점검과 프롬프트 전문. 생성 그림이 없으면 빈 목록."""
    def cell(x):
        return _s(x).replace("|", "／").replace("\n", " ")
    gen = [r for r in rows if "concept" in r]
    if not gen:
        return []
    out = ["## 생성 그림", "", "생성 그림은 개념도만 쓴다. 점검 칸(concept_check)은 그림을 연 쪽이 채운 것이고, 코드는 칸이 찼는지와 프롬프트의 정해 둔 꼴만 본다.", "",
           "| 번호 | 쪽 | 모델 | 만든 시각 | 개념도 | 점검 |", "|---|---|---|---|---|---|"]
    for r in gen:
        cc = r.get("concept_check")
        if isinstance(cc, dict):
            checks = " · ".join(f"{name} {'있음' if cc.get(k) is True else '없음' if cc.get(k) is False else '미기재'}" for k, name in CONCEPT_CHECKS.items())
        else:
            checks = "점검 칸 없음"
        concept = "예" if r.get("concept") is True else "아니오" if r.get("concept") is False else "미기재"
        out.append(f"| {r['id']} | {cell(', '.join(r['pages']))} | {cell(r['generator']) or '—'} | {cell(r.get('generated_at')) or '—'} | {concept} | {checks} |")
    out += ["", "프롬프트 전문:", ""]
    out += [f"- {r['id']}: {cell(r.get('prompt')) or '(없음)'}" for r in gen]
    return out + [""]


RIGHTS_PENDING_MARK = "권리 확인 대기, 비공개 판에서만"


def swap_table(swaps: list[dict] | None, edition: str) -> list[str]:
    """그림 검수 대장의 「바꾼 장」 절 — 쪽, 원래 그림, 바꾼 것, 까닭. 두 판의 대장에 같은 표가 들어간다."""
    def cell(x):
        return _s(x).replace("|", "／").replace("\n", " ")
    lead = ("바꾼 판에서는 아래 장이 이렇게 바뀐다." if edition == EDITION_PRIVATE else "비공개 판의 아래 장을 이렇게 바꿨다.")
    out = ["## 바꾼 장", ""]
    if not swaps:
        return out + ["바꾼 장 없음 — 사양에 swap 이 없다(바꾼 판을 만들 수 없는 사양이다).", ""]
    out += [lead, "", "| 쪽 | 원래 그림 | 바꾼 것 | 까닭 |", "|---|---|---|---|"]
    out += [f"| {s['page']} | {cell(s['from'])} | {cell(s['to'])} | {cell(s['why'])} |" for s in swaps]
    return out + [""]


def ledger_md(rows: list[dict], status: dict, card_id: str, ts: str, edition: str | None = None, swaps: list[dict] | None = None,
              pair: str = "") -> str:
    """edition 이 없으면(판을 가르지 않는 빌드) 지금까지와 같은 글이다. 있으면 머리에 판 이름을 적고 끝에 「바꾼 장」 표를 둔다."""
    def cell(x):
        return _s(x).replace("|", "／").replace("\n", " ")
    head = (f"공개 불가 — 막는 그림 {', '.join(b['id'] for b in status['blocking'])}" if not status["public_ok"] else "공개 가능(막는 그림 없음)")
    lines = [f"# 그림 검수 대장 — {card_id}", "", f"만든 시각 {ts} · 쓴 그림 {len(rows)}장 · {head}", ""]
    if edition is not None:
        what = "막는 그림이 든 판이다. 공개하지 않는다" if edition == EDITION_PRIVATE else "막는 그림이 든 장을 모두 바꾼 판이다"
        lines += [f"판: {edition} — {what}." + (f" 짝 폴더: `{pair}`." if pair else ""), ""]
    lines += [f"규칙: {status['rule']}. 원출처 대조는 지각 해시 거리 {PHASH_MAX} 이하이고 구역 차이 {LOCAL_DIFF_MAX:g} 이하인 것만 받는다. "
              "맥락 점검의 판단은 에이전트가 적고, 코드는 칸이 찼는지만 본다.", ""]
    if any(r.get("rights_pending") for r in rows):
        lines += [f"권리 확인 대기: 판정은 그대로 두고 공개만 막는다. {', '.join(RIGHTS_PENDING_HOSTS)} 화면 갈무리와 rights_pending 칸을 적은 그림이 여기에 든다.", ""]
    tail = swap_table(swaps, edition) if edition is not None else []
    if not rows:
        if edition is None:
            return "\n".join(lines + ["이 덱에는 그림 파일이 없다.", ""])
        return "\n".join(lines + ["이 덱에는 그림 파일이 없다.", ""] + tail)
    lines += ["| 번호 | 쪽 | 종류 | 권리자 · 라이선스 | 판정 | 원출처 대조 | 맥락 점검 | 공개 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        verdict = cell(r["verdict"]) + (f" — {RIGHTS_PENDING_MARK}" if r.get("rights_pending") else "")
        lines.append(f"| {r['id']} | {cell(', '.join(r['pages']))} | {cell(r['kind'])} | {cell(r['rights_holder'])} · {cell(r['license'])} | "
                     f"{verdict} | {cell(r['origin_check']) or '—'} | {cell(r['context_check']) or '—'} | {cell(r['public'])} |")
    lines += ["", "## 출처 주소", ""]
    for r in rows:
        extra = f" · 생성 {r['generator']}" if r["generator"] else ""
        lines.append(f"- {r['id']}: {r['source_url']} · 원출처 {cell(r['origin'])} · 확인 {r['checked_at']}{extra}")
    gen = generated_table(rows)
    if gen:
        lines += [""] + gen[:-1]
    if tail:
        lines += [""] + tail[:-1]
    return "\n".join(lines) + "\n"


# ── 비공개 등록 대장 ─────────────────────────────────────────────────────────
def registry_paths(extra=()) -> list[pathlib.Path]:
    """읽을 등록 대장 — 기본 대장(REGISTRY), 환경 변수 OZL_PRIVATE_REGISTRY 의 경로들, extra. 기본 대장은 늘 든다(빼는 길이 없다)."""
    import os
    out = [REGISTRY]
    for x in (os.environ.get(REGISTRY_ENV) or "").split(os.pathsep):
        if x.strip():
            out.append(pathlib.Path(x.strip()))
    out += [pathlib.Path(x) for x in extra]
    seen: dict[str, pathlib.Path] = {}
    for q in out:
        seen.setdefault(str(q.resolve()), q)
    return list(seen.values())


def registry_rows(paths=None) -> tuple[dict[str, dict], list[str]]:
    """({sha256: 그 해시의 첫 줄}, 읽지 못한 까닭). 없는 대장 파일은 빈 것으로 본다(아직 비공개판을 만든 적이 없다).
    줄을 읽지 못하면 까닭을 돌려준다 — public_check 는 그때 통과시키지 않는다(대장이 깨졌는데 '등록 없음'으로 보지 않는다)."""
    import json
    rows: dict[str, dict] = {}
    problems: list[str] = []
    for q in (registry_paths() if paths is None else [pathlib.Path(x) for x in paths]):
        if not q.exists():
            continue
        try:
            text = q.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as x:   # 글자가 깨진 대장도 '읽지 못했다'다 — 예외로 죽지 않고 통과시키지도 않는다
            problems.append(f"비공개 등록 대장을 읽지 못했다({type(x).__name__}): {q}")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                sha = _s(d.get("sha256")).lower()
                if not SHA_RE.match(sha):
                    raise ValueError("sha256")
            except (ValueError, AttributeError):
                problems.append(f"비공개 등록 대장 {q.name} {n}줄을 읽지 못했다 — 대장을 고친 뒤 다시 본다")
                continue
            rows.setdefault(sha, d)
    return rows, problems


def register_private(rows: list[dict], path: pathlib.Path | None = None) -> int:
    """등록 대장에 줄을 덧붙인다(줄마다 sha256 · what 무엇 · name 그림 번호나 파일 이름 · card_id · built_at · dir). 그 대장에 이미 있는 sha256 은 건너뛴다.
    돌려주는 값 = 새로 적은 줄 수."""
    import json
    q = pathlib.Path(path) if path is not None else REGISTRY
    have, _ = registry_rows([q])
    new = []
    for r in rows:
        sha = _s(r.get("sha256")).lower()
        if SHA_RE.match(sha) and sha not in have:
            have[sha] = r
            new.append(json.dumps({**r, "sha256": sha}, ensure_ascii=False))
    if new:
        q.parent.mkdir(parents=True, exist_ok=True)
        with open(q, "a", encoding="utf-8") as f:
            f.write("\n".join(new) + "\n")
    return len(new)


def _registry_note(d: dict) -> str:
    return " · ".join(x for x in (_s(d.get("what")), _s(d.get("name")), _s(d.get("card_id")), _s(d.get("built_at"))) if x)


def pptx_media_hashes(p: pathlib.Path) -> list[tuple[str, str]]:
    """pptx 안 미디어 파일(ppt/media/*)의 (이름, sha256). python-pptx 는 그림 파일을 바이트 그대로 넣으므로 대장의 그림 해시와 같다."""
    import zipfile
    out = []
    with zipfile.ZipFile(p) as z:
        for name in sorted(z.namelist()):
            if name.startswith("ppt/media/") and not name.endswith("/"):
                out.append((name, hashlib.sha256(z.read(name)).hexdigest()))
    return out


def _deck_keywords(src) -> str:
    """덱의 문서 속성 keywords. src 는 경로 또는 바이트(묶음 안의 덱). 프레젠테이션으로 열리지 않으면 예외가 난다."""
    from pptx import Presentation
    if isinstance(src, pathlib.Path):
        return _s(Presentation(str(src)).core_properties.keywords)
    import io
    return _s(Presentation(io.BytesIO(src)).core_properties.keywords)


def _pptx_keywords(p: pathlib.Path) -> str:
    return _deck_keywords(pathlib.Path(p))


# ── 파일 안 보기: 덱과 묶음(zip · tar · 압축 한 겹) ─────────────────────────────
# 묶음 안의 파일은 메모리에서만 읽는다. 디스크에 풀지 않고, 항목 이름은 출력 글에만 쓴다(경로로 쓰지 않는다 — '../' 가 든 이름도 해가 없다).
ARCHIVE_MAX_DEPTH = 3                    # 묶음을 풀어 보는 겹 수의 상한. 넘으면 안을 다 보지 못한 것이므로 '검사 불가'로 끝낸다.
#   겹으로 세는 것: 덱이 아닌 zip, tar(압축된 것 포함), 압축 한 겹(gz · bz2 · xz), 덱에 박힌 zip 꼴 파일. 묶음 바로 안의 덱은 세지 않는다.
ARCHIVE_MAX_BYTES = 256 * 1024 * 1024    # 파일 하나에서 풀어 보는 크기(풀린 바이트)의 합 상한. 넘으면 '검사 불가'
ARCHIVE_MAX_MEMBERS = 10_000             # 파일 하나에서 풀어 보는 항목 수의 합 상한. 넘으면 '검사 불가'
FILE_DECK, FILE_ZIP, FILE_TAR, FILE_PACKED, FILE_PLAIN = "deck", "zip", "tar", "packed", "plain"
PACKED_NAME = "(압축을 푼 것)"           # 압축 한 겹을 푼 내용의 이름(출력 글에 쓴다)
NOTICE = "[public-check] 알림:"          # 종료 코드에 영향이 없는 알림 줄의 머리(공개 게이트는 이 줄을 오류로 세지 않는다)
_UNPACKABLE = ((b"7z\xbc\xaf\x27\x1c", "7z"), (b"Rar!\x1a\x07", "rar"), (b"\x28\xb5\x2f\xfd", "zstd"), (b"\x04\x22\x4d\x18", "lz4"),
               (b"!<arch>\n", "ar"))
LZMA_ALONE_PROBE = 4096                  # lzma-alone(.lzma)인지 보려고 풀어 보는 머리 바이트 수
_ZIP_END = b"PK\x05\x06"                 # zip 끝 표지 — 끝 65,557 바이트(표지 22 + 덧글 최대 65,535) 안에 있다


class Unscannable(Exception):
    """파일이나 묶음의 안을 끝까지 보지 못했다(가리지 못했다, 너무 깊다, 너무 크다, 풀 수 없다). 부르는 쪽은 통과시키지 않는다."""


@dataclass
class Found:
    """scan 이 내는 파일 하나 — 맨 바깥 파일이거나 묶음·덱 안의 파일."""
    label: str           # 어디에 있는가(출력 글) — 맨 바깥은 파일 이름, 안의 것은 '<바깥> 안 <항목 이름>'
    kind: str            # FILE_* — 여러 꼴로 읽히면 첫째 꼴(덱 · zip 이 먼저)
    sha256: str
    src: object          # 경로(맨 바깥 파일) 또는 바이트(안의 파일)
    name: str            # 항목 이름(맨 바깥은 파일 이름)
    holder: str = ""     # 이 파일이 든 것의 종류(FILE_*). 맨 바깥은 빈 문자열
    holder_label: str = ""
    views: tuple = ()    # 읽을 수 있는 꼴 전부


class _Budget:
    """파일 하나를 보는 동안 푼 크기와 항목 수 — 상한을 넘으면 Unscannable."""
    def __init__(self):
        self.bytes = self.members = 0

    def add(self, n: int, label: str):
        self.bytes += n
        if self.bytes > ARCHIVE_MAX_BYTES:
            raise Unscannable(f"{label}: 풀린 크기의 합이 상한({ARCHIVE_MAX_BYTES:,} 바이트)을 넘는다 — 안을 다 보지 못했다(풀어서 파일마다 검사한다)")

    def count(self, label: str, n: int = 1):
        self.members += n
        if self.members > ARCHIVE_MAX_MEMBERS:
            raise Unscannable(f"{label}: 항목 수가 상한({ARCHIVE_MAX_MEMBERS:,}개)을 넘는다 — 안을 다 보지 못했다(풀어서 파일마다 검사한다)")

    def need(self, n: int, label: str, name: str = ""):
        """풀기 전에 적힌 크기(zip 의 file_size · tar 의 size)를 남은 한도와 견준다 — 넘으면 풀지 않는다. 세지는 않는다(푼 바이트는 add 가 센다)."""
        if self.bytes + n > ARCHIVE_MAX_BYTES:
            what = f" 항목 {_clean(name)} 의" if name else ""
            raise Unscannable(f"{label}:{what} 적힌 크기({n:,} 바이트)까지 풀면 상한({ARCHIVE_MAX_BYTES:,} 바이트)을 넘는다 — 풀지 않았다(풀어서 파일마다 검사한다)")


def _clean(name) -> str:
    """출력에 넣을 이름 — 제어 문자(줄바꿈 포함)를 '?' 로 바꾸고 120자에서 자른다(항목 이름이 출력 줄을 지어내지 못하게)."""
    s = "".join(ch if ch.isprintable() else "?" for ch in str(name))
    return s if len(s) <= 120 else s[:117] + "…"


def _open_src(src):
    import io
    return open(src, "rb") if isinstance(src, pathlib.Path) else io.BytesIO(src)


def _packed_kind(head: bytes) -> str:
    """압축 한 겹의 표지면 그 이름('gz' · 'bz2' · 'xz'), 아니면 빈 문자열. 글 파일이 우연히 걸리지 않게 표지를 끝까지 본다."""
    if head[:3] == b"\x1f\x8b\x08":
        return "gz"
    if len(head) >= 10 and head[:3] == b"BZh" and head[3:4] in b"123456789" and head[4:10] in (b"1AY&SY", b"\x17rE8P\x90"):
        return "bz2"
    if head[:6] == b"\xfd7zXZ\x00":
        return "xz"
    return ""


def _unpack_strict(f, name: str, budget: _Budget, label: str) -> bytes:
    """bz2 · xz 한 겹을 푼 바이트(이어진 압축 흐름은 이어서 푼다). 표준 파일 객체(BZ2File · LZMAFile)는 압축 흐름 뒤에 붙은 풀리지 않는 내용을
    말없이 버린다 — 여기서는 버리지 않고 예외로 끝낸다(보지 못한 부분이 있다). 뒤에 붙은 0 은 받는다(xz 의 흐름 사이 채움)."""
    import bz2
    import lzma
    make = bz2.BZ2Decompressor if name == "bz2" else lzma.LZMADecompressor
    out, d = [], make()
    while True:
        if d.eof:
            rest = d.unused_data
            while rest.count(0) == len(rest):   # 다음 흐름의 처음까지 0 을 건너뛴다(빈 것도 여기 든다)
                rest = f.read(1 << 16)
                if not rest:
                    return b"".join(out)
            d, data = make(), rest.lstrip(b"\0")
        elif d.needs_input:
            data = f.read(1 << 16)
            if not data:
                raise EOFError("압축 흐름이 끝 표지 전에 끝났다")
        else:
            data = b""
        part = d.decompress(data, 1 << 20)
        budget.add(len(part), label)
        out.append(part)


def _zip_view(f) -> tuple[str, int] | None:
    """zip 으로 읽히면 (FILE_DECK 또는 FILE_ZIP, 첫 항목 앞에 붙은 바이트 수), zip 이 아니면 None.
    덱 = 항목 이름이 ppt/ 로 시작하거나(대소문자와 역슬래시를 가리지 않는다) [Content_Types].xml 이 프레젠테이션 부품을 적은 묶음.
    끝에 zip 표지가 있는데 목록을 읽지 못하면 '덱이 아님'이 아니라 '가리지 못함'이다 — Unscannable."""
    import zipfile
    try:
        with zipfile.ZipFile(f) as z:
            infos = z.infolist()
            lead = min((i.header_offset for i in infos), default=z.start_dir)
            if any(i.filename.replace("\\", "/").lstrip("/").lower().startswith("ppt/") for i in infos):
                return FILE_DECK, lead
            for i in infos:
                if i.filename.replace("\\", "/").lstrip("/").lower() == "[content_types].xml" and i.file_size <= (1 << 20):
                    if b"presentationml" in z.read(i):
                        return FILE_DECK, lead
            return FILE_ZIP, lead
    except zipfile.BadZipFile as x:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 65557))
        if _ZIP_END in f.read():
            raise Unscannable(f"끝에 zip 표지가 있는데 목록을 읽지 못했다({x})") from x
        return None
    except Exception as x:  # noqa: BLE001 — zip 으로 열리다가 난 그 밖의 오류(지원하지 않는 판, 읽기 오류)도 가리지 못한 것이다
        raise Unscannable(f"zip 꼴인데 읽지 못했다({type(x).__name__}: {x})") from x


def _tar_mode(head: bytes) -> str:
    """tarfile 을 열 방식 — 압축 표지(_packed_kind)가 있으면 그 압축으로만('r:gz' · 'r:bz2' · 'r:xz'), 없으면 압축 없는 tar 로만('r:').
    'r:*' 는 쓰지 않는다: 압축 방식을 하나씩 다 열어 보는데, 그 가운데 xz 풀이가 0 으로 찬 파일을 끝까지 읽는다(64MiB 에 5초 넘게 — 실측)."""
    kind = _packed_kind(head)
    return f"r:{kind}" if kind else "r:"


def _tar_view(f) -> bool:
    """tar(압축된 것 포함)로 읽히고 첫 항목이 있으면 참. 0 으로 찬 구역으로 시작하는 파일은 tar 로 보지 않는다 —
    tarfile 은 그것을 빈 tar 로 읽고 뒤의 내용을 보지 않는다(뒤에 내용이 있으면 압축 한 겹이나 그 밖의 파일로 본다).
    종류는 머리의 표지로 먼저 가린다(_tar_mode)."""
    import tarfile
    f.seek(0)
    mode = _tar_mode(f.read(16))
    f.seek(0)
    try:
        with tarfile.open(fileobj=f, mode=mode) as t:
            return t.next() is not None
    except tarfile.TarError:
        return False


def _lzma_alone(f) -> bool:
    """lzma-alone(.lzma — 표지가 없는 옛 형식)으로 풀리는가. 머리 13바이트의 꼴이 맞을 때만 머리 LZMA_ALONE_PROBE 바이트를 그 형식으로 풀어 본다.
    꼴: 속성 바이트 0x5D(lc=3 · lp=0 · pb=2 — 압축 도구들의 기본값), 사전 크기가 2^n 또는 2^n + 2^(n-1)(4KiB 이상), 압축 흐름의 첫 바이트 0.
    글 파일과 0 으로 찬 파일은 이 꼴이 아니다(시험이 본다). 다른 속성값으로 만든 .lzma 는 못 잡는다."""
    import lzma
    f.seek(0)
    head = f.read(LZMA_ALONE_PROBE)
    if len(head) < 14 or head[0] != 0x5D or head[13] != 0:
        return False
    d = int.from_bytes(head[1:5], "little")
    if d < 4096 or not any(d == (1 << n) or d == (1 << n) + (1 << (n - 1)) for n in range(12, 32)):
        return False
    try:
        return bool(lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(head, 1))   # 한 바이트라도 풀리면 그 형식이다(빈 내용의 .lzma 는 볼 것이 없다)
    except lzma.LZMAError:
        return False


def _views(src) -> list[str]:
    """이 파일을 읽을 수 있는 꼴 전부 — [덱 또는 zip][, tar 또는 압축 한 겹]. 빈 목록이면 그 밖의 파일이다. 확장자는 보지 않는다.
    한 파일이 두 꼴로 읽힐 수 있다: 압축하지 않은 tar 의 끝에 pptx 가 있으면 zip 으로도 읽혀 마지막 항목만 보인다(zip 은 끝에서, tar 는
    앞에서 읽는다). 그때는 두 꼴을 다 본다. 가리지 못하면 Unscannable: 읽지 못하는 파일, 끝에 zip 표지가 있는데 목록을 읽지 못하는 파일,
    첫 항목 앞에 다른 내용이 붙은 zip(그 앞부분을 tar 로도 읽지 못할 때 — 앞에 붙은 것을 보지 못한다), 풀 줄 모르는 묶음 형식(_UNPACKABLE)."""
    try:
        with _open_src(src) as f:
            head = f.read(16)
            views = []
            z = _zip_view(f)
            tar_error = None
            try:
                is_tar = _tar_view(f)
            except Exception as x:  # noqa: BLE001 — 압축된 꼴인데 머리를 풀지 못했다(잘린 gz 등). 아래에서 압축 한 겹으로 다시 읽다가 실패한다
                is_tar, tar_error = False, x
            if z is not None:
                if z[1] > 0 and not is_tar:
                    raise Unscannable(f"zip 의 첫 항목 앞에 다른 내용이 {z[1]:,} 바이트 붙어 있다 — 그 부분을 보지 못한다(풀어서 파일마다 검사한다)")
                views.append(z[0])
            if is_tar:
                views.append(FILE_TAR)
            elif _packed_kind(head):
                views.append(FILE_PACKED)
            elif tar_error is not None:
                raise Unscannable(f"tar 인지 가리지 못했다({type(tar_error).__name__}: {tar_error})")
            if not views:
                if head[:4] == b"PK\x03\x04":   # zip 항목 머리로 시작하는데 끝 표지를 찾지 못했다(잘린 zip, 뒤에 64KiB 넘게 덧붙인 zip)
                    raise Unscannable("zip 머리(PK)로 시작하는데 목록을 읽지 못했다 — 잘렸거나 뒤에 다른 내용이 붙었다")
                for magic, name in _UNPACKABLE:
                    if head.startswith(magic):
                        raise Unscannable(f"풀 줄 모르는 묶음 형식이다({name}) — 풀어서 파일마다 검사한다")
                if _lzma_alone(f):
                    raise Unscannable("풀 줄 모르는 묶음 형식이다(lzma) — 풀어서 파일마다 검사한다")
            return views
    except OSError as x:
        raise Unscannable(f"읽지 못했다({type(x).__name__}: {x})") from x


def content_kind(src) -> str:
    """파일 안을 보고 가린 종류(FILE_*). src 는 경로 또는 바이트. 여러 꼴로 읽히면 첫째 꼴(덱 · zip 이 먼저). 가리지 못하면 Unscannable."""
    views = _views(src if isinstance(src, (bytes, bytearray)) else pathlib.Path(src))
    return views[0] if views else FILE_PLAIN


def is_deck_file(p: pathlib.Path) -> bool:
    """파일 안을 보고 가린다 — zip 안에 프레젠테이션 부품이 있으면 덱이다. 확장자는 보지 않는다
    (.ppsx · .pptx.zip · 확장자 없는 이름으로 바꾼 pptx 사본을 덱으로 검사하려는 것이다).
    거짓 = 덱이 아니다. 가리지 못한 파일(읽지 못한다, zip 꼴인데 목록이 깨졌다)은 거짓이 아니라 Unscannable 이다 — 부르는 쪽이 통과시키지 않는다."""
    return content_kind(pathlib.Path(p)) == FILE_DECK


def _read_all(f, budget: _Budget | None, label: str) -> bytes:
    """파일 객체를 끝까지 읽는다. budget 이 있으면 읽은 바이트를 센다(이미 센 바이트를 다시 읽을 때는 None)."""
    parts = []
    while True:
        chunk = f.read(1 << 20)
        if not chunk:
            break
        if budget is not None:
            budget.add(len(chunk), label)   # 적힌 크기를 믿지 않고 실제로 푼 바이트를 센다
        parts.append(chunk)
    return b"".join(parts)


def _unpack(f, budget: _Budget, label: str) -> bytes:
    """압축 한 겹(gz · bz2 · xz)을 푼 바이트. 압축 흐름 뒤에 풀리지 않는 내용이 붙어 있으면 예외가 난다(보지 못한 부분을 남기지 않는다)."""
    f.seek(0)
    name = _packed_kind(f.read(16))
    f.seek(0)
    if name == "gz":   # GzipFile 은 압축 흐름 뒤에 붙은 풀리지 않는 내용에서 예외를 낸다
        import gzip
        with gzip.GzipFile(fileobj=f) as m:
            return _read_all(m, budget, label)
    return _unpack_strict(f, name, budget, label)


def _members(src, views, label: str, budget: _Budget):
    """묶음 · 덱 안의 파일마다 (항목 이름, 바이트). 폴더와 링크 같은 내용 없는 항목은 건너뛴다. 풀지 못하면(암호, 깨진 항목, 잘린 압축) Unscannable."""
    import io
    import tarfile
    import zipfile
    for view in views:
        try:
            with _open_src(src) as f:
                if view in (FILE_DECK, FILE_ZIP):
                    with zipfile.ZipFile(f) as z:
                        infos = z.infolist()
                        budget.count(label, len(infos))   # 항목을 읽기 전에 목록 길이를 한 번에 견준다(목록 자체는 zipfile 이 열 때 다 읽는다)
                        for info in infos:   # 이름이 겹치는 항목도 하나씩 본다(이름이 아니라 항목으로 연다)
                            if info.is_dir():
                                continue
                            budget.need(info.file_size, label, info.filename)   # 적힌 크기가 남은 한도를 넘으면 풀지 않는다
                            with z.open(info) as m:
                                data = _read_all(m, budget, label)
                            yield info.filename, data
                elif view == FILE_TAR:
                    packed = bool(_packed_kind(f.read(16)))
                    f.seek(0)
                    # 압축된 tar 는 먼저 직접 푼다 — tarfile 이 쓰는 BZ2File · LZMAFile 은 압축 흐름 뒤에 붙은 내용을 말없이 버린다.
                    # 그때 푼 바이트는 이미 셌으므로 항목을 읽을 때 다시 세지 않는다
                    raw = io.BytesIO(_unpack(f, budget, label)) if packed else f
                    inner = None if packed else budget
                    with tarfile.open(fileobj=raw, mode="r:") as t:
                        for m in t:
                            budget.count(label)
                            if not (m.isreg() or m.type not in tarfile.SUPPORTED_TYPES):   # 폴더 · 링크 · 장치는 내용이 없다. 모르는 종류는 tar 가 파일로 푼다
                                continue
                            if inner is not None or m.issparse():   # 적힌 크기가 남은 한도를 넘으면 풀지 않는다(압축된 tar 는 흐름을 풀 때 이미 셌다)
                                budget.need(m.size, label, m.name)
                            # 구멍 난(sparse) 항목은 풀면 흐름보다 커진다 — 압축된 tar 에서도 센다
                            data = _read_all(t.extractfile(m), budget if m.issparse() else inner, label)
                            yield m.name, data
                        raw.seek(t.offset)   # tarfile 은 끝 표지(0 으로 찬 구역)나 읽지 못하는 머리에서 조용히 멈춘다 — 그 뒤가 0 뿐인지 본다
                        while True:
                            chunk = raw.read(1 << 20)
                            if not chunk:
                                break
                            if inner is not None:
                                inner.add(len(chunk), label)
                            if chunk.count(0) != len(chunk):
                                raise Unscannable(f"{label}: tar 의 마지막 항목 뒤에 내용이 더 있다 — 그 부분을 보지 못한다(풀어서 파일마다 검사한다)")
                else:
                    yield PACKED_NAME, _unpack(f, budget, label)
        except Unscannable:
            raise
        except Exception as x:  # noqa: BLE001 — 까닭이 무엇이든 안을 다 보지 못했다
            raise Unscannable(f"{label}: 풀지 못했다({type(x).__name__}: {x})") from x


def _inside(h: Found, depth: int, budget: _Budget):
    """h(덱 또는 묶음) 안의 파일을 차례로 낸다. depth = h 까지 센 겹 수."""
    for name, data in _members(h.src, h.views, h.label, budget):
        label = f"{h.label} 안 {_clean(name)}"
        try:
            views = _views(data)
        except Unscannable as x:
            raise Unscannable(f"{label}: {x}") from x
        f = Found(label, views[0] if views else FILE_PLAIN, hashlib.sha256(data).hexdigest(), data, name, h.kind, h.label, tuple(views))
        yield f
        if not views:
            continue
        cost = 0 if (views == [FILE_DECK] and h.kind != FILE_DECK) else 1
        if depth + cost > ARCHIVE_MAX_DEPTH:
            raise Unscannable(f"{label}: 묶음이 {ARCHIVE_MAX_DEPTH}겹보다 깊다 — 안을 다 보지 못했다(풀어서 파일마다 검사한다)")
        yield from _inside(f, depth + cost, budget)


def scan(path: pathlib.Path, label: str | None = None):
    """파일 하나와 그 안의 파일을 차례로 낸다(Found) — 맨 바깥 파일, 덱이면 부품마다, 묶음(zip · tar · 압축 한 겹)이면 항목마다,
    겹쳐 있으면 ARCHIVE_MAX_DEPTH 겹까지. 안의 파일도 확장자가 아니라 안을 보고 가린다(묶음 안의 덱은 kind 가 FILE_DECK 이다).
    메모리에서만 읽는다. 끝까지 보지 못하면(가리지 못했다, 너무 깊다, 너무 크다, 풀 수 없다) 그 자리에서 Unscannable 이 난다."""
    path = pathlib.Path(path)
    label = _clean(path.name if label is None else label)
    try:
        views = _views(path)
        sha = file_sha256(path)
    except Unscannable as x:
        raise Unscannable(f"{label}: {x}") from x
    except OSError as x:
        raise Unscannable(f"{label}: 읽지 못했다({type(x).__name__}: {x})") from x
    top = Found(label, views[0] if views else FILE_PLAIN, sha, path, path.name, "", "", tuple(views))
    yield top
    if views:
        yield from _inside(top, 0 if views == [FILE_DECK] else 1, _Budget())


def walk_folder(folder: pathlib.Path) -> tuple[list[pathlib.Path], list[tuple[pathlib.Path, str]]]:
    """(폴더 안의 모든 파일 — 하위 폴더 포함, 이름 순서 · 보지 못한 것 [(경로, 까닭)]).
    보지 못한 것: 목록을 읽지 못한 폴더(권한), 폴더로 가는 링크(따라가지 않는다 — 폴더 밖을 훑게 되고 고리가 생길 수 있다), 깨진 링크,
    상태를 읽지 못한 항목(목록은 읽히는데 안으로 들어갈 권한이 없는 폴더의 항목), 보통 파일이 아닌 항목(소켓 · 이름 붙은 파이프 · 장치).
    파일로 가는 링크는 가리키는 파일의 내용을 본다. 부르는 쪽은 보지 못한 것이 있으면 통과시키지 않는다('검사 불가')."""
    import os
    import stat
    files: list[pathlib.Path] = []
    gaps: list[tuple[pathlib.Path, str]] = []

    def unreadable(x: OSError):
        gaps.append((pathlib.Path(x.filename or folder), f"폴더의 목록을 읽지 못했다({type(x).__name__}) — 그 아래를 보지 못했다"))

    def is_link(q: pathlib.Path) -> bool:   # 링크 자체의 상태도 읽지 못하면(들어갈 권한이 없는 폴더의 항목) 링크가 아닌 것으로 본다
        try:
            return stat.S_ISLNK(os.lstat(q).st_mode)
        except OSError:
            return False

    for base, dirs, names in os.walk(folder, followlinks=False, onerror=unreadable):
        dirs.sort()
        for d in dirs:
            q = pathlib.Path(base) / d
            if is_link(q):
                gaps.append((q, "폴더로 가는 링크다 — 따라가지 않았다. 가리키는 폴더를 직접 검사한다"))
        for n in sorted(names):
            q = pathlib.Path(base) / n
            try:
                mode = os.stat(q).st_mode
            except OSError as x:
                if is_link(q):
                    gaps.append((q, f"깨진 링크다({type(x).__name__}) — 가리키는 것을 보지 못했다"))
                else:
                    gaps.append((q, f"상태를 읽지 못했다({type(x).__name__}) — 파일인지 폴더인지 알 수 없다"))
                continue
            if stat.S_ISREG(mode):
                files.append(q)
            elif stat.S_ISDIR(mode):   # 목록을 읽은 뒤에 폴더로 바뀌었거나 os.walk 가 폴더로 보지 못한 항목
                gaps.append((q, "폴더인데 안을 보지 못했다"))
            else:
                gaps.append((q, "보통 파일이 아니다(소켓 · 파이프 · 장치) — 읽지 않았다"))
    gaps.sort(key=lambda g: str(g[0]))
    return files, gaps


def _files_under(folder: pathlib.Path) -> list[pathlib.Path]:
    """폴더 안의 모든 파일(하위 폴더 포함, 이름 순서). 보지 못한 것까지 알아야 하면 walk_folder 를 쓴다."""
    return walk_folder(folder)[0]


def _gap_label(q: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return _clean(pathlib.Path(q).relative_to(root).as_posix() or ".")
    except ValueError:
        return _clean(q)


def private_marks(keywords: str) -> tuple[bool, list[str]]:
    """문서 속성 keywords → (비공개 판 표시가 있는가, ozl:block 의 그림 번호들)."""
    toks = _s(keywords).split()
    m = re.search(r"ozl:block=(\S+)", _s(keywords))
    return (PRIVATE_KEYWORD in toks or EDITION_KEYWORD + EDITION_KEY[EDITION_PRIVATE] in toks,
            [x for x in (m.group(1).split(",") if m else []) if x])


def public_check(path: pathlib.Path, registries=None) -> tuple[int, list[str]]:
    """산출 폴더 또는 파일 하나 → (종료 코드, 출력 줄). 막는 것이 있으면 1, 없으면 0, 읽을 것이 없으면(없는 경로, 빈 폴더) 2.
    파일은 확장자가 아니라 안을 보고 가린다(scan): 덱(이름이 .pptx 가 아니어도) · 묶음(zip · tar · 압축 한 겹) · 그 밖의 파일.
    보는 것:
      - 폴더의 공개_가부.json: 막는 그림 목록, 공개 불가 표시, 판(edition 이 비공개판이면 목록이 비어도 막는다)
      - 덱의 문서 속성 keywords: ozl:private-only(와 ozl:block=번호들), ozl:edition=private
      - 파일의 sha256 과 덱 · 묶음 안에 든 파일마다의 sha256 이 비공개 등록 대장에 있는가(keywords 를 지운 사본을 안에 든 그림으로 잡는다)
      - 묶음 안의 덱도 덱으로 연다(문서 속성, 안에 든 그림). 겹친 묶음은 ARCHIVE_MAX_DEPTH 겹까지 풀어 본다
    폴더는 그 안의 모든 파일을 하위 폴더까지 이렇게 본다(하나라도 막으면 막는다). 폴더에서 보지 못한 것(walk_folder — 목록을 읽지 못한
    하위 폴더, 폴더로 가는 링크, 깨진 링크, 상태를 읽지 못한 항목)이 있으면 '검사 불가' 줄과 종료 코드 1 이다. 폴더 링크는 따라가지 않는다.
    끝까지 보지 못한 파일은 통과시키지 않는다 — 종료 코드 1 과 '검사 불가' 줄: 덱 꼴인데 프레젠테이션으로 열리지 않는 파일, 이름이 .pptx 인데
    덱이 아닌 파일, 가리지 못한 파일, ARCHIVE_MAX_DEPTH 겹보다 깊은 묶음, 풀린 크기나 항목 수가 상한을 넘는 묶음, 풀 수 없는 묶음,
    묶음 목록에 나오지 않는 내용이 붙은 파일(zip 의 첫 항목 앞, tar 의 마지막 항목 뒤, 압축 흐름 뒤).
    registries = 볼 등록 대장 목록(없으면 registry_paths()). 대장의 줄을 읽지 못하면 통과시키지 않는다.
    대장이 없거나 비면 해시를 견줄 것이 없다 — 종료 코드는 그대로이고 알림 줄(NOTICE)을 낸다(대장은 비공개판을 만든 기기에만 있다)."""
    import json
    path = pathlib.Path(path)
    blocked: dict[str, str] = {}     # 막는 그림 번호 → 까닭
    other: list[str] = []            # 그 밖에 막는 까닭(판 표시 · 등록 대장의 해시 · 읽지 못한 대장 · 검사 불가)
    seen: list[str] = []
    if path.is_dir():
        pj = path / PUBLIC_FILE
        if pj.is_file():
            seen.append(PUBLIC_FILE)
            try:
                st = json.loads(pj.read_text(encoding="utf-8"))
                if not isinstance(st, dict):
                    raise ValueError("사전이 아니다")
            except (OSError, ValueError) as x:
                st = {}
                other.append(f"검사 불가 — {PUBLIC_FILE} 을 읽지 못했다({type(x).__name__})")
            for b in st.get("blocking") or []:
                b = b if isinstance(b, dict) else {}
                blocked[_s(b.get("id")) or "?"] = f"{b.get('kind', '')} · {', '.join(map(str, b.get('pages') or []))}쪽 — {b.get('why', '')}"
            if st.get("edition") == EDITION_PRIVATE:
                other.append(f"{PUBLIC_FILE} 의 판이 {EDITION_PRIVATE}이다")
            elif st.get("public_ok") is False and not st.get("blocking"):
                blocked["?"] = "공개_가부.json 이 공개 불가라고 적었다"
        found, gaps = walk_folder(path)
        files = [(f, f.relative_to(path).as_posix()) for f in found]
        # 읽지 못한 하위 폴더, 폴더 링크, 깨진 링크 — 그 아래를 보지 못했으므로 통과시키지 않는다
        other += [f"검사 불가 — {_gap_label(q, path)}: {why}" for q, why in gaps]
    elif path.is_file():
        files = [(path, path.name)]
        seen.append(_clean(path.name))
    else:
        return 2, [f"[public-check] 파일이나 산출 폴더가 아니다: {path}"]
    if not files and not seen and not other:
        return 2, [f"[public-check] {path} 에 볼 파일이 없다"]
    reg, problems = registry_rows(registries)
    other += problems
    for f, label in files:
        top = None
        try:
            for it in scan(f, label):
                top = top or it
                if it.sha256 in reg:
                    note = _registry_note(reg[it.sha256])
                    if not it.holder:
                        other.append(f"{it.label} 파일의 sha256 이 비공개 등록 대장에 있다({note})")
                    elif it.holder == FILE_DECK and it.name.replace("\\", "/").lstrip("/").lower().startswith("ppt/media/"):
                        other.append(f"{it.holder_label} 안 그림 {_clean(it.name)} 의 sha256 이 비공개 등록 대장에 있다({note})")
                    else:
                        other.append(f"{it.label} 의 sha256 이 비공개 등록 대장에 있다({note})")
                if it.kind != FILE_DECK:
                    continue
                if it.label not in seen:
                    seen.append(it.label)
                try:
                    kw = _deck_keywords(it.src)
                except Exception as x:  # noqa: BLE001 — 덱 꼴인데 열리지 않는 파일(슬라이드 쇼 형식, 깨진 묶음)은 문서 속성을 볼 수 없다
                    other.append(f"검사 불가 — {it.label}: 덱 꼴인데 프레젠테이션으로 열지 못했다({type(x).__name__}: {x})")
                    continue
                toks = kw.split()
                if PRIVATE_KEYWORD in toks:
                    m = re.search(r"ozl:block=(\S+)", kw)
                    for pid in (m.group(1).split(",") if m else ["?"]):
                        blocked.setdefault(pid, f"{it.label} 문서 속성에 {PRIVATE_KEYWORD}")
                elif EDITION_KEYWORD + EDITION_KEY[EDITION_PRIVATE] in toks:
                    other.append(f"{it.label} 문서 속성의 판이 {EDITION_PRIVATE}이다")
        except Unscannable as x:
            other.append(f"검사 불가 — {x}")
        except Exception as x:  # noqa: BLE001 — 읽다가 난 그 밖의 오류도 통과시키지 않는다
            other.append(f"검사 불가 — {_clean(label)} 을 읽지 못했다({type(x).__name__}: {x})")
        if top is not None and f.suffix.lower() == ".pptx" and top.kind != FILE_DECK:
            other.append(f"검사 불가 — {top.label}: 이름이 .pptx 인데 덱(프레젠테이션)으로 읽히지 않는다")
    other = list(dict.fromkeys(other))
    if path.is_dir() and files:
        seen.append(f"파일 해시 {len(files)}개")
    notes = []
    if not reg and not problems:
        names = ", ".join(_rel_root(q) for q in (registry_paths() if registries is None else [pathlib.Path(x) for x in registries])) or "없음"
        notes.append(f"{NOTICE} 비공개 등록 대장이 없거나 비어 있어 파일 해시를 견주지 못했다 — 문서 속성과 {PUBLIC_FILE} 만 봤다"
                     f"(본 대장: {names}). 대장은 비공개판을 만든 기기에만 있다")
    if blocked or other:
        head = "[public-check] 공개 불가" + (f" · 막는 그림 {len(blocked)}장: {', '.join(blocked)}" if blocked else "") + \
            (f" · 그 밖 {len(other)}건" if other else "")
        return 1, [head] + [f"  {k}: {v}" for k, v in blocked.items()] + [f"  {x}" for x in other] + [f"  본 것: {', '.join(seen) or '없음'}"] + notes
    return 0, [f"[public-check] 공개 가능(막는 그림 없음) · 본 것: {', '.join(seen)}"] + notes


def _rel_root(q: pathlib.Path) -> str:
    try:
        return str(pathlib.Path(q).resolve().relative_to(ROOT))
    except ValueError:
        return str(q)


def public_check_main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("python -m ozl.render public-check <산출 폴더 · 파일 하나(pptx · pdf · png · jpg · zip · tar · 이름을 바꾼 사본)>   "
              "# 비공개 판의 것이면 종료 코드 1(문서 속성, 공개_가부.json, 등록 대장의 해시). 끝까지 보지 못한 파일도 1('검사 불가')")
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    try:
        code, lines = public_check(pathlib.Path(argv[0]))
    except Exception as x:  # noqa: BLE001 — traceback 으로 끝내지 않는다. 보지 못한 것은 통과가 아니다
        print(f"[public-check] 검사 불가 — {argv[0]} 을 읽지 못했다({type(x).__name__}: {x})")
        return 1
    for x in lines:
        print(x)
    return code


# ── 이미 만든 비공개 판을 등록 대장에 채우기 ─────────────────────────────────────
def backfill_rows(pptx: pathlib.Path) -> tuple[list[dict], list[str]]:
    """이미 만들어진 덱 하나 → (등록 대장에 적을 줄, 알림). 문서 속성 keywords 에 비공개 판 표시가 없는 덱은 ([], []).
    빌드(build.register_private_outputs)와 같은 것을 적는다: 막는 그림 파일의 해시, 그 판의 pptx 와 같은 이름의 PDF, 막는 그림이 든 쪽의 PNG
    (그 밖의 쪽은 바꾼판의 같은 쪽과 바이트가 같아 적지 않는다). 사양이 없으므로 같은 폴더의 파일에서 읽는다:
      - 막는 그림 번호와 쪽: 공개_가부.json(그 keywords 칸이 이 덱의 것과 같을 때만 이 덱의 것으로 본다). 없으면 keywords 의 ozl:block 과 그림_검수대장_*.json 의 쪽
      - 막는 그림의 해시: 그림_검수대장_*.json(막는 그림 번호가 이 덱의 것과 같은 대장)
    쪽을 알 수 없으면 쪽 PNG 를 전부 적고(덜 막는 쪽보다 더 막는 쪽을 고른다) 알림을 낸다 — 그때는 내용이 같은 쪽을 가진 바꾼판도 막힌다."""
    import json
    pptx = pathlib.Path(pptx)
    d = pptx.parent
    kw = _deck_keywords(pptx)
    private, ids = private_marks(kw)
    if not private:
        return [], []
    notes: list[str] = []

    def load(p: pathlib.Path) -> dict:
        try:
            got = json.loads(p.read_text(encoding="utf-8"))
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            notes.append(f"{p.name} 을 읽지 못했다")
            return {}

    def page_numbers(pages) -> set[int]:
        return {int(str(x).split()[0]) for x in pages or [] if str(x).split() and str(x).split()[0].isdigit()}
    st = load(d / PUBLIC_FILE) if (d / PUBLIC_FILE).is_file() else {}
    if _s(st.get("keywords")) != kw:   # 다른 덱의 것이다(폴더에 덱이 여럿이거나 파일을 옮겼다)
        st = {}
    if st:
        block = [(_s(b.get("id")), b.get("pages")) for b in st.get("blocking") or [] if isinstance(b, dict) and _s(b.get("id"))]
    else:
        block = [(pid, None) for pid in ids]
    want = {pid for pid, _ in block}
    led: dict[str, dict] = {}
    meta = st   # card_id 와 built_at 을 읽을 곳 — 공개_가부.json, 없으면 그림 검수 대장
    for p in sorted(d.glob("그림_검수대장_*.json")):
        x = load(p)
        pub = x.get("public") if isinstance(x.get("public"), dict) else {}
        if isinstance(x.get("pictures"), list) and {_s(b.get("id")) for b in pub.get("blocking") or [] if isinstance(b, dict)} == want:
            led = {_s(r.get("id")): r for r in x["pictures"] if isinstance(r, dict)}
            meta = meta or x
            break
    base = {"card_id": _s(meta.get("card_id")), "built_at": _s(meta.get("built_at")), "dir": d.name}
    rows: list[dict] = []
    media = {sha for _, sha in pptx_media_hashes(pptx)}
    pages: set[int] = set()
    pages_known, no_hash = True, []
    for pid, pgs in block:
        r = led.get(pid) or {}
        if pgs is None and not r:
            pages_known = False
        pages |= page_numbers(pgs if pgs is not None else r.get("pages"))
        sha = _s(r.get("sha256")).lower()
        if not SHA_RE.match(sha):
            no_hash.append(pid)
            continue
        rows.append({"sha256": sha, "what": "막는 그림", "name": pid, **base})
        if sha not in media:
            notes.append(f"막는 그림 {pid} 의 해시가 덱 안 그림에 없다 — keywords 를 지운 사본은 안에 든 그림으로 잡히지 않는다")
    if no_hash:
        notes.append(f"막는 그림 {', '.join(no_hash)} 의 파일 해시를 찾지 못했다(같은 폴더의 그림_검수대장 json 에 없다) — "
                     "keywords 를 지운 사본은 안에 든 그림으로 잡히지 않는다")
    for f, what in ((pptx, "pptx"), (pptx.with_suffix(".pdf"), "pdf")):
        if f.is_file():
            rows.append({"sha256": file_sha256(f), "what": what, "name": f.name, **base})
    pngs = sorted((d / (pptx.stem + "_png")).glob("*.png"))
    numbered = {int(m.group(1)): f for f in pngs if (m := re.search(r"(\d+)$", f.stem))}
    if pages_known and len(numbered) == len(pngs):
        for i in sorted(pages):
            if i in numbered:
                rows.append({"sha256": file_sha256(numbered[i]), "what": "쪽 png", "name": f"{numbered[i].name}({i}쪽)", **base})
    elif pngs:
        notes.append(f"막는 그림이 든 쪽을 알 수 없어 쪽 PNG {len(pngs)}장을 전부 적는다 — 내용이 같은 쪽을 가진 바꾼판도 막힌다")
        rows += [{"sha256": file_sha256(f), "what": "쪽 png", "name": f.name, **base} for f in pngs]
    return rows, notes


def register_main(argv: list[str]) -> int:
    """python -m ozl.render register-private [<폴더 또는 덱 파일>…] [--dry-run]
    이미 만들어진 비공개 판을 비공개 등록 대장(REGISTRY)에 채운다. 인자가 없으면 대장이 있는 폴더(private/decks) 아래를 다 본다.
    덱은 파일 안을 보고 찾고(확장자와 무관), 문서 속성 keywords 에 비공개 판 표시(ozl:private-only · ozl:edition=private)가 있는 것만 적는다.
    적는 것은 backfill_rows 의 줄이다. 대장에 이미 있는 해시는 건너뛴다. 파일을 지우거나 옮기지 않는다. --dry-run 은 적지 않고 세기만 한다.
    종료 코드: 0 = 끝까지 봤다, 1 = 가리지 못했거나 열지 못한 덱이 있다(그 덱은 적지 못했다) 또는 보지 못한 폴더 · 링크가 있다
    (walk_folder — 읽지 못한 하위 폴더, 폴더 링크, 깨진 링크. 그 아래의 판은 등록에서 빠졌다), 2 = 인자가 틀렸다."""
    dry = "--dry-run" in argv
    args = [a for a in argv if a != "--dry-run"]
    if any(a in ("-h", "--help") for a in args):
        print(register_main.__doc__)
        return 0
    if any(a.startswith("--") for a in args):
        print(register_main.__doc__)
        return 2
    roots = [pathlib.Path(a) for a in args]
    for r in roots:
        if not r.exists():
            print(f"[register-private] 없는 경로다: {r}")
            return 2
    if not roots and REGISTRY.parent.is_dir():
        roots = [REGISTRY.parent]
    have, problems = registry_rows([REGISTRY])
    if problems:   # 깨진 대장에 덧붙이지 않는다
        for x in problems:
            print(f"[register-private] {x}")
        return 1
    known = set(have)
    word = "새로 적을" if dry else "새로 적은"
    decks = bad = n_rows = n_new = 0
    for r in roots:
        found, gaps = ([r], []) if r.is_file() else walk_folder(r)
        for q, why in gaps:   # 그 아래의 비공개 판을 적지 못했을 수 있다 — 끝에 종료 코드 1 로 알린다
            bad += 1
            print(f"[register-private] 검사 불가 — {_rel_root(q)}: {why}")
        for f in found:
            try:
                if not is_deck_file(f):
                    continue
                rows, notes = backfill_rows(f)
            except Exception as x:  # noqa: BLE001 — 가리지 못했거나 열지 못한 덱은 적지 못한다. 끝에 종료 코드 1 로 알린다
                bad += 1
                print(f"[register-private] 검사 불가 — {_rel_root(f)}: {type(x).__name__}: {x}")
                continue
            if not rows:
                continue
            decks += 1
            fresh = len({x["sha256"] for x in rows} - known)
            known |= {x["sha256"] for x in rows}
            new = fresh if dry else register_private(rows, REGISTRY)
            n_rows, n_new = n_rows + len(rows), n_new + new
            kinds = " · ".join(f"{k} {sum(1 for x in rows if x['what'] == k)}" for k in dict.fromkeys(x["what"] for x in rows))
            print(f"[register-private] {_rel_root(f)}: {kinds} → {word} 줄 {new}")
            for n in notes:
                print(f"  알림: {n}")
    print(f"[register-private] 비공개 판 {decks}개 · 줄 {n_rows}개 가운데 {word} 줄 {n_new}개 · 대장 {_rel_root(REGISTRY)}"
          + (" · 적지 않았다(--dry-run)" if dry else "") + (f" · 검사 불가 {bad}개" if bad else ""))
    return 1 if bad else 0


def origin_main(argv: list[str]) -> int:
    """python -m ozl.render origin <덱에 넣을 그림> <원 게시처에서 받은 파일> --url <원 게시처 주소>
        origin_check 칸 초안(yaml)을 찍는다 — 지각 해시 거리(phash_distance)와 구역 차이(local_diff).
    python -m ozl.render origin --survey <원본> <사본…> [--json <파일>]
        사본마다 두 값을 잰 표(markdown)를 찍는다. 상한(PHASH_MAX · LOCAL_DIFF_MAX)을 다시 정할 때 쓴다."""
    import yaml
    args, url, survey, json_out = [], "", False, ""
    it = iter(argv)
    for a in it:
        if a == "--url":
            url = next(it, "")
        elif a == "--survey":
            survey = True
        elif a == "--json":
            json_out = next(it, "")
        elif a in ("-h", "--help"):
            print(origin_main.__doc__)
            return 0
        else:
            args.append(a)
    if survey:
        if len(args) < 2:
            print(origin_main.__doc__)
            return 2
        orig, copies = pathlib.Path(args[0]), [pathlib.Path(x) for x in args[1:]]
        for q in [orig] + copies:
            if not q.is_file():
                print(f"[origin] 파일이 없다: {q}")
                return 1
        rows = survey_rows(orig, copies)
        print(survey_md(orig, rows))
        if json_out:
            import json
            pathlib.Path(json_out).write_text(json.dumps({"original": str(orig), "phash_max": PHASH_MAX, "local_diff_max": LOCAL_DIFF_MAX, "rows": rows},
                                                         ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    if len(args) != 2 or not url:
        print(origin_main.__doc__)
        return 2
    mine, orig = pathlib.Path(args[0]), pathlib.Path(args[1])
    for q in (mine, orig):
        if not q.is_file():
            print(f"[origin] 파일이 없다: {q}")
            return 1
    d, ld = phash_distance(mine, orig), local_diff(mine, orig)
    block = {"origin_check": {"url": url, "sha256": file_sha256(orig), "phash_distance": d, "local_diff": ld,
                              "checked_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "original_path": str(orig)}}
    print(yaml.safe_dump(block, allow_unicode=True, sort_keys=False).rstrip())
    print(f"# 거리 {d} / 상한 {PHASH_MAX} · 구역 차이 {ld:g} / 상한 {LOCAL_DIFF_MAX:g} — " + origin_verdict(d, ld) + ("(쓰지 않는다)" if origin_verdict(d, ld) != "받는다" else ""))
    return 0
