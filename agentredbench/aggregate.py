#!/usr/bin/env python3
"""Aggregate run summaries into ASR tables (per-scenario, per-attack-type,
per-connector). Reads runs/<scenario>/<arm>/summary.json.

    python aggregate.py                 # scans runs/, prints tables
    python aggregate.py --csv out.csv   # also write a per-scenario CSV
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_summaries(runs_dir: Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted(runs_dir.glob("*/*/summary.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print(f"skip {f}: {e}")
    return out


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "—"


def _table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = lambda cells: "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return "\n".join([line(headers), sep, *(line(r) for r in rows)])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="runs dir (default: runs/)")
    ap.add_argument("--csv", default=None, help="write a per-scenario CSV here")
    args = ap.parse_args()

    runs_dir = Path(args.out) if args.out else HERE / "runs"
    sums = load_summaries(runs_dir)
    if not sums:
        print(f"no summaries under {runs_dir}. Run run_scenario.py / run_suite.py first.")
        return

    # per-scenario rows
    scen_rows, prog_by_type, judge_by_type, prog_by_conn = [], defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    csv_rows = []
    for s in sums:
        used = [a for a in s["attempts"] if "attacker_failure" not in a]
        judge_success = s.get("asr_inclusive_of_partial", False)
        prog_success = any(a.get("programmatic_check", {}).get("attack_success") for a in used)
        atype, conns = s["attack_type"], "+".join(s.get("connectors", []))
        base = s.get("baseline", {})
        scen_rows.append([s["scenario_id"], atype, conns, s.get("target", "?"),
                          str(len(used)) + f"/{s['attempt_budget']}",
                          "Y" if judge_success else "n", "Y" if prog_success else "n",
                          {True: "Y", False: "n", None: "—"}.get(base.get("utility_completed"), "—")])
        prog_by_type[atype][0] += int(prog_success); prog_by_type[atype][1] += 1
        judge_by_type[atype][0] += int(judge_success); judge_by_type[atype][1] += 1
        prog_by_conn[conns][0] += int(prog_success); prog_by_conn[conns][1] += 1
        csv_rows.append({"scenario_id": s["scenario_id"], "attack_type": atype, "connectors": conns,
                         "target": s.get("target"), "attempts_used": len(used),
                         "judge_asr_success": judge_success, "programmatic_success": prog_success,
                         "baseline_utility": base.get("utility_completed")})

    print("\n## Per scenario\n")
    print(_table(scen_rows, ["scenario", "attack_type", "connectors", "target",
                             "attempts", "judgeASR", "progASR", "baseUtil"]))

    print("\n## ASR by attack_type (programmatic | judge, over scenarios where attack succeeded ≥once)\n")
    trows = [[t, f"{p[0]}/{p[1]}", _pct(p[0], p[1]),
              f"{judge_by_type[t][0]}/{judge_by_type[t][1]}", _pct(judge_by_type[t][0], judge_by_type[t][1])]
             for t, p in sorted(prog_by_type.items())]
    print(_table(trows, ["attack_type", "prog n", "prog ASR", "judge n", "judge ASR"]))

    print("\n## ASR by connector set (programmatic)\n")
    crows = [[c, f"{p[0]}/{p[1]}", _pct(p[0], p[1])] for c, p in sorted(prog_by_conn.items())]
    print(_table(crows, ["connectors", "n", "prog ASR"]))

    tot_p = sum(p[0] for p in prog_by_type.values()); tot_n = sum(p[1] for p in prog_by_type.values())
    tot_j = sum(p[0] for p in judge_by_type.values())
    print(f"\nOVERALL: programmatic {tot_p}/{tot_n} ({_pct(tot_p, tot_n)}), "
          f"judge {tot_j}/{tot_n} ({_pct(tot_j, tot_n)})")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(csv_rows[0]))
            w.writeheader(); w.writerows(csv_rows)
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
