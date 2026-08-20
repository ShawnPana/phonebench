#!/usr/bin/env python3
"""Run L1 tasks: spec -> setup -> sealed agent -> check -> cleanup -> record.

    python3 run_l1.py --track real-ios --tasks alarm-0730,contact-carol,headline-web
    python3 run_l1.py --track real-android --tasks alarm-0730 --model claude-sonnet-5

The agent under test is a fresh `claude -p` per task: it sees ONLY the task
prompt and the phone-harness skill text, its Bash is restricted to
phone-harness invocations, and it runs from an empty scratch cwd so it cannot
read this repo (no checkers, no specs). Checks never trust the agent's own
claim: state checkers re-read the phone; answer checks match the final
answer against a known string.
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from tracks import resolve as resolve_track
from checkers.registry import resolve as resolve_checker
from agents.adapters import ADAPTERS

AGENT_BUFFER_S = 90          # process grace beyond the task's own timeout
FAILURE_SIGNS = [            # transcript signatures -> tool-vs-model tags
    ("locked", "device-locked"), ("iPhone in Use", "mirroring-paused"),
    ("paste", "paste-sheet"), ("tap_text", "tap-miss"),
    ("Traceback", "helper-exception"),
]


def ph(code, env, timeout=180):
    """Run a phone-harness snippet; return (parsed ::PB:: dict, raw output)."""
    p = subprocess.run(["phone-harness"], input=code, text=True,
                       capture_output=True, timeout=timeout,
                       env={**os.environ, **env})
    out = p.stdout + p.stderr
    line = next((l for l in out.splitlines() if l.startswith("::PB::")), None)
    return (json.loads(line[6:]) if line else {"ok": False, "error": "no ::PB:: line"}), out


def run_agent(prompt, skill_text, env, model, max_turns, timeout_s, cwd):
    cmd = ["claude", "-p", prompt,
           "--append-system-prompt", skill_text,
           "--allowedTools", "Bash(phone-harness*)",
           "--max-turns", str(max_turns), "--model", model,
           "--output-format", "json"]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s + AGENT_BUFFER_S,
                           cwd=cwd, env={**os.environ, **env})
        try:
            data = json.loads(p.stdout)
        except json.JSONDecodeError:
            data = {"result": p.stdout, "parse_error": True}
        data["stderr_tail"] = p.stderr.strip()[-400:]
    except subprocess.TimeoutExpired as e:
        data = {"result": "", "timeout": True,
                "partial": (e.stdout or b"")[-400:].decode(errors="replace")
                if isinstance(e.stdout, bytes) else str(e.stdout or "")[-400:]}
    data["agent_wall_s"] = round(time.time() - t0, 1)
    return data


def final_screenshot(env, dest):
    try:
        r, _ = ph("p = screenshot()\nimport json\n"
                  "print('::PB::' + json.dumps({'ok': True, 'path': p}))", env)
        if r.get("path"):
            shutil.copy(r["path"], dest)
            return True
    except Exception:
        pass
    return False


def classify(agent_data):
    blob = json.dumps(agent_data)[:20000]
    for sign, tag in FAILURE_SIGNS:
        if sign in blob:
            return tag
    if agent_data.get("timeout"):
        return "timeout"
    return "unclassified"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--tasks", required=True, help="comma-separated task ids")
    ap.add_argument("--serial")
    ap.add_argument("--model", default=None, help="agent-native model id; default = the agent's own default")
    ap.add_argument("--agent", default="claude", choices=list(ADAPTERS))
    args = ap.parse_args()

    track = resolve_track(args.track, serial=args.serial)
    env, platform = track["env"], track["platform"]
    skill_text = subprocess.run(["phone-harness", "skill"], capture_output=True,
                                text=True).stdout

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = HERE / "results" / f"{stamp}-l1-{args.track}"
    run_dir.mkdir(parents=True)
    agent_cwd = run_dir / "agent-cwd"
    agent_cwd.mkdir()
    rows_path = run_dir / "results.jsonl"

    # preflight: the device must be ready before anything runs
    state, _ = ph("import json\nprint('::PB::' + json.dumps("
                  "{'ok': connection_state() == 'ready', 's': connection_state()}))", env)
    if not state.get("ok"):
        print(f"device not ready ({state.get('s')}) — connect the phone and rerun")
        return 1

    for task_id in args.tasks.split(","):
        spec = yaml.safe_load((HERE / "tasks" / f"{task_id}.yaml").read_text())
        row = {"task": task_id, "track": args.track, "agent": args.agent,
               "model": args.model, "started": time.strftime("%F %T")}
        print(f"\n=== {task_id} [{args.track}] ===")

        # setup
        r, raw = ph(resolve_checker(spec["setup"], platform, spec.get("setup_args")), env)
        (run_dir / f"{task_id}-setup.log").write_text(raw)
        if r.get("skip"):
            row.update(status="skipped", reason=r.get("reason"))
            print(f"  SKIPPED: {r.get('reason')}")
            with open(rows_path, "a") as f: f.write(json.dumps(row) + "\n")
            continue
        if not r.get("ok"):
            row.update(status="setup-failed", detail=r)
            print(f"  setup FAILED: {r}")
            with open(rows_path, "a") as f: f.write(json.dumps(row) + "\n")
            continue

        # sealed agent
        print(f"  {args.agent} running ({args.model or 'default model'}, "
              f"{spec['timeout_s']}s cap) ...", flush=True)
        agent = ADAPTERS[args.agent](spec["prompt"].strip(), skill_text, env,
                                     args.model, spec["timeout_s"], str(agent_cwd))
        (run_dir / f"{task_id}-{args.agent}-agent.json").write_text(json.dumps(agent, indent=2))

        # check — never trusts the agent
        if spec["check"] == "answer.contains":
            want = spec["check_args"]["substring"].lower()
            passed = want in str(agent.get("result", "")).lower()
            check_detail = {"answer_excerpt": str(agent.get("result", ""))[:300]}
        else:
            c, raw = ph(resolve_checker(spec["check"], platform, spec.get("check_args")), env)
            (run_dir / f"{task_id}-check.log").write_text(raw)
            passed, check_detail = bool(c.get("ok")), c

        final_screenshot(env, run_dir / f"{task_id}-{args.agent}-final.png")

        # cleanup — always
        cl, raw = ph(resolve_checker(spec["cleanup"], platform, spec.get("cleanup_args")), env)
        (run_dir / f"{task_id}-cleanup.log").write_text(raw)

        row.update(status="pass" if passed else "fail",
                   check=check_detail, cleanup_ok=bool(cl.get("ok")),
                   agent_wall_s=agent.get("agent_wall_s"),
                   turns=agent.get("turns"),
                   cost_usd=agent.get("cost_usd"),
                   usage=agent.get("usage", {}),
                   failure_class=None if passed else classify(agent))
        print(f"  {'PASS' if passed else 'FAIL'}  wall={row['agent_wall_s']}s "
              f"turns={row['turns']} cost=${row['cost_usd']}"
              + ("" if passed else f"  [{row['failure_class']}]"))
        with open(rows_path, "a") as f: f.write(json.dumps(row) + "\n")

    print(f"\nresults -> {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
