"""Generate site/app/base.css: the rules of site/app/app.css that chat and the IPO page can use (UI-T1).

app.css stays the one source and every other page loads it whole, so their cascade is unchanged. base.css is
derived from it for the two pages that need only a slice: a rule is kept when, for some selector in its list, every
class it names appears in those pages' sources (prov-card.js included, which chat loads on the first figure tap);
at-rules other than @media/@supports are kept whole, and @media/@supports blocks keep only their kept rules. Order
is app.css's own.

    python scripts/build_base_css.py           # write site/app/base.css
    python scripts/build_base_css.py --check   # exit 1 if base.css is not what app.css gives (after an edit)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"
SOURCES = ("chat.js", "chat/index.html", "prov-card.js", "chat.css",
           "ipos/ipos.js", "ipos/index.html", "ipos/ipos.css")
HEADER = ("/* GENERATED from app/app.css by scripts/build_base_css.py: do not edit; edit app.css and run it.\n"
          "   The rules chat and the IPO page can use (UI-T1); every other page loads app.css whole. */\n")
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def blocks(css: str) -> list[str]:
    out, level, acc = [], 0, ""
    for t in re.split(r"([{}])", css):
        acc += t
        if t == "{":
            level += 1
        elif t == "}":
            level -= 1
            if level == 0:
                out.append(acc)
                acc = ""
    return out


def classes(selector: str) -> set[str]:
    return set(re.findall(r"\.([a-zA-Z][\w-]*)", selector))


def keep(block: str, used: set[str]) -> str:
    head = COMMENT.sub("", block[: block.index("{")]).strip()
    if head.startswith(("@media", "@supports")):
        inner = block[block.index("{") + 1: block.rindex("}")]
        kept = "".join(k for k in (keep(b, used) for b in blocks(inner)) if k)
        return f"{head} {{{kept}\n}}\n" if kept else ""
    if head.startswith("@"):
        return COMMENT.sub("", block).strip() + "\n"
    if any(classes(s) <= used for s in head.split(",")):
        return COMMENT.sub("", block).strip() + "\n"
    return ""


def build() -> str:
    css = (SITE / "app" / "app.css").read_text()
    used = set(re.findall(r"[\w-]+", "".join((SITE / f).read_text() for f in SOURCES)))
    return HEADER + "".join(k for k in (keep(b, used) for b in blocks(css)) if k)


def main() -> int:
    out, path = build(), SITE / "app" / "base.css"
    if "--check" in sys.argv:
        ok = path.exists() and path.read_text() == out
        print("base.css is up to date" if ok else "base.css is stale: run scripts/build_base_css.py")
        return 0 if ok else 1
    path.write_text(out)
    print(f"wrote {path.relative_to(SITE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
