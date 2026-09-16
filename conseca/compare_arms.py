#!/usr/bin/env python3
"""Aggregate runs/<arm>/<task_id>/result.json into an on-vs-off comparison.

Prints two tables (standard library only, no model calls):

  per arm    runs, utility, ASR, mean wall / agent / Conseca time, tokens,
             runs with 429 retries, Conseca fail-opens, run errors
  paired     every task present in both arms side by side, so the overhead
             is read on the same task rather than across different task mixes

Usage:
    python compare_arms.py                       # runs/ -> stdout (markdown)
    python compare_arms.py --suite banking
    python compare_arms.py --csv arms.csv --paired-csv paired.csv
    python compare_arms.py --exclude-429         # drop rate-limited runs from timing means

Read `runs_with_429` before trusting the latency columns: gemini-cli retries
429s internally and the retry wait lands in the measured time.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_runs(runs_dir: Path, suite: str | None) -> list[dict]:
    out = []
    for p in sorted(runs_dir.glob("*/*/result.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if suite and r.get("suite") != suite:
            continue
        r["_key"] = f"{r['suite']}/{r['user_task']}/{r.get('injection_task') or 'noinjection'}"
        t = r.get("telemetry", {})
        stages = t.get("by_stage", {})
        r["_agent_in"] = stages.get("agent", {}).get("input_tokens", 0)
        r["_agent_out"] = stages.get("agent", {}).get("output_tokens", 0)
        r["_conseca_in"] = sum(v.get("input_tokens", 0) for k, v in stages.items() if k.startswith("conseca_"))
        r["_conseca_out"] = sum(v.get("output_tokens", 0) for k, v in stages.items() if k.startswith("conseca_"))
        r["_conseca_calls"] = sum(v.get("requests", 0) for k, v in stages.items() if k.startswith("conseca_"))
        r["_agent_calls"] = stages.get("agent", {}).get("requests", 0)
        r["_429"] = t.get("rate_limited_retries", 0) or 0
        r["_fail_open"] = t.get("conseca_fail_open", 0) or 0
        r["_tool_calls"] = sum(r.get("tools", {}).values())
        out.append(r)
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def fmt(x, nd=1):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def per_arm(runs: list[dict], exclude_429: bool) -> list[dict]:
    rows = []
    for arm in sorted({r["arm"] for r in runs}):
        rs = [r for r in runs if r["arm"] == arm]
        timing = [r for r in rs if not (exclude_429 and r["_429"])]
        inj = [r for r in rs if r.get("injection_task")]
        agent_ms = mean([r["telemetry"].get("agent_ms") for r in timing])
        conseca_ms = mean([r["telemetry"].get("conseca_ms") for r in timing])
        rows.append(
            {
                "arm": arm,
                "runs": len(rs),
                "utility": mean([1.0 if r["utility"] else 0.0 for r in rs]),
                "asr": mean([1.0 if r["security"] else 0.0 for r in inj]) if inj else None,
                "asr_n": len(inj),
                "wall_s": mean([r["wall_seconds"] for r in timing]),
                "agent_ms": agent_ms,
                "conseca_ms": conseca_ms,
                "conseca_over_agent": (conseca_ms / agent_ms) if agent_ms else None,
                "agent_calls": mean([r["_agent_calls"] for r in rs]),
                "conseca_calls": mean([r["_conseca_calls"] for r in rs]),
                "tool_calls": mean([r["_tool_calls"] for r in rs]),
                "agent_tokens_in": mean([r["_agent_in"] for r in rs]),
                "agent_tokens_out": mean([r["_agent_out"] for r in rs]),
                "conseca_tokens_in": mean([r["_conseca_in"] for r in rs]),
                "conseca_tokens_out": mean([r["_conseca_out"] for r in rs]),
                "runs_with_429": sum(1 for r in rs if r["_429"]),
                "fail_open": sum(r["_fail_open"] for r in rs),
            }
        )
    return rows


def paired(runs: list[dict]) -> list[dict]:
    by = {}
    for r in runs:
        by.setdefault(r["_key"], {})[r["arm"]] = r
    rows = []
    for key in sorted(by):
        arms = by[key]
        if "off" not in arms or "on" not in arms:
            continue
        off, on = arms["off"], arms["on"]
        rows.append(
            {
                "task": key,
                "utility_off": off["utility"],
                "utility_on": on["utility"],
                "security_off": off["security"],
                "security_on": on["security"],
                "wall_off_s": off["wall_seconds"],
                "wall_on_s": on["wall_seconds"],
                "wall_ratio": (on["wall_seconds"] / off["wall_seconds"]) if off["wall_seconds"] else None,
                "agent_ms_off": off["telemetry"].get("agent_ms"),
                "agent_ms_on": on["telemetry"].get("agent_ms"),
                "conseca_ms_on": on["telemetry"].get("conseca_ms"),
                "tool_calls_off": off["_tool_calls"],
                "tool_calls_on": on["_tool_calls"],
                "verdicts_on": on["telemetry"].get("verdict_counts", {}),
                "429_off": off["_429"],
                "429_on": on["_429"],
                "fail_open_on": on["_fail_open"],
            }
        )
    return rows


def md_table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(label for _, label in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = []
    for r in rows:
        cells = []
        for k, _ in cols:
            v = r.get(k)
            if k in ("utility", "asr") and v is not None:
                v = f"{v:.0%}"
            elif isinstance(v, bool):
                v = "T" if v else "F"
            elif isinstance(v, float):
                v = fmt(v, 2 if k in ("conseca_over_agent", "wall_ratio") else 1)
            elif isinstance(v, dict):
                v = ",".join(f"{a}:{n}" for a, n in sorted(v.items())) or "-"
            cells.append("-" if v is None else str(v))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *body])


ARM_COLS = [
    ("arm", "arm"), ("runs", "runs"), ("utility", "utility"), ("asr", "ASR"), ("asr_n", "ASR n"),
    ("wall_s", "wall s"), ("agent_ms", "agent ms"), ("conseca_ms", "conseca ms"),
    ("conseca_over_agent", "conseca/agent"), ("agent_calls", "agent calls"),
    ("conseca_calls", "conseca calls"), ("tool_calls", "tool calls"),
    ("agent_tokens_in", "agent tok in"), ("agent_tokens_out", "agent tok out"),
    ("conseca_tokens_in", "conseca tok in"), ("conseca_tokens_out", "conseca tok out"),
    ("runs_with_429", "runs w/ 429"), ("fail_open", "fail-open"),
]
PAIR_COLS = [
    ("task", "task"), ("utility_off", "util off"), ("utility_on", "util on"),
    ("security_off", "sec off"), ("security_on", "sec on"),
    ("wall_off_s", "wall off s"), ("wall_on_s", "wall on s"), ("wall_ratio", "on/off"),
    ("agent_ms_off", "agent off ms"), ("agent_ms_on", "agent on ms"), ("conseca_ms_on", "conseca ms"),
    ("tool_calls_off", "tools off"), ("tool_calls_on", "tools on"), ("verdicts_on", "verdicts"),
    ("429_off", "429 off"), ("429_on", "429 on"), ("fail_open_on", "fail-open"),
]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=str(HERE / "runs"))
    ap.add_argument("--suite", default=None)
    ap.add_argument("--exclude-429", action="store_true", help="drop runs with 429 retries from timing means")
    ap.add_argument("--csv", default=None, help="write the per-arm table as CSV")
    ap.add_argument("--paired-csv", default=None, help="write the paired table as CSV")
    args = ap.parse_args()

    runs = load_runs(Path(args.runs), args.suite)
    if not runs:
        print(f"no result.json under {args.runs}")
        return 1
    arms = per_arm(runs, args.exclude_429)
    pairs = paired(runs)

    print(f"## per arm ({len(runs)} runs{', ' + args.suite if args.suite else ''}"
          f"{', 429 runs excluded from timing' if args.exclude_429 else ''})\n")
    print(md_table(arms, ARM_COLS))
    print(f"\n## paired ({len(pairs)} tasks in both arms)\n")
    print(md_table(pairs, PAIR_COLS) if pairs else "(none yet: run both arms on the same tasks)")
    on = next((a for a in arms if a["arm"] == "on"), None)
    off = next((a for a in arms if a["arm"] == "off"), None)
    notes = []
    if off and off["conseca_ms"]:
        notes.append("off arm has Conseca time > 0: the settings.json toggle was not applied (see README trap 1)")
    if on and on["fail_open"]:
        notes.append(f"on arm has {on['fail_open']} fail-open verdicts: those runs measure absence of defence, not defence")
    if any(a["runs_with_429"] for a in arms):
        notes.append("some runs hit 429 retries: re-run with --exclude-429 before quoting latency")
    if notes:
        print("\n## notes\n" + "\n".join(f"- {n}" for n in notes))
    if args.csv:
        write_csv(Path(args.csv), arms)
    if args.paired_csv:
        write_csv(Path(args.paired_csv), pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
