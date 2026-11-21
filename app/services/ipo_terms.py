"""IPO deal terms from the prospectus (launch plan F-02): price range, final price, shares
offered (new and sold by holders), gross proceeds, underwriting discount, exchange and ticker,
underwriters, lock-up and closing date.

Rules on the cover page and the Underwriting section, never a model. Every value carries the
verbatim sentence or table row it came from; a value without evidence is not returned. Dates
computed from a rule (lock-up expiry, quiet period end) say they are derived.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

EXTRACTOR_VERSION = "ipo-terms-1"
QUIET_PERIOD_DAYS = 25  # research quiet period after an IPO (FINRA Rule 2241)

_NUM = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
_MONEY = rf"\$\s?({_NUM})"
_SENT = re.compile(r"[^.;\n]*(?:\.(?=\d)[^.;\n]*)*[.;]?")


def _n(text: str) -> float:
    return float(text.replace(",", ""))


def _flat(text: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", " ", text or "")


_END = re.compile(r"[.!?][”\"’)]?\s+(?=[A-Z“\"(])|\n|\s\|\s")


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence around [start, end): from the previous sentence end (a full stop, a line
    break or a table cell edge) to the next one."""
    left = 0
    for m in _END.finditer(text, 0, start):
        left = m.end()
    nxt = _END.search(text, end)
    right = nxt.start() + 1 if nxt else len(text)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _find(pattern: str, text: str, flags=re.IGNORECASE):
    return re.search(pattern, text, flags)


def _value(fields: dict, key: str, value, evidence: str, derived: bool = False) -> None:
    if value is None or not evidence:
        return
    fields[key] = {"value": value, "evidence": evidence, "derived": derived}


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(re.sub(r"\s+", " ", text.strip()), "%B %d, %Y").date()
    except ValueError:
        return None


def extract(
    cover: str,
    underwriting: str = "",
    form_type: str = "",
    filed: date | None = None,
    summary: str = "",
):
    """{field: {"value", "evidence", "derived"}} from a prospectus's cover and Underwriting."""
    fields: dict = {}
    flat = _flat(cover)
    rows = cover.split("\n")

    # Price: the final price on a 424B4; the expected range on an S-1/A.
    m = _find(rf"(?:initial )?public offering price (?:per share )?(?:is|of) {_MONEY}", flat)
    if m:
        _value(fields, "price_final", _n(m.group(1)), _sentence(flat, m.start(), m.start(1)))
    m = _find(rf"offering price[^.]{{0,80}}?between {_MONEY} and {_MONEY}", flat)
    if m:
        ev = _sentence(flat, m.start(), m.end())
        _value(fields, "price_low", _n(m.group(1)), ev)
        _value(fields, "price_high", _n(m.group(2)), ev)

    # Shares offered: "We are selling X shares ... the selling stockholders ... an additional Y"
    m = _find(rf"we are (?:selling|offering) ({_NUM}) shares", flat)
    if m:
        _value(fields, "shares_primary", _n(m.group(1)), _sentence(flat, m.start(), m.end()))
    m = _find(rf"selling (?:stockholders|shareholders)[^.]*? (?:are )?(?:selling|offering) "
              rf"(?:an additional )?({_NUM}) shares", flat)  # fmt: skip
    if m:
        _value(fields, "shares_secondary", _n(m.group(1)), _sentence(flat, m.start(), m.end()))
    m = _find(rf"(?:^|\|)\s*({_NUM}) (?:American Depositary )?Shares\b", cover, re.M)
    if m:
        row = next((r for r in rows if m.group(1) in r and "Shares" in r), m.group(0))
        _value(fields, "shares_offered", _n(m.group(1)), row.strip())
    elif "shares_primary" in fields:
        total = fields["shares_primary"]["value"] + fields.get("shares_secondary", {}).get(
            "value", 0
        )
        _value(fields, "shares_offered", total, fields["shares_primary"]["evidence"], True)

    # Cover table rows: price, discount, proceeds
    for row in rows:
        cells = [c.strip() for c in row.split("|")]
        if len(cells) < 3:
            continue
        head = cells[0].lower()
        money = [c for c in cells[1:] if re.fullmatch(rf"\$?\s?(?:{_NUM})", c.replace("$ ", "$"))]
        if len(money) < 2:
            continue
        per, total = _n(money[0].lstrip("$ ")), _n(money[-1].lstrip("$ "))
        if "public offering price" in head or head.startswith("price to public"):
            _value(fields, "gross_proceeds", total, row.strip())
            _value(fields, "price_final", per, row.strip()) if "price_final" not in fields else None
        elif "underwriting discount" in head:
            _value(fields, "underwriting_discount_per_share", per, row.strip())
            _value(fields, "underwriting_discount_total", total, row.strip())

    # Exchange and ticker
    m = _find(r"(?:list|listed|listing|quoted)[^.]*? on (?:the )?((?:Nasdaq|NYSE|New York Stock "
              r"Exchange|NYSE American)[A-Za-z ]*?) under the (?:trading )?symbol "
              r"[“\"']([A-Z.]{1,6})[.”\"']", flat)  # fmt: skip
    if m:
        ev = _sentence(flat, m.start(), m.start(2))
        _value(fields, "exchange", m.group(1).strip(), ev)
        _value(fields, "ticker", m.group(2).rstrip("."), ev)

    # Closing: "expect to deliver the shares ... on or about November 20, 2026"
    m = _find(r"deliver the shares[^.]*? on or about ([A-Z][a-z]+ \d{1,2}, \d{4})", flat)
    if m and (d := _parse_date(m.group(1))):
        _value(fields, "closing_date", d.isoformat(), _sentence(flat, m.start(), m.end()))

    # Underwriters: the Underwriting section's table of underwriters and share counts
    uw = underwriting or ""
    names = []
    for line in uw.split("\n"):
        cells = [c.strip() for c in line.split("|")]
        if len(cells) == 2 and re.fullmatch(_NUM, cells[1]) and cells[0] and cells[0] != "Total":
            if not re.search(r"\d", cells[0]):
                names.append(cells[0])
    if names:
        _value(fields, "underwriters", names, "Underwriting table: " + "; ".join(names))
    flat_uw = _flat(uw)
    m = _find(r"representatives? of the (?:several )?underwriters", flat_uw)
    if m and names:
        # the sentence naming the representatives; names hold "Co." so search the names in it
        window = flat_uw[max(0, m.start() - 400) : m.end()]
        leads = [n for n in names if n in window]
        if leads:
            start = min(window.find(n) for n in leads)
            ev = re.sub(r"\s+", " ", window[start:]).strip()
            _value(fields, "lead_underwriters", leads, ev)

    # Lock-up: the period most often stated as "for a period of N days after the date of this
    # prospectus" (early-release schedules name many other day counts), and any longer period
    # stated with it ("up to 180 days or, for co-founders, up to 365 days").
    text = " ".join(_flat(x) for x in (summary, uw, cover))
    pattern = re.compile(
        r"(?:period of|for)(?: up to)? (\d{2,3}) days"
        r"(?:(?:(?!\. ).){0,240}?up to (\d{2,3}) days)? (?:after|following) the date of this "
        r"prospectus",
        re.IGNORECASE,
    )
    counts: dict[int, int] = {}
    longer: list[int] = []
    first_ev: dict[int, str] = {}
    for m in pattern.finditer(text):
        sentence = _sentence(text, m.start(), m.end())
        if not re.search(r"lock-?\s?up|market standoff|without the prior written consent", sentence,
                         re.IGNORECASE):  # fmt: skip
            continue
        d = int(m.group(1))
        if 60 <= d <= 730:
            counts[d] = counts.get(d, 0) + 1
            first_ev.setdefault(d, sentence)
        if m.group(2):
            longer.append(int(m.group(2)))
    if counts:
        main = max(counts, key=lambda d: (counts[d], -d))
        _value(fields, "lockup_days", main, first_ev[main][:600])
        if longer and max(longer) > main:
            ev = next((first_ev[d] for d in first_ev if str(max(longer)) in first_ev[d]), "")
            ev = ev or next(m.group(0) for m in pattern.finditer(text) if m.group(2))
            _value(fields, "lockup_days_max", max(longer), ev[:600])

    if form_type.upper().startswith("424B") and filed:
        if "lockup_days" in fields:
            expiry = filed + timedelta(days=fields["lockup_days"]["value"])
            _value(fields, "lockup_expiry", expiry.isoformat(),
                   f"Derived: prospectus dated {filed.isoformat()} plus "
                   f"{fields['lockup_days']['value']} days", True)  # fmt: skip
        quiet = filed + timedelta(days=QUIET_PERIOD_DAYS)
        _value(fields, "quiet_period_end", quiet.isoformat(),
               f"Derived: prospectus dated {filed.isoformat()} plus {QUIET_PERIOD_DAYS} days "
               "(FINRA Rule 2241 research quiet period)", True)  # fmt: skip
    if fields.get("price_final") or fields.get("price_low"):
        _value(fields, "currency", "USD", (fields.get("price_final") or fields["price_low"])[
            "evidence"])  # fmt: skip
    return fields


# -- storage ------------------------------------------------------------------------------------

PRICE_FIELDS = ("price_low", "price_high", "price_final", "currency", "gross_proceeds")


def _documents(db, cik: str) -> list:
    """The filings to read for a company going public: its final prospectus (424B4) and its
    latest registration amendment (where the price range is), from the IPO milestones."""
    from sqlalchemy import select

    from app.db.models import Filing
    from app.services import ipo_pipeline

    filings = db.scalars(
        select(Filing)
        .where(Filing.cik == cik, Filing.form_type.in_(ipo_pipeline.FORMS + ipo_pipeline.REPORTS))
        .order_by(Filing.filing_date, Filing.accession_number)
    ).all()
    track = ipo_pipeline._track(list(filings))
    if not track:
        return []
    ms = track["milestones"]
    wanted = {ms[k]["accession_number"] for k in ("priced", "filed") if k in ms}
    # the latest S-1/A or F-1/A up to pricing holds the price range (an S-1MEF only upsizes)
    until = ms["priced"]["filing_date"] if "priced" in ms else date.max
    start = ms["filed"]["filing_date"] if "filed" in ms else date.min
    amendments = [f for f in filings if f.form_type in ("S-1/A", "F-1/A")
                  and start <= f.filing_date <= until]  # fmt: skip
    if amendments:
        wanted.add(amendments[-1].accession_number)
    return [f for f in filings if f.accession_number in wanted]


def read_company(db, cik: str, sec) -> int:
    """Read and store deal terms for one company going public. Returns documents extracted.
    With `sec` None only documents already stored are used (the demo never fetches)."""
    import json

    from sqlalchemy import delete, select

    from app.db.models import FilingSection, IpoTerms, utcnow
    from app.services import prospectus

    done = 0
    for f in _documents(db, cik):
        have = db.scalar(select(IpoTerms).where(IpoTerms.accession_number == f.accession_number))
        if have is not None and have.extractor_version == EXTRACTOR_VERSION:
            continue
        rows = {r.item: r for r in prospectus.stored_sections(db, f.accession_number)}
        if rows and prospectus.COVER_ITEM not in rows and sec is not None:
            # read before the cover was kept: read the document again, once
            db.execute(delete(FilingSection).where(
                FilingSection.accession_number == f.accession_number))  # fmt: skip
            db.commit()
            rows = {}
        if not rows:
            prospectus.ensure_read(db, f, sec)
            rows = {r.item: r for r in prospectus.stored_sections(db, f.accession_number)}
        cover = rows.get(prospectus.COVER_ITEM)
        if cover is None or not cover.text:
            continue
        uw, summ = rows.get("pr:uw"), rows.get("pr:summ")
        fields = extract(cover.text, uw.text if uw else "", f.form_type, f.filing_date,
                         summ.text if summ else "")  # fmt: skip
        if have is None:
            have = IpoTerms(cik=cik, accession_number=f.accession_number)
            db.add(have)
        have.form_type, have.filing_date = f.form_type, f.filing_date
        have.source_url = cover.source_url or f.source_url
        have.terms = json.dumps(fields)
        have.extractor_version = EXTRACTOR_VERSION
        have.extracted_at = utcnow()
        done += 1
    db.commit()
    return done


def terms_by_cik(db, ciks: list[str]) -> dict[str, dict]:
    """Merged deal terms per company: the final prospectus first, then the latest amendment;
    each value keeps its evidence and the filing it came from."""
    import json

    from sqlalchemy import select

    from app.db.models import IpoTerms

    if not ciks:
        return {}
    rows = db.scalars(select(IpoTerms).where(IpoTerms.cik.in_(ciks))).all()
    out: dict[str, dict] = {}
    rank = {"424B4": 0, "S-1/A": 1, "F-1/A": 1, "S-1": 2, "F-1": 2}
    for r in sorted(rows, key=lambda r: (rank.get(r.form_type, 3), -(r.filing_date or date.min)
                                         .toordinal())):  # fmt: skip
        merged = out.setdefault(r.cik, {})
        for key, v in json.loads(r.terms).items():
            if key not in merged:
                merged[key] = {**v, "form_type": r.form_type,
                               "filing_date": r.filing_date.isoformat() if r.filing_date else None,
                               "source_url": r.source_url}  # fmt: skip
    return out


def flat(terms: dict | None) -> dict:
    """The price fields as plain values (null when not read), for compact lists."""
    terms = terms or {}
    return {k: (terms[k]["value"] if k in terms else None) for k in PRICE_FIELDS}


# -- chat (C-01) --------------------------------------------------------------------------------

_TERMS_Q = re.compile(
    r"\b(ipo terms?|terms of (?:the|its) (?:ipo|offering)|ipo price|price range|priced|"
    r"offering price|underwr\w*|lock-?ups?|raised?|proceeds|shares (?:offered|sold)|"
    r"deal terms?|ipo)\b",
    re.IGNORECASE,
)
_NOT_TERMS = re.compile(r"\b(risk|business|compet\w*|revenue|customers?|strategy|dilution)\b",
                        re.IGNORECASE)  # fmt: skip


def is_terms_question(text: str) -> bool:
    return bool(_TERMS_Q.search(text)) and not _NOT_TERMS.search(text)


def _usd(v: float) -> str:
    for div, word in ((1e9, "billion"), (1e6, "million")):
        if abs(v) >= div:
            return f"${v / div:,.1f} {word}"
    return f"${v:,.2f}"


def chat_answer(name: str, terms: dict) -> tuple[str, list[dict]]:
    """A data-first answer from stored deal terms; every sentence cites its filing."""
    from app.services.form_names import form_label, form_phrase, human_date

    cites: list[dict] = []

    def cite(field: str) -> str:
        t = terms[field]
        label = f"{t['form_type']} filed {human_date(t['filing_date'])}"
        for c in cites:
            if c["url"] == t["source_url"]:
                return f"[{c['n']}]"
        cites.append({"n": len(cites) + 1, "label": label, "url": t["source_url"],
                      "what": form_phrase(t["form_type"])})  # fmt: skip
        return f"[{len(cites)}]"

    def v(field):
        return terms[field]["value"] if field in terms else None

    out = []
    if v("price_final") is not None:
        s = (f"{name} priced its IPO at ${v('price_final'):,.2f} a share in "
             f"{form_phrase('424B4')} filed {human_date(terms['price_final']['filing_date'])}"
             f" {cite('price_final')}")  # fmt: skip
        if v("price_low") is not None and v("price_high") is not None:
            lo, hi, p = v("price_low"), v("price_high"), v("price_final")
            where = "above" if p > hi else "below" if p < lo else "within"
            rng = terms["price_low"]
            doc = form_label(rng["form_type"])
            s += (f", {where} the ${lo:,.2f} to ${hi:,.2f} range in its {doc[0].lower()}{doc[1:]}"
                  f" filed {human_date(rng['filing_date'])} {cite('price_low')}")  # fmt: skip
        out.append(s + ".")
    elif v("price_low") is not None:
        out.append(f"{name} expects to price its IPO between ${v('price_low'):,.2f} and "
                   f"${v('price_high'):,.2f} a share {cite('price_low')}.")  # fmt: skip
    if v("shares_offered"):
        s = f"It offered {v('shares_offered'):,.0f} shares"
        if v("shares_primary") and v("shares_secondary"):
            s += (f": {v('shares_primary'):,.0f} new and {v('shares_secondary'):,.0f} sold by "
                  "existing holders")  # fmt: skip
        out.append(f"{s} {cite('shares_offered')}.")
    if v("gross_proceeds"):
        s = f"Gross proceeds were {_usd(v('gross_proceeds'))}"
        if v("underwriting_discount_total"):
            s += f", before an underwriting discount of {_usd(v('underwriting_discount_total'))}"
        out.append(f"{s} {cite('gross_proceeds')}.")
    if v("lead_underwriters"):
        leads = v("lead_underwriters")
        n = len(v("underwriters") or [])
        lead_text = (
            " and ".join(leads) if len(leads) < 3 else ", ".join(leads[:-1]) + ", and " + leads[-1]
        )
        out.append(f"{lead_text} led {'the ' + str(n) + ' underwriters' if n else 'the offering'} "
                   f"{cite('lead_underwriters')}.")  # fmt: skip
    if v("exchange") and v("ticker"):
        out.append(f"The shares list on the {v('exchange')} as {v('ticker')} {cite('ticker')}.")
    if v("lockup_days"):
        s = f"The lock-up runs {v('lockup_days')} days"
        if v("lockup_days_max"):
            s += f" ({v('lockup_days_max')} for some holders)"
        if v("lockup_expiry"):
            s += (f", to {human_date(v('lockup_expiry'))}, a date derived from the "
                  "prospectus date")  # fmt: skip
        out.append(f"{s} {cite('lockup_days')}.")
    return " ".join(out), cites
