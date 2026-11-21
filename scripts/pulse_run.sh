#!/bin/zsh
# OZL Pulse 매시 실행 — launchd(com.hyunbin.ozl-pulse)가 매시 5분에 부른다. 모델 호출 없음(결정적 코드만).
# 로그: <pulse>/logs/run_YYYYMM.log(지금 private/pulse/logs) · 새벽 4시대 실행에서 90일 지난 기록을 정리한다.
set -u
cd "${0:A:h}/.." || exit 1
# 로그 폴더는 src/ozl/paths.py 가 정한다(폴더를 옮겨도 이 파일은 그대로다). 위치를 못 받으면 수집을 하지 않는다.
LOGDIR="$(.venv/bin/python -c 'from ozl import paths; print(paths.at("pulse", "logs"))')"
# 실패하면 launchd 의 표준 오류(plist 의 StandardErrorPath)에 남기고 멈춘다 — 감시(ops-watchdog)가 회차 기록이 없는 것을 잡는다
[[ -n "$LOGDIR" ]] || { echo "$(date '+%Y-%m-%d %H:%M:%S') pulse_run: 로그 위치를 받지 못해 수집하지 않았다(.venv 또는 src/ozl/paths.py 확인)" >&2; exit 1; }
mkdir -p "$LOGDIR"
LOG="$LOGDIR/run_$(date +%Y%m).log"
{
  echo "== $(date '+%Y-%m-%d %H:%M:%S %Z')"
  nice -n 10 .venv/bin/python -m ozl.pulse run
  echo "exit=$?"
  # 화제 엔진: 수집 뒤에 한 번. 실패해도 수집의 종료 코드와 로그는 그대로다. 300초를 넘기면 끊는다(엔진이 멈춰 수집 실행 전체를 붙잡지 않게).
  { echo "== $(date '+%Y-%m-%d %H:%M:%S %Z')"; nice -n 10 perl -e 'alarm 300; exec @ARGV' .venv/bin/python -m ozl.signals run; echo "exit=$?"; } >>"$LOGDIR/engine_$(date +%Y%m).log" 2>&1
  if [[ "$(date +%H)" == "04" ]]; then .venv/bin/python -m ozl.pulse prune; fi
} >>"$LOG" 2>&1
