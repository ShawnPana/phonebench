# Control surfaces: how anything talks to a phone

Every phone-automation stack is three layers: a **connection point** (the
pipe), **eyes** (how you read the screen/state), and **hands** (how you act).
phonebench standardizes the agent-facing layer on phone-harness's op
vocabulary; underneath, each track rides one of these surfaces.

## The surfaces

| | **adb** | **XCUITest / WDA** | **iPhone Mirroring** | **Simulator window** |
|---|---|---|---|---|
| **What it is** | debug daemon built into Android | Apple's test channel, held open as a server | the phone screen-shared to a Mac window | a fake phone as a local Mac window |
| **Eyes** | pixels · tree · **real state** | tree | OCR on pixels | OCR on pixels |
| **Hands** | shell input | element taps | mouse + keys | mouse + keys |
| **On-phone install** | none | **WDA helper app** | none | none |
| **Setup** | one toggle | Xcode + signing | none | Xcode |
| **Track** | `android-emu`, `real-android` | `appium` | `real-ios` | `sim` |

Reading it in one line each:

- **adb** — Android ships its own debug door; you get a privileged shell, so
  eyes include *actual app state* (`dumpsys`, sqlite), not just the screen.
- **XCUITest/WDA** — iOS has no shell, only a test framework; automation means
  installing a helper app (WebDriverAgent) that runs as a fake test which
  never exits and serves HTTP. Only path that puts software on the phone —
  and that helper must be signed, launched, and babysat.
- **iPhone Mirroring** — no debug channel at all: the *human* channel. The Mac
  sees the streamed screen and sends normal input; the phone can't tell an
  agent from a person.
- **Simulator window** — same eyes and hands as Mirroring, pointed at a local
  simulator instead of a real phone. That's deliberate: scores transfer.

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
