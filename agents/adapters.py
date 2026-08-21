"""Agent adapters — one function per CLI agent, same contract.

The A/B design holds everything constant except the agent product:
  - identical prompt: skill text + task, delivered inline as the user prompt
    to both (no system-prompt injection for either, no native skill
    discovery — that variance is a separate, later experiment)
  - both permission-free (claude --dangerously-skip-permissions, codex
    --dangerously-bypass-approvals-and-sandbox): symmetric capability
  - both bounded by the task's wall-clock timeout; claude's turn cap is set
    high so time, not turns, is the binding constraint for both
  - both sealed in an empty scratch cwd

Each adapter returns the same row shape:
  {result, agent_wall_s, turns, cost_usd, usage{input,output}, model, raw}
cost_usd is the CLI's own accounting where it provides one (claude);
codex reports tokens only — dollars are computed at report time from
published rates, never guessed here.
"""
import json, os, subprocess, time

AGENT_BUFFER_S = 90


def _sealed_prompt(skill_text, prompt):
    # Never start with '-': SKILL.md opens with '---' frontmatter and a
    # leading-dash positional reads as a flag to both CLIs (rc=2).
    return (f"Tool guide for controlling the phone:\n\n{skill_text}\n\n---\n\nTask: {prompt}\n\n"
            "Do the task on the phone now, then state the outcome in one "
            "or two sentences. Do not ask questions.")


def run_claude(prompt, skill_text, env, model, timeout_s, cwd):
    cmd = ["claude", "-p",
           "--dangerously-skip-permissions",
           "--max-turns", "60",              # high: wall-clock is the cap
           "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    cmd += ["--", _sealed_prompt(skill_text, prompt)]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL,
                           timeout=timeout_s + AGENT_BUFFER_S,
                           cwd=cwd, env={**os.environ, **env})
        try:
            data = json.loads(p.stdout)
        except json.JSONDecodeError:
            data = {"result": p.stdout[-2000:], "parse_error": True}
        row = {"result": data.get("result"),
               "turns": data.get("num_turns"),
               "cost_usd": data.get("total_cost_usd"),
               "usage": data.get("usage", {}),
               "model": model or "claude-default",
               "raw": data, "rc": p.returncode,
               "stderr_tail": p.stderr.strip()[-500:]}
    except subprocess.TimeoutExpired:
        row = {"result": None, "timeout": True, "turns": None,
               "cost_usd": None, "usage": {}, "model": model, "raw": {}}
    row["agent_wall_s"] = round(time.time() - t0, 1)
    row["agent"] = "claude"
    return row


def run_codex(prompt, skill_text, env, model, timeout_s, cwd):
    last = os.path.join(cwd, "codex-last-message.txt")
    # clap rejects flags after the positional prompt — every option must
    # precede it (this exact bug shipped once: -m after the prompt, rc=2).
    cmd = ["codex", "exec", "--json", "-o", last,
           "--dangerously-bypass-approvals-and-sandbox",
           "--skip-git-repo-check", "--ephemeral",
           "-C", cwd]
    if model:
        cmd += ["-m", model]
    extra = os.environ.get("PHONEBENCH_CODEX_ARGS")
    if extra:                       # e.g. -c model_reasoning_effort="medium"
        cmd += extra.split("\x1f") if "\x1f" in extra else extra.split()
    cmd += ["--", _sealed_prompt(skill_text, prompt)]
    t0 = time.time()
    usage, turns, mdl, events = {}, 0, model or "codex-default", []
    result = None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL,
                           timeout=timeout_s + AGENT_BUFFER_S,
                           cwd=cwd, env={**os.environ, **env})
        for line in p.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(ev)
            it = ev.get("item", {})
            if it.get("type") == "command_execution":
                if ev.get("type") == "item.completed":
                    turns += 1
            if ev.get("type") == "turn.completed" and ev.get("usage"):
                u = ev["usage"]
                usage = {"input_tokens": usage.get("input_tokens", 0)
                         + u.get("input_tokens", 0),
                         "output_tokens": usage.get("output_tokens", 0)
                         + u.get("output_tokens", 0)}
        if os.path.exists(last):
            result = open(last).read().strip()
        row = {"result": result, "turns": turns, "cost_usd": None,
               "usage": usage, "model": mdl, "raw": {"events": events[-40:]},
               "rc": p.returncode, "stderr_tail": p.stderr.strip()[-500:]}
    except subprocess.TimeoutExpired:
        row = {"result": None, "timeout": True, "turns": turns,
               "cost_usd": None, "usage": usage, "model": mdl, "raw": {}}
    row["agent_wall_s"] = round(time.time() - t0, 1)
    row["agent"] = "codex"
    return row




def run_opencode(prompt, skill_text, env, model, timeout_s, cwd):
    cmd = ["opencode", "run", "--format", "json"]
    if model:
        cmd += ["--model", model]        # provider/model form
    cmd += ["--", _sealed_prompt(skill_text, prompt)]
    t0 = time.time()
    turns, texts, events_tail = 0, [], []
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL,
                           timeout=timeout_s + AGENT_BUFFER_S,
                           cwd=cwd, env={**os.environ, **env})
        for line in p.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            events_tail.append(ev)
            part = ev.get("part") or {}
            if ev.get("type") == "tool_use":
                turns += 1
            if ev.get("type") == "text" and part.get("text"):
                texts.append(part["text"])
        row = {"result": texts[-1] if texts else None, "turns": turns,
               "cost_usd": None, "usage": {},
               "model": model or "opencode-default",
               "raw": {"events": events_tail[-40:]},
               "rc": p.returncode, "stderr_tail": p.stderr.strip()[-500:]}
    except subprocess.TimeoutExpired:
        row = {"result": None, "timeout": True, "turns": turns,
               "cost_usd": None, "usage": {}, "model": model, "raw": {}}
    row["agent_wall_s"] = round(time.time() - t0, 1)
    row["agent"] = "opencode"
    return row


ADAPTERS = {"claude": run_claude, "codex": run_codex,
            "opencode": run_opencode}
