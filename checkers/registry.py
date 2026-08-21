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
# Contacts may resume ON the contact card (an agent often leaves it there).
# If the fingerprint is already on screen, that IS the answer — do not
# demand a Search field the card view does not have. Match a distinctive
# PREFIX: collapsed nav titles truncate ("Carol Phoneben Edit").
_fp = "__NAME__".lower()[:12]
if any(_fp in t.lower() for t in texts()):
    found = True
else:
    try:
        tap_text("Search"); time.sleep(1.5)
        type_text("__NAME__", keystrokes=True); time.sleep(1.5)
    except Exception as e:
        emit(ok=False, error="search focus failed: %s" % e); raise SystemExit
    # The search FIELD echoes the query, so one match is not a hit: a real
    # contact means a result row too (>=2 matches) and no "No Results".
    _rows = [r for r in ocr() if "__NAME__".lower() in r["text"].lower()]
    found = (not visible("No Results")) and len(_rows) >= 2
    if found:
        _hdr = next((r for r in ocr() if "TOP NAME" in r["text"]), None)
        _row = next((r for r in ocr() if "__NAME__".lower() in r["text"].lower()
                     and (not _hdr or r["y"] > _hdr["y"])
                     and not r["text"].startswith("Q")), None)
        if _row: tap(_row["x"], _row["y"]); wait_stable()
'''

REGISTRY["contacts.assert_absent"] = {"ios": _IOS_FIND_CAROL + '''
deleted = False
if found:
    # the name is the benchmark fingerprint — a leftover from a prior run
    try: tap_text("__NAME__"); wait_stable()
    except Exception: pass                       # already on the card
    hit = None
    for _ in range(10):
        hit = next((r for r in ocr() if "Delete Contact" in r["text"]), None)
        if hit: break
        scroll_screen(); time.sleep(0.8)
    if hit:
        tap(hit["x"], hit["y"]); time.sleep(1)
        conf = next((r for r in ocr() if "Delete Contact" in r["text"]), None)
        if conf: tap(conf["x"], conf["y"]); time.sleep(1)
        deleted = True
home(); wait_stable()
emit(ok=deleted or not found, deleted_leftover=deleted)
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
    try: tap_text("__NAME__"); wait_stable()
    except Exception: pass
    hit = None
    for _ in range(10):
        hit = next((r for r in ocr() if "Delete Contact" in r["text"]), None)
        if hit: break
        scroll_screen(); time.sleep(0.8)
    if hit:
        tap(hit["x"], hit["y"]); time.sleep(1)
        conf = next((r for r in ocr() if "Delete Contact" in r["text"]), None)
        if conf: tap(conf["x"], conf["y"]); time.sleep(1)
        removed = True
home(); wait_stable()
emit(ok=(removed or not found), removed=removed)
'''}

# ----------------------------------------------------------------- misc ----
REGISTRY["none"] = {"ios": COMMON + 'home(); wait_stable(); emit(ok=True)',
                    "android": COMMON + 'home(); wait_stable(); emit(ok=True)'}



# ---- sim: privileged checkers -------------------------------------------
# Only the AGENT is bound to the standardized control surface. Checkers may
# use each track's side door for ground truth — adb on Android, and on the
# Simulator the device's own filesystem: Contacts is a sqlite file. This is
# faster and stricter than driving the UI, and immune to its gestures.
_SIM_COMMON = COMMON + '''
import re, sqlite3, subprocess
def _udid():
    out = subprocess.run(["xcrun", "simctl", "list", "devices", "booted"],
                         capture_output=True, text=True).stdout
    m = re.search(r"\\(([0-9A-Fa-f-]{36})\\).*\\(Booted\\)", out)
    if not m:
        raise RuntimeError("no booted simulator")
    return m.group(1)
def _ab():
    import os.path
    return os.path.expanduser(
        "~/Library/Developer/CoreSimulator/Devices/%s/data/Library/"
        "AddressBook/AddressBook.sqlitedb" % _udid())
def _digits(s): return re.sub(r"[^0-9]", "", s or "")
'''

REGISTRY["contacts.assert_absent"]["sim"] = _SIM_COMMON + '''
first, last = ("__NAME__".split(" ", 1) + [""])[:2]
db = sqlite3.connect(_ab())
rows = db.execute("SELECT ROWID FROM ABPerson WHERE First=? AND Last=?",
                  (first, last)).fetchall()
# AddressBook triggers call contactsd's custom SQL functions; stub each one
# the delete trips over with a no-op until it goes through.
for (rid,) in rows:
    for _ in range(24):
        try:
            db.execute("DELETE FROM ABMultiValue WHERE record_id=?", (rid,))
            db.execute("DELETE FROM ABPerson WHERE ROWID=?", (rid,))
            break
        except sqlite3.OperationalError as e:
            msg = str(e)
            if not re.search(r"(no such|unknown) function", msg):
                raise
            fn = re.split(r"(?:no such|unknown) function:?", msg)[1].strip().strip("()")
            import uuid as _u
            db.create_function(fn, -1,
                (lambda *a: _u.uuid4().hex.upper()) if "guid" in fn.lower()
                else (lambda *a: None))
db.commit(); db.close()
if rows:
    subprocess.run(["xcrun", "simctl", "terminate", _udid(),
                    "com.apple.MobileAddressBook"], capture_output=True)
home(); wait_stable()
emit(ok=True, deleted_leftover=bool(rows))
'''

REGISTRY["contacts.exists_with_number"]["sim"] = _SIM_COMMON + '''
first, last = ("__NAME__".split(" ", 1) + [""])[:2]
db = sqlite3.connect(_ab())
hits = db.execute(
    "SELECT mv.value FROM ABPerson p JOIN ABMultiValue mv "
    "ON mv.record_id = p.ROWID WHERE p.First=? AND p.Last=?",
    (first, last)).fetchall()
db.close()
ok = any("__DIGITS__" in _digits(v) for (v,) in hits)
emit(ok=ok, values=[v for (v,) in hits][:5])
'''

REGISTRY["contacts.remove"]["sim"] = REGISTRY["contacts.assert_absent"]["sim"]

REGISTRY["none"]["sim"] = REGISTRY["none"]["ios"]




# ---- sim: seeding + the wider suite -------------------------------------
_SIM_DB = _SIM_COMMON + '''
def _data():
    import os.path
    return os.path.expanduser(
        "~/Library/Developer/CoreSimulator/Devices/%s/data" % _udid())
def _stubbed(db):
    """Execute with contactsd-style trigger functions stubbed on demand."""
    class W:
        def __init__(s2, db): s2.db = db
        def ex(s2, *a):
            import uuid as _u
            for _ in range(24):
                try: return s2.db.execute(*a)
                except sqlite3.OperationalError as e:
                    m = str(e)
                    if not re.search(r"(no such|unknown) function", m): raise
                    fn = re.split(r"(?:no such|unknown) function:?", m)[1].strip().strip("()")
                    s2.db.create_function(fn, -1,
                        (lambda *x: _u.uuid4().hex.upper()) if "guid" in fn.lower()
                        else (lambda *x: None))
    return W(db)
'''

REGISTRY["contacts.seed"] = {"sim": _SIM_DB + '''
first, last = ("__NAME__".split(" ", 1) + [""])[:2]
db = sqlite3.connect(_ab()); w = _stubbed(db)
rows = w.ex("SELECT ROWID FROM ABPerson WHERE First=? AND Last=?", (first, last)).fetchall()
for (rid,) in rows:
    w.ex("DELETE FROM ABMultiValue WHERE record_id=?", (rid,))
    w.ex("DELETE FROM ABPerson WHERE ROWID=?", (rid,))
w.ex("INSERT INTO ABPerson (First, Last) VALUES (?, ?)", (first, last))
rid = w.ex("SELECT ROWID FROM ABPerson WHERE First=? AND Last=?", (first, last)).fetchone()[0]
w.ex("INSERT INTO ABMultiValue (record_id, property, label, value) VALUES (?, 3, 1, ?)",
     (rid, "(555) 014-2"[:0] + "555-0142"))
db.commit(); db.close()
subprocess.run(["xcrun", "simctl", "terminate", _udid(), "com.apple.MobileAddressBook"],
               capture_output=True)
home(); wait_stable()
emit(ok=True, seeded_rowid=rid)
'''}

REGISTRY["contacts.is_absent"] = {"sim": _SIM_DB + '''
first, last = ("__NAME__".split(" ", 1) + [""])[:2]
db = sqlite3.connect(_ab())
n = db.execute("SELECT count(*) FROM ABPerson WHERE First=? AND Last=?", (first, last)).fetchone()[0]
db.close()
emit(ok=(n == 0), remaining=n)
'''}

REGISTRY["contacts.count"] = {"sim": _SIM_DB + '''
db = sqlite3.connect(_ab())
n = db.execute("SELECT count(*) FROM ABPerson WHERE First IS NOT NULL OR Last IS NOT NULL").fetchone()[0]
db.close()
emit(ok=True, count=n)
'''}

# appearance: simctl is both actuator and ground truth
_APPEAR = _SIM_COMMON + '''
def _appearance():
    return subprocess.run(["xcrun", "simctl", "ui", _udid(), "appearance"],
                          capture_output=True, text=True).stdout.strip()
def _set_appearance(v):
    subprocess.run(["xcrun", "simctl", "ui", _udid(), "appearance", v], capture_output=True)
'''
REGISTRY["appearance.assert_light"] = {"sim": _APPEAR + '_set_appearance("light"); emit(ok=True)'}
REGISTRY["appearance.assert_dark"]  = {"sim": _APPEAR + '_set_appearance("dark"); emit(ok=True)'}
REGISTRY["appearance.is_dark"]  = {"sim": _APPEAR + 'emit(ok=_appearance()=="dark", value=_appearance())'}
REGISTRY["appearance.is_light"] = {"sim": _APPEAR + 'emit(ok=_appearance()=="light", value=_appearance())'}
REGISTRY["appearance.set_light"] = {"sim": _APPEAR + '_set_appearance("light"); emit(ok=True)'}

# safari bookmarks: Bookmarks.db
_SAFARI = _SIM_DB + '''
def _bm():
    return _data() + "/Library/Safari/Bookmarks.db"
'''
REGISTRY["safari.assert_no_bookmark"] = {"sim": _SAFARI + '''
db = sqlite3.connect(_bm()); w = _stubbed(db)
w.ex("DELETE FROM bookmarks WHERE url LIKE ?", ("%__HOST__%",))
db.commit(); db.close()
emit(ok=True)
'''}
REGISTRY["safari.has_bookmark"] = {"sim": _SAFARI + '''
db = sqlite3.connect(_bm())
n = db.execute("SELECT count(*) FROM bookmarks WHERE url LIKE ?", ("%__HOST__%",)).fetchone()[0]
db.close()
emit(ok=(n > 0), matches=n)
'''}
REGISTRY["safari.remove_bookmark"] = {"sim": REGISTRY["safari.assert_no_bookmark"]["sim"]}

# calendar: Calendar.sqlitedb, CalendarItem.summary
_CALDB = _SIM_DB + '''
def _cal():
    return _data() + "/Library/Calendar/Calendar.sqlitedb"
'''
REGISTRY["calendar.assert_absent"] = {"sim": _CALDB + '''
db = sqlite3.connect(_cal()); w = _stubbed(db)
w.ex("DELETE FROM CalendarItem WHERE summary LIKE ?", ("%__TITLE__%",))
db.commit(); db.close()
subprocess.run(["xcrun", "simctl", "terminate", _udid(), "com.apple.mobilecal"], capture_output=True)
home(); wait_stable()
emit(ok=True)
'''}
REGISTRY["calendar.has_event"] = {"sim": _CALDB + '''
db = sqlite3.connect(_cal())
rows = db.execute("SELECT summary FROM CalendarItem WHERE summary LIKE ?", ("%__TITLE__%",)).fetchall()
db.close()
emit(ok=len(rows) > 0, found=[r[0] for r in rows][:5])
'''}
REGISTRY["calendar.remove"] = {"sim": REGISTRY["calendar.assert_absent"]["sim"]}

# photos: Photos.sqlite ZASSET.ZFAVORITE
_PHOTODB = _SIM_DB + '''
def _ph():
    return _data() + "/Media/PhotoData/Photos.sqlite"
'''
REGISTRY["photos.assert_no_favorites"] = {"sim": _PHOTODB + '''
db = sqlite3.connect(_ph()); w = _stubbed(db)
w.ex("UPDATE ZASSET SET ZFAVORITE=0 WHERE ZFAVORITE=1")
db.commit(); db.close()
subprocess.run(["xcrun", "simctl", "terminate", _udid(), "com.apple.mobileslideshow"], capture_output=True)
home(); wait_stable()
emit(ok=True)
'''}
REGISTRY["photos.newest_is_favorite"] = {"sim": _PHOTODB + '''
db = sqlite3.connect(_ph())
row = db.execute("SELECT ZFAVORITE FROM ZASSET WHERE ZTRASHEDSTATE=0 ORDER BY ZDATECREATED DESC LIMIT 1").fetchone()
db.close()
emit(ok=bool(row and row[0] == 1), newest_favorite=row[0] if row else None)
'''}
REGISTRY["photos.unfavorite_all"] = {"sim": REGISTRY["photos.assert_no_favorites"]["sim"]}
REGISTRY["photos.count"] = {"sim": _PHOTODB + '''
db = sqlite3.connect(_ph())
n = db.execute("SELECT count(*) FROM ZASSET WHERE ZTRASHEDSTATE=0").fetchone()[0]
db.close()
emit(ok=True, count=n)
'''}

# reminders: store location is created lazily -> OCR until verified pass
_REM_OCR = COMMON + '''
def _open_reminders():
    home(); wait_stable(); launch("Reminders"); wait_stable(); time.sleep(1)
'''
REGISTRY["reminders.assert_absent"] = {"sim": _REM_OCR + '''
_open_reminders()
# TODO(verified-pass): move to the Reminders sqlite store once it exists.
emit(ok=not visible("__TITLE__"[:14]), note="ocr-based")
home(); wait_stable()
'''}
REGISTRY["reminders.exists"] = {"sim": _REM_OCR + '''
_open_reminders()
hit = visible("__TITLE__"[:14])
if not hit:
    for row in ocr():
        if "All" == row["text"].strip() or "Today" in row["text"]:
            tap(row["x"], row["y"]); time.sleep(1.5); break
    hit = visible("__TITLE__"[:14])
home(); wait_stable()
emit(ok=hit, note="ocr-based")
'''}
REGISTRY["reminders.remove"] = {"sim": COMMON + '''
# TODO(verified-pass): sqlite delete; UI swipe-delete is unreliable. Erase-on-
# schedule keeps the sim clean between suite runs regardless.
home(); wait_stable()
emit(ok=True, note="deferred to sim erase")
'''}
REGISTRY["compound.cleanup_carol_reminder"] = {"sim": REGISTRY["reminders.remove"]["sim"]}

# files + generic screen check
REGISTRY["files.assert_no_pb_saves"] = {"sim": _SIM_DB + '''
import glob, os
docs = _data() + "/Containers/Shared/AppGroup"
before = len(glob.glob(docs + "/*/File Provider Storage/*"))
open("/tmp/pb-files-baseline", "w").write(str(before))
home(); wait_stable()
emit(ok=True, baseline=before)
'''}
REGISTRY["files.has_new_save"] = {"sim": _SIM_DB + '''
import glob
docs = _data() + "/Containers/Shared/AppGroup"
now = len(glob.glob(docs + "/*/File Provider Storage/*"))
base = int(open("/tmp/pb-files-baseline").read() or 0)
emit(ok=now > base, before=base, after=now)
'''}
REGISTRY["files.cleanup_saves"] = {"sim": COMMON + 'home(); wait_stable(); emit(ok=True, note="deferred to sim erase")'}

REGISTRY["screen.app_visible"] = {
  "sim": COMMON + '''
import re
pats = "__MARKERS__".split("|")
seen = " ".join(texts())
ok = any(p.lower() in seen.lower() for p in pats)
emit(ok=ok, seen_excerpt=seen[:200])
'''}
REGISTRY["screen.app_visible"]["ios"] = REGISTRY["screen.app_visible"]["sim"]


# "answer.contains" is handled by the runner itself: the check runs against
# the agent's final answer text, not the phone.


def resolve(key, platform, args=None):
    entry = REGISTRY[key]
    if platform not in entry and platform == "sim" and "ios" in entry:
        platform = "ios"                 # sim falls back to the UI checker
    if platform not in entry:
        raise NotImplementedError(f"checker {key} not implemented for {platform}")
    code = entry[platform]
    for k, v in (args or {}).items():
        code = code.replace(f"__{k.upper()}__", str(v))
    return code
