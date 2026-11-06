import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.db.models import Issuer, ListedInstrument, ListingEvent, MarketSourceFile
from app.services.markets import firds, gleif
from app.services.markets.http import MarketHttp

FIX = Path(__file__).parents[1] / "fixtures/markets"
NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("DLTINS_20261021_01of04.xml", (FIX / "dltins_sample.xml").read_bytes())
    return buf.getvalue()


def test_parse_dltins_covers_only_equities_on_covered_venues():
    recs = list(
        firds.parse_firds_xml(
            io.BytesIO((FIX / "dltins_sample.xml").read_bytes()),
            "esma_firds",
            "https://firds.esma.europa.eu/firds/DLTINS_20261021_01of04.zip",
            {"XPAR", "XGAT", "FRAB"},
            published_at=datetime(2026, 10, 21, 6, 37, tzinfo=UTC),
        )
    )
    kinds = {(r.record.isin, r.record.mic): r for r in recs}
    assert set(kinds) == {
        ("CA39540E4013", "XGAT"),
        ("CA39540E5002", "FRAB"),
        ("FR001400AJ45", "XPAR"),
        ("FR0000120271", "XPAR"),
    }  # STUB not covered; LU fund excluded by CFI
    term = kinds[("CA39540E4013", "XGAT")]
    assert (
        term.kind == "terminated"
        and term.record.termination_date == date(2026, 6, 25)
        and term.record.status == "delisted"
    )
    mod = kinds[("CA39540E5002", "FRAB")]
    assert (
        mod.kind == "modified"
        and mod.record.termination_date is None
        and mod.record.status == "listed"
    )
    new = kinds[("FR001400AJ45", "XPAR")].record
    assert (
        new.first_trade_date == date(2026, 10, 20)
        and new.admission_requested_date == date(2026, 10, 1)
        and new.admission_approved_date == date(2026, 10, 15)
    )
    # IssrReq: the issuer asked for admission (a primary listing) vs a venue's trading line.
    assert new.issuer_requested is True and mod.record.issuer_requested is False
    assert kinds[("FR0000120271", "XPAR")].record.issuer_requested is None  # not in the record
    assert (
        new.issuer_lei == "969500ABCDEFGHIJ1234"
        and new.currency == "EUR"
        and new.cfi_code == "ESVUFR"
        and new.quality_status == "ok"
    )
    assert new.source_published_at == datetime(2026, 10, 21, 6, 37, tzinfo=UTC)
    assert any("GLEIF" in n for n in new.notes)


def test_register_listing_parsers(settings, tmp_path):
    esma = {
        "response": {
            "docs": [
                {
                    "file_name": "DLTINS_20261021_01of04.zip",
                    "file_type": "DLTINS",
                    "publication_date": "2026-10-21T00:00:00Z",
                    "download_link": "https://firds.esma.europa.eu/firds/DLTINS_20261021_01of04.zip",
                },
                {
                    "file_name": "FULINS_E_20261017_01of02.zip",
                    "file_type": "FULINS",
                    "publication_date": "2026-10-17T00:00:00Z",
                    "download_link": "https://firds.esma.europa.eu/firds/FULINS_E_20261017_01of02.zip",
                },
                {
                    "file_name": "DLTINS_20261020_01of03.zip",
                    "file_type": "DLTINS",
                    "publication_date": "2026-10-20T00:00:00Z",
                    "download_link": "https://firds.esma.europa.eu/firds/DLTINS_20261020_01of03.zip",
                },
            ]
        }
    }
    fca = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "file_name": "DLTINS_20261021_01of02.zip",
                        "file_type": "DLTINS",
                        "publication_date": "2026-10-21",
                        "download_link": "https://data.fca.org.uk/artefacts/FIRDS/DLTINS_20261021_01of02.zip",
                    }
                }
            ]
        }
    }

    def handler(request):
        return httpx.Response(200, json=esma if "esma" in str(request.url) else fca)

    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    files = firds.list_esma_files(http, date(2026, 10, 15), date(2026, 10, 22))
    assert [f.file_name for f in files] == [
        "DLTINS_20261020_01of03.zip",
        "DLTINS_20261021_01of04.zip",
    ]  # deltas only, ascending
    assert (
        firds.list_fca_files(http, date(2026, 10, 15), date(2026, 10, 22))[0].source == "fca_firds"
    )


def test_ingest_firds_end_to_end_is_idempotent(db, settings, tmp_path):
    zipped = _zip_bytes()
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "solr" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "response": {
                        "docs": [
                            {
                                "file_name": "DLTINS_20261021_01of04.zip",
                                "file_type": "DLTINS",
                                "publication_date": "2026-10-21T06:37:12Z",
                                "download_link": "https://firds.esma.europa.eu/firds/DLTINS_20261021_01of04.zip",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, content=zipped, headers={"Content-Type": "application/zip"})

    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    summary = firds.ingest_firds(db, settings, http, "esma_firds", days_back=3, now=NOW)
    assert (
        summary["files_processed"] == 1 and summary["records_seen"] == 2
    )  # XPAR records only (registry venues)
    assert summary["inserted"] == 2 and summary["events"] == {"new_listing": 1}
    ev = db.scalar(select(ListingEvent))
    assert (
        ev.isin == "FR001400AJ45"
        and ev.event_date == date(2026, 10, 20)
        and ev.source == "esma_firds"
    )
    assert ev.source_url.endswith("DLTINS_20261021_01of04.zip")
    sf = db.scalar(select(MarketSourceFile))
    assert sf.status == "done" and sf.records_seen == 2
    again = firds.ingest_firds(db, settings, http, "esma_firds", days_back=3, now=NOW)
    assert again["files_skipped"] == 1 and again["files_processed"] == 0
    assert (
        db.scalar(select(func.count(ListedInstrument.id))) == 2
        and db.scalar(select(func.count(ListingEvent.id))) == 1
    )
    assert len([c for c in calls if c.endswith(".zip")]) == 1


def test_ingest_firds_records_failed_file(db, settings, tmp_path):
    def handler(request):
        if "solr" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "response": {
                        "docs": [
                            {
                                "file_name": "DLTINS_bad.zip",
                                "file_type": "DLTINS",
                                "publication_date": "2026-10-21T00:00:00Z",
                                "download_link": "https://firds.esma.europa.eu/firds/DLTINS_bad.zip",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, content=b"not a zip")

    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    summary = firds.ingest_firds(db, settings, http, "esma_firds", days_back=1, now=NOW)
    assert summary["files_processed"] == 0 and summary["errors"] == ["DLTINS_bad.zip: BadZipFile"]
    assert db.scalar(select(MarketSourceFile)).status == "failed"


def test_gleif_parse_and_enrichment(db, settings, tmp_path):
    payload = json.loads((FIX / "gleif_lei_record.json").read_text())
    rec = gleif.parse_lei_record(payload)
    assert (
        rec.lei == "529900S21EQ1BO4ESM68"
        and rec.legal_name == "TotalEnergies SE"
        and rec.country == "FR"
        and rec.registration_status == "ISSUED"
    )
    assert gleif.parse_lei_record({"data": []}) is None
    from app.services.markets import ingest
    from app.services.markets.records import ListingRecord

    ingest.ensure_market(db, "XPAR", "Euronext Paris", "FR", "europe", "esma_firds", "https://x")
    db.commit()
    ingest.ingest_records(
        db,
        [
            ListingRecord(
                isin="FR0000120271",
                mic="XPAR",
                issuer_name="TOTALENERGIES SE Registered Shares o.N.",
                issuer_lei="529900S21EQ1BO4ESM68",
                source="esma_firds",
                source_url="https://x",
            )
        ],
        "esma_firds",
        now=NOW,
    )
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json=payload)

    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    summary = gleif.enrich_issuers(db, settings, http, now=NOW)
    assert summary == {"calls": 1, "looked_up": 1, "enriched": 1, "refreshed": 0, "not_found": 0}
    assert urls == [
        "https://api.gleif.org/api/v1/lei-records?filter%5Blei%5D=529900S21EQ1BO4ESM68"
        "&page%5Bsize%5D=200"
    ]
    issuer = db.scalar(select(Issuer))
    assert (
        issuer.source == "gleif"
        and issuer.legal_name == "TotalEnergies SE"
        and issuer.country == "FR"
    )
    assert db.scalar(select(ListedInstrument)).issuer_name == "TotalEnergies SE"
    assert gleif.enrich_issuers(db, settings, http, now=NOW)["looked_up"] == 0  # already enriched


def test_full_file_listing_keeps_only_equities_part(settings, tmp_path):
    docs = [
        {
            "file_name": n,
            "file_type": "FULINS",
            "publication_date": "2026-10-24T00:00:00Z",
            "download_link": "https://firds.esma.europa.eu/firds/" + n,
        }
        for n in (
            "FULINS_D_20261024_01of03.zip",
            "FULINS_E_20261024_01of02.zip",
            "FULINS_E_20261024_02of02.zip",
            "FULINS_C_20261024_01of01.zip",
        )
    ]
    http = MarketHttp(
        settings,
        http=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"response": {"docs": docs}})
            )
        ),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    names = [
        f.file_name
        for f in firds.list_esma_files(
            http, date(2026, 10, 20), date(2026, 10, 30), file_types=("FULINS",)
        )
    ]
    assert names == ["FULINS_E_20261024_01of02.zip", "FULINS_E_20261024_02of02.zip"]


def _gleif_server(urls):
    """GLEIF as recorded on 2026-11-06: batch LEI records and the ISIN-LEI mapping (trimmed)."""
    records = json.loads((FIX / "gleif_lei_batch.json").read_text())["data"] + [
        json.loads((FIX / "gleif_lei_record.json").read_text())["data"]
    ]
    zip_bytes = (FIX / "gleif_isin_lei_sample.zip").read_bytes()

    def handler(request):
        urls.append(str(request.url))
        if request.url.path.endswith("/isin-lei/latest"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "attributes": {
                            "fileName": "isin-lei-20261106T081508.zip",
                            "downloadLink": "https://mapping.gleif.org/api/v2/isin-lei/x/download",
                        }
                    }
                },
            )
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=zip_bytes)
        wanted = set(request.url.params.get("filter[lei]", "").split(","))
        found = [r for r in records if r["attributes"]["lei"] in wanted]
        return httpx.Response(200, json={"data": found})

    return handler


def _three_listings(db):
    from app.services.markets import ingest
    from app.services.markets.records import ListingRecord

    for mic, name, cc in (("XPAR", "Euronext Paris", "FR"), ("XLON", "London", "GB")):
        ingest.ensure_market(db, mic, name, cc, "europe", "esma_firds", "https://x")
    db.commit()
    rows = [
        ("FR0000120271", "XPAR", "TOTALENERGIES SE Registered Shares o.N.", "529900S21EQ1BO4ESM68"),
        ("GB0007980591", "XLON", "BP PLC ORD USD0.25", None),  # register gives no issuer LEI
        ("US0378331005", "XLON", "APPLE INC COM NPV", None),
    ]
    ingest.ingest_records(
        db,
        [
            ListingRecord(isin=i, mic=m, issuer_name=n, issuer_lei=lei, source="esma_firds",
                          source_url="https://x",
                          first_trade_date=NOW.date() if i == "GB0007980591" else None)
            for i, m, n, lei in rows
        ],
        "esma_firds",
        now=NOW,
    )  # fmt: skip


def test_isin_map_then_batch_lookup_resolves_every_issuer(db, settings, tmp_path):
    _three_listings(db)
    urls = []
    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(_gleif_server(urls))),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    mapped = gleif.map_isins(db, settings, http, now=NOW)
    assert mapped == {"isins_without_lei": 2, "mapped": 2, "new_issuers": 2}
    leis = dict(db.execute(select(ListedInstrument.isin, ListedInstrument.issuer_lei)).all())
    assert leis["GB0007980591"] == "213800LH1BZH3DI6G760"
    assert leis["US0378331005"] == "HWUPKR0MPOU8FGXBT394"
    summary = gleif.enrich_issuers(db, settings, http, now=NOW)
    assert summary["calls"] == 1 and summary["enriched"] == 3 and summary["not_found"] == 0
    from app.db.models import ListingEvent

    assert [e.issuer_name for e in db.scalars(select(ListingEvent))] == ["BP P.L.C."]
    names = dict(db.execute(select(ListedInstrument.isin, ListedInstrument.issuer_name)).all())
    assert names == {
        "FR0000120271": "TotalEnergies SE",
        "GB0007980591": "BP P.L.C.",
        "US0378331005": "Apple Inc.",
    }
    countries = {i.lei: i.country for i in db.scalars(select(Issuer))}
    assert countries["213800LH1BZH3DI6G760"] == "GB" and countries["HWUPKR0MPOU8FGXBT394"] == "US"
    # The mapping file is downloaded once and cached; nothing is left to map.
    downloads = sum(u.endswith("/download") for u in urls)
    assert gleif.map_isins(db, settings, http, now=NOW)["isins_without_lei"] == 0
    assert sum(u.endswith("/download") for u in urls) == downloads == 1


def test_stale_records_are_refreshed_and_missing_ones_wait(db, settings, tmp_path):
    from datetime import timedelta

    _three_listings(db)
    urls = []
    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(_gleif_server(urls))),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    gleif.map_isins(db, settings, http, now=NOW)
    gleif.enrich_issuers(db, settings, http, now=NOW)
    later = NOW + timedelta(days=settings.markets_gleif_refresh_days + 1)
    summary = gleif.enrich_issuers(db, settings, http, now=later)
    assert summary["refreshed"] == 3 and summary["enriched"] == 0
    assert gleif.enrich_issuers(db, settings, http, now=later)["looked_up"] == 0
    # An LEI GLEIF does not know is counted and left for a later run.
    db.add(Issuer(lei="000000000000000000X0", legal_name="UNKNOWN", source="esma_firds",
                  first_detected_at=NOW, updated_at=NOW))  # fmt: skip
    db.commit()
    assert gleif.enrich_issuers(db, settings, http, now=later)["not_found"] == 1


def test_read_isin_map_streams_only_wanted_rows():
    found = gleif.read_isin_map(FIX / "gleif_isin_lei_sample.zip", {"FR0000120271", "XX0"})
    assert found == {"FR0000120271": "529900S21EQ1BO4ESM68"}


def test_non_shares_coded_as_shares_are_excluded():
    """Real records from ESMA's FULINS_E files of 2026-10-31 (ticket 08)."""
    recs = list(
        firds.parse_firds_xml(
            io.BytesIO((FIX / "fulins_non_shares.xml").read_bytes()),
            "esma_firds",
            "https://firds.esma.europa.eu/firds/FULINS_E_20261031_02of02.zip",
            {"XMSM", "TWEM", "XOSL", "NPEX"},
            published_at=datetime(2026, 10, 31, tzinfo=UTC),
        )
    )
    kept = {r.record.isin for r in recs}
    # Kept: a company named "... ETC PLC" and Dutch depositary receipts for shares.
    assert kept == {"CY0101550917", "NL0015001A60"}
    assert firds.not_a_share("XS2000000000", "ESVUFR", "BNP PARIBAS CERT") is not None
    assert "CDO" in firds.not_a_share("KYG015912085", "EPNXFR", "ALESCO PREFERRED FUNDING VI")
    assert firds.not_a_share("US90137T1034", "ESNUFR", "21SHARES XRP ETF").startswith("exchange")
    for company in ("Anhui Expressway Co. Ltd.", "NOTE AB", "TURBOMECANICA S.A.", "BONDUELLE"):
        assert firds.not_a_share("FR0000063935", "ESVUFR", company) is None


def test_stored_non_shares_are_removed_with_their_events(db):
    from app.db.models import ListingEvent
    from app.services.markets import ingest
    from app.services.markets.records import ListingRecord

    ingest.ensure_market(db, "XMSM", "Euronext Dublin MSM", "IE", "europe", "esma_firds", "x")
    ingest.ensure_market(db, "XPAR", "Euronext Paris", "FR", "europe", "esma_firds", "x")
    db.commit()
    ingest.ingest_records(
        db,
        [
            ListingRecord(isin="KYG015912085", mic="XMSM", cfi_code="EPNXFR",
                          issuer_name="ALESCO PREFERRED FUNDING  VI LTD Preferred Shares",
                          first_trade_date=NOW.date(), source="esma_firds", source_url="x"),
            ListingRecord(isin="FR001400AJ45", mic="XPAR", cfi_code="ESVUFR",
                          issuer_name="EXOSENS", first_trade_date=NOW.date(),
                          source="esma_firds", source_url="x"),
        ],
        "esma_firds",
        now=NOW,
    )  # fmt: skip
    assert db.scalar(select(func.count(ListingEvent.id))) == 2
    assert firds.remove_non_shares(db, "esma_firds") == 1
    assert [i.isin for i in db.scalars(select(ListedInstrument))] == ["FR001400AJ45"]
    assert db.scalar(select(func.count(ListingEvent.id))) == 1
    assert firds.remove_non_shares(db, "esma_firds") == 0
