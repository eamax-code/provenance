from sqlalchemy import func, select

from app.db.models import Market
from app.services.markets import venues


def test_registry_is_consistent():
    mics = [v.mic for v in venues.VENUES]
    assert len(mics) == len(set(mics)) and all(len(m) == 4 and m.isupper() for m in mics)
    assert {v.region for v in venues.VENUES} == {"europe", "uk", "canada"}
    assert all(len(v.country) == 2 for v in venues.VENUES)
    assert {v.source for v in venues.venues_for_source("fca_firds")} == {"fca_firds"}
    assert venues.BY_MIC["XLON"].region == "uk" and venues.BY_MIC["XTSX"].country == "CA"


def test_seed_is_idempotent_and_filterable(db):
    first = venues.seed_venues(db)
    db.commit()
    assert set(first) == set(venues.BY_MIC)
    venues.seed_venues(db, source="esma_firds")
    db.commit()
    assert db.scalar(select(func.count(Market.id))) == len(venues.VENUES)
