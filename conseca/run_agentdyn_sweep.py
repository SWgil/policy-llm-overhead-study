#!/usr/bin/env python3
"""Sweep one agent model over the AgentDyn suites and every non-DoS attack,
Conseca off and on, surviving the Gemini daily quota.

    .venv/bin/python run_agentdyn_sweep.py --model gemini-3.1-flash-lite
    .venv/bin/python run_agentdyn_sweep.py --model gemini-3.5-flash --arms off --pause 20
    .venv/bin/python run_agentdyn_sweep.py --model gemini-3.1-flash-lite --report-only

What it does, per model:
  1. starts the bridge if needed (bridge.sh) and asks it for the attack list
  2. for each arm x suite: the no-injection runs once (attack "none"), then
     every attack over the suite's injection tasks, via run_task.py with
       --out <out>/<attack>   --run-label <attack>
     so runs land in <out>/<attack>/<model>/<arm>/<task_id>/ (run_task.py adds
     the model and arm) and the bridge files in mcp_results/<attack>/...;
     nothing collides across models or attacks and every finished task is
     cached (an interrupted sweep resumes with the same command)
  3. when run_task.py exits 75 (Gemini daily quota exhausted: it already
     deleted the interrupted run), probes the model with one tiny request
     every --quota-wait seconds (default 30 min) until it answers, then
     re-issues the same job; the cache skips what was done
  4. prints a per-attack x arm table at the end (also --report-only)

Rate limits inside a day are not handled here: gemini-cli retries 429s itself
and --pause spaces the tasks; see README §5-③.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_task import AGENTDYN_SUITES, EXIT_QUOTA, SUITES  # noqa: E402

HERE = Path(__file__).resolve().parent
PY = sys.executable
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"


def log(logfile: Path | None, msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    if logfile:
        with logfile.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------- bridge

def bridge_running() -> bool:
    return subprocess.run(["./bridge.sh", "status"], cwd=HERE, capture_output=True).returncode == 0


def bridge(cmd: str) -> None:
    subprocess.run(["./bridge.sh", cmd], cwd=HERE, check=(cmd == "start"))


def list_attacks(rest_url: str, include_dos: bool) -> list[str]:
    r = requests.get(f"{rest_url}/attacks", timeout=30)
    r.raise_for_status()
    return sorted(name for name, info in r.json().items()
                  if include_dos or not info["is_dos_attack"])


# --------------------------------------------------------------------------- quota

def probe_model(model: str, timeout: int = 60) -> tuple[bool, str]:
    """One minimal generateContent call. (ok, detail). Only a 429 counts as
    'quota still exhausted'; any other failure is reported and treated as
    'try the real run' so a broken key does not wait forever silently."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return True, "GEMINI_API_KEY not set; cannot probe, assuming the quota is back"
    try:
        r = requests.post(
            f"{GEMINI_API}/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": "Reply with the single word OK."}]}],
                  "generationConfig": {"maxOutputTokens": 8}},
            timeout=timeout,
        )
    except requests.RequestException as e:
        return False, f"probe failed: {e}"
    if r.status_code == 200:
        return True, "probe ok"
    if r.status_code == 429:
        try:
            detail = r.json()["error"]["message"][:200]
        except Exception:
            detail = r.text[:200]
        return False, f"429: {detail}"
    return True, f"probe returned HTTP {r.status_code}: {r.text[:200]}"


def wait_for_quota(model: str, wait_s: int, logfile: Path | None) -> None:
    while True:
        log(logfile, f"[quota] waiting {wait_s}s before probing {model}")
        time.sleep(wait_s)
        ok, detail = probe_model(model)
        log(logfile, f"[quota] {detail}")
        if ok:
            return


# --------------------------------------------------------------------------- jobs

def run_job(args, arm: str, suite: str, attack: str, injection_tasks: list[str], logfile: Path | None) -> int:
    out_dir = Path(args.out) / attack
    cmd = [
        PY, str(HERE / "run_task.py"),
        "--arm", arm, "--suite", suite, "--model", args.model,
        "--out", str(out_dir), "--run-label", attack,
        "--rest-url", args.rest_url, "--mcp-url", args.mcp_url,
        "--timeout", str(args.timeout), "--pause", str(args.pause),
        "--injection-tasks", *injection_tasks,
    ]
    if attack != "none":
        cmd += ["--attack", attack]
    if args.user_tasks:
        cmd += ["--user-tasks", *args.user_tasks]
    if args.force:
        cmd.append("--force")
    if args.gemini:
        cmd += ["--gemini", args.gemini]
    while True:
        log(logfile, f"[job ] arm={arm} suite={suite} attack={attack} ({len(injection_tasks)} injection sets)")
        rc = subprocess.run(cmd, cwd=HERE).returncode
        if rc != EXIT_QUOTA:
            if rc != 0:
                log(logfile, f"[job ] arm={arm} suite={suite} attack={attack} finished with rc={rc} "
                             f"(some tasks failed; rerun the sweep to retry them)")
            return rc
        log(logfile, f"[quota] daily quota hit in arm={arm} suite={suite} attack={attack}; "
                     f"the interrupted run was deleted")
        wait_for_quota(args.model, args.quota_wait, logfile)
        log(logfile, "[quota] resuming")


# --------------------------------------------------------------------------- report

def report(args) -> None:
    root = Path(args.out)
    if not root.exists():
        print(f"no runs under {root}")
        return
    rows = []
    for attack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        model_dir = attack_dir / args.model
        if not model_dir.is_dir():
            continue
        for arm in sorted(p.name for p in model_dir.iterdir() if p.is_dir()):
            runs = [json.loads(p.read_text(encoding="utf-8"))
                    for p in sorted((model_dir / arm).glob("*/result.json"))]
            runs = [r for r in runs if "utility" in r]
            if args.suites:
                runs = [r for r in runs if r.get("suite") in args.suites]
            if not runs:
                continue
            util = sum(1 for r in runs if r["utility"]) / len(runs)
            asr = sum(1 for r in runs if r["security"]) / len(runs) if attack_dir.name != "none" else None
            walls = [r["wall_seconds"] for r in runs if r.get("wall_seconds")]
            cms = [r["telemetry"].get("conseca_ms") or 0 for r in runs]
            fo = sum(r["telemetry"].get("conseca_fail_open") or 0 for r in runs)
            r429 = sum(1 for r in runs if r["telemetry"].get("rate_limited_retries"))
            rows.append((attack_dir.name, arm, len(runs), util, asr, statistics.mean(walls) if walls else 0,
                         statistics.mean(cms) if cms else 0, r429, fo))
    print(f"\n## {args.model}: runs under {root}/<attack>/{args.model}/<arm>/\n")
    print("| attack | arm | runs | utility | ASR | wall s | conseca ms | runs w/ 429 | fail-open |")
    print("|---|---|---|---|---|---|---|---|---|")
    for a, arm, n, u, asr, w, c, r429, fo in rows:
        print(f"| {a} | {arm} | {n} | {u:.0%} | {'-' if asr is None else f'{asr:.0%}'} | {w:.1f} | {c:.0f} | {r429} | {fo} |")
    print("\n('none' rows are the no-injection runs: their utility is the benign utility.)")


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True,
                    help="agent model, e.g. gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.1-pro-preview")
    ap.add_argument("--arms", nargs="+", default=["off", "on"], choices=["off", "on"])
    ap.add_argument("--suites", nargs="+", default=sorted(AGENTDYN_SUITES), choices=sorted(SUITES))
    ap.add_argument("--attacks", nargs="+", default=None,
                    help="default: every registered attack that is not a DoS attack")
    ap.add_argument("--include-dos", action="store_true", help="keep DoS attacks in the default list")
    ap.add_argument("--user-tasks", nargs="+", default=None, help="subset (default: all of each suite)")
    ap.add_argument("--injection-tasks", nargs="+", default=None,
                    help="subset for the attack jobs (default: all of each suite)")
    ap.add_argument("--out", default=str(HERE / "runs_agentdyn"),
                    help="root: <out>/<attack>/<model>/<arm>/<task_id>/ ('none' = no-injection runs)")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between tasks (free tier: 60)")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per gemini process")
    ap.add_argument("--quota-wait", type=int, default=1800, help="seconds between quota probes")
    ap.add_argument("--rest-url", default="http://127.0.0.1:9000")
    ap.add_argument("--mcp-url", default="http://127.0.0.1:9001/mcp/")
    ap.add_argument("--gemini", default=None, help="path to the gemini binary")
    ap.add_argument("--force", action="store_true", help="ignore cached results")
    ap.add_argument("--report-only", action="store_true", help="only print the table for existing runs")
    args = ap.parse_args()

    if args.report_only:
        report(args)
        return 0

    logfile = Path(args.out) / f"sweep_{args.model}.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)

    started = False
    if not bridge_running():
        bridge("start")
        started = True
    try:
        attacks = args.attacks or list_attacks(args.rest_url, args.include_dos)
        log(logfile, f"model={args.model} arms={args.arms} suites={args.suites} attacks={attacks}")
        ok, detail = probe_model(args.model)
        log(logfile, f"[quota] initial probe: {detail}")
        if not ok:
            wait_for_quota(args.model, args.quota_wait, logfile)

        for arm in args.arms:
            for suite in args.suites:
                all_inj = SUITES[suite][1]
                inj = [t for t in (args.injection_tasks or all_inj) if t != "none"]
                run_job(args, arm, suite, "none", ["none"], logfile)
                for attack in attacks:
                    run_job(args, arm, suite, attack, inj, logfile)
        log(logfile, "sweep finished")
    finally:
        if started:
            bridge("stop")
    report(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
