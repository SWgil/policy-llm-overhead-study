#!/usr/bin/env python3
"""Summarise one gemini-cli telemetry file into per-role cost and Conseca verdicts.

gemini-cli writes the file when run with
    GEMINI_TELEMETRY_ENABLED=true GEMINI_TELEMETRY_TARGET=local
    GEMINI_TELEMETRY_OUTFILE=<path> GEMINI_TELEMETRY_LOG_PROMPTS=true

The file is a sequence of pretty-printed JSON objects (not JSONL). Each log
record carries an ``attributes`` object whose ``event.name`` identifies it.
The three record kinds this study needs:

- ``gemini_cli.api_response``  one per model call: model, duration_ms, tokens,
  ``role`` (``main`` = agent, ``subagent`` = Conseca) and ``prompt_id``
  (``conseca-policy-generation`` / ``conseca-policy-enforcement`` for the
  policy LLM, a session uuid for the agent).
- ``gemini_cli.api_error``     a failed call (429 retries land here).
- ``gemini_cli.conseca.verdict`` / ``gemini_cli.conseca.policy_generation``
  what Conseca decided, plus an ``error`` field when it fell open.

Usage:
    python parse_telemetry.py telemetry.log            # JSON summary to stdout
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def iter_attribute_objects(text: str):
    """Yield every ``"attributes": {...}`` object in the file, parsed."""
    needle = '"attributes": {'
    pos = 0
    while True:
        i = text.find(needle, pos)
        if i < 0:
            return
        start = i + len(needle) - 1
        depth = 0
        in_str = False
        esc = False
        j = start
        while j < len(text):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        chunk = text[start : j + 1]
        pos = j + 1
        try:
            yield json.loads(chunk)
        except json.JSONDecodeError:
            continue


def summarise(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    calls: list[dict] = []
    errors: list[dict] = []
    verdicts: list[dict] = []
    policy_events: list[dict] = []

    for attrs in iter_attribute_objects(text):
        name = attrs.get("event.name")
        if name == "gemini_cli.api_response":
            pid = attrs.get("prompt_id", "")
            if pid == "conseca-policy-generation":
                stage = "conseca_generate"
            elif pid == "conseca-policy-enforcement":
                stage = "conseca_enforce"
            elif attrs.get("role") == "subagent":
                stage = "other_subagent"
            else:
                stage = "agent"
            calls.append(
                {
                    "stage": stage,
                    "role": attrs.get("role"),
                    "model": attrs.get("model"),
                    "duration_ms": attrs.get("duration_ms", 0),
                    "input_tokens": attrs.get("input_token_count", 0),
                    "output_tokens": attrs.get("output_token_count", 0),
                    "cached_tokens": attrs.get("cached_content_token_count", 0),
                    "thoughts_tokens": attrs.get("thoughts_token_count", 0),
                    "timestamp": attrs.get("event.timestamp"),
                }
            )
        elif name == "gemini_cli.api_error":
            msg = str(attrs.get("error.message", attrs.get("error", "")))
            errors.append(
                {
                    "model": attrs.get("model"),
                    "duration_ms": attrs.get("duration", attrs.get("duration_ms", 0)),
                    "status_code": attrs.get("status_code"),
                    "rate_limited": '"code": 429' in msg or "RESOURCE_EXHAUSTED" in msg,
                    "message": msg[:300],
                }
            )
        elif name == "gemini_cli.conseca.verdict":
            tool_call = attrs.get("tool_call")
            try:
                tool_call = json.loads(tool_call) if isinstance(tool_call, str) else tool_call
            except json.JSONDecodeError:
                pass
            verdicts.append(
                {
                    "verdict": attrs.get("verdict"),
                    "tool": (tool_call or {}).get("name") if isinstance(tool_call, dict) else None,
                    "tool_call": tool_call,
                    "rationale": attrs.get("verdict_rationale"),
                    "error": attrs.get("error"),
                    "timestamp": attrs.get("event.timestamp"),
                }
            )
        elif name == "gemini_cli.conseca.policy_generation":
            policy = attrs.get("policy")
            try:
                policy = json.loads(policy) if isinstance(policy, str) else policy
            except json.JSONDecodeError:
                pass
            policy_events.append(
                {
                    "policy": policy,
                    "error": attrs.get("error"),
                    "timestamp": attrs.get("event.timestamp"),
                }
            )

    by_stage: dict[str, dict] = {}
    for c in calls:
        s = by_stage.setdefault(
            c["stage"],
            {"requests": 0, "duration_ms": 0, "input_tokens": 0, "output_tokens": 0},
        )
        s["requests"] += 1
        s["duration_ms"] += c["duration_ms"] or 0
        s["input_tokens"] += c["input_tokens"] or 0
        s["output_tokens"] += c["output_tokens"] or 0

    agent_ms = by_stage.get("agent", {}).get("duration_ms", 0)
    conseca_ms = sum(
        v["duration_ms"] for k, v in by_stage.items() if k.startswith("conseca_")
    )
    verdict_counts: dict[str, int] = {}
    for v in verdicts:
        verdict_counts[v["verdict"] or "?"] = verdict_counts.get(v["verdict"] or "?", 0) + 1

    return {
        "by_stage": by_stage,
        "agent_ms": agent_ms,
        "conseca_ms": conseca_ms,
        "conseca_over_agent": (conseca_ms / agent_ms) if agent_ms else None,
        "api_errors": len(errors),
        "rate_limited_retries": sum(1 for e in errors if e["rate_limited"]),
        "verdict_counts": verdict_counts,
        # A Conseca event with an error is a fail-open: the checker allowed
        # because it could not decide, not because the policy allowed.
        "conseca_fail_open": sum(1 for v in verdicts if v["error"])
        + sum(1 for p in policy_events if p["error"]),
        "verdicts": verdicts,
        "policies": policy_events,
        "calls": calls,
        "errors": errors,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    print(json.dumps(summarise(Path(argv[1])), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
