#!/usr/bin/env python3
"""Verify from a run's telemetry what the model actually received.

Checks, per run directory (runs/<arm>/<task_id>/):

  system prompt      every gen_ai.system_instructions equals the benchmark's
                     message: agentdyn_system.md for shopping/github/dailylife
                     runs, agentdojo_system.md for banking/slack/travel/workspace
  untrusted_context  how many times the tag appears in the log (2 per tool
                     call on the stock CLI)
  tool outputs       the functionResponse texts as sent to the model, so the
                     wrapping (or its absence) is visible directly
  session_context    whether the CLI prepended its <session_context> block
                     (always true on the stock CLI; cannot be turned off)
  tools              the function declarations the agent received: how many,
                     and whether every one is an mcp_agentdojo_* tool (a
                     built-in gemini-cli tool here means tools.exclude in
                     settings.template.json is incomplete). Conseca's own
                     calls carry no tools and are ignored.

Standard library only. Usage:
    python check_run.py runs/off/geminioff_banking_user_task_0_injection_task_0
    python check_run.py runs/*/*            # every run
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTDYN_SUITES = ("shopping", "github", "dailylife")
SUITE_RE = re.compile(r"_(banking|slack|travel|workspace|shopping|github|dailylife)_user_task_")


def expected_prompt(run_dir: Path) -> tuple[str, str]:
    """(file name, expected system prompt) for this run, picked from the suite in the task id."""
    m = SUITE_RE.search(run_dir.name)
    name = "agentdyn_system.md" if m and m.group(1) in AGENTDYN_SUITES else "agentdojo_system.md"
    return name, (HERE / name).read_text(encoding="utf-8").strip()


def check(run_dir: Path) -> bool:
    log = run_dir / "telemetry.log"
    if not log.exists():
        print(f"{run_dir}: no telemetry.log")
        return False
    raw = log.read_text(encoding="utf-8")

    prompts = set()
    for m in re.finditer(r'"gen_ai\.system_instructions": (".*?")(?=,\n|\n)', raw):
        v = json.loads(m.group(1))
        try:
            parsed = json.loads(v)
            texts = [p["content"] for p in parsed] if isinstance(parsed, list) else [parsed]
        except Exception:
            texts = [v]
        prompts.update(t.strip() for t in texts)

    outputs = []
    for m in re.finditer(r'"request_text": (".*?")(?=,\n|\n)', raw):
        for msg in json.loads(json.loads(m.group(1))):
            for part in msg.get("parts", []):
                fr = part.get("functionResponse")
                if fr:
                    outputs.append(str(fr["response"].get("output", fr["response"])))

    tool_sets = set()
    for m in re.finditer(r'"gen_ai\.tool\.definitions": (".*?")(?=,\n|\n)', raw):
        defs = json.loads(json.loads(m.group(1)))
        names = tuple(sorted(fd["name"] for d in defs for fd in d.get("functionDeclarations", [])))
        if names:  # Conseca's policy/verdict calls send no tools
            tool_sets.add(names)
    tools = sorted(set().union(*tool_sets)) if tool_sets else []
    foreign = [n for n in tools if not n.startswith("mcp_agentdojo_")]
    tools_ok = bool(tools) and not foreign and len(tool_sets) == 1

    expected_name, expected = expected_prompt(run_dir)
    prompt_ok = bool(prompts) and all(p == expected for p in prompts)
    n_tag = raw.count("untrusted_context")
    print(f"{run_dir.name}")
    print(f"  system prompt == {expected_name:<19}: {prompt_ok} ({len(prompts)} distinct)")
    print(f"  untrusted_context occurrences        : {n_tag}")
    print(f"  tool outputs seen by the model       : {len(outputs)}")
    if outputs:
        print(f"    first output starts: {outputs[0][:60]!r}")
    print(f"  <session_context> prepended          : {'<session_context>' in raw}")
    print(f"  tools sent to the agent              : {len(tools)} "
          f"({'all mcp_agentdojo_*' if not foreign else 'NON-AGENTDOJO: ' + ', '.join(foreign)}"
          f"{'' if len(tool_sets) <= 1 else '; list changes between requests'})")
    return prompt_ok and tools_ok


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    ok = True
    for a in argv[1:]:
        ok &= check(Path(a))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
