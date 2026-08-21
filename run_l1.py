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
from taskload import load_task
from judge import judge as judge_answer, compute_ground_truth

AGENT_BUFFER_S = 90          # process grace beyond the task's own timeout
ESCAPE_PAT = re.compile(
    r"simctl\s+(ui|launch|openurl|spawn|boot|shutdown|erase|addmedia|privacy|terminate)"
    r"|sqlite3?[^\n]{0,80}(AddressBook|Calendar\.sqlitedb|Photos\.sqlite|Bookmarks\.db|CoreSimulator)"
    r"|defaults\s+write", re.I)

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


def _wait_sim_ready(env, timeout_s=360):
    """Fixed sleeps lied to us: a first boot after erase can take minutes and
    checkers poking a booting sim fail as 'setup-broken'. Ready means the
    home screen is OCR-visible through the same eyes everything else uses."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r, _ = ph("import json\nprint('::PB::' + json.dumps("
                      "{'ok': True, 'n': len(ocr())}))", env, timeout=60)
            if r.get("n", 0) > 6:
                return True
        except Exception:
            pass          # a hanging probe against a booting sim is NORMAL
        time.sleep(10)
    return False


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
    ap.add_argument("--fresh", default="none",
                    choices=["none", "apps", "clone", "erase"],
                    help="between tasks: none | terminate suite apps | boot a "
                         "fresh CLONE of a first-booted template (~30-60s, "
                         "recommended for CI) | full erase+reboot (slowest)")
    args = ap.parse_args()

    harness_dir = HERE / ".harness"
    harness_sha = None
    if harness_dir.exists():
        os.environ["PATH"] = f"{harness_dir}:{os.environ['PATH']}"
        # Agent CLIs may run LOGIN shells that rebuild PATH from dotfiles and
        # bury our prepend; the ~/.local/bin shim (first in login PATH)
        # delegates to this env var, which login shells DO inherit.
        os.environ["PHONEBENCH_HARNESS"] = str(harness_dir)
        lock = HERE / "harness.lock"
        if lock.exists():
            harness_sha = json.loads(lock.read_text()).get("sha")

    track = resolve_track(args.track, serial=args.serial)
    env, platform = track["env"], track["platform"]
    platform = track.get("checker_platform", platform)
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

    # app availability: ask the environment which apps exist (sim is exact;
    # other tracks run optimistically and fail honestly at task time)
    daemon_proc = [None]

    def restart_daemon():
        """One warm process per device: imports and backend held resident.
        Restarted on every clone swap — the socket path is device-derived,
        so a stale daemon simply never gets connected to."""
        if daemon_proc[0]:
            daemon_proc[0].kill()
        daemon_proc[0] = subprocess.Popen(
            ["phone-harness", "--serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, **{k: v for k, v in env.items()
                                  if k != "PHONE_HARNESS_DAEMON"}})
        env["PHONE_HARNESS_DAEMON"] = "1"
        os.environ["PHONE_HARNESS_DAEMON"] = "1"

    # ---- self-calibration: this machine's harness-op cost vs the reference.
    # A GitHub runner is ~4x slower per op than the M-series the timeouts were
    # written on; scale every budget by MEASURED speed, never a guess.
    REFERENCE_OP_S = 2.0
    speed_mult = 1.0

    def calibrate():
        nonlocal speed_mult
        t0 = time.time()
        n = 0
        for _ in range(2):
            try:
                ph("import json\nprint('::PB::' + json.dumps({'ok': True, "
                   "'n': len(ocr())}))", env, timeout=90)
                n += 1
            except Exception:
                pass
        if n:
            op_s = (time.time() - t0) / n
            floor = 2.0 if os.environ.get("GITHUB_ACTIONS") else 1.0
            # op cost is only part of CI slowness: agents also take more
            # turns there, so CI keeps a 2x floor even with fast ops
            speed_mult = min(4.0, max(floor, op_s / REFERENCE_OP_S))
            print(f"harness op: {op_s:.1f}s -> time budgets x{speed_mult:.1f}")

    available = None
    if platform == "sim":
        subprocess.run(["bash", str(HERE / "tools" / "ensure_pbtools.sh")],
                       capture_output=True)
        restart_daemon()
        time.sleep(3)
        calibrate()          # measured HOT: budgets reflect real op cost
        apps = subprocess.run(["xcrun", "simctl", "listapps", "booted"],
                              capture_output=True, text=True).stdout
        available = set(re.findall(r'CFBundleDisplayName = "?([^";]+)"?;', apps))
        print(f"apps on device: {len(available)}")

    template_udid = None
    if args.fresh == "clone" and platform == "sim":
        # Bake the template ONCE: the currently booted device, with PBTools
        # installed and granted, first boot already paid. Every task then
        # boots a byte-identical clone WARM instead of re-first-booting.
        out = subprocess.run(["xcrun", "simctl", "list", "devices", "booted"],
                             capture_output=True, text=True).stdout
        m = re.search(r"\(([0-9A-Fa-f-]{36})\).*\(Booted\)", out)
        if not m:
            print("--fresh clone needs a booted template device")
            return 1
        template_udid = m.group(1)
        subprocess.run(["bash", str(HERE / "tools" / "ensure_pbtools.sh")],
                       capture_output=True)
        subprocess.run(["xcrun", "simctl", "shutdown", template_udid],
                       capture_output=True)

    def freshen():
        if args.fresh == "none" or platform != "sim":
            return
        if args.fresh == "clone":
            # retire the previous clone, mint and boot a new one
            out = subprocess.run(["xcrun", "simctl", "list", "devices"],
                                 capture_output=True, text=True).stdout
            for mm in re.finditer(r"pb-clone \(([0-9A-Fa-f-]{36})\)", out):
                subprocess.run(["xcrun", "simctl", "shutdown", mm.group(1)],
                               capture_output=True)
                subprocess.run(["xcrun", "simctl", "delete", mm.group(1)],
                               capture_output=True)
            subprocess.run(["xcrun", "simctl", "clone", template_udid, "pb-clone"],
                           capture_output=True)
            subprocess.run(["xcrun", "simctl", "boot", "pb-clone"],
                           capture_output=True)
            subprocess.run(["open", "-a", "Simulator"], capture_output=True)
            os.environ["PHONE_HARNESS_SIM_DEVICE"] = "pb-clone"
            env["PHONE_HARNESS_SIM_DEVICE"] = "pb-clone"
            restart_daemon()
            if not _wait_sim_ready(env, timeout_s=240):
                # one retry with a brand-new clone before giving up loudly
                subprocess.run(["xcrun", "simctl", "shutdown", "pb-clone"], capture_output=True)
                subprocess.run(["xcrun", "simctl", "delete", "pb-clone"], capture_output=True)
                subprocess.run(["xcrun", "simctl", "clone", template_udid, "pb-clone"], capture_output=True)
                subprocess.run(["xcrun", "simctl", "boot", "pb-clone"], capture_output=True)
                if not _wait_sim_ready(env, timeout_s=240):
                    raise SystemExit("clone never became ready twice — aborting "
                                     "shard instead of failing every task confusingly")
            return
        if args.fresh == "erase":
            # "booted" is NOT a stable target: after shutdown nothing is
            # booted, so erase/boot silently no-op and the sim stays dead
            # (this killed an entire CI sweep). Resolve the concrete UDID.
            out = subprocess.run(["xcrun", "simctl", "list", "devices", "booted"],
                                 capture_output=True, text=True).stdout
            m = re.search(r"\(([0-9A-Fa-f-]{36})\).*\(Booted\)", out)
            dev = m.group(1) if m else os.environ.get("PHONE_HARNESS_SIM_DEVICE", "booted")
            subprocess.run(["xcrun", "simctl", "shutdown", dev], capture_output=True)
            subprocess.run(["xcrun", "simctl", "erase", dev], capture_output=True)
            subprocess.run(["xcrun", "simctl", "boot", dev], capture_output=True)
            subprocess.run(["open", "-a", "Simulator"], capture_output=True)
            _wait_sim_ready(env)                 # first boot after erase is SLOW
            subprocess.run(["bash", str(HERE / "tools" / "ensure_pbtools.sh")],
                           capture_output=True)
            return
        # apps: kill every app the suite touches — lingering search fields,
        # nav stacks and keyboards die with them
        apps_txt = subprocess.run(["xcrun", "simctl", "listapps", "booted"],
                                  capture_output=True, text=True).stdout
        import re as _re
        pairs = dict(zip(_re.findall(r'CFBundleIdentifier = "?([^";]+)"?;', apps_txt),
                         _re.findall(r'CFBundleDisplayName = "?([^";]+)"?;', apps_txt)))
        suite_apps = set()
        from taskload import load_all
        for _t in load_all():
            suite_apps.update(_t.get("requires_apps") or [])
        for bid, name in pairs.items():
            if name in suite_apps:
                subprocess.run(["xcrun", "simctl", "terminate", "booted", bid],
                               capture_output=True)

    for task_id in args.tasks.split(","):
      try:
          freshen()
          spec = load_task(task_id)
          row = {"task": task_id, "track": args.track, "agent": args.agent,
                 "model": args.model, "harness_sha": harness_sha,
                 "started": time.strftime("%F %T")}
          print(f"\n=== {task_id} [{args.track}] ===")

          needs = spec.get("requires_apps") or []
          if available is not None and not set(needs) <= available:
              missing = sorted(set(needs) - available)
              row.update(status="unsupported-on-track", missing_apps=missing)
              print(f"  UNSUPPORTED here: needs {missing}")
              with open(rows_path, "a") as f: f.write(json.dumps(row) + "\n")
              continue

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
          trace_dir = run_dir / f"{task_id}-{args.agent}-trace"
          agent_env = {**env, "PHONE_HARNESS_TRACE": str(trace_dir)}
          budget_s = int(spec["timeout_s"] * speed_mult)
          agent_env["PHONEBENCH_SPEED_MULT"] = str(round(speed_mult, 2))
          agent = ADAPTERS[args.agent](spec["prompt"].strip(), skill_text, agent_env,
                                       args.model, budget_s, str(agent_cwd))
          row["speed_mult"] = round(speed_mult, 2)
          row["budget_s"] = budget_s
          (run_dir / f"{task_id}-{args.agent}-agent.json").write_text(json.dumps(agent, indent=2))

          # integrity: an agent that manipulated the device outside
          # phone-harness is disqualified no matter what the checker says
          escaped = bool(ESCAPE_PAT.search(json.dumps(agent.get("raw", {}))))

          # check — never trusts the agent
          if spec["check"] == "answer.judge":
              gt = spec.get("ground_truth") or ""
              if gt.startswith("COMPUTED"):
                  gt = compute_ground_truth(task_id, platform) or gt
              verdict = judge_answer(spec["prompt"], agent.get("result"), gt)
              passed = verdict["verdict"]
              check_detail = {**verdict, "ground_truth": gt,
                              "answer_excerpt": str(agent.get("result", ""))[:300]}
          elif spec["check"] == "answer.contains":
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

          if escaped:
              passed = False
          row.update(status="disqualified" if escaped else
                     ("pass" if passed else "fail"),
                     env_escape=escaped,
                     check=check_detail, cleanup_ok=bool(cl.get("ok")),
                     agent_wall_s=agent.get("agent_wall_s"),
                     turns=agent.get("turns"),
                     cost_usd=agent.get("cost_usd"),
                     usage=agent.get("usage", {}),
                     failure_class="env-escape" if escaped else
                                   (None if passed else classify(agent)))
          print(f"  {'PASS' if passed else 'FAIL'}  wall={row['agent_wall_s']}s "
                f"turns={row['turns']} cost=${row['cost_usd']}"
                + ("" if passed else f"  [{row['failure_class']}]"))
          with open(rows_path, "a") as f: f.write(json.dumps(row) + "\n")

      except Exception as e:
          # a single task's infra crash must never kill the shard:
          # record it as an infra-error row and move on (shard-1 lost
          # 3 of 4 tasks to one silent crash)
          import traceback; traceback.print_exc()
          with open(rows_path, "a") as f:
              f.write(json.dumps({"task": task_id, "track": args.track,
                  "agent": args.agent, "status": "infra-error",
                  "error": str(e)[:300]}) + "\n")
          print(f"  INFRA-ERROR: {str(e)[:120]}")
    print(f"\nresults -> {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
