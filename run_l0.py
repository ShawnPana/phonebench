#!/usr/bin/env python3
"""Run the L0 primitive probes on one device and write a result file.

    python3 run_l0.py --track real-android
    python3 run_l0.py --track real-ios
    python3 run_l0.py --track emulate --serial emulator-5554
    python3 run_l0.py --track real-android --probe tap    # one probe

Each probe runs as its own `phone-harness` process — exactly the surface an
agent uses — and reports one `::PB::{json}` line. Results land in
results/<stamp>-l0-<track>.jsonl and a summary table prints at the end.
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tracks import resolve
from primitives.probes import PROBES

TIMEOUT_S = 240


def run_probe(name, code, platform, env):
    script = f'PLATFORM = "{platform}"\n' + code
    t0 = time.time()
    try:
        p = subprocess.run(["phone-harness"], input=script, text=True,
                           capture_output=True, timeout=TIMEOUT_S,
                           env={**os.environ, **env})
        out = p.stdout + p.stderr
        line = next((l for l in out.splitlines() if l.startswith("::PB::")), None)
        result = json.loads(line[6:]) if line else {
            "ok": False, "error": "no ::PB:: line", "tail": out.strip()[-400:]}
        if p.returncode != 0 and "error" not in result:
            result.setdefault("stderr_tail", p.stderr.strip()[-200:])
    except subprocess.TimeoutExpired:
        result = {"ok": False, "error": f"timeout after {TIMEOUT_S}s"}
    result.update(probe=name, wall_ms=round((time.time() - t0) * 1000))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--serial", help="ANDROID_SERIAL for emulate track")
    ap.add_argument("--probe", help="run a single probe by name")
    args = ap.parse_args()

    track = resolve(args.track, serial=args.serial)
    names = [args.probe] if args.probe else list(PROBES)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = Path(__file__).parent / "results" / f"{stamp}-l0-{args.track}.jsonl"
    out_path.parent.mkdir(exist_ok=True)

    results = []
    for name in names:
        print(f"[{args.track}] {name} ...", flush=True)
        r = run_probe(name, PROBES[name], track["platform"], track["env"])
        r["track"] = args.track
        results.append(r)
        with open(out_path, "a") as f:
            f.write(json.dumps(r) + "\n")
        print(f"  {'ok' if r.get('ok') else 'FAIL'}  {r}", flush=True)
        if name == "session" and not r.get("ok"):
            print("device not ready — stopping (connect the phone and rerun)")
            break

    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n{ok}/{len(results)} probes ok -> {out_path}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
