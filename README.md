# phonebench

Benchmarks for **agents driving phones through tools** — not screenshot-in,
action-out GUI policies. The agent under test is a general-purpose coding agent
(Claude Code, Codex, …) operating a phone through
[phone-harness](https://github.com/ShawnPana/phone-harness)'s helper
vocabulary: it writes Python, reads exceptions, batches work, and verifies its
own actions. That is what real agents do in practice, and no existing mobile
benchmark measures it.

phonebench is one framework, one task suite, and several **tracks** — the same
tasks scored against different device classes. Results are always labeled by
track and never blended.

| Track | Devices | Role |
|---|---|---|
| **sim** | iOS Simulators, driven with the *same* pixels-and-HID control as a real iPhone | The hermetic iOS lane: parallel, CI-able, $0. Where the leaderboard's volume runs. |
| **emulate** | Android emulators (AVDs) over adb | The hermetic Android lane — same role, other OS. |
| **real-ios** / **real-android** | a real iPhone via iPhone Mirroring / a real Android over adb | Small-N realism reference: the sim-to-real delta is itself a result. |
| **appium** | cloud iPhones through the XCUITest tree (phone-cloud / AWS Device Farm) | Same tasks through a tree-based backend; parallel real-hardware iOS. Note: cloud devices restrict most stock apps. |

The thing being ranked is the **agent product × model** (Claude Code, Codex,
opencode, …) — every row drives every track through the same phone-harness
vocabulary, pinned by SHA (`harness.yaml` → `harness.lock`).

## Control surfaces

How anything talks to a phone — adb, XCUITest/WDA, iPhone Mirroring, the
Simulator window — and why agents only ever see one standardized layer:
[docs/control-surfaces.md](docs/control-surfaces.md).

## Two layers, measured separately

- **L0 — primitives** (`primitives/`): deterministic, no-LLM probes of the
  tool layer itself — tap accuracy, OCR/tree latency, typing fidelity, scroll
  termination, app-launch round-trips. This is the harness-reliability number;
  it makes L1 failures attributable (tool failed vs. agent failed).
- **L1 — tasks** (`tasks/`): 20 curated tasks an agent completes end-to-end,
  each with a deterministic setup / check / cleanup. Stock apps only, every
  task reversible, nothing outward-facing (no messages, purchases, or
  settings writes).

## Design rules

- Tasks are specs, not scripts: any phone with the stock apps can run them.
- Checkers read end state (adb `dumpsys`/`content query` on Android; OCR plus
  a saved final screenshot on iOS) — never the agent's own claim of success.
- Per-task accounting: pass/fail, wall time, agent turns, tokens/cost,
  harness-call count, failure class.
- Parallel across devices, sequential per device.

## Running

```bash
python3 run_l0.py --track real-android        # primitives on the real Android
python3 run_l0.py --track real-ios            # primitives on the iPhone
python3 run_l0.py --track emulate --serial emulator-5554
```

L1 runner (`run_l1.py`) lands with the task suite.
