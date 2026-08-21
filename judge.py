"""Answer judging for retrieval tasks — the browser-use shape, not iOSWorld's.

One universal prompt; the per-task ground truth is the authority (the judge
only does semantic matching against it, never free-form rubric grading).
Deterministic state checkers always override this module — it exists solely
for tasks whose deliverable is an ANSWER, where substring matching is too
brittle ("78 degrees" vs "78°F").

Neutrality: the judge model must be a third party to the agents being ranked
(Claude vs Codex ⇒ judge with Gemini). Set GEMINI_API_KEY to activate;
without it, judging falls back to normalized substring matching against the
ground truth and says so in the verdict. The judge model id is pinned per
run and recorded in every verdict.
"""
import json
import os
import re
import subprocess
import urllib.request

JUDGE_MODEL = os.environ.get("PHONEBENCH_JUDGE_MODEL", "gemini-2.5-flash")

PROMPT = """You are judging whether a phone-automation agent answered a task correctly.

<task>{task}</task>
<agent_answer>{answer}</agent_answer>
<ground_truth>{ground_truth}</ground_truth>

The ground truth is verified correct information and takes ABSOLUTE precedence.
Judge ONLY whether the agent's answer satisfies the ground truth — accept
equivalent phrasings, formats, and units; reject missing, extra-invented, or
contradicting facts. An answer that hedges without committing is false.

Reply with EXACTLY this JSON and nothing else:
{{"verdict": true/false, "reasoning": "<one sentence>"}}"""


def _fallback(answer, ground_truth):
    """No API key: normalized containment of the ground truth's quoted core."""
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())
    cores = re.findall(r"'([^']+)'", ground_truth)
    cores.append(re.sub(r"\([^)]*\)", "", ground_truth))   # drop parentheticals
    cores.append(ground_truth)
    # a core matches if it appears in the answer once both are normalized
    hit = any(norm(c) and norm(c) in norm(answer) for c in cores)
    return {"verdict": hit, "reasoning": "substring fallback (no GEMINI_API_KEY)",
            "judge": "fallback-substring"}


def judge(task, answer, ground_truth):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return _fallback(answer, ground_truth)
    body = json.dumps({
        "contents": [{"parts": [{"text": PROMPT.format(
            task=task, answer=answer or "(no answer)", ground_truth=ground_truth)}]}],
        "generationConfig": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE_MODEL}:generateContent",
        data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)
        text = out["candidates"][0]["content"]["parts"][0]["text"]
        m = re.search(r"\{.*\}", text, re.S)
        v = json.loads(m.group(0))
        return {"verdict": bool(v.get("verdict")), "reasoning": v.get("reasoning"),
                "judge": JUDGE_MODEL}
    except Exception as e:
        fb = _fallback(answer, ground_truth)
        fb["judge_error"] = str(e)[:200]
        return fb


# --- computed ground truths: the runner asks the ENVIRONMENT, not a human --

def _sim_udid():
    out = subprocess.run(["xcrun", "simctl", "list", "devices", "booted"],
                         capture_output=True, text=True).stdout
    m = re.search(r"\(([0-9A-Fa-f-]{36})\).*\(Booted\)", out)
    return m.group(1) if m else None


def _sim_data():
    u = _sim_udid()
    return os.path.expanduser(
        f"~/Library/Developer/CoreSimulator/Devices/{u}/data") if u else None


def compute_ground_truth(task_id, checker_platform):
    """Ground truth read from the device itself at run time; None = can't."""
    import sqlite3
    if checker_platform != "sim":
        return None
    if task_id == "settings-version":
        # the BOOTED DEVICE's runtime, not the first installed runtime —
        # a CI runner booted iOS 26.2 while the list led with 18.5, and we
        # failed an agent that read the About screen correctly
        out = subprocess.run(["xcrun", "simctl", "list", "devices", "booted", "-j"],
                             capture_output=True, text=True).stdout
        m = re.search(r"iOS[.-](\d+)[.-](\d+)", out)
        return f"The version is 'iOS {m.group(1)}.{m.group(2)}'." if m else None
    if task_id == "photos-count":
        db = sqlite3.connect(_sim_data() + "/Media/PhotoData/Photos.sqlite")
        n = db.execute("SELECT count(*) FROM ZASSET WHERE ZTRASHEDSTATE=0").fetchone()[0]
        db.close()
        return f"There are exactly '{n} photos'."
    if task_id == "list-scroll-count":
        db = sqlite3.connect(_sim_data() + "/Library/AddressBook/AddressBook.sqlitedb")
        n = db.execute("SELECT count(*) FROM ABPerson WHERE First IS NOT NULL"
                       " OR Last IS NOT NULL").fetchone()[0]
        db.close()
        return f"There are exactly '{n} contacts'."
    return None
