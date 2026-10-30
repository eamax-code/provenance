"""Registry of covered trading venues (ISO 10383 MICs) grouped by source and region.

Only instruments on these venues are ingested; FIRDS alone references hundreds of MICs
(MTFs, SIs, derivatives venues) that are out of scope. Keep this list small and deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Market
from app.services.markets.ingest import ensure_market

VENUE_REGISTRY_VERSION = "1.1.0"
# 1.1.0 (2026-10-30): codes verified against the ISO 10383 MIC list and the ESMA FIRDS full
# equities file of 2026-10-24. FIRDS reports listings under segment MICs (e.g. XETA, FRAA,
# MTAA, WBAH, XMSM), not the operating MICs (XETR, XFRA, XMIL, XWBO, XDUB, category NSPD).
# SIX (XSWX) removed: Switzerland is outside EU FIRDS. Growth/SME markets added.


@dataclass(frozen=True)
class Venue:
    mic: str
    name: str
    country: str
    region: str  # europe | uk | canada
    source: str  # which adapter supplies it
    source_url: str
    operating_mic: str | None = None


ESMA_URL = "https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_firds"
FCA_URL = "https://data.fca.org.uk/#/firds/files"


def _eu(mic: str, name: str, country: str, operating: str | None = None) -> Venue:
    return Venue(mic, name, country, "europe", "esma_firds", ESMA_URL, operating or mic)


VENUES: tuple[Venue, ...] = (
    # EU / EEA regulated markets (ESMA FIRDS)
    _eu("XPAR", "Euronext Paris", "FR"),
    _eu("XAMS", "Euronext Amsterdam", "NL"),
    _eu("XBRU", "Euronext Brussels", "BE"),
    _eu("XLIS", "Euronext Lisbon", "PT"),
    _eu("XMSM", "Euronext Dublin", "IE", "XDUB"),
    _eu("MTAA", "Euronext Milan", "IT", "XMIL"),
    _eu("XOSL", "Oslo Børs", "NO"),
    _eu("XOAS", "Euronext Expand Oslo", "NO", "XOSL"),
    _eu("XETA", "Xetra (regulated market)", "DE", "XETR"),
    _eu("FRAA", "Börse Frankfurt (regulated market)", "DE", "XFRA"),
    _eu("XMAD", "Bolsa de Madrid", "ES", "BMEX"),
    _eu("XSTO", "Nasdaq Stockholm", "SE"),
    _eu("XHEL", "Nasdaq Helsinki", "FI"),
    _eu("XCSE", "Nasdaq Copenhagen", "DK"),
    _eu("XICE", "Nasdaq Iceland", "IS"),
    _eu("XRIS", "Nasdaq Riga", "LV"),
    _eu("XTAL", "Nasdaq Tallinn", "EE"),
    _eu("XLIT", "Nasdaq Vilnius", "LT"),
    _eu("WBAH", "Wiener Börse (official market)", "AT", "XWBO"),
    _eu("XWAR", "Warsaw Stock Exchange (main market)", "PL"),
    _eu("XATH", "Athens Exchange", "GR", "ASEX"),
    _eu("XPRA", "Prague Stock Exchange", "CZ"),
    _eu("XBUD", "Budapest Stock Exchange", "HU"),
    _eu("XBSE", "Bucharest Stock Exchange (regulated market)", "RO"),
    _eu("XZAG", "Zagreb Stock Exchange", "HR"),
    _eu("XLJU", "Ljubljana Stock Exchange", "SI"),
    _eu("XBRA", "Bratislava Stock Exchange", "SK"),
    _eu("XLUX", "Luxembourg Stock Exchange", "LU"),
    _eu("XCYS", "Cyprus Stock Exchange", "CY"),
    _eu("XMAL", "Malta Stock Exchange", "MT"),
    # EU growth / SME markets (where many IPOs happen)
    _eu("ALXP", "Euronext Growth Paris", "FR", "XPAR"),
    _eu("EXGM", "Euronext Growth Milan", "IT", "XMIL"),
    _eu("XESM", "Euronext Growth Dublin", "IE", "XDUB"),
    _eu("SSME", "Nasdaq First North Sweden", "SE", "XSTO"),
    _eu("XNCO", "NewConnect (Warsaw)", "PL", "XWAR"),
    _eu("GROW", "BME Growth", "ES", "BMEX"),
    # United Kingdom (FCA FIRDS)
    Venue("XLON", "London Stock Exchange", "GB", "uk", "fca_firds", FCA_URL, "XLON"),
    Venue("AIMX", "AIM (London Stock Exchange)", "GB", "uk", "fca_firds", FCA_URL, "XLON"),
    # Canada (exchange-direct adapters; enabled per source terms)
    Venue("XTSE", "Toronto Stock Exchange", "CA", "canada", "tsx", "https://www.tsx.com/"),
    Venue("XTSX", "TSX Venture Exchange", "CA", "canada", "tsx", "https://www.tsx.com/"),
    Venue("XCNQ", "Canadian Securities Exchange", "CA", "canada", "cse", "https://thecse.com/"),
    Venue("NEOE", "Cboe Canada (formerly NEO)", "CA", "canada", "cboe_ca", "https://www.cboe.ca/"),
)

BY_MIC: dict[str, Venue] = {v.mic: v for v in VENUES}


def venues_for_source(source: str) -> list[Venue]:
    return [v for v in VENUES if v.source == source]


def seed_venues(db: Session, source: str | None = None) -> dict[str, Market]:
    """Ensure Market rows exist for the registry (optionally one source). Flushes, no commit."""
    out: dict[str, Market] = {}
    for v in VENUES:
        if source is not None and v.source != source:
            continue
        out[v.mic] = ensure_market(
            db, v.mic, v.name, v.country, v.region, v.source, v.source_url, v.operating_mic
        )
    return out
