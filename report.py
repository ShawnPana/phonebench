#!/usr/bin/env python3
"""Fold every results/*.jsonl into the leaderboard.

    python3 report.py                 # print tables
    python3 report.py --md out.md     # also write markdown

Latest row wins per (track, agent, model, task): reruns supersede. Rows with
status unsupported-on-track are excluded from the denominator — a track that
cannot host a task neither passes nor fails it.
"""
import argparse, collections, glob, json, sys
from pathlib import Path

import yaml
import sys as _sys; _sys.path.insert(0, str(Path(__file__).parent))
from taskload import load_all

HERE = Path(__file__).parent


def load():
    rows = {}
    for f in sorted(glob.glob(str(HERE / "results" / "*" / "results.jsonl"))):
        for line in open(f):
            r = json.loads(line)
            key = (r.get("track"), r.get("agent"), r.get("model"), r["task"])
            rows[key] = r                      # later files supersede
    return list(rows.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md")
    args = ap.parse_args()

    strata = {t["id"]: t["stratum"] for t in load_all()}
    rows = load()

    cells = collections.defaultdict(list)
    for r in rows:
        if r["status"] == "unsupported-on-track":
            continue
        cells[(r["track"], r.get("agent") or "claude", r.get("model") or "default")].append(r)

    lines = ["| track | agent | model | pass | rate | $/task | s/task |",
             "|---|---|---|---|---|---|---|"]
    for (track, agent, model), rs in sorted(cells.items()):
        scored = [r for r in rs if r["status"] in ("pass", "fail", "disqualified")]
        p = sum(1 for r in scored if r["status"] == "pass")
        costs = [r["cost_usd"] for r in scored if r.get("cost_usd")]
        walls = [r["agent_wall_s"] for r in scored if r.get("agent_wall_s")]
        lines.append(
            f"| {track} | {agent} | {model} | {p}/{len(scored)} "
            f"| {p/len(scored)*100:.0f}% "
            f"| {'$%.2f' % (sum(costs)/len(costs)) if costs else '—'} "
            f"| {sum(walls)/len(walls):.0f} |" if scored else
            f"| {track} | {agent} | {model} | 0/0 | — | — | — |")

    stratum_lines = ["", "| agent | " + " | ".join(sorted(set(strata.values()))) + " |",
                     "|---|" + "---|" * len(set(strata.values()))]
    for (track, agent, model), rs in sorted(cells.items()):
        by = collections.defaultdict(lambda: [0, 0])
        for r in rs:
            if r["status"] in ("pass", "fail", "disqualified"):
                st = strata.get(r["task"], "?")
                by[st][1] += 1
                by[st][0] += r["status"] == "pass"
        stratum_lines.append(
            f"| {agent} ({model}) | " + " | ".join(
                f"{by[s][0]}/{by[s][1]}" if by[s][1] else "—"
                for s in sorted(set(strata.values()))) + " |")

    out = "\n".join(["# phonebench leaderboard", "",
                     *lines, "", "## By stratum", *stratum_lines])
    print(out)
    if args.md:
        Path(args.md).write_text(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
