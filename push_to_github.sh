#!/bin/bash
# Upload this study to GitHub as three private repositories.
#
# Run `gh auth login` first - that step needs a browser and cannot be
# scripted. Everything else is already committed; this only creates the
# remotes and pushes.
#
#   ./push_to_github.sh [owner]
#
# Note on forks: GitHub forks of a public repository are always public, so
# the two upstream checkouts go up as private mirrors rather than forks. They
# carry full upstream history, so a later `git remote add upstream ...` and
# rebase onto a newer release works as usual.

set -euo pipefail

command -v gh >/dev/null || { echo "gh not on PATH (try '/c/Program Files/GitHub CLI')" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "not logged in - run: gh auth login" >&2; exit 1; }

OWNER="${1:-$(gh api user --jq .login)}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

push() {
  local dir="$1" name="$2" desc="$3"
  local branch
  branch="$(git -C "$dir" branch --show-current)"
  echo
  echo "==> $OWNER/$name  (branch $branch)"
  if gh repo view "$OWNER/$name" >/dev/null 2>&1; then
    echo "    repository exists, pushing"
  else
    gh repo create "$OWNER/$name" --private --description "$desc"
  fi
  git -C "$dir" remote remove study 2>/dev/null || true
  git -C "$dir" remote add study "https://github.com/$OWNER/$name.git"
  # Upstream's own history first where it exists, so the study branch reads
  # as a diff against the release it was written on.
  if git -C "$dir" show-ref --verify --quiet refs/heads/main; then
    git -C "$dir" push -u study main
  fi
  git -C "$dir" push -u study "$branch"
}

push "$ROOT" \
  "policy-llm-overhead-study" \
  "Policy-generator LLM overhead in Progent and Conseca, and whether a small model can replace it"

push "$ROOT/progent" \
  "progent-policy-overhead" \
  "Progent with stage-level policy LLM instrumentation, per-stage model routing and a local-model backend"

push "$ROOT/gemini-cli" \
  "gemini-cli-conseca-overhead" \
  "gemini-cli with Conseca cost instrumentation and the paper's deterministic enforcer restored"

echo
echo "done:"
echo "  https://github.com/$OWNER/policy-llm-overhead-study"
echo "  https://github.com/$OWNER/progent-policy-overhead"
echo "  https://github.com/$OWNER/gemini-cli-conseca-overhead"
