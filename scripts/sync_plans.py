"""Write the static copies of the plan table (launch plan G-01) from app/core/plans.py.

- site/plans.json: the public plans, for the pricing section without an API call
- the "offers" list in the home page's JSON-LD (search engines read prices from it)

`--check` exits non-zero when either is out of date; the tests call `out_of_date()`. The
/developers/ limits table reads /v1/public/plans live, so it needs nothing here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.plans import PLANS, PUBLIC_PLAN_NAMES, public_view  # noqa: E402

SITE = ROOT / "site"
PLANS_JSON = SITE / "plans.json"
HOME = SITE / "index.html"
_OFFERS = re.compile(r'("offers": \[)(.*?)(\n  \])', re.S)


def plans_json() -> str:
    rows = []
    for name in PUBLIC_PLAN_NAMES:
        view = public_view(PLANS[name])
        view["keys"] = view.pop("max_keys")
        rows.append(view)
    return json.dumps({"data": rows, "source": "app/core/plans.py"}, indent=2) + "\n"


def offers() -> str:
    out = []
    for name in PUBLIC_PLAN_NAMES:
        p = PLANS[name]
        if p.price_usd_per_month is None:
            continue  # priced per contract: no list price to state
        offer = {"@type": "Offer", "name": p.label, "price": str(p.price_usd_per_month),
                 "priceCurrency": "USD"}  # fmt: skip
        if p.price_usd_per_month:
            offer["billingIncrement"] = "P1M"
        out.append("    " + json.dumps(offer))
    return "\n" + ",\n".join(out)


def _home(text: str) -> str:
    return _OFFERS.sub(lambda m: m.group(1) + offers() + m.group(3), text, count=1)


def out_of_date() -> list[str]:
    stale = []
    if not PLANS_JSON.exists() or PLANS_JSON.read_text() != plans_json():
        stale.append(str(PLANS_JSON.relative_to(SITE.parent)))
    text = HOME.read_text()
    if _OFFERS.search(text) and _home(text) != text:
        stale.append(str(HOME.relative_to(SITE.parent)))
    return stale


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        stale = out_of_date()
        for path in stale:
            print(f"out of date: {path}")
        return 1 if stale else 0
    PLANS_JSON.write_text(plans_json())
    HOME.write_text(_home(HOME.read_text()))
    print("plans written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
