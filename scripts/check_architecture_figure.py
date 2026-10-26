#!/usr/bin/env python3
"""Check the architecture figure against the package's real import graph.

The architecture diagram, docs/architecture.svg, is drawn by hand rather than
plotted, which makes it easy to get wrong when the code changes. This script
reads the arrows straight out of the SVG and compares them with the imports it
finds in src/calrcpsp.

It fails if an arrow points at the wrong module, if a real dependency has no
arrow, or if a connector crosses a box it does not belong to.

    python scripts/check_architecture_figure.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SVG = REPO / "docs" / "architecture.svg"
SRC = REPO / "src" / "calrcpsp"

#: Where each module sits in the drawing, as (x0, y0, x1, y1).
BOXES = {
    "cli": (170, 42, 500, 170), "scripts": (595, 42, 925, 170),
    "instance": (90, 272, 360, 400), "assignment": (395, 272, 665, 400),
    "calendar": (700, 272, 970, 400), "maxplus": (170, 470, 500, 598),
    "scheduler": (595, 470, 925, 598), "metrics": (90, 668, 360, 796),
    "schedule": (395, 668, 665, 796), "reschedule": (700, 668, 970, 796),
}

#: Drawn deliberately against the import direction, because it is a call the
#: figure labels "re-solve" rather than a flow of data.
CALLS = {("reschedule", "scheduler")}

#: Imports where the arrow belongs the other way round. An import of a type
#: that the importer then builds is not a flow of data into the importer: the
#: data comes out of it. scheduler.py imports Schedule in order to return one,
#: so the figure correctly draws scheduler -> schedule.
CONSTRUCTS = {("schedule", "scheduler"): ("scheduler", "schedule")}

#: Edges the figure may leave out: they are implied by a path already drawn,
#: and drawing them all would make the picture unreadable.
IMPLIED = {
    ("instance", "scheduler"), ("instance", "schedule"), ("instance", "reschedule"),
    ("assignment", "scheduler"), ("assignment", "schedule"),
    ("calendar", "schedule"), ("schedule", "scheduler"), ("metrics", "schedule"),
    ("scheduler", "reschedule"),
    ("instance", "cli"), ("scheduler", "cli"), ("metrics", "cli"),
    ("reschedule", "cli"),
}


def imports() -> set[tuple[str, str]]:
    """Data-flow edges: (a, b) when module b imports module a."""
    edges = set()
    for path in SRC.glob("*.py"):
        if path.stem == "__init__":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                edges.add((node.module, path.stem))
    return edges


def _at(x: float, y: float, tol: float = 16) -> str:
    for name, (x0, y0, x1, y1) in BOXES.items():
        if x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol:
            return name
    return "none"


def _segments(d: str):
    x = y = None
    out = []
    for cmd, arg in re.findall(r"([MLHV])\s*([-\d.,\s]*)", d):
        nums = [float(v) for v in re.findall(r"-?[\d.]+", arg)]
        if cmd == "M":
            x, y = nums[0], nums[1]
            continue
        nx, ny = (nums[0], y) if cmd == "H" else ((x, nums[0]) if cmd == "V"
                                                  else (nums[0], nums[1]))
        out.append((x, y, nx, ny))
        x, y = nx, ny
    return out


def _crosses(seg, skip) -> str | None:
    x0, y0, x1, y1 = seg
    for name, (bx0, by0, bx1, by1) in BOXES.items():
        if name in skip:
            continue
        if x0 == x1 and bx0 < x0 < bx1 and min(y0, y1) < by1 and max(y0, y1) > by0:
            return name
        if y0 == y1 and by0 < y0 < by1 and min(x0, x1) < bx1 and max(x0, x1) > bx0:
            return name
    return None


def drawn() -> tuple[set[tuple[str, str]], list[str]]:
    svg = SVG.read_text(encoding="utf-8")
    edges, faults = set(), []
    for m in re.finditer(r'<path d="([^"]+)"([^>]*)/>', svg):
        d, attrs = m.group(1), m.group(2)
        if "marker-end" not in attrs or "dasharray" in attrs:
            continue
        segs = _segments(d)
        if not segs:
            continue
        a = _at(segs[0][0], segs[0][1])
        b = _at(segs[-1][2], segs[-1][3])
        if a == "none" and b == "none":
            continue
        if a == "none" or b == "none":
            faults.append(f"connector {d!r} does not join two modules")
            continue
        edges.add((a, b))
        hit = next((h for s in segs if (h := _crosses(s, {a, b}))), None)
        if hit:
            faults.append(f"the {a} to {b} connector crosses {hit}")
    return edges, faults


def main() -> int:
    real, (shown, faults) = imports(), drawn()
    for wrong_way, right_way in CONSTRUCTS.items():
        if wrong_way in real:
            real.discard(wrong_way)
            real.add(right_way)
    flow = shown - CALLS
    wrong = [e for e in flow if e not in real]
    missing = [e for e in real if e not in flow and e not in IMPLIED]

    for e in sorted(flow):
        print(f"  ok    {e[0]} -> {e[1]}")
    for e in sorted(shown & CALLS):
        print(f"  call  {e[0]} -> {e[1]} (labelled in the figure)")
    for e in sorted(wrong):
        print(f"  WRONG {e[0]} -> {e[1]} is drawn but {e[1]} does not import {e[0]}")
    for e in sorted(missing):
        print(f"  MISSING {e[0]} -> {e[1]} is a real import with no arrow")
    for f in faults:
        print(f"  FAULT {f}")

    bad = len(wrong) + len(missing) + len(faults)
    print(f"\n{'figure matches the code' if not bad else str(bad) + ' problem(s)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
