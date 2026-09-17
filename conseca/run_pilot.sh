#!/usr/bin/env bash
# Run both arms on a task set, then print the on-vs-off comparison.
#
#   ./run_pilot.sh --smoke            # 1 task  x 2 arms  (~30 requests)  pipeline check
#   ./run_pilot.sh --pilot            # 4x4 tasks x 2 arms (~500 requests) the README pilot
#   VARIANT=1 ./run_pilot.sh --pilot  # same pairs with the cache's 2nd-ranked injection
#   ATTACK=important_instructions ./run_pilot.sh --pilot   # static baseline
#   ./run_pilot.sh --full             # whole suite x 2 arms
#   ./run_pilot.sh --smoke --dry-run  # print the gemini commands only
#
# Env: SUITE (banking|slack|travel) ARMS ("off on") PAUSE (0; use 60 on a free-tier key)
#      MODEL (gemini-3.1-flash-lite) ATTACK (autodojo|important_instructions) VARIANT (0).
#      Extra args go to run_task.py (e.g. --force, --include-unoptimized).
# Results: runs/autodojo-v$VARIANT/ (or runs/important_instructions/); the
# comparison and extraction at the end read the same directory.
# Starts the bridge if it is not running and stops it again at the end.
# Finished tasks are cached in runs/; re-running resumes where it stopped.
set -euo pipefail
cd "$(dirname "$0")"

SUITE="${SUITE:-banking}"
ARMS="${ARMS:-off on}"
PAUSE="${PAUSE:-0}"
MODEL="${MODEL:-gemini-3.1-flash-lite}"
ATTACK="${ATTACK:-autodojo}"
VARIANT="${VARIANT:-0}"
if [ "$ATTACK" = autodojo ]; then RUNS="runs/autodojo-v$VARIANT"; else RUNS="runs/$ATTACK"; fi

scope=""; extra=()
for a in "$@"; do
  case "$a" in
    --smoke|--pilot|--full) scope="$a" ;;
    *) extra+=("$a") ;;
  esac
done
[ -n "$scope" ] || { sed -n '2,12p' "$0"; exit 2; }
[ -x .venv/bin/python ] || { echo "no .venv; run ./setup.sh first" >&2; exit 1; }

# slack's injection tasks start at 1. The banking user tasks below are ones
# whose AutoDojo variant 0 is optimised for every injection task (user_task_0
# and _2 are not: their injection_task_0 would be skipped as unoptimised).
case "$SUITE" in
  slack) inj=(injection_task_1 injection_task_2 injection_task_3) ;;
  *)     inj=(injection_task_0 injection_task_1 injection_task_2) ;;
esac
case "$scope" in
  --smoke) sel=(--user-tasks user_task_1 --injection-tasks "${inj[0]}") ;;
  --pilot) sel=(--user-tasks user_task_1 user_task_3 user_task_4 user_task_5
                --injection-tasks none "${inj[@]}") ;;
  --full)  sel=() ;;
esac

started=0
if ! ./bridge.sh status >/dev/null 2>&1; then ./bridge.sh start; started=1; fi
trap '[ "$started" = 1 ] && ./bridge.sh stop' EXIT

rc=0
for arm in $ARMS; do
  echo; echo "=== arm=$arm suite=$SUITE scope=$scope ==="
  .venv/bin/python run_task.py --arm "$arm" --suite "$SUITE" --model "$MODEL" --pause "$PAUSE" \
    --attack "$ATTACK" --attack-variant "$VARIANT" --out "$RUNS" \
    "${sel[@]}" "${extra[@]}" || rc=$?
done

if ! printf '%s\n' "${extra[@]}" | grep -q -- '--dry-run'; then
  echo; .venv/bin/python compare_arms.py --suite "$SUITE" --runs "$RUNS"
  echo; echo "per-run detail: .venv/bin/python extract_runs.py --suite $SUITE --runs $RUNS   -> extracted/"
fi
exit $rc
