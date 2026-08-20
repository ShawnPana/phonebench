#!/usr/bin/env python3
"""Fetch the pinned phone-harness into .harness/ and write harness.lock.

    python3 setup_harness.py            # clone/fetch harness.yaml's ref
    python3 setup_harness.py --locked   # check out exactly harness.lock's SHA

The checkout's own dev launcher (./phone-harness) runs the working tree, so
callers just prepend .harness/ to PATH. Every results row records the locked
SHA: a leaderboard entry is (agent x model x task-suite SHA x harness SHA).
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

import yaml

HERE = Path(__file__).parent
DEST = HERE / ".harness"
LOCK = HERE / "harness.lock"


def sh(*args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          **kw).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--locked", action="store_true",
                    help="use harness.lock's SHA instead of resolving the ref")
    args = ap.parse_args()

    cfg = yaml.safe_load((HERE / "harness.yaml").read_text())
    repo, ref = cfg["repo"], str(cfg["ref"])
    if args.locked:
        ref = json.loads(LOCK.read_text())["sha"]

    if not (DEST / ".git").exists():
        sh("git", "clone", "--quiet", repo, str(DEST))
    sh("git", "-C", str(DEST), "fetch", "--quiet", "origin")
    sh("git", "-C", str(DEST), "checkout", "--quiet", ref)
    # a branch ref should track its remote tip
    try:
        sh("git", "-C", str(DEST), "reset", "--quiet", "--hard",
           f"origin/{ref}")
    except subprocess.CalledProcessError:
        pass                                   # tag or SHA: already exact
    sha = sh("git", "-C", str(DEST), "rev-parse", "HEAD")

    LOCK.write_text(json.dumps(
        {"repo": repo, "ref": ref, "sha": sha,
         "resolved": time.strftime("%F %T")}, indent=2) + "\n")
    print(f"phone-harness @ {ref} -> {sha[:12]}  ({DEST})")
    print(f'PATH hint: export PATH="{DEST}:$PATH"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
