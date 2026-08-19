#!/usr/bin/env python3
"""Fail if anything in a rendered report runs past the text column.

A PDF has no scrollbar. `overflow-x: auto` on a code block, which is the
sensible thing on screen, silently CLIPS on paper -- and a truncated shell
command reads exactly like a complete one, so the reader has no way to tell.
Estimating "how many characters fit" from the font metrics is guesswork; this
renders the real document and measures the real boxes.

Walks the laid-out box tree of every page and reports any box whose right edge
crosses the body's content edge. Run from build.sh after each render.

Usage:  ./fitcheck.py <file.html> [...]      (exit 1 if anything overflows)
"""
import sys
import pathlib
from weasyprint import HTML

TOL = 0.5          # px; sub-pixel rounding in the layout engine


def boxes(box):
    yield box
    for child in getattr(box, "children", None) or []:
        yield from boxes(child)


def text_of(box):
    return getattr(box, "text", "") or ""


def check(path):
    doc = HTML(str(path), base_url=str(pathlib.Path(path).parent)).render()
    bad = []
    for n, page in enumerate(doc.pages, 1):
        # The page box's children are the body flow plus the @page margin
        # boxes (running header/footer). Only the flow is subject to the
        # text column, so take the first child as the body root.
        kids = getattr(page._page_box, "children", None) or []
        if not kids:
            continue
        body = kids[0]
        right = body.position_x + body.width
        for b in boxes(body):
            x = getattr(b, "position_x", None)
            w = getattr(b, "width", None)
            if x is None or not isinstance(w, (int, float)):
                continue
            if x + w > right + TOL:
                bad.append((n, round(x + w - right, 1),
                            type(b).__name__, text_of(b)[:60]))
    return bad


def main(argv):
    rc = 0
    for f in argv:
        bad = check(f)
        name = pathlib.Path(f).name
        if not bad:
            print(f"    fit: {name} OK -- nothing past the text column")
            continue
        rc = 1
        print(f"    fit: {name} FAIL -- {len(bad)} box(es) overflow:")
        for page, over, kind, txt in bad[:20]:
            print(f"      p{page} +{over}px {kind}: {txt!r}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
