#!/usr/bin/env bash
# One-shot environment setup for the Conseca on/off harness. Safe to re-run.
#
#   ./setup.sh
#
# Installs the pinned gemini-cli, creates .venv with the AgentDojo MCP bridge,
# and checks the two things that make runs fail silently (auth, global memory).
# Override the pins with GEMINI_CLI_VERSION / PYTHON_VERSION.
#
# Needs: node >= 20 with npm on PATH. uv is installed if missing.
set -euo pipefail
cd "$(dirname "$0")"

GEMINI_CLI_VERSION="${GEMINI_CLI_VERSION:-0.59.0}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)" >&2; exit 1; }; }
need node "install Node.js >= 20 from https://nodejs.org"
need npm "ships with Node.js"
if ! command -v uv >/dev/null 2>&1; then
  echo "==> uv not found, installing to ~/.local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> gemini-cli $GEMINI_CLI_VERSION"
if [ "$(gemini --version 2>/dev/null | tail -1 || true)" != "$GEMINI_CLI_VERSION" ]; then
  npm i -g "@google/gemini-cli@$GEMINI_CLI_VERSION"
fi
echo "    $(command -v gemini) -> $(gemini --version | tail -1)"

echo "==> python venv (.venv, python $PYTHON_VERSION) + AgentDojo MCP bridge"
[ -d .venv ] || uv venv --python "$PYTHON_VERSION" .venv
uv pip install --python .venv/bin/python --quiet ./agentdojo-mcp requests
.venv/bin/python -c "import agentdojo, fastmcp, requests; print('    agentdojo bridge importable')"

echo "==> checks"
ok=1
if [ -n "${GEMINI_API_KEY:-}" ]; then
  echo "    auth: GEMINI_API_KEY is set (free-tier keys: ~20 req/min, use PAUSE=60)"
elif [ -f "$HOME/.gemini/oauth_creds.json" ]; then
  echo "    auth: OAuth credentials found in ~/.gemini"
else
  echo "    auth: NONE. export GEMINI_API_KEY=... or run \`gemini\` once interactively to log in" >&2
  ok=0
fi
if [ -s "$HOME/.gemini/GEMINI.md" ]; then
  echo "    WARNING: ~/.gemini/GEMINI.md is not empty; it is appended to every system prompt. Empty it for experiments." >&2
  ok=0
fi
[ "$ok" = 1 ] && echo "==> ready. next: ./run_pilot.sh --smoke" || { echo "==> fix the items above, then: ./run_pilot.sh --smoke" >&2; exit 1; }
