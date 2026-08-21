#!/usr/bin/env python3
"""Contamination armor for task definitions.

Task prompts and ground truths in plaintext on a public repo become training
data; a future model that memorized the answer key invalidates the
leaderboard. This encodes tasks so crawlers and training pipelines ingest
noise, while anyone RUNNING the benchmark decodes transparently — the key
lives right here, because the threat model is scraping, not humans.

    python3 tools/taskcrypt.py encrypt     # tasks/*.yaml -> tasks.enc/*.tenc
    python3 tools/taskcrypt.py decrypt     # tasks.enc/*.tenc -> tasks/*.yaml

Scheme: zlib | XOR keystream (SHA-256 counter mode over a fixed passphrase)
| base64. Stdlib-only, deterministic, and utterly opaque to an ngram-hungry
crawler.
"""
import base64
import hashlib
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).parent.parent
KEY = b"phonebench-anticontamination-v1"


def _stream(n):
    out = b""
    i = 0
    while len(out) < n:
        out += hashlib.sha256(KEY + i.to_bytes(8, "big")).digest()
        i += 1
    return out[:n]


def encode(text):
    raw = zlib.compress(text.encode("utf-8"), 9)
    ks = _stream(len(raw))
    return base64.b64encode(bytes(a ^ b for a, b in zip(raw, ks))).decode()


def decode(blob):
    raw = base64.b64decode(blob)
    ks = _stream(len(raw))
    return zlib.decompress(bytes(a ^ b for a, b in zip(raw, ks))).decode("utf-8")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    src, dst = HERE / "tasks", HERE / "tasks.enc"
    if cmd == "encrypt":
        dst.mkdir(exist_ok=True)
        n = 0
        for f in sorted(src.glob("*.yaml")):
            (dst / (f.stem + ".tenc")).write_text(encode(f.read_text()))
            n += 1
        print(f"{n} tasks -> tasks.enc/")
    elif cmd == "decrypt":
        src.mkdir(exist_ok=True)
        n = 0
        for f in sorted(dst.glob("*.tenc")):
            (src / (f.stem + ".yaml")).write_text(decode(f.read_text()))
            n += 1
        print(f"{n} tasks -> tasks/")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
