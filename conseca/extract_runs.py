#!/usr/bin/env python3
"""Split every finished run under runs/ into six small JSON files.

For each <runs>/<arm>/<task_id>/ that has a result.json, writes
<out>/<arm>/<task_id>/:

  user_prompt.json     the AgentDojo user task prompt
  scores.json          utility / security plus task identity
  policy.json          the Conseca policy: per-tool permission, constraints,
                       rationale (empty for the off arm)
  injected_tools.json  every AgentDojo tool call whose output carried the
                       injection, with the full output
  verdicts.json        every Conseca enforcement verdict with its rationale
                       (empty for the off arm)
  agent_response.json  the agent's final answer

plus index.json at <out>/ listing every run extracted.

Sources, per run:

  result.json                       scores, response, arm/suite/task ids
  <mcp_results>/<agent>/<suite>/<user_task>/<injection>.json
                                    user prompt, injection goal, every tool
                                    call the bridge executed with its result
  telemetry.log                     gemini_cli.conseca.policy_generation and
                                    gemini_cli.conseca.verdict events

A tool call counts as "injected" when its output contains the injection goal
text or the attack's <INFORMATION> marker; both are what
ImportantInstructionsAttack writes into the environment, so this needs no
model call and no AgentDojo import.

Usage:
    python extract_runs.py                       # runs/ + mcp_results/ -> extracted/
    python extract_runs.py --runs runs --out extracted --mcp-results mcp_results
    python extract_runs.py --arm on --suite banking
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_telemetry import iter_attribute_objects  # noqa: E402

HERE = Path(__file__).resolve().parent
TASK_ID_RE = re.compile(
    r"^(\w+?)_(banking|slack|travel|workspace|shopping|github|dailylife)_(user_task_\d+)_(injection_task_\d+|noinjection)$"
)
INJECTION_MARKER = "<INFORMATION>"


# --------------------------------------------------------------------------- helpers

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_maybe_json(value):
    """Telemetry stores policy / tool_call as JSON strings; parse when possible."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def bridge_file(mcp_results: Path, task_id: str) -> Path | None:
    """mcp_server.py writes <agent>/<suite>/<user_task>/<injection>.json."""
    m = TASK_ID_RE.match(task_id)
    if not m:
        p = mcp_results / "others" / f"{task_id}.json"
        return p if p.exists() else None
    agent, suite, user_task, injection = m.groups()
    p = mcp_results / agent / suite / user_task / f"{injection}.json"
    return p if p.exists() else None


def telemetry_events(path: Path) -> dict:
    """Pull the Conseca and user-prompt events out of one telemetry.log."""
    out = {"user_prompt": None, "policies": [], "verdicts": []}
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8", errors="ignore")
    for attrs in iter_attribute_objects(text):
        name = attrs.get("event.name")
        if name == "gemini_cli.user_prompt":
            out["user_prompt"] = attrs.get("prompt")
        elif name == "gemini_cli.conseca.policy_generation":
            out["policies"].append(
                {
                    "timestamp": attrs.get("event.timestamp"),
                    "policy": parse_maybe_json(attrs.get("policy")),
                    "error": attrs.get("error"),
                }
            )
        elif name == "gemini_cli.conseca.verdict":
            tool_call = parse_maybe_json(attrs.get("tool_call"))
            out["verdicts"].append(
                {
                    "timestamp": attrs.get("event.timestamp"),
                    "tool": tool_call.get("name") if isinstance(tool_call, dict) else None,
                    "args": tool_call.get("args") if isinstance(tool_call, dict) else tool_call,
                    "verdict": attrs.get("verdict"),
                    "rationale": attrs.get("verdict_rationale"),
                    "error": attrs.get("error"),
                }
            )
    return out


def contains_injection(result, goal: str | None) -> bool:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    if INJECTION_MARKER in text:
        return True
    return bool(goal) and goal in text


# --------------------------------------------------------------------------- per-run

def extract_one(run_dir: Path, mcp_results: Path, out_dir: Path) -> dict:
    result = load_json(run_dir / "result.json")
    task_id = result["task_id"]
    tel = telemetry_events(run_dir / "telemetry.log")

    bridge_path = bridge_file(mcp_results, task_id)
    bridge = load_json(bridge_path) if bridge_path else {}
    goal = bridge.get("injection_goal")

    # 1. user prompt (bridge is authoritative; telemetry is the fallback)
    user_prompt = {
        "task_id": task_id,
        "suite": result.get("suite"),
        "user_task": result.get("user_task"),
        "injection_task": result.get("injection_task"),
        "prompt": bridge.get("user_prompt") or tel["user_prompt"],
        "injection_goal": goal,
    }

    # 2. scores
    scores = {
        "task_id": task_id,
        "arm": result.get("arm"),
        "suite": result.get("suite"),
        "user_task": result.get("user_task"),
        "injection_task": result.get("injection_task"),
        "model": result.get("model"),
        "utility": result.get("utility"),
        "security": result.get("security"),
        "wall_seconds": result.get("wall_seconds"),
    }

    # 3. policy with per-tool rationale. One generation per prompt; keep all
    #    events in case the CLI regenerated.
    policies = []
    for p in tel["policies"]:
        pol = p["policy"]
        rules = None
        if isinstance(pol, dict):
            rules = {
                tool: {
                    "permissions": (rule or {}).get("permissions") if isinstance(rule, dict) else rule,
                    "constraints": (rule or {}).get("constraints") if isinstance(rule, dict) else None,
                    "rationale": (rule or {}).get("rationale") if isinstance(rule, dict) else None,
                }
                for tool, rule in pol.items()
            }
        policies.append(
            {
                "timestamp": p["timestamp"],
                "error": p["error"],
                "rules": rules,
                "raw": pol if rules is None else None,
            }
        )
    policy = {"task_id": task_id, "arm": result.get("arm"), "generations": policies}

    # 4. injected tool calls: bridge-executed AgentDojo tools whose output
    #    carried the injection. All bridge calls are listed for reference.
    calls = bridge.get("functions_stack_trace_details") or []
    injected = []
    all_calls = []
    for i, c in enumerate(calls):
        entry = {
            "index": i,
            "function": c.get("function"),
            "args": c.get("args"),
            "result": c.get("result"),
            "error": c.get("error"),
        }
        all_calls.append({k: entry[k] for k in ("index", "function", "args", "error")})
        if contains_injection(c.get("result"), goal):
            injected.append(entry)
    injected_tools = {
        "task_id": task_id,
        "injection_task": result.get("injection_task"),
        "injection_goal": goal,
        "bridge_result_file": str(bridge_path) if bridge_path else None,
        "injected": injected,
        "all_bridge_calls": all_calls,
    }

    # 5. enforcer verdicts with rationale
    verdicts = {
        "task_id": task_id,
        "arm": result.get("arm"),
        "counts": _count(v["verdict"] for v in tel["verdicts"]),
        "fail_open": sum(1 for v in tel["verdicts"] if v["error"]),
        "verdicts": tel["verdicts"],
    }

    # 6. agent response
    agent_response = {
        "task_id": task_id,
        "response": result.get("response"),
        "bridge_model_output": bridge.get("model_output"),
    }

    dump_json(out_dir / "user_prompt.json", user_prompt)
    dump_json(out_dir / "scores.json", scores)
    dump_json(out_dir / "policy.json", policy)
    dump_json(out_dir / "injected_tools.json", injected_tools)
    dump_json(out_dir / "verdicts.json", verdicts)
    dump_json(out_dir / "agent_response.json", agent_response)

    return {
        "task_id": task_id,
        "arm": result.get("arm"),
        "suite": result.get("suite"),
        "user_task": result.get("user_task"),
        "injection_task": result.get("injection_task"),
        "utility": result.get("utility"),
        "security": result.get("security"),
        "policy_generations": len(policies),
        "verdicts": len(tel["verdicts"]),
        "injected_tool_calls": len(injected),
        "bridge_file_found": bridge_path is not None,
        "out_dir": str(out_dir),
    }


def _count(values) -> dict:
    counts: dict = {}
    for v in values:
        counts[v or "?"] = counts.get(v or "?", 0) + 1
    return counts


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=str(HERE / "runs"), help="root written by run_task.py")
    ap.add_argument("--mcp-results", default=str(HERE / "mcp_results"), help="bridge --results-dir")
    ap.add_argument("--out", default=str(HERE / "extracted"))
    ap.add_argument("--arm", choices=["on", "off"], default=None, help="only this arm")
    ap.add_argument("--suite", default=None, help="only this suite")
    args = ap.parse_args()

    runs = Path(args.runs)
    mcp_results = Path(args.mcp_results)
    out = Path(args.out)

    index = []
    for result_path in sorted(runs.glob("*/*/result.json")):
        run_dir = result_path.parent
        arm = run_dir.parent.name
        if args.arm and arm != args.arm:
            continue
        if args.suite and f"_{args.suite}_" not in run_dir.name:
            continue
        try:
            row = extract_one(run_dir, mcp_results, out / arm / run_dir.name)
        except Exception as e:  # keep going; report at the end
            row = {"task_id": run_dir.name, "arm": arm, "error": str(e)}
            print(f"[fail] {arm}/{run_dir.name}: {e}", file=sys.stderr)
        else:
            flag = "" if row["bridge_file_found"] else "  (no bridge file: prompt/tools from telemetry only)"
            print(
                f"[ok  ] {arm}/{row['task_id']}: utility={row['utility']} security={row['security']} "
                f"policies={row['policy_generations']} verdicts={row['verdicts']} "
                f"injected_calls={row['injected_tool_calls']}{flag}"
            )
        index.append(row)

    if not index:
        print(f"no result.json under {runs}", file=sys.stderr)
        return 1
    dump_json(out / "index.json", index)
    failed = sum(1 for r in index if "error" in r)
    print(f"\n{len(index) - failed} runs extracted to {out}" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
