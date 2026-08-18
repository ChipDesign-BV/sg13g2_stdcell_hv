#!/usr/bin/env python3
"""Pandoc filter: render TeX math to SVG with matplotlib mathtext.

Lets the HTML/PDF flow show real math without a LaTeX engine or network — each
Math element becomes an <img> referencing a cached SVG in _mathcache/.
WeasyPrint renders the SVG natively (it cannot lay out MathML)."""
import sys, json, os, hashlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CACHE = "_mathcache"
FONTSIZE = 11.0

def render(tex, display):
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.md5((("D:" if display else "I:") + tex).encode()).hexdigest()[:16]
    path = os.path.join(CACHE, key + ".svg")
    if not os.path.exists(path):
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${tex}$", fontsize=FONTSIZE * (1.25 if display else 1.0))
        # a small pad keeps tight bboxes from clipping fraction bars and
        # descenders (the K_p fraction lost its lower digits at pad 0)
        fig.savefig(path, format="svg", bbox_inches="tight",
                    pad_inches=0.02 if display else 0.005, transparent=True)
        plt.close(fig)
    return path

def walk(obj):
    if isinstance(obj, list):
        return [walk(x) for x in obj]
    if isinstance(obj, dict):
        if obj.get("t") == "Math":
            display = obj["c"][0]["t"] == "DisplayMath"
            tex = obj["c"][1]
            try:
                path = render(tex, display)
            except Exception as e:
                sys.stderr.write(f"[texmath_svg] could not render: {tex!r}: {e}\n")
                return obj
            cls = "math-display" if display else "math-inline"
            return {"t": "Image", "c": [["", [cls], []], [], [path, tex]]}
        return {k: walk(v) for k, v in obj.items()}
    return obj

doc = json.load(sys.stdin)
json.dump(walk(doc), sys.stdout)
