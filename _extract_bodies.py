#!/usr/bin/env python3
"""Extract English page bodies from _source.html into _source_bodies.json.

Each entry maps page ID -> inner HTML of the page <div>. Used as the source
of truth that translation subagents consume.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "_source.html"
OUT = ROOT / "_source_bodies.json"

PAGE_START_RE = re.compile(
    r'<div\s+id="([^"]+)"\s+class="page[^"]*"\s+'
    r'data-title="[^"]*"\s+'
    r'data-description="[^"]*"\s+'
    r'data-slug="[^"]*">',
    re.IGNORECASE,
)


def extract_block(source: str, start: int) -> tuple[str, int]:
    i = start
    depth = 0
    open_re = re.compile(r"<div\b", re.IGNORECASE)
    close_re = re.compile(r"</div>", re.IGNORECASE)
    n = len(source)
    while i < n:
        o = open_re.search(source, i)
        c = close_re.search(source, i)
        if c is None:
            sys.exit("unbalanced <div>")
        if o is not None and o.start() < c.start():
            depth += 1
            i = o.end()
        else:
            depth -= 1
            i = c.end()
            if depth == 0:
                return source[start:i], i
    sys.exit("unbalanced <div>")


def main() -> None:
    src = SOURCE.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    for m in PAGE_START_RE.finditer(src):
        pid = m.group(1)
        block, _ = extract_block(src, m.start())
        opening_end = src.index(">", m.start()) + 1
        inner_end = block.rfind("</div>")
        inner = block[opening_end - m.start() : inner_end].strip("\n")
        bodies[pid] = inner
    OUT.write_text(json.dumps(bodies, ensure_ascii=False, indent=2), encoding="utf-8")
    total_chars = sum(len(v) for v in bodies.values())
    print(f"wrote {OUT.name} with {len(bodies)} page bodies ({total_chars:,} chars)")


if __name__ == "__main__":
    main()
