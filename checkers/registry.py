"""Checkers — deterministic setup / check / cleanup snippets, run through the
same `phone-harness` CLI the agent uses (iOS has no side door; Android
checkers will prefer adb state reads when they land).

Registry key: "<module>.<fn>" from the task YAML. Each entry maps platform ->
snippet. A snippet prints one line `::PB::{json}` with:
    ok: bool          the step's verdict
    skip: bool        (setup only) precondition dirty in a way we must not
                      touch — the task is skipped, never run dirty
Args from the task's *_args dicts are substituted as __NAME__ tokens.

Benchmark state is only ever created and deleted by its unmistakable
fingerprint ("Carol Phonebench", the exact alarm time). A checker never
deletes anything it cannot prove the benchmark created — a pre-existing
7:30 alarm skips the task instead of being deleted; only cleanup (which runs
after setup proved the alarm was absent) may remove it.
"""

COMMON = '''
import json, os, time
def emit(**kw): print("::PB::" + json.dumps(kw))
def texts(): return [r["text"] for r in ocr()]
def visible(s): return any(s.lower() in t.lower() for t in texts())
# A datacenter phone has no Spotlight: the cloud backend launches by bundle
# id. Locally the name is the Spotlight query. Same checker, both backends.
_BUNDLES = {"Clock": "com.apple.mobiletimer",
            "Contacts": "com.apple.MobileAddressBook",
            "Safari": "com.apple.mobilesafari",
            "Calculator": "com.apple.calculator",
            "Settings": "com.apple.Preferences"}
_CLOUD = os.environ.get("PHONE_HARNESS_PLATFORM", "").lower() == "cloud"
def launch(name):
    open_app(_BUNDLES.get(name, name) if _CLOUD else name)
'''

# iOS: swipe a list row left and confirm Delete — the only removal path the
# stock apps give us.
IOS_ROW_DELETE = '''
def delete_row(needle):
    rows = [r for r in ocr() if needle.lower() in r["text"].lower()]
    if not rows: return False
    r = rows[0]
    info = screen_info(); w = info["window"]
    drag(w["x"] + w["w"] * 0.85, r["y"], w["x"] + w["w"] * 0.25, r["y"], duration=0.3)
    time.sleep(1)
    try: tap_text("Delete"); time.sleep(1); return True
    except Exception: return False
'''

REGISTRY = {}

# ---------------------------------------------------------------- clock ----
REGISTRY["clock.assert_no_alarm"] = {"ios": COMMON + '''
home(); wait_stable()
launch("Clock"); wait_stable()
try: tap_text("Alarms"); wait_stable()
except Exception: pass
if visible("__TIME__"):
    emit(ok=False, skip=True, reason="an alarm showing __TIME__ already exists; not touching it")
else:
    home(); wait_stable()
    emit(ok=True)
'''}

REGISTRY["clock.has_alarm"] = {"ios": COMMON + '''
home(); wait_stable()
launch("Clock"); wait_stable()
try: tap_text("Alarms"); wait_stable()
except Exception: pass
found = visible("__TIME__")
emit(ok=found, saw=[t for t in texts() if ":" in t][:12])
'''}

REGISTRY["clock.remove_alarm"] = {"ios": COMMON + IOS_ROW_DELETE + '''
home(); wait_stable()
launch("Clock"); wait_stable()
try: tap_text("Alarms"); wait_stable()
except Exception: pass
removed = False
if visible("__TIME__"):
    rows = [r for r in ocr() if "__TIME__".lower() in r["text"].lower()]
    if rows:
        r = rows[0]
        info = screen_info(); w = info["window"]
        drag(w["x"] + w["w"] * 0.85, r["y"], w["x"] + w["w"] * 0.25, r["y"], duration=0.3)
        time.sleep(1)
        try: tap_text("Delete"); removed = True
        except Exception: pass
        time.sleep(1)
home(); wait_stable()
emit(ok=(removed or not visible("__TIME__")), removed=removed)
'''}

# ------------------------------------------------------------- contacts ----
_IOS_FIND_CAROL = COMMON + '''
home(); wait_stable()
launch("Contacts"); wait_stable()
try:
    tap_text("Search"); time.sleep(1.5)
    type_text("__NAME__", keystrokes=True); time.sleep(1.5)
except Exception as e:
    emit(ok=False, error="search focus failed: %s" % e); raise SystemExit
# The search FIELD itself echoes the query, so one match is not a hit:
# a real contact means a result row too (>=2 matches) and no "No Results".
_rows = [r for r in ocr() if "__NAME__".lower() in r["text"].lower()]
found = (not visible("No Results")) and len(_rows) >= 2
'''

REGISTRY["contacts.assert_absent"] = {"ios": _IOS_FIND_CAROL + '''
deleted = False
if found:
    # the name is the benchmark fingerprint — a leftover from a prior run
    tap_text("__NAME__"); wait_stable()
    scroll_until(lambda rows: any("Delete Contact" in r["text"] for r in rows))
    tap_text("Delete Contact"); time.sleep(1)
    tap_text("Delete Contact"); time.sleep(1)   # the confirm sheet
    deleted = True
home(); wait_stable()
emit(ok=True, deleted_leftover=deleted)
'''}

REGISTRY["contacts.exists_with_number"] = {"ios": _IOS_FIND_CAROL + '''
ok = False; card = []
if found:
    tap_text("__NAME__"); wait_stable()
    card = texts()
    ok = any("__DIGITS__" in t.replace(" ", "").replace("-", "").replace("(", "").replace(")", "") for t in card)
home(); wait_stable()
emit(ok=ok, found_name=found, card_excerpt=card[:15])
'''}

REGISTRY["contacts.remove"] = {"ios": _IOS_FIND_CAROL + '''
removed = False
if found:
    tap_text("__NAME__"); wait_stable()
    scroll_until(lambda rows: any("Delete Contact" in r["text"] for r in rows))
    tap_text("Delete Contact"); time.sleep(1)
    tap_text("Delete Contact"); time.sleep(1)
    removed = True
home(); wait_stable()
emit(ok=(removed or not found), removed=removed)
'''}

# ----------------------------------------------------------------- misc ----
REGISTRY["none"] = {"ios": COMMON + 'home(); wait_stable(); emit(ok=True)',
                    "android": COMMON + 'home(); wait_stable(); emit(ok=True)'}

# "answer.contains" is handled by the runner itself: the check runs against
# the agent's final answer text, not the phone.


def resolve(key, platform, args=None):
    entry = REGISTRY[key]
    if platform not in entry:
        raise NotImplementedError(f"checker {key} not implemented for {platform}")
    code = entry[platform]
    for k, v in (args or {}).items():
        code = code.replace(f"__{k.upper()}__", str(v))
    return code
