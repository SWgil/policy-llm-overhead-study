#!/usr/bin/env bash
# Run both arms on a task set, then print the on-vs-off comparison.
#
#   ./run_pilot.sh --smoke            # 1 task  x 2 arms  (~30 requests)  pipeline check
#   ./run_pilot.sh --pilot            # 4x4 tasks x 2 arms (~500 requests) the README pilot
#   ./run_pilot.sh --full             # whole suite x 2 arms
#   ./run_pilot.sh --smoke --dry-run  # print the gemini commands only
#
# Env: SUITE (banking) ARMS ("off on") PAUSE (0; use 60 on a free-tier key)
#      MODEL (gemini-2.5-flash). Extra args go to run_task.py (e.g. --force).
# Starts the bridge if it is not running and stops it again at the end.
# Finished tasks are cached in runs/; re-running resumes where it stopped.
set -euo pipefail
cd "$(dirname "$0")"

SUITE="${SUITE:-banking}"
ARMS="${ARMS:-off on}"
PAUSE="${PAUSE:-0}"
MODEL="${MODEL:-gemini-2.5-flash}"

scope=""; extra=()
for a in "$@"; do
  case "$a" in
    --smoke|--pilot|--full) scope="$a" ;;
    *) extra+=("$a") ;;
  esac
done
[ -n "$scope" ] || { sed -n '2,12p' "$0"; exit 2; }
[ -x .venv/bin/python ] || { echo "no .venv; run ./setup.sh first" >&2; exit 1; }

case "$scope" in
  --smoke) sel=(--user-tasks user_task_0 --injection-tasks injection_task_0) ;;
  --pilot) sel=(--user-tasks user_task_0 user_task_1 user_task_2 user_task_3
                --injection-tasks none injection_task_0 injection_task_1 injection_task_2) ;;
  --full)  sel=() ;;
esac

started=0
if ! ./bridge.sh status >/dev/null 2>&1; then ./bridge.sh start; started=1; fi
trap '[ "$started" = 1 ] && ./bridge.sh stop' EXIT

rc=0
for arm in $ARMS; do
  echo; echo "=== arm=$arm suite=$SUITE scope=$scope ==="
  .venv/bin/python run_task.py --arm "$arm" --suite "$SUITE" --model "$MODEL" --pause "$PAUSE" \
    "${sel[@]}" "${extra[@]}" || rc=$?
done

if ! printf '%s\n' "${extra[@]}" | grep -q -- '--dry-run'; then
  echo; .venv/bin/python compare_arms.py --suite "$SUITE"
  echo; echo "per-run detail: .venv/bin/python extract_runs.py --suite $SUITE   -> extracted/"
fi
exit $rc
