#!/usr/bin/env python3
"""One table over every run under runs/: model x suite x arm.

run_task.py keeps each agent model's results apart (runs/<model>/<arm>/<task_id>/).
This script reads all of them and prints, per (model, suite, arm) row:

  runs, benign n + utility, attack n + utility under attack + ASR, mean wall
  time, agent ms, Conseca ms, Conseca/agent, tool calls, runs with 429 retries,
  fail-open verdicts, and the model the API actually served (README trap 4).

Then, per (model, suite), an on-vs-off overhead row computed only on tasks
that finished in both arms. With --tasks every single run is listed.

Standard library only. Usage:
    python results_table.py                          # markdown to stdout
    python results_table.py --by model,arm           # merge suites
    python results_table.py --suite shopping --model gemini-3.1-flash-lite
    python results_table.py --tasks                  # also list every run
    python results_table.py --csv summary.csv --overhead-csv overhead.csv --tasks-csv runs.csv
    python results_table.py --exclude-429            # drop rate-limited runs from timing means
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
GROUP_KEYS = ("model", "suite", "arm")


# --------------------------------------------------------------------------- loading

def load_runs(runs_dir: Path, *, model: str | None, suite: str | None, arm: str | None) -> list[dict]:
    rows = []
    for p in sorted(runs_dir.rglob("result.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if "utility" not in r:  # dry runs / partial writes
            continue
        if model and r.get("model") != model:
            continue
        if suite and r.get("suite") != suite:
            continue
        if arm and r.get("arm") != arm:
            continue
        t = r.get("telemetry") or {}
        stages = t.get("by_stage") or {}
        served = r.get("served_model")
        rows.append(
            {
                "path": str(p.parent),
                "model": str(r.get("model")),
                "served_model": ", ".join(served) if isinstance(served, list) else (served or ""),
                "cli": r.get("gemini_cli_version") or "",
                "suite": r.get("suite"),
                "arm": r.get("arm"),
                "user_task": r.get("user_task"),
                "injection_task": r.get("injection_task"),
                "attack": bool(r.get("injection_task")),
                "utility": bool(r.get("utility")),
                "security": bool(r.get("security")) if r.get("injection_task") else None,
                "wall_s": r.get("wall_seconds"),
                "agent_ms": t.get("agent_ms"),
                "conseca_ms": t.get("conseca_ms"),
                "agent_calls": stages.get("agent", {}).get("requests", 0),
                "conseca_calls": sum(v.get("requests", 0) for k, v in stages.items() if k.startswith("conseca_")),
                "tool_calls": sum((r.get("tools") or {}).values()),
                "verdicts": t.get("verdict_counts") or {},
                "rate_429": t.get("rate_limited_retries") or 0,
                "fail_open": t.get("conseca_fail_open") or 0,
                "started_at": r.get("started_at") or "",
            }
        )
    return rows


# --------------------------------------------------------------------------- aggregation

def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def rate(flags):
    flags = [f for f in flags if f is not None]
    return (sum(1 for f in flags if f) / len(flags)) if flags else None


def group_key(r: dict, by: tuple[str, ...]) -> tuple:
    return tuple(r[k] for k in by)


def summary(rows: list[dict], by: tuple[str, ...], exclude_429: bool) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(group_key(r, by), []).append(r)
    out = []
    for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
        rs = groups[key]
        benign = [r for r in rs if not r["attack"]]
        attack = [r for r in rs if r["attack"]]
        timing = [r for r in rs if not (exclude_429 and r["rate_429"])]
        agent_ms = mean([r["agent_ms"] for r in timing])
        conseca_ms = mean([r["conseca_ms"] for r in timing])
        row = dict(zip(by, key))
        row.update(
            {
                "runs": len(rs),
                "benign_n": len(benign),
                "utility": rate([r["utility"] for r in benign]),
                "attack_n": len(attack),
                "utility_under_attack": rate([r["utility"] for r in attack]),
                "asr": rate([r["security"] for r in attack]),
                "wall_s": mean([r["wall_s"] for r in timing]),
                "agent_ms": agent_ms,
                "conseca_ms": conseca_ms,
                "conseca_over_agent": (conseca_ms / agent_ms) if agent_ms and conseca_ms is not None else None,
                "agent_calls": mean([r["agent_calls"] for r in rs]),
                "conseca_calls": mean([r["conseca_calls"] for r in rs]),
                "tool_calls": mean([r["tool_calls"] for r in rs]),
                "runs_with_429": sum(1 for r in rs if r["rate_429"]),
                "fail_open": sum(r["fail_open"] for r in rs),
                "served_model": ", ".join(sorted({r["served_model"] for r in rs if r["served_model"]})),
                "cli": ", ".join(sorted({r["cli"] for r in rs if r["cli"]})),
            }
        )
        out.append(row)
    return out


def overhead(rows: list[dict], by: tuple[str, ...], exclude_429: bool) -> list[dict]:
    """on-vs-off on the tasks present in both arms, per group (model[, suite])."""
    keys = tuple(k for k in by if k != "arm")
    groups: dict[tuple, dict[tuple, dict[str, dict]]] = {}
    for r in rows:
        task = (r["suite"], r["user_task"], r["injection_task"])
        groups.setdefault(group_key(r, keys), {}).setdefault(task, {})[r["arm"]] = r
    out = []
    for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
        pairs = [(t, arms["off"], arms["on"]) for t, arms in groups[key].items() if "off" in arms and "on" in arms]
        if not pairs:
            continue
        off = [o for _, o, _ in pairs]
        on = [n for _, _, n in pairs]
        benign = [(o, n) for o, n in zip(off, on) if not o["attack"]]
        attack = [(o, n) for o, n in zip(off, on) if o["attack"]]
        timing = [(o, n) for o, n in zip(off, on) if not (exclude_429 and (o["rate_429"] or n["rate_429"]))]
        wall_off = mean([o["wall_s"] for o, _ in timing])
        wall_on = mean([n["wall_s"] for _, n in timing])
        agent_off = mean([o["agent_ms"] for o, _ in timing])
        agent_on = mean([n["agent_ms"] for _, n in timing])
        conseca_on = mean([n["conseca_ms"] for _, n in timing])
        row = dict(zip(keys, key))
        row.update(
            {
                "paired": len(pairs),
                "benign_n": len(benign),
                "utility_off": rate([o["utility"] for o, _ in benign]),
                "utility_on": rate([n["utility"] for _, n in benign]),
                "attack_n": len(attack),
                "utility_under_attack_off": rate([o["utility"] for o, _ in attack]),
                "utility_under_attack_on": rate([n["utility"] for _, n in attack]),
                "asr_off": rate([o["security"] for o, _ in attack]),
                "asr_on": rate([n["security"] for _, n in attack]),
                "wall_off_s": wall_off,
                "wall_on_s": wall_on,
                "wall_ratio": (wall_on / wall_off) if wall_off and wall_on is not None else None,
                "agent_ms_off": agent_off,
                "agent_ms_on": agent_on,
                "conseca_ms_on": conseca_on,
                "conseca_over_agent": (conseca_on / agent_on) if agent_on and conseca_on is not None else None,
                "tool_calls_off": mean([o["tool_calls"] for o in off]),
                "tool_calls_on": mean([n["tool_calls"] for n in on]),
                "fail_open_on": sum(n["fail_open"] for n in on),
            }
        )
        out.append(row)
    return out


# --------------------------------------------------------------------------- output

PCT = {"utility", "utility_under_attack", "asr", "utility_off", "utility_on",
       "utility_under_attack_off", "utility_under_attack_on", "asr_off", "asr_on"}
RATIO = {"conseca_over_agent", "wall_ratio"}


def cell(k, v) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, bool):  # per-run flags; the group rates below are floats
        return "T" if v else "F"
    if k in PCT:
        return f"{v:.0%}"
    if isinstance(v, float):
        return f"{v:.2f}" if k in RATIO else f"{v:.1f}"
    if isinstance(v, dict):
        return ",".join(f"{a}:{n}" for a, n in sorted(v.items())) or "-"
    return str(v)


def md_table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(label for _, label in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = ["| " + " | ".join(cell(k, r.get(k)) for k, _ in cols) + " |" for r in rows]
    return "\n".join([head, sep, *body])


SUMMARY_COLS = [
    ("runs", "runs"), ("benign_n", "benign n"), ("utility", "utility"),
    ("attack_n", "attack n"), ("utility_under_attack", "util under attack"), ("asr", "ASR"),
    ("wall_s", "wall s"), ("agent_ms", "agent ms"), ("conseca_ms", "conseca ms"),
    ("conseca_over_agent", "conseca/agent"), ("agent_calls", "agent calls"),
    ("conseca_calls", "conseca calls"), ("tool_calls", "tool calls"),
    ("runs_with_429", "runs w/ 429"), ("fail_open", "fail-open"),
    ("served_model", "served model"), ("cli", "cli"),
]
OVERHEAD_COLS = [
    ("paired", "paired"), ("benign_n", "benign n"), ("utility_off", "util off"), ("utility_on", "util on"),
    ("attack_n", "attack n"), ("utility_under_attack_off", "util@attack off"),
    ("utility_under_attack_on", "util@attack on"), ("asr_off", "ASR off"), ("asr_on", "ASR on"),
    ("wall_off_s", "wall off s"), ("wall_on_s", "wall on s"), ("wall_ratio", "on/off"),
    ("agent_ms_off", "agent off ms"), ("agent_ms_on", "agent on ms"), ("conseca_ms_on", "conseca ms"),
    ("conseca_over_agent", "conseca/agent"), ("tool_calls_off", "tools off"), ("tool_calls_on", "tools on"),
    ("fail_open_on", "fail-open"),
]
TASK_COLS = [
    ("model", "model"), ("arm", "arm"), ("suite", "suite"), ("user_task", "user task"),
    ("injection_task", "injection"), ("utility", "util"), ("security", "sec"),
    ("wall_s", "wall s"), ("agent_ms", "agent ms"), ("conseca_ms", "conseca ms"),
    ("tool_calls", "tools"), ("verdicts", "verdicts"), ("rate_429", "429"), ("fail_open", "fail-open"),
    ("served_model", "served model"), ("started_at", "started"),
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
    ap.add_argument("--runs", default=str(HERE / "runs"), help="results root written by run_task.py")
    ap.add_argument("--by", default="model,suite,arm",
                    help="grouping columns, comma separated, from model/suite/arm (default: model,suite,arm)")
    ap.add_argument("--model", default=None, help="only this agent model")
    ap.add_argument("--suite", default=None, help="only this suite")
    ap.add_argument("--arm", choices=["on", "off"], default=None, help="only this arm")
    ap.add_argument("--exclude-429", action="store_true", help="drop runs with 429 retries from timing means")
    ap.add_argument("--tasks", action="store_true", help="also list every run")
    ap.add_argument("--csv", default=None, help="write the summary table as CSV")
    ap.add_argument("--overhead-csv", default=None, help="write the overhead table as CSV")
    ap.add_argument("--tasks-csv", default=None, help="write every run as CSV")
    args = ap.parse_args()

    by = tuple(k.strip() for k in args.by.split(",") if k.strip())
    bad = [k for k in by if k not in GROUP_KEYS]
    if bad or not by:
        ap.error(f"--by takes a subset of {','.join(GROUP_KEYS)}; got {args.by!r}")
    if "arm" not in by:
        by = (*by, "arm")  # the summary is always split by arm; overhead drops it itself

    rows = load_runs(Path(args.runs), model=args.model, suite=args.suite, arm=args.arm)
    if not rows:
        print(f"no finished runs under {args.runs}")
        return 1

    models = sorted({r["model"] for r in rows})
    suites = sorted({r["suite"] for r in rows})
    print(f"## summary ({len(rows)} runs, {len(models)} model(s): {', '.join(models)}; "
          f"suites: {', '.join(suites)}{'; 429 runs excluded from timing' if args.exclude_429 else ''})\n")
    summ = summary(rows, by, args.exclude_429)
    print(md_table(summ, [(k, k) for k in by] + SUMMARY_COLS))

    over = overhead(rows, by, args.exclude_429)
    print(f"\n## overhead: Conseca on vs off on tasks finished in both arms ({len(over)} group(s))\n")
    print(md_table(over, [(k, k) for k in by if k != "arm"] + OVERHEAD_COLS) if over
          else "(none yet: run both arms on the same tasks)")

    if args.tasks:
        print(f"\n## runs ({len(rows)})\n")
        rows_sorted = sorted(rows, key=lambda r: (r["model"], r["suite"], r["arm"], r["user_task"],
                                                  r["injection_task"] or ""))
        print(md_table(rows_sorted, TASK_COLS))

    notes = []
    if any(s["arm"] == "off" and s["conseca_ms"] for s in summ):
        notes.append("an off row has Conseca time > 0: the settings.json toggle was not applied (README trap 1)")
    if any(s["arm"] == "on" and s["fail_open"] for s in summ):
        notes.append("an on row has fail-open verdicts: those runs measure absence of defence, not defence")
    if any(s["runs_with_429"] for s in summ):
        notes.append("some runs hit 429 retries: re-run with --exclude-429 before quoting latency")
    aliased = sorted({(s.get("model"), s["served_model"]) for s in summ
                      if s["served_model"] and s["served_model"] != s.get("model")})
    if aliased:
        notes.append("served model differs from the requested one for: " +
                     "; ".join(f"{m} -> {sm}" for m, sm in aliased))
    if notes:
        print("\n## notes\n" + "\n".join(f"- {n}" for n in notes))

    if args.csv:
        write_csv(Path(args.csv), summ)
    if args.overhead_csv:
        write_csv(Path(args.overhead_csv), over)
    if args.tasks_csv:
        write_csv(Path(args.tasks_csv), rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
