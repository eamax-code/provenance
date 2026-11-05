"""Charts and figure tiles for chat answers, built from the cited brief.

A widget is plain JSON that the chat page draws (site/chat.js). Every reported value in it is a
stored SEC fact with its citation; growth rates are computed here from those facts and say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.services import intel, periods

_METRIC_WORDS = [
    ("operating_cash_flow", r"operating cash ?flows?|cash ?flows? from operations|cash ?flows?"),
    ("operating_income", r"operating (?:income|profits?|loss)|ebit"),
    ("net_income", r"net (?:income|profits?|loss|earnings)|profits?|earnings|bottom line"),
    ("total_assets", r"(?:total )?assets"),
    ("revenue", r"revenues?|sales|turnover|top line"),
]
_TREND = re.compile(
    r"\b(growth|grow\w*|grew|trend\w*|histor\w*|years|chart|graph|plot|chang\w*|evolv\w*|"
    r"declin\w*|ris(?:e|en|ing)|fall\w*|fell|over time|year over year|yoy|cagr)\b",
    re.IGNORECASE,
)
_YEARS = re.compile(
    r"\b(?:last|past|previous)\s+(\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:fiscal\s+)?years?\b",
    re.IGNORECASE,
)
_WORD_NUMBERS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10,
}  # fmt: skip
_GROWTH = re.compile(r"\b(growth|grow\w*|grew)\b", re.IGNORECASE)
_FORECAST = re.compile(
    r"\b(forecast\w*|predict\w*|projections?|outlook|estimates?|"
    r"(?:next|coming|following|upcoming)\s+(?:\d{1,2}\s+|[a-z]+\s+)?(?:fiscal\s+)?years?)\b",
    re.IGNORECASE,
)
_NEXT_YEARS = re.compile(
    r"\b(?:next|coming|following|upcoming)\s+(\d{1,2}|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(?:fiscal\s+)?years?\b",
    re.IGNORECASE,
)
_PRICE = re.compile(r"\b(stock|share)\s+price|price target|\bshares? (?:go|trade)\b", re.I)
FORECAST_YEARS = 3
MAX_FORECAST_YEARS = 5
DEFAULT_YEARS = 5
MAX_YEARS = 10


@dataclass(frozen=True)
class Plan:
    """What a question asks for: a metric's trend, one metric, or an overview."""

    kind: str  # "forecast" | "trend" | "metric" | "overview"
    metric: str | None = None
    years: int = DEFAULT_YEARS


def plan(text: str) -> Plan:
    metric = next(
        (m for m, words in _METRIC_WORDS if re.search(rf"\b(?:{words})\b", text, re.IGNORECASE)),
        None,
    )
    if _FORECAST.search(text) and not _PRICE.search(text):
        ahead = _NEXT_YEARS.search(text)
        n = FORECAST_YEARS
        if ahead:
            raw = ahead.group(1).lower()
            n = max(1, min(MAX_FORECAST_YEARS, int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]))
        return Plan("forecast", metric or "revenue", n)
    m = _YEARS.search(text)
    years = DEFAULT_YEARS
    if m:
        raw = m.group(1).lower()
        years = max(2, min(MAX_YEARS, int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]))
    trend = bool(_TREND.search(text) or m)
    if trend and metric:
        return Plan("trend", metric, years)
    if trend and _GROWTH.search(text):  # "How fast is Apple growing?" means revenue
        return Plan("trend", "revenue", years)
    if metric:
        return Plan("metric", metric, years)
    return Plan("overview")


def _pct(cur: float, prev: float | None) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def add_trend(b: intel.Brief, db: Session, metric: str, years: int) -> dict | None:
    """A chart of one metric by fiscal year. Adds a cited context line per year to the brief."""
    # Growth over N years needs N + 1 annual figures: the first is the starting point.
    facts = intel.annual_series(db, b.company.cik, metric, b.as_of)[: years + 1]
    if not facts:
        return None
    facts.reverse()
    label = intel.METRIC_LABELS[metric]
    names = periods.labels([f.period_end for f in facts], "annual", b.company.fiscal_year_end)
    points = []
    for i, f in enumerate(facts):
        prev = float(facts[i - 1].value) if i else None
        points.append(
            {
                "label": names[i],
                "period_end": f.period_end.isoformat(),
                "value": float(f.value),
                "display": intel.money(f.value),
                "change_pct": _pct(float(f.value), prev),
                "form_type": f.form_type,
                "filed_date": f.filed_date.isoformat() if f.filed_date else None,
                "source_url": f.source_url,
            }
        )
    for p in points:
        n = b.cite(
            f"{label}, fiscal year ended {p['period_end']} ({p['form_type']} filed "
            f"{p['filed_date']})",
            p["source_url"],
        )
        p["citation"] = n
        line = f"[{n}] {label}, fiscal year ended {p['period_end']}: {p['display']}"
        if p["change_pct"] is not None:
            line += f"; change from the prior fiscal year {p['change_pct']:+.1f}% (computed here)"
        b.context_lines.append(line + f". Filed {p['filed_date']} ({p['form_type']}).")
    b.context_lines.append(f"Fiscal years of {label.lower()} shown: {len(points)}.")

    first, last = points[0], points[-1]
    span = round(
        (date.fromisoformat(last["period_end"]) - date.fromisoformat(first["period_end"])).days
        / 365.25
    )
    cagr = total = None
    if span >= 1 and first["value"] > 0 and last["value"] > 0:
        cagr = round(((last["value"] / first["value"]) ** (1 / span) - 1) * 100, 1)
    if len(points) > 1:
        total = _pct(last["value"], first["value"])
        b.context_lines.append(
            f"Computed here from [{first['citation']}] and [{last['citation']}]: total change "
            f"{total:+.1f}% over {span} years"
            + (f"; compound annual growth {cagr:+.1f}% a year." if cagr is not None else ".")
        )
    changes = [p for p in points if p["change_pct"] is not None]
    best = max(changes, key=lambda p: p["change_pct"]) if len(changes) > 1 else None
    worst = min(changes, key=lambda p: p["change_pct"]) if len(changes) > 1 else None

    stats = [
        {
            "label": f"Latest ({last['label']})",
            "value": last["display"],
            "change_pct": last["change_pct"],
            "sub": f"Fiscal year ended {last['period_end']}",
            "citation": last["citation"],
        }
    ]
    if cagr is not None:
        stats.append(
            {
                "label": "Compound annual growth",
                "value": f"{cagr:+.1f}%",
                "sub": f"{first['label']} to {last['label']}, computed here",
            }
        )
    elif total is not None:
        stats.append(
            {
                "label": "Total change",
                "value": f"{total:+.1f}%",
                "sub": f"{first['label']} to {last['label']}, computed here",
            }
        )
    if best is not None and worst is not None:
        stats.append(
            {
                "label": "Best year",
                "value": f"{best['change_pct']:+.1f}%",
                "sub": best["label"],
                "citation": best["citation"],
            }
        )
        stats.append(
            {
                "label": "Weakest year",
                "value": f"{worst['change_pct']:+.1f}%",
                "sub": worst["label"],
                "citation": worst["citation"],
            }
        )
    return {
        "type": "chart",
        "metric": metric,
        "title": f"{label} by fiscal year",
        "unit": "USD",
        "points": points,
        "stats": stats,
        "summary": {
            "years_requested": years,
            "years_shown": len(points) - 1,
            "span_years": span,
            "total_change_pct": total,
            "cagr_pct": cagr,
            "best": best and {"label": best["label"], "change_pct": best["change_pct"]},
            "worst": worst and {"label": worst["label"], "change_pct": worst["change_pct"]},
        },
        "note": (
            "Bars are the figures reported in each annual report; the line is the change from "
            "the prior fiscal year, computed here."
        ),
    }


def trend_answer(b: intel.Brief, metric: str, chart: dict | None) -> str:
    """A metric's trend told from the chart's cited figures; no model needed."""
    label = intel.METRIC_LABELS[metric]
    name = intel.display_name(b.company.legal_name)
    if chart is None:
        return f"No annual {label.lower()} figures for {name} are loaded in this service [1]."
    pts, s = chart["points"], chart["summary"]
    first, last = pts[0], pts[-1]
    if len(pts) == 1:
        return (
            f"Only one fiscal year of {label.lower()} is loaded for {name}: {last['display']} "
            f"in the fiscal year ended {last['period_end']} [{last['citation']}]."
        )
    went = "rose" if last["value"] > first["value"] else "fell"
    lines = [
        f"{name}'s {label.lower()} {went} from {first['display']} in the fiscal year ended "
        f"{first['period_end']} [{first['citation']}] to {last['display']} in the fiscal year "
        f"ended {last['period_end']} [{last['citation']}]"
        + (
            f", compound annual growth of {s['cagr_pct']:+.1f}% a year over {s['span_years']} "
            "years."
            if s["cagr_pct"] is not None
            else f", a total change of {s['total_change_pct']:+.1f}%."
        )
    ]
    if s["best"] and s["worst"]:
        best = next(p for p in pts if p["label"] == s["best"]["label"])
        worst = next(p for p in pts if p["label"] == s["worst"]["label"])
        lines.append(
            f"Strongest year: {best['change_pct']:+.1f}% in the fiscal year ended "
            f"{best['period_end']} [{best['citation']}]. Weakest: {worst['change_pct']:+.1f}% "
            f"in the fiscal year ended {worst['period_end']} [{worst['citation']}]."
        )
    if last["change_pct"] is not None and last["label"] not in (
        (s["best"] or {}).get("label"),
        (s["worst"] or {}).get("label"),
    ):
        lines.append(f"Latest year: {last['change_pct']:+.1f}% [{last['citation']}].")
    if s["years_shown"] < s["years_requested"]:
        lines.append(f"Only {len(pts)} fiscal years are loaded here for {name}.")
    lines.append("Growth rates are computed here from the cited annual figures.")
    return "\n".join(lines)


def overview(b: intel.Brief) -> dict | None:
    """Tiles for the latest annual figures, each with its change and a small history line."""
    if not b.metrics:
        return None
    return {
        "type": "stats",
        "title": "Latest annual figures",
        "items": [
            {
                "metric": m["metric"],
                "label": m["label"],
                "value": m["display"],
                "change_pct": m["growth_pct"],
                "sub": f"FY ended {m['period_end']}",
                "citation": m["citation"],
                "spark": [h["value"] for h in reversed(m["history"])],
            }
            for m in b.metrics
        ],
    }
