#!/usr/bin/env python3
"""Copy the shared MTF engine block from the indicator into the strategy.

The engine lives between these marker lines in both Pine files:
    // ==== ENGINE START (keep in sync) ====
    // ==== ENGINE END (keep in sync) ====
Pine cannot import a local file without publishing a library, so the block is duplicated.
Edit it in trading_context_pack.pine, then run:  python3 tools/sync_engine.py
Run with --check to only verify the two copies match (exit code 1 if they differ).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "trading_context_pack.pine"
DST = ROOT / "mtf_zone_strategy.pine"
START = "// ==== ENGINE START (keep in sync) ===="
END = "// ==== ENGINE END (keep in sync) ===="


def block(text: str, name: str) -> tuple[int, int]:
    if text.count(START) != 1 or text.count(END) != 1:
        sys.exit(f"{name}: expected exactly one ENGINE START and one ENGINE END marker")
    a = text.index(START)
    b = text.index(END) + len(END)
    if b <= a:
        sys.exit(f"{name}: ENGINE END comes before ENGINE START")
    return a, b


def main() -> int:
    src = SRC.read_text()
    dst = DST.read_text()
    sa, sb = block(src, SRC.name)
    da, db = block(dst, DST.name)
    engine = src[sa:sb]
    if dst[da:db] == engine:
        print("engine blocks already in sync")
        return 0
    if "--check" in sys.argv:
        print("engine blocks differ -- run: python3 tools/sync_engine.py")
        return 1
    DST.write_text(dst[:da] + engine + dst[db:])
    print(f"copied engine block ({engine.count(chr(10)) + 1} lines) into {DST.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
