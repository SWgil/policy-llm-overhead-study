#!/usr/bin/env python3
"""Aggregate runs/<model>/<arm>/<task_id>/result.json into an on-vs-off comparison.

Runs are grouped by agent model: the tables below are printed once per model,
and tasks are only paired within the same model. Use --model to look at one.
For a cross-model overview see results_table.py.

Prints three tables per model (standard library only, no model calls):

  headline   per arm: utility on no-injection runs, utility under attack and
             ASR on injection runs, each with its run count (AgentDojo's
             reporting split)
  per arm    one row per arm x kind (benign = no injection, attack = with
             injection, all): runs, utility, ASR, mean wall / agent / Conseca
             time, calls, tokens, runs with 429 retries, Conseca fail-opens
  paired     every task present in both arms side by side, so the overhead
             is read on the same task rather than across different task mixes;
             the injection column separates benign rows from attack rows

Usage:
    python compare_arms.py                       # runs/ -> stdout (markdown)
    python compare_arms.py --suite banking
    python compare_arms.py --model gemini-3.1-flash-lite
    python compare_arms.py --kind attack         # per-arm and paired tables: injection runs only
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


def load_runs(runs_dir: Path, suite: str | None, model: str | None = None) -> list[dict]:
    """Every result.json under runs_dir, whatever the layout (runs/<model>/<arm>/
    <task_id>/ now, runs/<arm>/<task_id>/ before models were separated)."""
    out = []
    for p in sorted(runs_dir.rglob("result.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if "utility" not in r:
            continue
        if suite and r.get("suite") != suite:
            continue
        if model and r.get("model") != model:
            continue
        r["_key"] = f"{r.get('model')}/{r['suite']}/{r['user_task']}/{r.get('injection_task') or 'noinjection'}"
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


KINDS = ("benign", "attack", "all")


def of_kind(runs: list[dict], kind: str) -> list[dict]:
    if kind == "benign":
        return [r for r in runs if not r.get("injection_task")]
    if kind == "attack":
        return [r for r in runs if r.get("injection_task")]
    return list(runs)


def headline(runs: list[dict]) -> list[dict]:
    rows = []
    for arm in sorted({r["arm"] for r in runs}):
        rs = [r for r in runs if r["arm"] == arm]
        benign, attack = of_kind(rs, "benign"), of_kind(rs, "attack")
        rows.append(
            {
                "arm": arm,
                "utility": mean([1.0 if r["utility"] else 0.0 for r in benign]) if benign else None,
                "utility_n": len(benign),
                "utility_under_attack": mean([1.0 if r["utility"] else 0.0 for r in attack]) if attack else None,
                "asr": mean([1.0 if r["security"] else 0.0 for r in attack]) if attack else None,
                "attack_n": len(attack),
            }
        )
    return rows


def per_arm(runs: list[dict], exclude_429: bool, kinds: tuple[str, ...] = KINDS) -> list[dict]:
    rows = []
    for arm in sorted({r["arm"] for r in runs}):
        for kind in kinds:
            rs = of_kind([r for r in runs if r["arm"] == arm], kind)
            if not rs:
                continue
            timing = [r for r in rs if not (exclude_429 and r["_429"])]
            agent_ms = mean([r["telemetry"].get("agent_ms") for r in timing])
            conseca_ms = mean([r["telemetry"].get("conseca_ms") for r in timing])
            rows.append(
                {
                    "arm": arm,
                    "kind": kind,
                    "runs": len(rs),
                    "utility": mean([1.0 if r["utility"] else 0.0 for r in rs]),
                    "asr": mean([1.0 if r["security"] else 0.0 for r in rs]) if kind != "benign" else None,
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
    # benign rows first, then attacks, each in task order
    for key in sorted(by, key=lambda k: (not k.endswith("/noinjection"), k)):
        arms = by[key]
        if "off" not in arms or "on" not in arms:
            continue
        off, on = arms["off"], arms["on"]
        attack = bool(off.get("injection_task"))
        rows.append(
            {
                "task": f"{off['suite']}/{off['user_task']}",
                "injection": off.get("injection_task") or "none",
                "utility_off": off["utility"],
                "utility_on": on["utility"],
                "security_off": off["security"] if attack else None,
                "security_on": on["security"] if attack else None,
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
            if k in ("utility", "asr", "utility_under_attack") and v is not None:
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


HEADLINE_COLS = [
    ("arm", "arm"), ("utility", "utility (no injection)"), ("utility_n", "n"),
    ("utility_under_attack", "utility under attack"), ("asr", "ASR"), ("attack_n", "n"),
]
ARM_COLS = [
    ("arm", "arm"), ("kind", "kind"), ("runs", "runs"), ("utility", "utility"), ("asr", "ASR"),
    ("wall_s", "wall s"), ("agent_ms", "agent ms"), ("conseca_ms", "conseca ms"),
    ("conseca_over_agent", "conseca/agent"), ("agent_calls", "agent calls"),
    ("conseca_calls", "conseca calls"), ("tool_calls", "tool calls"),
    ("agent_tokens_in", "agent tok in"), ("agent_tokens_out", "agent tok out"),
    ("conseca_tokens_in", "conseca tok in"), ("conseca_tokens_out", "conseca tok out"),
    ("runs_with_429", "runs w/ 429"), ("fail_open", "fail-open"),
]
PAIR_COLS = [
    ("task", "task"), ("injection", "injection"), ("utility_off", "util off"), ("utility_on", "util on"),
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
    ap.add_argument("--model", default=None, help="only runs made with this agent model")
    ap.add_argument("--kind", choices=KINDS, default=None,
                    help="restrict the per-arm and paired tables to benign (no injection) or attack runs")
    ap.add_argument("--exclude-429", action="store_true", help="drop runs with 429 retries from timing means")
    ap.add_argument("--csv", default=None, help="write the per-arm table as CSV")
    ap.add_argument("--paired-csv", default=None, help="write the paired table as CSV")
    args = ap.parse_args()

    all_runs = load_runs(Path(args.runs), args.suite, args.model)
    if not all_runs:
        print(f"no result.json under {args.runs}")
        return 1
    kinds = (args.kind,) if args.kind else KINDS
    models = sorted({str(r.get("model")) for r in all_runs})
    all_arms, all_pairs = [], []
    for model in models:
        runs = [r for r in all_runs if str(r.get("model")) == model]
        head = headline(runs)
        arms = per_arm(runs, args.exclude_429, kinds)
        pairs = paired(of_kind(runs, args.kind) if args.kind else runs)
        scope = f"{len(runs)} runs{', ' + args.suite if args.suite else ''}"
        for a in arms:
            a["model"] = model
        for pr in pairs:
            pr["model"] = model
        all_arms += arms
        all_pairs += pairs

        if len(models) > 1:
            print(f"# model: {model}\n")
        print(f"## headline ({model}, {scope})\n")
        print(md_table(head, HEADLINE_COLS))
        print(f"\n## per arm x kind ({scope}{', ' + args.kind + ' only' if args.kind else ''}"
              f"{', 429 runs excluded from timing' if args.exclude_429 else ''})\n")
        print(md_table(arms, ARM_COLS))
        print(f"\n## paired ({len(pairs)} tasks in both arms)\n")
        print(md_table(pairs, PAIR_COLS) if pairs else "(none yet: run both arms on the same tasks)")
        on = next((a for a in arms if a["arm"] == "on" and a["kind"] == kinds[-1]), None)
        off = next((a for a in arms if a["arm"] == "off" and a["kind"] == kinds[-1]), None)
        notes = []
        if off and off["conseca_ms"]:
            notes.append("off arm has Conseca time > 0: the settings.json toggle was not applied (see README trap 1)")
        if on and on["fail_open"]:
            notes.append(f"on arm has {on['fail_open']} fail-open verdicts: those runs measure absence of defence, not defence")
        if any(a["runs_with_429"] for a in arms):
            notes.append("some runs hit 429 retries: re-run with --exclude-429 before quoting latency")
        if notes:
            print("\n## notes\n" + "\n".join(f"- {n}" for n in notes))
        print()
    if args.csv:
        write_csv(Path(args.csv), all_arms)
    if args.paired_csv:
        write_csv(Path(args.paired_csv), all_pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
