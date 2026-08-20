"""L0 probes — deterministic, no-LLM exercises of the tool layer itself.

Each probe is a phone-harness script (helpers pre-imported by the CLI). It
must print exactly one line `::PB::{json}` with at least {"ok": bool}; any
timing detail rides along. Probes only touch stock apps, change nothing that
survives them, and end at the home screen.

The runner injects PLATFORM ("ios"/"android") as the first line.
"""

COMMON = '''
import json, time
def emit(**kw):
    print("::PB::" + json.dumps(kw))
def timed(fn):
    t0 = time.time(); r = fn(); return r, round((time.time() - t0) * 1000)
def try_taps(*labels):
    """Tap the first label that exists, by tree on Android, text on iOS."""
    for lab in labels:
        try:
            (tap_ui if PLATFORM == "android" else tap_text)(lab)
            return lab
        except Exception:
            continue
    raise RuntimeError("none of %r tappable" % (labels,))
'''

PROBES = {}

# -- session: is the device usable, and how fast is one look at the screen --
PROBES["session"] = COMMON + '''
state = connection_state()
if state != "ready":
    emit(ok=False, state=state)
else:
    info, ms = timed(screen_info)
    emit(ok=True, state=state, screen_info_ms=ms, info=str(info)[:200])
'''

# -- capture: latency + yield of screen.text, the load-bearing op --
PROBES["capture"] = COMMON + '''
samples = []
source = None
for _ in range(3):
    rows, ms = timed(ocr)
    samples.append(ms)
    source = rows[0]["source"] if rows else source
    texts = len(rows)
emit(ok=texts > 0, ms_samples=samples, texts=texts, source=source)
'''

# -- nav: home -> launch Clock -> verify by content -> home, all timed --
PROBES["nav"] = COMMON + '''
home(); wait_stable()
name = "Clock" if PLATFORM == "ios" else "clock"
_, launch_ms = timed(lambda: open_app(name))
wait_stable()
hit, verify_ms = timed(lambda: wait_for_text("Alarm", timeout=15))
_, home_ms = timed(lambda: (home(), wait_stable()))
emit(ok=bool(hit), launch_ms=launch_ms, verify_ms=verify_ms, home_ms=home_ms)
'''

# -- tap: accuracy with a self-checking target: Calculator, 7 + 3 = 10 --
PROBES["tap"] = COMMON + '''
home(); wait_stable()
open_app("Calculator" if PLATFORM == "ios" else "calc")
wait_stable()
t0 = time.time()
try_taps("7")
try_taps("+", "plus", "add")
try_taps("3")
try_taps("=", "equals")
wait_stable()
taps_ms = round((time.time() - t0) * 1000)
rows = ocr()
seen = " ".join(r["text"] for r in rows)
ok = "10" in seen
try:
    try_taps("AC", "C", "clear", "Clear")   # leave it clean; best-effort
except Exception:
    pass
home(); wait_stable()
emit(ok=ok, taps_ms=taps_ms, saw="10" if ok else seen[:160])
'''

# -- scroll: does a long list walk terminate honestly, and what does it cost --
PROBES["scroll"] = COMMON + '''
home(); wait_stable()
open_app("Settings" if PLATFORM == "ios" else "settings")
wait_stable()
t0 = time.time()
res = scroll_collect(lambda rows: [r["text"] for r in rows],
                     key=lambda t: t, max_scrolls=8)
ms = round((time.time() - t0) * 1000)
home(); wait_stable()
emit(ok=res["stop"] in ("reached-end", "max-scrolls"),
     items=len(res["items"]), stop=res["stop"], scrolls=res["scrolls"], ms=ms)
'''

# -- text: does typed text arrive intact (keystroke path, autocorrect and all) --
PROBES["text"] = COMMON + '''
home(); wait_stable()
WANT = "phonebench probe 42"
if PLATFORM == "android":
    open_app("settings"); wait_stable()
    try_taps("Search settings", "search_action_bar", "Search")
    wait_stable()
    type_text(WANT); wait_stable()
    seen = " ".join(r["text"] for r in ocr())
    back(); back()
else:
    open_app("Safari"); wait_stable()
    bar = [r for r in ocr() if ".com" in r["text"] or "Search" in r["text"]]
    if not bar:
        raise RuntimeError("no address bar found")
    tap(bar[-1]["x"], bar[-1]["y"]); time.sleep(1.5)
    type_text(WANT, keystrokes=True); time.sleep(0.5)
    seen = " ".join(r["text"] for r in ocr())
    try_taps("Cancel")          # abandon the edit, never navigate
home(); wait_stable()
emit(ok=WANT in seen, wanted=WANT, seen_excerpt=seen[:200])
'''
