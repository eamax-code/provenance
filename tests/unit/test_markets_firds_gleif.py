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
    assert summary == {"looked_up": 1, "enriched": 1, "not_found": 0}
    assert urls == ["https://api.gleif.org/api/v1/lei-records/529900S21EQ1BO4ESM68"]
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
