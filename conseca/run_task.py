#!/usr/bin/env python3
"""Run AgentDojo tasks through headless gemini-cli, with Conseca on or off.

One task = one gemini-cli process. The flow, per task:

  1. POST /init_task on the AgentDojo MCP bridge  -> user prompt
  2. write a throwaway workspace: .gemini/settings.json (model, Conseca on/off,
     MCP server with the task id in a header) + GEMINI.md (AgentDojo's system
     prompt)
  3. gemini --approval-mode yolo -o json -p "<prompt>"   (cwd = workspace)
  4. POST /finish_task with the final response        -> utility, security
  5. parse the telemetry file                           -> agent vs Conseca cost

Results are cached per task in <out>/<arm>/<task_id>/result.json, so an
interrupted sweep resumes where it stopped. Delete the directory to rerun.

Examples:
    # single task, Conseca on (what the feasibility check ran)
    python run_task.py --arm on --suite banking --user-tasks user_task_0 \
        --injection-tasks injection_task_0

    # small pilot, both arms
    for arm in off on; do
      python run_task.py --arm $arm --suite banking \
        --user-tasks user_task_0 user_task_1 user_task_2 user_task_3 \
        --injection-tasks none injection_task_0 injection_task_1 injection_task_2
    done

    # print the gemini command without calling the model
    python run_task.py --arm on --suite banking --user-tasks user_task_0 --dry-run

See README.md for prerequisites and the traps that fail silently.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_telemetry import summarise  # noqa: E402

HERE = Path(__file__).resolve().parent

# Same suite shapes as progent/real-world-agents/run.py (AgentDojo v1.1.2).
SUITES = {
    "banking": (16, [f"injection_task_{i}" for i in range(9)]),
    "slack": (21, [f"injection_task_{i}" for i in range(1, 6)]),
    "travel": (20, [f"injection_task_{i}" for i in range(7)]),
    "workspace": (40, [f"injection_task_{i}" for i in range(6)]),
}


def find_gemini(explicit: str | None) -> str:
    if explicit:
        return explicit
    for name in ("gemini", "gemini.cmd"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("gemini-cli not on PATH; install with `npm i -g @google/gemini-cli` or pass --gemini")


def task_id_for(arm: str, suite: str, user_task: str, injection_task: str | None) -> str:
    # Must match the bridge's result-file regex:
    #   ^(\w+)_([\w]+)_(user_task_\d+)_(injection_task_\d+|noinjection)$
    return f"gemini{arm}_{suite}_{user_task}_{injection_task or 'noinjection'}"


def write_workspace(ws: Path, *, model: str, conseca: bool, mcp_url: str) -> None:
    (ws / ".gemini").mkdir(parents=True, exist_ok=True)
    template = (HERE / "settings.template.json").read_text(encoding="utf-8")
    settings = (
        template.replace("__MODEL__", model)
        .replace("__CONSECA__", "true" if conseca else "false")
        .replace("__MCP_URL__", mcp_url)
    )
    (ws / ".gemini" / "settings.json").write_text(settings, encoding="utf-8")
    shutil.copyfile(HERE / "GEMINI.md", ws / "GEMINI.md")


def run_gemini(gemini: str, ws: Path, prompt: str, task_id: str, timeout: int, dry_run: bool) -> dict:
    telemetry = ws / "telemetry.log"
    if telemetry.exists():
        telemetry.unlink()
    env = dict(os.environ)
    env.update(
        {
            "AGENTDOJO_TASK_ID": task_id,
            # Workspace settings are dropped unless the folder is trusted at
            # settings-load time; --skip-trust is applied too late for that.
            "GEMINI_CLI_TRUST_WORKSPACE": "true",
            "GEMINI_TELEMETRY_ENABLED": "true",
            "GEMINI_TELEMETRY_TARGET": "local",
            "GEMINI_TELEMETRY_OUTFILE": str(telemetry),
            "GEMINI_TELEMETRY_LOG_PROMPTS": "true",
        }
    )
    cmd = [gemini, "--approval-mode", "yolo", "-o", "json", "-p", prompt]
    if dry_run:
        print("DRY RUN, would execute in", ws)
        print("  ", " ".join(repr(c) if " " in c else c for c in cmd))
        return {"response": "", "stats": {}, "dry_run": True}

    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=ws, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    wall = time.time() - t0
    (ws / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (ws / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
    raw = proc.stdout
    i = raw.find("{")
    if proc.returncode != 0 or i < 0:
        raise RuntimeError(
            f"gemini exited {proc.returncode}; stderr tail: {proc.stderr[-800:]}"
        )
    out = json.loads(raw[i:])
    out["wall_seconds"] = wall
    out["returncode"] = proc.returncode
    return out


def run_one(args, gemini: str, arm: str, suite: str, user_task: str, injection_task: str | None) -> dict:
    task_id = task_id_for(arm, suite, user_task, injection_task)
    ws = Path(args.out) / arm / task_id
    result_path = ws / "result.json"
    if result_path.exists() and not args.force:
        print(f"[skip] {task_id} (cached)")
        return json.loads(result_path.read_text(encoding="utf-8"))

    init = requests.post(
        f"{args.rest_url}/init_task",
        json={
            "task_id": task_id,
            "suite_name": suite,
            "user_task_id": user_task,
            "injection_task_id": injection_task,
        },
        timeout=60,
    )
    init.raise_for_status()
    prompt = init.json()["user_task_prompt"]
    print(f"[run ] {task_id}: {prompt[:80]}")

    write_workspace(ws, model=args.model, conseca=(arm == "on"), mcp_url=args.mcp_url)
    out = run_gemini(gemini, ws, prompt, task_id, args.timeout, args.dry_run)
    if args.dry_run:
        return {"task_id": task_id, "dry_run": True}

    fin = requests.post(
        f"{args.rest_url}/finish_task",
        json={"task_id": task_id, "model_output": out.get("response", "")},
        timeout=60,
    )
    fin.raise_for_status()
    score = fin.json()

    telemetry = summarise(ws / "telemetry.log") if (ws / "telemetry.log").exists() else None
    roles = {}
    for model, mstats in out.get("stats", {}).get("models", {}).items():
        for role, r in mstats.get("roles", {}).items():
            roles[f"{role}:{model}"] = {
                "requests": r["totalRequests"],
                "errors": r["totalErrors"],
                "latency_ms": r["totalLatencyMs"],
                "prompt_tokens": r["tokens"]["prompt"],
                "output_tokens": r["tokens"]["candidates"],
            }
    result = {
        "task_id": task_id,
        "arm": arm,
        "suite": suite,
        "user_task": user_task,
        "injection_task": injection_task,
        "model": args.model,
        "utility": score.get("utility"),
        "security": score.get("security"),
        "wall_seconds": out.get("wall_seconds"),
        "roles": roles,
        "tools": {k: v["count"] for k, v in out.get("stats", {}).get("tools", {}).get("byName", {}).items()},
        "telemetry": {k: v for k, v in (telemetry or {}).items() if k not in ("calls", "verdicts", "policies", "errors")},
        "conseca_verdicts": [
            {"tool": v["tool"], "verdict": v["verdict"], "error": v["error"]}
            for v in (telemetry or {}).get("verdicts", [])
        ],
        "response": out.get("response", ""),
    }
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    t = result["telemetry"]
    print(
        f"[done] utility={result['utility']} security={result['security']} "
        f"wall={result['wall_seconds']:.1f}s agent={t.get('agent_ms')}ms "
        f"conseca={t.get('conseca_ms')}ms verdicts={t.get('verdict_counts')} "
        f"429s={t.get('rate_limited_retries')} fail_open={t.get('conseca_fail_open')}"
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=["on", "off"], required=True, help="Conseca on or off")
    ap.add_argument("--suite", choices=sorted(SUITES), required=True)
    ap.add_argument("--user-tasks", nargs="+", default=None, help="default: all in suite")
    ap.add_argument("--injection-tasks", nargs="+", default=None,
                    help="'none' = no injection; default: none + all in suite")
    ap.add_argument("--model", default="gemini-2.5-flash",
                    help="agent model (Conseca itself is pinned to the CLI's flash default)")
    ap.add_argument("--out", default=str(HERE / "runs"))
    ap.add_argument("--rest-url", default="http://127.0.0.1:9000")
    ap.add_argument("--mcp-url", default="http://127.0.0.1:9001/mcp/")
    ap.add_argument("--gemini", default=None, help="path to the gemini binary")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per task")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds to sleep between tasks (free-tier keys: try 60)")
    ap.add_argument("--force", action="store_true", help="ignore cached results")
    ap.add_argument("--dry-run", action="store_true", help="init the task and print the command only")
    args = ap.parse_args()

    gemini = find_gemini(args.gemini)
    n_users, injections = SUITES[args.suite]
    user_tasks = args.user_tasks or [f"user_task_{i}" for i in range(n_users)]
    injection_tasks = args.injection_tasks or ["none", *injections]

    results = []
    for ut in user_tasks:
        for it in injection_tasks:
            inj = None if it == "none" else it
            try:
                results.append(run_one(args, gemini, args.arm, args.suite, ut, inj))
            except Exception as e:  # keep the sweep going; the task is simply not cached
                print(f"[fail] {ut} {it}: {e}", file=sys.stderr)
                results.append({"user_task": ut, "injection_task": inj, "error": str(e)})
            if args.pause and not args.dry_run:
                time.sleep(args.pause)

    done = [r for r in results if "utility" in r]
    if done:
        u = sum(1 for r in done if r["utility"]) / len(done)
        sec = [r for r in done if r["injection_task"]]
        asr = (sum(1 for r in sec if r["security"]) / len(sec)) if sec else None
        print(f"\n{args.arm}: {len(done)} tasks, utility={u:.2%}, ASR={asr if asr is None else f'{asr:.2%}'}, "
              f"errors={len(results) - len(done)}")
    return 0 if args.dry_run or len(done) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
