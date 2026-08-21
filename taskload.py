"""One loader for task specs, plaintext or encrypted.

Local editing happens in tasks/*.yaml (gitignored). The repo commits only
tasks.enc/*.tenc (see tools/taskcrypt.py). Loading prefers plaintext when
present — an edited task wins over its stale encrypted twin — and falls
back to decoding, which is how CI runs from a fresh clone.
"""
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "tools"))
from taskcrypt import decode  # noqa: E402


def all_ids():
    ids = {f.stem for f in (HERE / "tasks").glob("*.yaml")}
    ids |= {f.stem for f in (HERE / "tasks.enc").glob("*.tenc")}
    return sorted(ids)


def load_task(task_id):
    plain = HERE / "tasks" / f"{task_id}.yaml"
    if plain.exists():
        return yaml.safe_load(plain.read_text())
    enc = HERE / "tasks.enc" / f"{task_id}.tenc"
    if enc.exists():
        return yaml.safe_load(decode(enc.read_text()))
    raise FileNotFoundError(f"no task {task_id!r} in tasks/ or tasks.enc/")


def load_all():
    return [load_task(t) for t in all_ids()]
