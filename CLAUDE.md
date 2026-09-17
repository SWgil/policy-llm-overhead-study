# Repository memory for Claude

## External qwen (Ollama) connection — remembered fact

- The AgentRedBench-style attack harness in this repo (directory `agentredbench/`,
  on branch `claude/gemini-flash-attack-testing-50d2y1`) uses **`qwen3.8:27b`**
  served by **Ollama at `http://10.251.36.222:11434`** (OpenAI-compatible base
  `http://10.251.36.222:11434/v1`). No API key is needed.
- **Confirmed reachable and working** from an environment where this repo was
  cloned and run (user verified). It is **NOT reachable from the Claude Code
  cloud / web dev container** — that host has no route to this private IP, so a
  live `curl` / connection attempt from there times out. That is expected, not a
  misconfiguration.

## When asked to "set up the connection to external qwen"

Do **not** try to open a live connection from a container that cannot reach the
private IP — it will just time out. Instead, make sure the repo is set up so a
plain `git clone` + run works wherever the server *is* reachable:

1. Keep the baked defaults in `agentredbench/run_scenario.py`:
   `DEFAULT_OLLAMA_URL = http://10.251.36.222:11434/v1`, `DEFAULT_MODEL = qwen3.8:27b`
   (overridable via `--ollama-base-url` / `--target` / `--attacker` or the env
   vars `OLLAMA_BASE_URL` / `OLLAMA_MODEL`).
2. `normalize_ollama_url()` accepts a scheme-less host and an optional `/v1`
   suffix, so `10.251.36.222:11434` also works.
3. Verify from the *target* environment (not the cloud container) with
   `curl http://10.251.36.222:11434/api/tags` and confirm `qwen3.8:27b` is listed.
4. Then `python agentredbench/run_suite.py --baseline` runs with no extra flags.

The connection cannot be made live from the cloud container; the deliverable is a
repo that connects correctly once cloned into a networked-in environment.

## AgentDyn branch — remembered fact

- Branch `claude/conseca-agentdyn-benchmark-rt27v8` is the **AgentDyn** variant of the
  Conseca harness. `conseca/agentdojo-mcp/src/agentdojo` there is the AgentDyn fork
  (AgentDojo 0.1.35 + shopping/github/dailylife suites, `defenses/` dropped), not
  upstream 0.1.29 as on `main`. See `conseca/README.md` §8 for every difference.
- AgentDyn and upstream AgentDojo share the package name `agentdojo`, so the two
  cores cannot be installed in one venv; keep AgentDojo-only work on `main`.
- `benchmark_version` v1.2.2 is an upstream AgentDojo version (0.1.35), not an
  AgentDyn invention. AgentDyn suites are identical under every version key; the
  four AgentDojo suites are not (workspace v1.1.2 has 6 injection tasks, v1.2.2 has 14).
