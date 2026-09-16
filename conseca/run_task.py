#!/usr/bin/env python3
"""Run AgentDojo tasks through headless gemini-cli, with Conseca on or off.

The injection text comes from an AutoDojo cache by default (attacks/autodojo/
<suite>/injections.json: injections optimised by an LLM against undefended
gemini-2.5-flash, replayed here as a transfer attack). AgentDojo's static
important_instructions jailbreak is still available with --attack.

One task = one gemini-cli process. The flow, per task:

  1. POST /init_task on the AgentDojo MCP bridge  -> user prompt, which
     injection vectors got an optimised variant (pairs with none are skipped
     unless --include-unoptimized: they would be the static attack again)
  2. write a throwaway workspace: .gemini/settings.json (model, Conseca on/off,
     MCP server with the task id in a header, built-in tools excluded,
     temperature 0, no directory tree)
  3. gemini --approval-mode yolo -o json -p "<prompt>"   (cwd = workspace),
     with GEMINI_SYSTEM_MD pointing at agentdojo_system.md so the system
     instruction is AgentDojo's own system message instead of the CLI's
  4. POST /finish_task with the final response        -> utility, security
  5. parse the telemetry file                           -> agent vs Conseca cost

Results are cached per task in <out>/<arm>/<task_id>/result.json, so an
interrupted sweep resumes where it stopped. Delete the directory to rerun.

Examples:
    # single task, Conseca on, AutoDojo variant 0 (default attack)
    python run_task.py --arm on --suite banking --user-tasks user_task_0 \
        --injection-tasks injection_task_0

    # second-best variant; results land in runs/autodojo-v1/
    python run_task.py --arm off --suite banking --attack-variant 1

    # the static baseline; results land in runs/important_instructions/
    python run_task.py --arm off --suite banking --attack important_instructions

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

# Suite shapes of AgentDojo v1.1.2, restricted to the suites AutoDojo shipped a
# gemini-2.5-flash cache for (workspace has none). The cache covers every
# injection task of these three suites; run_task.py checks that at start-up.
SUITES = {
    "banking": (16, [f"injection_task_{i}" for i in range(9)]),
    "slack": (21, [f"injection_task_{i}" for i in range(1, 6)]),
    "travel": (20, [f"injection_task_{i}" for i in range(7)]),
}
ATTACKS = ("autodojo", "important_instructions")
ATTACK_CACHE_DIR = HERE / "attacks" / "autodojo"


def attack_cache_path(cache_dir: str, suite: str) -> Path:
    return Path(cache_dir) / suite / "injections.json"


def cached_injection_tasks(cache_dir: str, suite: str) -> list[str]:
    p = attack_cache_path(cache_dir, suite)
    if not p.exists():
        sys.exit(f"no AutoDojo cache for {suite}: {p}")
    return sorted(json.loads(p.read_text(encoding="utf-8"))["injection_tasks"])


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


SYSTEM_PROMPT = HERE / "agentdojo_system.md"  # AgentDojo's default system message, verbatim


def write_workspace(ws: Path, *, model: str, conseca: bool, mcp_url: str, cli_prompt: bool) -> None:
    (ws / ".gemini").mkdir(parents=True, exist_ok=True)
    template = (HERE / "settings.template.json").read_text(encoding="utf-8")
    settings = (
        template.replace("__MODEL__", model)
        .replace("__CONSECA__", "true" if conseca else "false")
        .replace("__MCP_URL__", mcp_url)
    )
    (ws / ".gemini" / "settings.json").write_text(settings, encoding="utf-8")
    if cli_prompt:
        # Legacy layout: keep the CLI's own system prompt and feed the AgentDojo
        # message in as project context (lands in the first user message).
        shutil.copyfile(SYSTEM_PROMPT, ws / "GEMINI.md")


def run_gemini(gemini: str, ws: Path, prompt: str, task_id: str, timeout: int, dry_run: bool,
               cli_prompt: bool) -> dict:
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
    if not cli_prompt:
        # Replace the CLI's coding-agent system prompt with AgentDojo's. Global
        # memory (~/.gemini/GEMINI.md) is still appended if present; keep it empty.
        env["GEMINI_SYSTEM_MD"] = str(SYSTEM_PROMPT)
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
            # Name the model in the injection text, as upstream AgentDojo does
            # (get_model_name_from_pipeline); the vendored bridge defaulted to
            # the generic "the AI language model".
            "attack_model_name": args.attack_model_name,
            "attack": args.attack,
            "attack_cache": str(attack_cache_path(args.attack_cache_dir, suite).resolve()),
            "attack_variant": args.attack_variant,
        },
        timeout=60,
    )
    if init.status_code == 400:
        raise RuntimeError(f"init_task rejected: {init.json().get('detail')}")
    init.raise_for_status()
    init = init.json()
    prompt = init["user_task_prompt"]
    plan = init.get("injection_plan", {})
    optimized = init.get("optimized_vectors", 0)
    if injection_task and args.attack == "autodojo" and optimized == 0 and not args.include_unoptimized:
        # every vector this user task reads fell back to the static wrapper
        print(f"[skip] {task_id}: no optimised vector for variant {args.attack_variant} "
              f"({', '.join(plan) or 'no vectors'})")
        return {"task_id": task_id, "user_task": user_task, "injection_task": injection_task,
                "skipped": "unoptimized"}
    print(f"[run ] {task_id}: {prompt[:80]}"
          + (f"  [{args.attack} v{args.attack_variant}: {optimized}/{len(plan)} optimised]"
             if injection_task and args.attack == "autodojo" else ""))

    write_workspace(ws, model=args.model, conseca=(arm == "on"), mcp_url=args.mcp_url,
                    cli_prompt=args.cli_prompt)
    out = run_gemini(gemini, ws, prompt, task_id, args.timeout, args.dry_run, args.cli_prompt)
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
        "attack": args.attack if injection_task else None,
        "attack_variant": args.attack_variant if (injection_task and args.attack == "autodojo") else None,
        "injection_plan": plan,
        "optimized_vectors": optimized if injection_task else None,
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
    ap.add_argument("--attack", choices=ATTACKS, default="autodojo",
                    help="autodojo = replay attacks/autodojo/<suite>/injections.json (default); "
                         "important_instructions = AgentDojo's static jailbreak")
    ap.add_argument("--attack-cache-dir", default=str(ATTACK_CACHE_DIR),
                    help="directory holding <suite>/injections.json AutoDojo caches")
    ap.add_argument("--attack-variant", type=int, default=0,
                    help="which of the cache's ranked variants to inject (0 = best on gemini-2.5-flash)")
    ap.add_argument("--include-unoptimized", action="store_true",
                    help="also run (user, injection) pairs whose vectors all fell back to the static "
                         "wrapper; by default they are skipped as they would repeat the static attack")
    ap.add_argument("--out", default=None,
                    help="results root; default runs/autodojo-v<variant> or runs/important_instructions")
    ap.add_argument("--rest-url", default="http://127.0.0.1:9000")
    ap.add_argument("--mcp-url", default="http://127.0.0.1:9001/mcp/")
    ap.add_argument("--gemini", default=None, help="path to the gemini binary")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per task")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds to sleep between tasks (free-tier keys: try 60)")
    ap.add_argument("--attack-model-name", default=None,
                    help="model name written into the injection text; default: 'Gemini' for gemini-* "
                         "models, else AgentDojo's generic 'the AI language model'")
    ap.add_argument("--cli-prompt", action="store_true",
                    help="keep gemini-cli's own system prompt and pass the AgentDojo message as "
                         "GEMINI.md project context (pre-alignment behaviour)")
    ap.add_argument("--force", action="store_true", help="ignore cached results")
    ap.add_argument("--dry-run", action="store_true", help="init the task and print the command only")
    args = ap.parse_args()

    gemini = find_gemini(args.gemini)
    if args.attack_model_name is None:
        args.attack_model_name = "Gemini" if "gemini" in args.model.lower() else "the AI language model"
    if args.out is None:
        args.out = str(HERE / "runs" / (f"autodojo-v{args.attack_variant}" if args.attack == "autodojo"
                                        else "important_instructions"))
    # gemini runs with cwd = the task workspace, and GEMINI_TELEMETRY_OUTFILE is
    # derived from --out; a relative --out would point it at a non-existent
    # directory and gemini exits 1 without printing anything.
    args.out = str(Path(args.out).resolve())
    n_users, injections = SUITES[args.suite]
    if args.attack == "autodojo":
        in_cache = cached_injection_tasks(args.attack_cache_dir, args.suite)
        missing = sorted(set(injections) - set(in_cache))
        if missing:
            print(f"[warn] {args.suite}: not in AutoDojo cache, not run: {', '.join(missing)}", file=sys.stderr)
        injections = [i for i in injections if i in in_cache]
        for it in args.injection_tasks or []:
            if it != "none" and it not in in_cache:
                sys.exit(f"{it} is not in the AutoDojo cache for {args.suite}")
    user_tasks = args.user_tasks or [f"user_task_{i}" for i in range(n_users)]
    injection_tasks = args.injection_tasks or ["none", *injections]
    print(f"attack={args.attack}" + (f" variant={args.attack_variant}" if args.attack == "autodojo" else "")
          + f" out={args.out}")

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
    skipped = [r for r in results if r.get("skipped")]
    if done:
        u = sum(1 for r in done if r["utility"]) / len(done)
        sec = [r for r in done if r["injection_task"]]
        asr = (sum(1 for r in sec if r["security"]) / len(sec)) if sec else None
        print(f"\n{args.arm}: {len(done)} tasks, utility={u:.2%}, ASR={asr if asr is None else f'{asr:.2%}'}, "
              f"skipped(unoptimised)={len(skipped)}, errors={len(results) - len(done) - len(skipped)}")
    return 0 if args.dry_run or len(done) + len(skipped) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
