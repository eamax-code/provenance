"""Subsidiaries listed in a 10-K's exhibit 21 (a 20-F's exhibit 8), GH #24 and ADR 0011.

Regulation S-K item 601(b)(21) requires a list of the registrant's significant subsidiaries
with each one's state or other jurisdiction of incorporation. The exhibit has no fixed layout:
most are an HTML table (name | jurisdiction, sometimes with an ownership column), some are lines
of text ("Foo LLC (Delaware)", "Foo Ltd. ........ Ireland"). The parser reads tables first and
falls back to lines; every row keeps the exhibit's URL so it can be checked against the source.
The latest two lists are kept, so the API can say which subsidiaries are new this year.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import date

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import Filing, GraphSourceState, Subsidiary, utcnow
from app.services.sec_client import SecClient, SecClientError, SecNotFound, normalize_cik

logger = logging.getLogger("app.subsidiaries")

ANNUAL_FORMS = ("10-K", "10-KT", "10-K405", "20-F")
EXHIBIT = re.compile(r"^EX-(21|8)(\.\d+)?$", re.I)
MAX_ROWS = 5000
MAX_BACK = 3  # annual reports to look back through for an exhibit

US_STATES = (
    "alabama alaska arizona arkansas california colorado connecticut delaware florida georgia "
    "hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts "
    "michigan minnesota mississippi missouri montana nebraska nevada ohio oklahoma oregon "
    "pennsylvania tennessee texas utah vermont virginia washington wisconsin wyoming"
).split() + [
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "rhode island", "south carolina", "south dakota", "west virginia", "district of columbia",
    "puerto rico",
]  # fmt: skip
COUNTRIES = [
    "argentina", "australia", "austria", "bahamas", "bahrain", "bangladesh", "barbados",
    "belgium", "bermuda", "bolivia", "brazil", "british virgin islands", "bulgaria", "canada",
    "cayman islands", "chile", "china", "colombia", "costa rica", "croatia", "curacao", "cyprus",
    "czech republic", "czechia", "denmark", "dominican republic", "ecuador", "egypt",
    "el salvador", "england", "estonia", "finland", "france", "germany", "ghana", "gibraltar",
    "greece", "guatemala", "guernsey", "honduras", "hong kong", "hungary", "iceland", "india",
    "indonesia", "ireland", "isle of man", "israel", "italy", "jamaica", "japan", "jersey",
    "jordan", "kazakhstan", "kenya", "korea", "kuwait", "latvia", "lebanon", "liechtenstein",
    "lithuania", "luxembourg", "macau", "malaysia", "malta", "marshall islands", "mauritius",
    "mexico", "monaco", "morocco", "netherlands", "new zealand", "nigeria", "northern ireland",
    "norway", "oman", "pakistan", "panama", "paraguay", "peru", "philippines", "poland",
    "portugal", "qatar", "romania", "russia", "saudi arabia", "scotland", "serbia", "singapore",
    "slovakia", "slovenia", "south africa", "spain", "sri lanka", "sweden", "switzerland",
    "taiwan", "tanzania", "thailand", "trinidad", "tunisia", "turkey", "turkiye", "uganda",
    "ukraine", "united arab emirates", "uae", "united kingdom", "uk", "united states", "usa",
    "u.s.", "u.s.a.", "united state", "bvi", "prc", "hong kong sar", "uruguay", "venezuela",
    "vietnam", "viet nam", "wales", "zambia", "zimbabwe",
]  # fmt: skip
US_CODES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR".split()
)
PLACES = sorted(US_STATES + COUNTRIES, key=len, reverse=True)
_PLACE = re.compile(r"(?<![\w.])(" + "|".join(re.escape(p) for p in PLACES) + r")(?![\w])", re.I)
_HEADER = re.compile(
    r"^(name|names|subsidiar(y|ies)|(state|jurisdiction|place|country)\b|domicile|organized|"
    r"incorporat|percent|%|ownership|owned|entity|company name|legal name)", re.I
)  # fmt: skip
_SKIP = re.compile(
    r"^(ex-\d|exhibit|list\b|of\b|\(?state\b|\(?country\b|\(?place\b|jurisdiction|"
    r"\(?incorporat|\(?organi[sz]|name\b|\d+(\.\d+)?\s+list\b|subsidiaries of|"
    r"significant subsidiaries|the following|as of|"
    r"\(?\d+\)?$|page \d|\*|omitted|pursuant to|certain subsidiaries|other subsidiaries)", re.I
)  # fmt: skip
_HEADER_WORDS = re.compile(
    r"\b(name of|jurisdiction|incorporat\w*|organi[sz]ed|domicile|laws of|state or|"
    r"percent\w*|ownership)\b", re.I
)  # fmt: skip
_PERCENT = re.compile(r"^\(?\d{1,3}(\.\d+)?\s*%\)?$")


def _clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    s = re.sub("[\u200b\u200c\u200d\ufeff]", "", s)
    return " ".join(s.split()).strip(" ,;:-–—·•")


def is_place(s: str) -> bool:
    s = (s or "").strip()
    if s.strip("()") in US_CODES:
        return True
    return bool(s) and len(s) <= 80 and bool(_PLACE.search(s))


_SUFFIX_ONLY = re.compile(
    r"^(inc|llc|l\.l\.c|ltd|limited|corp|co|lp|l\.p|plc|gmbh|s\.a|b\.v)\.?$", re.I
)
_ENTITY = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|llc|l\.l\.c|lp|l\.p|llp|ltd|limited|plc|"
    r"trust|fund|holdings?|partners(hip)?|bank|association|gmbh|ag|sa|s\.a|sas|sarl|s\.a\.r\.l|bv|"
    r"b\.v|nv|n\.v|pte|pty|kk|k\.k|ab|as|asa|oy|spa|s\.p\.a|srl|s\.r\.l|sl|s\.l|kft|sp|zoo|"
    r"ulc|lllp|pllc|pc|sociedad|cv|de c\.v|ltda|bhd|sdn|pvt|private|unlimited|dac|se|nv)\b\.?",
    re.I,
)  # fmt: skip
_NONE = {"none", "n/a", "na", "not applicable", "nil"}
_NUMBERING = re.compile(r"^\(?(\d{1,3}|[a-z]|[ivx]{1,4})[.)]?$", re.I)
_FOOTNOTE = re.compile(r"\s*(\(\d{1,2}\)|\*+|†+)$")


def _tidy(name: str) -> str:
    return _FOOTNOTE.sub("", name).strip(" ,;")


def _row(cells: list[str]) -> tuple[str, str | None] | None:
    cells = [c for c in cells if c and not _PERCENT.match(c)]
    while len(cells) > 1 and _NUMBERING.match(cells[0]):
        cells = cells[1:]
    while len(cells) > 1 and _SUFFIX_ONLY.match(cells[1]):  # "Blockchain.tv | Inc. | Delaware"
        cells = [cells[0] + ", " + cells[1], *cells[2:]]
    if not cells:
        return None
    joined = " ".join(cells)
    if _HEADER.match(joined) or _SKIP.match(joined):
        return None
    if len(cells) > 1 and _HEADER_WORDS.search(joined) and not any(map(is_place, cells)):
        return None
    if len(cells) == 1:
        return _line(cells[0])
    name = _tidy(cells[0])
    place = next((c for c in cells[1:] if is_place(c)), None) or (
        cells[1] if len(cells[1]) <= 60 else None
    )
    if is_place(name) and not is_place(cells[1]):  # "Delaware | Foo Inc." column order
        name, place = cells[1], name
    return (name, place) if 2 <= len(name) <= 200 else None


_PAREN = re.compile(r"^(.+?)\s*\(([^()]{2,60})\)\s*$")
_LEADER = re.compile(r"^(.+?)(?:\s*\.{3,}\s*|\s{3,}|\t+|\s+[-–—]\s+)(.+)$")
_A_PLACE = re.compile(
    r"^(.+?),\s*an?\s+(.+?)\s+(corporation|limited liability company|limited partnership|"
    r"partnership|company|trust|bank)\b.*$", re.I
)  # fmt: skip


def _line(text: str) -> tuple[str, str | None] | None:
    text = text.strip()
    if not text or _HEADER.match(text) or _SKIP.match(text) or len(text) > 300:
        return None
    text = _tidy(re.sub(r"^\(?(\d{1,3}|[a-z])[.)]\s+", "", text))
    m = _PAREN.match(text)
    if m and is_place(m.group(2)) and "formerly" not in m.group(2).lower():
        return m.group(1).strip(" ,"), m.group(2)
    m = _LEADER.match(text)
    if m and is_place(m.group(2)):
        return m.group(1).strip(" ,"), m.group(2)
    m = _A_PLACE.match(text)
    if m and is_place(m.group(2)):
        return m.group(1).strip(" ,"), m.group(2)
    m = re.match(r"^(.+?),\s*([^,]{2,40})$", text)  # "Foo Ltd., Ireland"
    if m and is_place(m.group(2)) and not is_place(m.group(1)):
        return m.group(1), m.group(2)
    return (text, None) if 2 <= len(text) <= 200 and re.search(r"[A-Za-z]{2}", text) else None


def parse_exhibit(doc: str) -> list[tuple[str, str | None]]:
    """(name, jurisdiction) rows of an exhibit 21, in document order, without duplicates."""
    out: list[tuple[str, str | None]] = []
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", doc, re.S | re.I)
    for r in rows:
        cells = [_clean(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
        got = _row(cells)
        if got:
            out.append(got)
    if len(out) < 2:  # no usable table: read lines
        out = []
        body = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", doc)
        body = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", body)
        for raw in re.sub(r"<[^>]+>", " ", body).splitlines():
            got = _line(_clean(raw))
            if got:
                out.append(got)
    # A name on one line and its jurisdiction alone on the next: join them.
    joined: list[tuple[str, str | None]] = []
    for name, place in out:
        if place is None and is_place(name) and len(name) <= 40:
            if joined and joined[-1][1] is None:
                joined[-1] = (joined[-1][0], name)
            continue  # a jurisdiction with no name before it is a heading
        joined.append((name, place))
    out = joined
    out = [(n, p) for n, p in out if n.strip(" .").lower() not in _NONE]
    # Lines before the first one with a jurisdiction are the title block ("EX-21.1", the file
    # name, the registrant's own name) when most lines name a jurisdiction.
    placed = [i for i, (_, p) in enumerate(out) if p]
    if placed and len(placed) * 2 >= len(out):
        out = out[placed[0] :]
    out = [(n, p) for n, p in out if not re.search(r"\.(htm|html|txt)$", n, re.I)]
    # When most rows name a jurisdiction, a row without one and without a legal form is a
    # heading inside the list ("Insurance Agencies and Brokers") or a trade name.
    if placed and len(placed) * 5 >= len(out) * 3:
        out = [(n, p) for n, p in out if p or _ENTITY.search(n)]
    seen, unique = set(), []
    for name, place in out:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            unique.append((name[:200], (place or None) and place[:80]))
    return unique[:MAX_ROWS]


def find_exhibit(index_html: str) -> tuple[str, str] | None:
    """(exhibit type, document path) of the subsidiaries exhibit in a filing index page."""
    for r in re.findall(r"<tr\b[^>]*>(.*?)</tr>", index_html, re.S | re.I):
        cells = [_clean(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", r, re.S | re.I)]
        href = re.search(r'href="([^"]+)"', r)
        kind = next((c for c in cells if EXHIBIT.match(c)), None)
        if kind and href and not href.group(1).lower().endswith((".pdf", ".jpg", ".gif")):
            path = href.group(1)
            if path.startswith("/ix?doc="):
                path = path[len("/ix?doc=") :]
            return kind.upper(), path
    return None


def jurisdiction_group(place: str | None) -> str:
    """'Delaware, U.S.' -> 'United States'; 'England and Wales' -> 'United Kingdom'."""
    if not place:
        return "Not stated"
    low = place.lower()
    m = _PLACE.search(low)
    word = m.group(1).lower() if m else low
    if word in US_STATES or word in ("united states", "united state", "usa", "u.s.", "u.s.a."):
        return "United States"
    if place.strip("() ").upper() in US_CODES:
        return "United States"
    if word in ("england", "wales", "scotland", "northern ireland", "uk", "united kingdom"):
        return "United Kingdom"
    if word in ("bvi",):
        return "British Virgin Islands"
    if word in ("prc",):
        return "China"
    if word in ("hong kong sar",):
        return "Hong Kong"
    if word in ("viet nam",):
        return "Vietnam"
    if word in ("czechia",):
        return "Czech Republic"
    if word in ("turkiye",):
        return "Turkey"
    if word in ("uae",):
        return "United Arab Emirates"
    return word.title() if m else place


def _state(db: Session, cik: str) -> GraphSourceState:
    st = db.get(GraphSourceState, (cik, "subsidiaries"))
    if st is None:
        st = GraphSourceState(cik=cik, kind="subsidiaries", status="none", detail="{}")
        db.add(st)
    return st


def refresh(db: Session, client: SecClient, cik: str) -> dict:
    """Read the exhibit of the latest annual report that has one, and of the one before it."""
    cik = normalize_cik(cik)
    st = _state(db, cik)
    checked = json.loads(st.detail or "{}").get("no_exhibit", [])
    annual = db.scalars(
        select(Filing)
        .where(Filing.cik == cik, Filing.form_type.in_(ANNUAL_FORMS))
        .order_by(Filing.filing_date.desc())
        .limit(MAX_BACK + 1)
    ).all()
    stored = set(
        db.scalars(select(Subsidiary.accession_number).where(Subsidiary.cik == cik).distinct())
    )
    found, failed = [], 0
    for f in annual:
        if len(found) == 2:
            break
        if f.accession_number in stored:
            found.append(f.accession_number)
            continue
        if f.accession_number in checked or f.filing_date is None:
            continue
        try:
            index = client.get_text(f.source_url).data
            ex = find_exhibit(index)
            if ex is None:
                checked.append(f.accession_number)
                continue
            kind, path = ex
            url = path if path.startswith("http") else "https://www.sec.gov" + path
            rows = parse_exhibit(client.get_text(url).data)
        except SecNotFound:
            checked.append(f.accession_number)
            continue
        except SecClientError:
            failed += 1
            continue
        db.execute(
            delete(Subsidiary).where(
                Subsidiary.cik == cik, Subsidiary.accession_number == f.accession_number
            )
        )
        if rows:
            db.execute(
                insert(Subsidiary),
                [
                    {
                        "cik": cik,
                        "accession_number": f.accession_number,
                        "form_type": f.form_type,
                        "filing_date": f.filing_date,
                        "exhibit": kind,
                        "position": i,
                        "name": n,
                        "jurisdiction": j,
                        "source_url": url,
                    }  # fmt: skip
                    for i, (n, j) in enumerate(rows)
                ],
            )
            found.append(f.accession_number)
        else:
            checked.append(f.accession_number)
    st.detail = json.dumps({"no_exhibit": checked[-20:]})
    st.status = "failed" if failed and not found else ("ok" if found else "none")
    st.checked_at = utcnow()
    db.commit()
    return {"cik": cik, "lists": len(found), "failed": failed}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def latest(db: Session, cik: str, as_of: date | None = None) -> dict | None:
    """The newest list filed by `as_of`, with names added and removed since the list before."""
    cik = normalize_cik(cik)
    stmt = select(Subsidiary.accession_number, Subsidiary.filing_date).where(Subsidiary.cik == cik)
    if as_of:
        stmt = stmt.where(Subsidiary.filing_date <= as_of)
    lists = db.execute(
        stmt.distinct().order_by(Subsidiary.filing_date.desc()).limit(2)
    ).all()  # fmt: skip
    if not lists:
        return None

    def rows_of(acc: str) -> list[Subsidiary]:
        q = select(Subsidiary).where(Subsidiary.cik == cik, Subsidiary.accession_number == acc)
        return list(db.scalars(q.order_by(Subsidiary.position)))

    cur = rows_of(lists[0][0])
    prev = rows_of(lists[1][0]) if len(lists) > 1 else None
    out = {
        "accession_number": lists[0][0],
        "filing_date": lists[0][1],
        "rows": cur,
        "form_type": cur[0].form_type,
        "exhibit": cur[0].exhibit,
        "source_url": cur[0].source_url,
        "previous": None,
        "added": [],
        "removed": [],
    }
    if prev:
        before = {_norm(r.name) for r in prev}
        now = {_norm(r.name) for r in cur}
        out["previous"] = {"accession_number": lists[1][0], "filing_date": lists[1][1],
                           "count": len(prev), "source_url": prev[0].source_url}  # fmt: skip
        out["added"] = [r.name for r in cur if _norm(r.name) not in before]
        out["removed"] = [r.name for r in prev if _norm(r.name) not in now]
    return out
