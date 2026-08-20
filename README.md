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

| Track | Devices | What it measures |
|---|---|---|
| **phonebench-real** | a real iPhone via iPhone Mirroring + a real Android over adb | The benchmark. Real tasks on real phones — including the first interactive iOS agent eval. |
| **phonebench-emulate** | Android emulators (AVDs) | Cheap, parallel iteration; the emulator-vs-real delta is itself a result. |
| **phonebench-appium** | cloud iPhones through the XCUITest tree (e.g. phone-cloud / AWS Device Farm) | The same tasks through a tree-based backend; parallel iOS. |

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
