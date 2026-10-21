"""Registry of covered trading venues (ISO 10383 MICs) grouped by source and region.

Only instruments on these venues are ingested; FIRDS alone references hundreds of MICs
(MTFs, SIs, derivatives venues) that are out of scope. Keep this list small and deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Market
from app.services.markets.ingest import ensure_market

VENUE_REGISTRY_VERSION = "1.0.0"


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

VENUES: tuple[Venue, ...] = (
    # EU / EEA regulated markets (ESMA FIRDS)
    Venue("XPAR", "Euronext Paris", "FR", "europe", "esma_firds", ESMA_URL),
    Venue("XAMS", "Euronext Amsterdam", "NL", "europe", "esma_firds", ESMA_URL),
    Venue("XBRU", "Euronext Brussels", "BE", "europe", "esma_firds", ESMA_URL),
    Venue("XLIS", "Euronext Lisbon", "PT", "europe", "esma_firds", ESMA_URL),
    Venue("XDUB", "Euronext Dublin", "IE", "europe", "esma_firds", ESMA_URL),
    Venue("XOSL", "Oslo Børs", "NO", "europe", "esma_firds", ESMA_URL),
    Venue("XMIL", "Borsa Italiana (Euronext Milan)", "IT", "europe", "esma_firds", ESMA_URL),
    Venue("XETR", "Xetra (Deutsche Börse)", "DE", "europe", "esma_firds", ESMA_URL, "XETR"),
    Venue("XFRA", "Frankfurt Stock Exchange", "DE", "europe", "esma_firds", ESMA_URL, "XFRA"),
    Venue("XMAD", "Bolsa de Madrid", "ES", "europe", "esma_firds", ESMA_URL, "BMEX"),
    Venue("XSTO", "Nasdaq Stockholm", "SE", "europe", "esma_firds", ESMA_URL),
    Venue("XHEL", "Nasdaq Helsinki", "FI", "europe", "esma_firds", ESMA_URL),
    Venue("XCSE", "Nasdaq Copenhagen", "DK", "europe", "esma_firds", ESMA_URL),
    Venue("XWBO", "Wiener Börse", "AT", "europe", "esma_firds", ESMA_URL),
    Venue("XWAR", "Warsaw Stock Exchange", "PL", "europe", "esma_firds", ESMA_URL),
    Venue("XATH", "Athens Exchange", "GR", "europe", "esma_firds", ESMA_URL),
    Venue("XPRA", "Prague Stock Exchange", "CZ", "europe", "esma_firds", ESMA_URL),
    Venue("XBUD", "Budapest Stock Exchange", "HU", "europe", "esma_firds", ESMA_URL),
    Venue("XSWX", "SIX Swiss Exchange", "CH", "europe", "esma_firds", ESMA_URL),
    # United Kingdom (FCA FIRDS)
    Venue("XLON", "London Stock Exchange", "GB", "uk", "fca_firds", FCA_URL),
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
