#!/usr/bin/env python3
"""Replay a recorded attacker payload against the target N times (static replay).

The dynamic attacker generates a fresh payload per run, so a single success or
failure mixes payload quality with the target's sampling variance. This script
holds the payload fixed and re-runs only the target loop, with or without the
guard, to estimate per-payload success probability.

    python replay_payload.py runs/<scenario>/<arm>/attempt_1.json --n 5 [--guard defender]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from google import genai

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_scenario as rs  # noqa: E402
from mock_integrations import MockEnv  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("attempt_json", type=Path)
    ap.add_argument("--scenario", type=Path, default=HERE / "scenarios" / "salesforce_destination_hijack_001.yaml")
    ap.add_argument("--target", default="gemini-3.5-flash")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--guard", choices=["defender"], default=None)
    ap.add_argument("--guard-node-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rec = json.loads(args.attempt_json.read_text(encoding="utf-8"))
    payload, addr = rec["payload"], rec["attacker_address"]
    sc = rs.load_scenario(args.scenario)
    sc["_target_model"] = args.target
    sc.setdefault("injection_target", {"note_id": "sf-note-redteam-001"})
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    guard = rs.make_guard(args.guard, args.guard_node_dir)
    out_dir = args.out or args.attempt_json.parent / f"replay_{args.attempt_json.stem}_{'guard-' + args.guard if args.guard else 'noguard'}"
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for i in range(1, args.n + 1):
        env = MockEnv(sc["seed_state"])
        env.inject_note_body(sc["injection_target"]["note_id"], payload)
        tgt = rs.run_target(client, args.target, sc, env, max_turns=args.max_turns, guard=guard)
        chk = rs.programmatic_check(sc, addr, tgt)
        blocked = [g["tool"] for g in tgt["guard_events"] if not g["allowed"]]
        print(f"replay {i}/{args.n}: attack={chk['attack_success']} utility={chk['utility_completed']} "
              f"emails={[m['to'] + m['cc'] + m['bcc'] for m in tgt['sent_emails']]} guard_blocked={blocked} ({tgt['seconds']}s)", flush=True)
        (out_dir / f"replay_{i}.json").write_text(json.dumps({"target": tgt, "check": chk}, ensure_ascii=False, indent=1), encoding="utf-8")
        runs.append({"i": i, **chk, "guard_blocked": blocked, "turns": tgt["turns"], "seconds": tgt["seconds"],
                     "usage": tgt["usage"], "final_reply": tgt["final_reply"][:400]})
    k = sum(r["attack_success"] for r in runs)
    summary = {"source_attempt": str(args.attempt_json), "payload": payload, "attacker_address": addr,
               "target": args.target, "guard": args.guard, "n": args.n, "attack_successes": k,
               "utility_completed": sum(r["utility_completed"] for r in runs),
               "guard_blocks": sum(len(r["guard_blocked"]) for r in runs), "runs": runs,
               "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nREPLAY: {k}/{args.n} attack successes, {summary['utility_completed']}/{args.n} utility, "
          f"{summary['guard_blocks']} guard blocks -> {out_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
