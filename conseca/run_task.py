#!/usr/bin/env python3
"""Run AgentDyn / AgentDojo tasks through headless gemini-cli, with Conseca on or off.

One task = one gemini-cli process. The flow, per task:

  1. POST /init_task on the AgentDojo MCP bridge  -> user prompt
  2. write a throwaway workspace: .gemini/settings.json (model, Conseca on/off,
     MCP server with the task id in a header, built-in tools excluded,
     temperature 0, no directory tree)
  3. gemini --approval-mode yolo -o json -p "<prompt>"   (cwd = workspace),
     with GEMINI_SYSTEM_MD pointing at agentdyn_system.md (AgentDyn suites) or
     agentdojo_system.md (AgentDojo suites) so the system instruction is the
     benchmark's own system message instead of the CLI's
  4. POST /finish_task with the final response        -> utility, security
  5. parse the telemetry file                           -> agent vs Conseca cost

Results are cached per task in <out>/<model>/<arm>/<task_id>/result.json, so
an interrupted sweep resumes where it stopped and every model keeps its own
results (the task id carries the model too, so the bridge's mcp_results/ files
are separate per model as well). Delete the directory to rerun.

Exit codes: 0 all tasks done, 1 some task failed (not cached, rerun later),
75 (EX_TEMPFAIL) the Gemini daily quota is exhausted: the run that hit it is
deleted, the sweep stops at once, and run_agentdyn_sweep.py waits for the
quota to come back before re-invoking this script.

Examples:
    # single AgentDyn task, Conseca on
    python run_task.py --arm on --suite shopping --user-tasks user_task_0 \
        --injection-tasks injection_task_0

    # single AgentDojo task, Conseca on (what the feasibility check ran)
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
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_telemetry import summarise  # noqa: E402

HERE = Path(__file__).resolve().parent

EXIT_QUOTA = 75  # EX_TEMPFAIL: stop now, retry later

# gemini-cli output that means the daily quota is gone (or that it silently
# switched model because of it). Per-minute 429s are retried inside the CLI
# and only show up as rate_limited_retries in the telemetry.
QUOTA_RE = re.compile(
    r"exhausted your daily quota|daily quota|quota exceeded|RESOURCE_EXHAUSTED|per day|"
    r"Switching to (the )?\S+ model|Switching to flash as Fallback|fallback model",
    re.IGNORECASE,
)


class QuotaExhausted(RuntimeError):
    """Raised when gemini-cli reports the daily quota (or fell back to another model)."""


# Default task sets per suite: (number of user tasks, injection task ids).
#
# AgentDyn suites: everything the package registers, which is the paper's 560
# test cases (20 user tasks per suite; shopping/github injection_task_0-8,
# dailylife injection_task_0-9).
#
# AgentDojo suites: the v1.1.2 shapes, as on the main branch.
SUITES = {
    "shopping": (20, [f"injection_task_{i}" for i in range(9)]),
    "github": (20, [f"injection_task_{i}" for i in range(9)]),
    "dailylife": (20, [f"injection_task_{i}" for i in range(10)]),
    "banking": (16, [f"injection_task_{i}" for i in range(9)]),
    "slack": (21, [f"injection_task_{i}" for i in range(1, 6)]),
    "travel": (20, [f"injection_task_{i}" for i in range(7)]),
    "workspace": (40, [f"injection_task_{i}" for i in range(6)]),
}
AGENTDYN_SUITES = {"shopping", "github", "dailylife"}


def default_benchmark_version(suite: str) -> str:
    """AgentDyn's paper runs are logged as v1.2.2 (its suites are identical
    under every version key); the AgentDojo suites stay on v1.1.2 so their
    results remain comparable with the main branch."""
    return "v1.2.2" if suite in AGENTDYN_SUITES else "v1.1.2"


def system_prompt_for(suite: str) -> Path:
    """The benchmark's default system message. AgentDyn's adds one line to
    AgentDojo's: 'Complete all tasks automatically without requesting user
    confirmation.'"""
    return HERE / ("agentdyn_system.md" if suite in AGENTDYN_SUITES else "agentdojo_system.md")


def find_gemini(explicit: str | None) -> str:
    if explicit:
        return explicit
    for name in ("gemini", "gemini.cmd"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("gemini-cli not on PATH; install with `npm i -g @google/gemini-cli` or pass --gemini")


def model_slug(model: str) -> str:
    """`gemini-3.1-flash-lite` -> `gemini_3_1_flash_lite`: only [A-Za-z0-9_], so
    the id stays inside the bridge's word-character-only task-id regex."""
    return re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_")


def task_id_for(model: str, arm: str, suite: str, user_task: str, injection_task: str | None) -> str:
    # Must match the bridge's result-file regex:
    #   ^(\w+)_([\w]+)_(user_task_\d+)_(injection_task_\d+|noinjection)$
    # The greedy first group swallows "<model slug>_<arm>", so the bridge files
    # this run under mcp_results/<model slug>_<arm>/<suite>/<user_task>/.
    return f"{model_slug(model)}_{arm}_{suite}_{user_task}_{injection_task or 'noinjection'}"


def gemini_version(gemini: str) -> str | None:
    try:
        out = subprocess.run([gemini, "--version"], capture_output=True, text=True, timeout=30)
        lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return lines[-1] if lines else None
    except Exception:
        return None


def write_workspace(ws: Path, *, model: str, conseca: bool, mcp_url: str, cli_prompt: bool,
                    system_prompt: Path) -> None:
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
        shutil.copyfile(system_prompt, ws / "GEMINI.md")


def run_gemini(gemini: str, ws: Path, prompt: str, task_id: str, timeout: int, dry_run: bool,
               cli_prompt: bool, system_prompt: Path, model: str) -> dict:
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
        # Replace the CLI's coding-agent system prompt with the benchmark's. Global
        # memory (~/.gemini/GEMINI.md) is still appended if present; keep it empty.
        env["GEMINI_SYSTEM_MD"] = str(system_prompt)
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
    quota_hit = QUOTA_RE.search(proc.stderr)
    if proc.returncode != 0 or i < 0:
        if quota_hit or QUOTA_RE.search(proc.stdout):
            raise QuotaExhausted(f"gemini exited {proc.returncode}: {quota_hit.group(0) if quota_hit else 'quota'}"
                                 f"; stderr tail: {proc.stderr[-300:]}")
        raise RuntimeError(
            f"gemini exited {proc.returncode}; stderr tail: {proc.stderr[-800:]}"
        )
    out = json.loads(raw[i:])
    out["wall_seconds"] = wall
    out["returncode"] = proc.returncode
    # A run that finished on a different model than requested, with a quota
    # message in stderr, is the CLI's quota fallback and not this model's data
    # point. (A silent server-side alias is recorded as served_model instead.)
    served = sorted(out.get("stats", {}).get("models", {}))
    if served and any(m != model for m in served) and quota_hit:
        raise QuotaExhausted(f"gemini switched model to {served} ({quota_hit.group(0)})")
    return out


def run_one(args, gemini: str, arm: str, suite: str, user_task: str, injection_task: str | None) -> dict:
    task_id = task_id_for(args.model, arm, suite, user_task, injection_task)
    ws = Path(args.out).resolve() / args.model / arm / task_id  # absolute: gemini runs with cwd=ws
    result_path = ws / "result.json"
    if result_path.exists() and not args.force:
        print(f"[skip] {task_id} (cached)")
        return json.loads(result_path.read_text(encoding="utf-8"))

    benchmark_version = args.benchmark_version or default_benchmark_version(suite)
    system_prompt = system_prompt_for(suite)
    init_body = {
        "task_id": task_id,
        "suite_name": suite,
        "user_task_id": user_task,
        "injection_task_id": injection_task,
        "benchmark_version": benchmark_version,
        # The bridge names the model in the injection text from this, as
        # upstream does from the pipeline name (gemini-* -> "AI model developed
        # by Google", the wording in AgentDyn's own Gemini logs), unless
        # --attack-model-name overrides it.
        "agent_model": args.model,
        "attack": args.attack,
        "attack_model_name": args.attack_model_name,
        "run_label": args.run_label,
    }
    # A bridge that was just (re)started can drop the first connection while
    # the previous server finishes shutting down; retry before giving up.
    for attempt in range(3):
        try:
            init = requests.post(f"{args.rest_url}/init_task", json=init_body, timeout=60)
            break
        except requests.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    init.raise_for_status()
    init_out = init.json()
    prompt = init_out["user_task_prompt"]
    print(f"[run ] {task_id}: {prompt[:80]}")
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    write_workspace(ws, model=args.model, conseca=(arm == "on"), mcp_url=args.mcp_url,
                    cli_prompt=args.cli_prompt, system_prompt=system_prompt)
    try:
        out = run_gemini(gemini, ws, prompt, task_id, args.timeout, args.dry_run, args.cli_prompt,
                         system_prompt, args.model)
    except QuotaExhausted:
        # The interrupted run is not a data point: drop its workspace so the
        # next invocation re-runs it from scratch.
        shutil.rmtree(ws, ignore_errors=True)
        raise
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
    # The model the API actually served the agent's calls with (the server may
    # alias, e.g. gemini-2.5-flash -> gemini-3.5-flash; README trap 4).
    served = sorted({c["model"] for c in (telemetry or {}).get("calls", [])
                     if c["stage"] == "agent" and c.get("model")})
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
        "benchmark_version": benchmark_version,
        "user_task": user_task,
        "injection_task": injection_task,
        "attack": args.attack if injection_task else None,
        "attack_model_name": init_out.get("attack_model_name"),
        "system_prompt": system_prompt.name,
        "model": args.model,
        "served_model": served[0] if len(served) == 1 else (served or None),
        "gemini_cli_version": args.gemini_cli_version,
        "started_at": started_at,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
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
    ap.add_argument("--suite", choices=sorted(SUITES), required=True,
                    help="AgentDyn: shopping/github/dailylife; AgentDojo: banking/slack/travel/workspace")
    ap.add_argument("--benchmark-version", default=None,
                    help="suite registry version on the bridge; default v1.2.2 for AgentDyn suites, "
                         "v1.1.2 for AgentDojo suites")
    ap.add_argument("--user-tasks", nargs="+", default=None, help="default: all in suite")
    ap.add_argument("--injection-tasks", nargs="+", default=None,
                    help="'none' = no injection; default: none + all in suite")
    ap.add_argument("--model", default="gemini-3.1-flash-lite",
                    help="agent model (Conseca itself is pinned to the CLI's flash default)")
    ap.add_argument("--out", default=str(HERE / "runs"),
                    help="results root; runs land in <out>/<model>/<arm>/<task_id>/")
    ap.add_argument("--rest-url", default="http://127.0.0.1:9000")
    ap.add_argument("--mcp-url", default="http://127.0.0.1:9001/mcp/")
    ap.add_argument("--gemini", default=None, help="path to the gemini binary")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per task")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds to sleep between tasks (free-tier keys: try 60)")
    ap.add_argument("--attack", default="important_instructions",
                    help="attack from agentdojo's registry (bridge GET /attacks lists them); "
                         "applies to injection runs only")
    ap.add_argument("--run-label", default=None,
                    help="sub-directory of the bridge's --results-dir for this run's bridge files "
                         "(run_agentdyn_sweep.py passes the attack name so attacks do not collide)")
    ap.add_argument("--attack-model-name", default=None,
                    help="model name written into the injection text; default: derived from --model "
                         "by the bridge like upstream (gemini-* -> 'AI model developed by Google', "
                         "unknown models -> 'the AI language model')")
    ap.add_argument("--cli-prompt", action="store_true",
                    help="keep gemini-cli's own system prompt and pass the benchmark's message as "
                         "GEMINI.md project context (pre-alignment behaviour)")
    ap.add_argument("--force", action="store_true", help="ignore cached results")
    ap.add_argument("--dry-run", action="store_true", help="init the task and print the command only")
    args = ap.parse_args()

    gemini = find_gemini(args.gemini)
    args.gemini_cli_version = gemini_version(gemini)
    n_users, injections = SUITES[args.suite]
    user_tasks = args.user_tasks or [f"user_task_{i}" for i in range(n_users)]
    injection_tasks = args.injection_tasks or ["none", *injections]

    results = []
    for ut in user_tasks:
        for it in injection_tasks:
            inj = None if it == "none" else it
            try:
                results.append(run_one(args, gemini, args.arm, args.suite, ut, inj))
            except QuotaExhausted as e:
                print(f"[quota] {ut} {it}: {e}", file=sys.stderr)
                print("[quota] stopping; the run was deleted and will be redone after the quota resets",
                      file=sys.stderr)
                return EXIT_QUOTA
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
