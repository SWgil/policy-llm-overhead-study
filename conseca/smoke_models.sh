#!/usr/bin/env bash
# Smoke-test several agent models: one task x both arms per model, then one table.
#
#   ./smoke_models.sh gemini-3.1-flash-lite gemini-2.5-flash gemini-3.5-flash
#   MODELS="gemini-3.1-flash-lite gemini-2.5-flash" ./smoke_models.sh
#   SUITE=github ./smoke_models.sh gemini-3.1-flash-lite     # another suite
#   ./smoke_models.sh gemini-3.1-flash-lite --dry-run          # commands only
#
# Each model runs `run_pilot.sh --smoke` (user_task_0 x the suite's first
# injection task, arms off and on), so every model lands in its own
# runs/<model>/<arm>/ and nothing is overwritten. A model that fails (404,
# quota, ...) is reported at the end and does not stop the others.
#
# Env: SUITE (shopping; AgentDyn: shopping/github/dailylife, AgentDojo: banking/
#      slack/travel/workspace) ARMS ("off on") PAUSE (0; 60 on a free-tier key).
# Args: model names first; from the first --option on, everything is passed to
#      run_task.py (e.g. --force, --dry-run, --out DIR, --timeout 900).
set -uo pipefail
cd "$(dirname "$0")"

SUITE="${SUITE:-shopping}"
export SUITE ARMS="${ARMS:-off on}" PAUSE="${PAUSE:-0}"

models=(); extra=()
while [ $# -gt 0 ] && [[ "$1" != --* ]]; do models+=("$1"); shift; done
extra=("$@")
if [ ${#models[@]} -eq 0 ] && [ -n "${MODELS:-}" ]; then
  read -r -a models <<<"$MODELS"
fi
[ ${#models[@]} -gt 0 ] || { sed -n '2,16p' "$0"; exit 2; }
[ -x .venv/bin/python ] || { echo "no .venv; run ./setup.sh first" >&2; exit 1; }

dry=0
printf '%s\n' "${extra[@]:-}" | grep -q -- '--dry-run' && dry=1

# One bridge for the whole sweep; run_pilot.sh leaves a running bridge alone.
started=0
if ! ./bridge.sh status >/dev/null 2>&1; then ./bridge.sh start || exit 1; started=1; fi
trap '[ "$started" = 1 ] && ./bridge.sh stop' EXIT

failed=()
for m in "${models[@]}"; do
  echo; echo "##### model=$m suite=$SUITE (smoke: 1 task x $ARMS) #####"
  if ! MODEL="$m" ./run_pilot.sh --smoke "${extra[@]}"; then
    failed+=("$m")
    echo "##### model=$m: some run failed; see runs/$m/<arm>/*/stderr.txt #####" >&2
  fi
done

if [ "$dry" = 0 ]; then
  echo; echo "##### all models, suite=$SUITE #####"; echo
  .venv/bin/python results_table.py --suite "$SUITE" --by model,arm
  echo; .venv/bin/python results_table.py --suite "$SUITE" --tasks | sed -n '/^## runs/,$p'
fi

if [ ${#failed[@]} -gt 0 ]; then
  echo; echo "models with a failed run: ${failed[*]}" >&2
  exit 1
fi
