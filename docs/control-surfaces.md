# Control surfaces: how anything talks to a phone

Every phone-automation stack is three layers: a **connection point** (the
pipe), **eyes** (how you read the screen/state), and **hands** (how you act).
phonebench standardizes the agent-facing layer on phone-harness's op
vocabulary; underneath, each track rides one of these surfaces.

## The surfaces

| Surface | Connection point | Eyes | Hands | On-device agent? | Setup friction | phonebench track |
|---|---|---|---|---|---|---|
| **adb** (Android) | `adbd`, a debug daemon **built into every Android** (USB or Wi-Fi; authorized once by RSA key prompt) | pixels via `screencap`; accessibility tree via `uiautomator dump`; **true state** via `dumpsys` / `content query` / sqlite | `input tap/swipe/text` (per-call process spawn); `am`/`pm` for app lifecycle | none — the daemon ships in the OS | Developer options toggle | `android-emu`, `real-android` |
| **XCUITest / WDA** (a.k.a. "Appium" on iOS) | `usbmuxd`/`lockdownd` (iOS 17+: CoreDevice/RemoteXPC) → `testmanagerd` runs a **test bundle that never exits** and serves HTTP (WebDriverAgent) | accessibility tree (`/source` XML) — exact, but only what apps declare; whole-page not viewport in web views | element actions + W3C gestures over HTTP | yes — WDA must be installed, signed (real devices), and kept alive | Xcode toolchain; real devices need an Apple developer cert | `appium` (cloud iPhones via phone-cloud) |
| **iPhone Mirroring** (phone-harness native) | a **consumer Continuity feature**: the phone streams video to a Mac window; the Mac forwards input. The phone doesn't know it's automated | window capture + **Vision OCR** — sees exactly what a human sees, with human-class misreads | HID-level CGEvents / SkyLight records into the window | none | none beyond normal Mirroring pairing | `real-ios` |
| **Simulator window** (phone-harness `sim`) | none — the "phone" is a local macOS process whose window is captured like Mirroring's | same OCR eyes as Mirroring (identical control modality, by design); checkers may side-door the sim's **filesystem/sqlite** | same CGEvents; nav accelerators differ (Home = ⌘⇧H) | none | Xcode + an iOS runtime download | `sim` |

Reference point outside phones: **CDP** (browsers) is a *semantic* protocol —
the browser instruments itself and streams DOM/network truth. adb is only a
very privileged pipe (the semantics live in what you run through it), and
Apple's pipe is narrower still: no shell, no input — which is why all
sanctioned iOS automation tunnels through the XCUITest loophole, and why
phone-harness goes around the pipe entirely via the human channel.

## Reliability is two different questions

**Plumbing reliability** (does the run survive):

| | Transport | Eyes fidelity | Hands fidelity |
|---|---|---|---|
| adb / USB | excellent (kernel-level, agentless) | tree exact but slow (2–3 s) and occasionally "not idle"; state reads are ground truth | deterministic, slowish |
| adb / Wi-Fi | drops on network events; needs keep-awake | same | same |
| Simulator window | no transport to fail | OCR misreads/truncations ("3arol Phoneben") | taps solid; **gesture physics weak** (rubber-banding, form sheets that barely scroll) |
| WDA / cloud | userspace agent can detach; ~0.8 s/op RTT | tree exact; viewport-blind quirks | element actions reliable, latency-taxed |
| iPhone Mirroring | **most fragile**: session pauses when the phone is unlocked or the Mac sleeps (measured mid-benchmark) | OCR, as above | taps solid; gestures weak, focus-sensitive |

**UX reliability** (what it feels like to hand an agent your phone) inverts
that ranking. Mirroring is the worst transport and the **best experience**:
zero ceremony (a consumer feature), the agent works *your* phone with *your*
apps, the window makes it glanceable, picking up your phone always preempts
the agent (consent by physics), and pixel/HID hands can only do what a human
could visibly do — failures look like fumbling, not sorcery. adb is close
behind but developer-flavored (and its side doors make cleanup *perfect*,
which Mirroring can't promise). WDA is lab equipment, not an end-user
experience. Sim/emulator has no UX at all — by design: it exists so the
benchmark can measure the others without touching anything a person cares
about.

## What phonebench standardizes

Agents never see any of this table. They drive every track through the same
phone-harness helper vocabulary (`ocr`, `tap_text`, `scroll_collect`, …), and
on iOS-shaped tracks that means the same pixels-and-HID modality on sim and
real alike — so scores transfer across the hermetic/real boundary. Checkers
are exempt: they may use each surface's most truthful side door (adb state
reads, sim sqlite), because ground truth should not depend on the thing being
measured. Only the agent is bound to the standardized control surface.
