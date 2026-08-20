# Task specs

One YAML file per task. Tasks are specs, not scripts — any phone with the
stock apps can run them. Rules: stock apps only, every task reversible via
`cleanup`, nothing outward-facing (no messages, purchases, settings writes).

```yaml
id: alarm-0730                # unique, kebab-case
title: Set a 7:30 AM alarm
prompt: >                     # verbatim to the agent; no hints about tools
  Set an alarm for 7:30 AM in the Clock app.
platforms: [ios, android]     # which tracks can score it
tier: easy                    # easy | medium | hard
setup: clock.clear_alarms     # checkers/<module>.<fn>, run before the agent
check: clock.has_alarm        # deterministic pass/fail on END STATE
check_args: {time: "7:30 AM"}
cleanup: clock.clear_alarms   # always runs, pass or fail
timeout_s: 240
max_turns: 25
```

Checkers live in `checkers/` and read the phone directly — adb
`dumpsys`/`content query` on Android where possible (independent of the
harness), OCR plus a saved final screenshot on iOS. A checker never trusts
the agent's own report.
