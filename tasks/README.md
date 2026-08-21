# Task specs

One YAML file per task. Tasks are specs, not scripts — any phone with the
stock apps can run them. Rules: stock apps only, every task reversible via
`cleanup`, nothing outward-facing (no messages, purchases, settings writes).

```yaml
id: alarm-0730                # unique, kebab-case
title: Set a 7:30 AM alarm
prompt: >                     # verbatim to the agent; no hints about tools
  Set an alarm for 7:30 AM in the Clock app.
stratum: state                # retrieval | state | gesture | compound
tier: medium                  # easy | medium | hard
requires_apps: [Clock]        # runner probes the device; missing app =>
                              # status "unsupported-on-track", never a fail
platforms: [ios, android]     # which tracks can host it (aspirational; the
                              # probe is the runtime authority)
source: custom                # provenance: custom | androidworld | ...
setup: clock.assert_no_alarm  # checkers/<module>.<fn>, run before the agent
check: clock.has_alarm        # deterministic pass/fail on END STATE, or
                              # answer.judge for retrieval tasks (see below)
cleanup: clock.remove_alarm   # always runs, pass or fail
timeout_s: 300
max_turns: 60
```

Retrieval tasks use `check: answer.judge` plus a `ground_truth` field — the
verified correct answer. A pinned third-party judge model (GEMINI_API_KEY;
never one of the ranked vendors) does semantic matching against that ground
truth; without a key the runner falls back to normalized substring matching
and labels the verdict accordingly. `ground_truth: COMPUTED` means the
runner reads the true value from the device itself at run time (judge.py's
compute registry). Deterministic state checkers always take precedence over
the judge — it exists only where the deliverable is an answer.

**Verified-achievable rule:** no task counts toward the leaderboard until it
has produced one confirmed true-pass and one confirmed true-fail on its
primary track. Reminders/Files checkers are OCR/fs-heuristic drafts pending
that pass (marked TODO in the registry).

Checkers live in `checkers/` and read the phone directly — adb
`dumpsys`/`content query` on Android where possible (independent of the
harness), OCR plus a saved final screenshot on iOS. A checker never trusts
the agent's own report.
