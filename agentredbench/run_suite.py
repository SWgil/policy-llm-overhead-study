#!/usr/bin/env python3
"""Run every scenario in scenarios/ (or a chosen subset) through run_scenario.py
and then print the aggregate ASR table with aggregate.py.

    python run_suite.py                 # all scenarios, defaults (remote qwen)
    python run_suite.py --baseline      # include the benign utility baseline
    python run_suite.py --only calendar_url_relay_001 gmail_content_hijack_001
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=None, help="scenario_id(s) to run (default: all)")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--strip-think", action="store_true")
    ap.add_argument("--target", default=None)
    ap.add_argument("--attacker", default=None)
    ap.add_argument("--ollama-base-url", default=None)
    ap.add_argument("--out", default=None)
    args, passthrough = ap.parse_known_args()

    scenarios = sorted((HERE / "scenarios").glob("*.yaml"))
    if args.only:
        scenarios = [s for s in scenarios if s.stem in args.only]
        if not scenarios:
            sys.exit(f"no scenarios matched {args.only}")

    for sc in scenarios:
        cmd = [sys.executable, str(HERE / "run_scenario.py"), "--scenario", str(sc)]
        for flag in ("target", "attacker", "ollama_base_url", "out"):
            v = getattr(args, flag)
            if v:
                cmd += [f"--{flag.replace('_', '-')}", str(v)]
        if args.baseline:
            cmd.append("--baseline")
        if args.strip_think:
            cmd.append("--strip-think")
        cmd += passthrough
        print(f"\n########## {sc.stem} ##########", flush=True)
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"   (run_scenario exited {rc})", flush=True)

    print("\n" + "=" * 60, flush=True)
    subprocess.run([sys.executable, str(HERE / "aggregate.py")]
                   + (["--out", str(args.out)] if args.out else []))


if __name__ == "__main__":
    main()
