# agentredbench — notes for Claude

## External qwen (Ollama) connection — remembered fact

- The target/attacker/judge model for this harness is **`qwen3.8:27b`** served by
  **Ollama at `http://10.251.36.222:11434`** (OpenAI-compatible base
  `http://10.251.36.222:11434/v1`). No API key is needed.
- **Confirmed reachable and working** from an environment where this repo was
  cloned and run (user verified). It is **NOT reachable from the Claude Code
  cloud/web dev container** — that host has no route to this private IP, so a
  live `curl`/connection attempt from here will time out. That is expected, not
  a misconfiguration.

## What to do when asked in another session to "set up the connection to external qwen"

Do **not** try to open a live connection from a container that cannot reach the
private IP — it will just time out. Instead, set the repo up so that a plain
`git clone` + run works wherever the server *is* reachable (this is the state
the repo is already in):

1. Keep the defaults baked in `run_scenario.py`:
   `DEFAULT_OLLAMA_URL = http://10.251.36.222:11434/v1`, `DEFAULT_MODEL = qwen3.8:27b`
   (both overridable via `--ollama-base-url` / `--target` / `--attacker` or the
   env vars `OLLAMA_BASE_URL` / `OLLAMA_MODEL`).
2. `normalize_ollama_url()` already accepts a scheme-less host and an optional
   `/v1` suffix, so `10.251.36.222:11434` works too.
3. Verify from the *target* environment (not this one) with
   `curl http://10.251.36.222:11434/api/tags` and confirm `qwen3.8:27b` is listed.
4. Then `python run_suite.py --baseline` runs with no extra flags.

In short: the connection can't be made live from here; the deliverable is a repo
that connects correctly once cloned into a networked-in environment.
