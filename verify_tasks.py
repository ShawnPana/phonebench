#!/usr/bin/env python3
"""Verified-achievable pass: prove every checker can say both no and yes.

For each task on a track:  setup -> check (expect FAIL: nothing happened yet)
-> satisfy (privileged side door does what the agent would) -> check (expect
PASS) -> cleanup. A task with no satisfy hook gets its true-fail half only
and is flagged: its true-pass must come from a reference agent run.

    python3 verify_tasks.py --track sim [--tasks id,id]
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from tracks import resolve as resolve_track
from checkers.registry import resolve as resolve_checker
from judge import judge as judge_answer, compute_ground_truth

# Privileged "do the task" hooks — sim side doors. Each is a phone-harness
# snippet (helpers preloaded) or a plain shell list run on the host.
SIM = os.path.expanduser("~/Library/Developer/CoreSimulator/Devices")


def _data():
    out = subprocess.run(["xcrun", "simctl", "list", "devices", "booted"],
                         capture_output=True, text=True).stdout
    import re
    m = re.search(r"\(([0-9A-Fa-f-]{36})\).*\(Booted\)", out)
    return f"{SIM}/{m.group(1)}/data" if m else None


def _sql(db, *stmts):
    import sqlite3
    conn = sqlite3.connect(db)
    for st in stmts:
        for _ in range(24):
            try:
                conn.execute(*st) if isinstance(st, tuple) else conn.execute(st)
                break
            except sqlite3.OperationalError as e:
                m = str(e)
                if not re.search(r"(no such|unknown) function", m):
                    raise
                fn = re.split(r"(?:no such|unknown) function:?", m)[1].strip().strip("()")
                import uuid as _u
                conn.create_function(fn, -1,
                    (lambda *a: _u.uuid4().hex.upper()) if "guid" in fn.lower()
                    else (lambda *a: None))
    conn.commit()
    conn.close()


def satisfy(task_id):
    """Return True if we could programmatically satisfy the task."""
    d = _data()
    def pbtool(*a):
        return subprocess.run(["xcrun", "simctl", "launch", "--console",
                               "booted", "com.phonebench.tools", *a],
                              capture_output=True, text=True).stdout
    if task_id in ("contact-carol",):
        pbtool("add", "Carol", "Phonebench", "555-0142")
        return True
    if task_id == "contact-edit":
        pbtool("remove", "Carol", "Phonebench")
        pbtool("add", "Carol", "Phonebench", "555-0199")
        return True
    if task_id == "contact-delete":
        pbtool("remove", "Carol", "Phonebench")
        return True
    if False and task_id in ("contact-carol",):
        _sql(d + "/Library/AddressBook/AddressBook.sqlitedb",
             ("INSERT INTO ABPerson (First, Last) VALUES ('Carol','Phonebench')",),
             ("INSERT INTO ABMultiValue (record_id, property, label, value) "
              "SELECT max(ROWID), 3, 1, '555-0142' FROM ABPerson",))
        return True
    if task_id == "contact-edit":
        _sql(d + "/Library/AddressBook/AddressBook.sqlitedb",
             ("UPDATE ABMultiValue SET value='555-0199' WHERE record_id IN "
              "(SELECT ROWID FROM ABPerson WHERE First='Carol')",))
        return True
    if task_id == "contact-delete":
        _sql(d + "/Library/AddressBook/AddressBook.sqlitedb",
             ("DELETE FROM ABMultiValue WHERE record_id IN "
              "(SELECT ROWID FROM ABPerson WHERE First='Carol')",),
             ("DELETE FROM ABPerson WHERE First='Carol'",))
        return True
    if task_id in ("calendar-event", "web-to-calendar"):
        title = {"calendar-event": "pb-standup",
                 "web-to-calendar": "Let your agent"}[task_id]
        _sql(d + "/Library/Calendar/Calendar.sqlitedb",
             (f"INSERT INTO CalendarItem (summary) VALUES ('{title}')",))
        return True
    if task_id == "photo-favorite":
        _sql(d + "/Media/PhotoData/Photos.sqlite",
             ("UPDATE ZASSET SET ZFAVORITE=1 WHERE Z_PK IN (SELECT Z_PK FROM "
              "ZASSET WHERE ZTRASHEDSTATE=0 ORDER BY ZDATECREATED DESC LIMIT 1)",))
        return True
    if task_id == "safari-bookmark":
        _sql(d + "/Library/Safari/Bookmarks.db",
             ("INSERT INTO bookmarks (special_id, parent, type, title, url, "
              "editable, deletable, hidden, order_index) VALUES "
              "(0, 1, 0, 'phone-harness', 'https://phone-harness.com/', 1, 1, 0, 999)",))
        return True
    if task_id == "appearance-dark":
        subprocess.run(["xcrun", "simctl", "ui", "booted", "appearance", "dark"],
                       capture_output=True)
        return True
    if task_id == "appearance-light":
        subprocess.run(["xcrun", "simctl", "ui", "booted", "appearance", "light"],
                       capture_output=True)
        return True
    if task_id == "app-switcher":
        subprocess.run(["xcrun", "simctl", "openurl", "booted",
                        "https://phone-harness.com"], capture_output=True)
        time.sleep(6)
        return True
    return False        # no side door: true-pass comes from a reference run


ANSWERS = {   # correct answers a competent agent would give, for judge tasks
    "headline-web": "The headline is: Let your agent control your phone.",
    "settings-version": None,       # filled from computed ground truth
    "contact-lookup": "Carol Phonebench's number is 555-0142.",
    "photos-count": None,
    "maps-place": "The Golden Gate Bridge is in San Francisco.",
    "list-scroll-count": None,
}


def ph(code, env, timeout=240):
    p = subprocess.run(["phone-harness"], input=code, text=True,
                       capture_output=True, timeout=timeout,
                       env={**os.environ, **env})
    out = p.stdout + p.stderr
    line = next((l for l in out.splitlines() if l.startswith("::PB::")), None)
    return (json.loads(line[6:]) if line else
            {"ok": False, "error": out.strip()[-300:]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", default="sim")
    ap.add_argument("--tasks")
    args = ap.parse_args()

    harness = HERE / ".harness"
    os.environ["PATH"] = f"{harness}:{os.environ['PATH']}"
    track = resolve_track(args.track)
    env, cplat = track["env"], track.get("checker_platform", track["platform"])

    ids = (args.tasks.split(",") if args.tasks else
           sorted(p.stem for p in (HERE / "tasks").glob("*.yaml")))
    results = []
    for tid in ids:
        spec = yaml.safe_load((HERE / "tasks" / f"{tid}.yaml").read_text())
        if args.track not in spec["platforms"] and cplat not in spec["platforms"]:
            results.append((tid, "off-track", ""))
            continue
        r = {"id": tid}
        try:
            s = ph(resolve_checker(spec["setup"], cplat, spec.get("setup_args")), env) \
                if spec["setup"] != "none" else {"ok": True}
            if not s.get("ok"):
                results.append((tid, "SETUP-BROKEN", str(s)[:90]))
                continue

            def run_check():
                if spec["check"] == "answer.judge":
                    gt = spec.get("ground_truth") or ""
                    if gt.startswith("COMPUTED"):
                        gt = compute_ground_truth(tid, cplat) or gt
                    good = ANSWERS.get(tid) or gt
                    bad = "I could not complete the task."
                    return (judge_answer(spec["prompt"], bad, gt)["verdict"],
                            judge_answer(spec["prompt"], good, gt)["verdict"])
                c1 = ph(resolve_checker(spec["check"], cplat, spec.get("check_args")), env)
                did = satisfy(tid)
                c2 = (ph(resolve_checker(spec["check"], cplat, spec.get("check_args")), env)
                      if did else None)
                return bool(c1.get("ok")), (bool(c2.get("ok")) if did else None)

            neg, pos = run_check()
            true_fail = (neg is False)
            true_pass = pos if pos is not None else "needs-reference-run"
            verdict = ("VERIFIED" if true_fail and true_pass is True else
                       "HALF (fail-only)" if true_fail and true_pass == "needs-reference-run" else
                       "BROKEN")
            results.append((tid, verdict,
                            f"neg={neg} pos={pos}"))
        except Exception as e:
            results.append((tid, "ERROR", str(e)[:90]))
        finally:
            try:
                if spec["cleanup"] != "none":
                    ph(resolve_checker(spec["cleanup"], cplat, spec.get("cleanup_args")), env)
            except Exception:
                pass

    print(f"\n{'task':24} {'verdict':18} detail")
    for tid, v, d in results:
        print(f"{tid:24} {v:18} {d}")
    ok = sum(1 for _, v, _ in results if v == "VERIFIED")
    print(f"\n{ok}/{len(results)} fully verified")


if __name__ == "__main__":
    main()
