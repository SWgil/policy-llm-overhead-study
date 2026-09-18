# Repository memory for Claude

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
