"""Venue duplicate resolution and coordinate entry.

Merging venues and pinning coordinates are both decisions that are hard to notice once wrong,
so the rules under test are the safety ones: nothing merges without a named reviewer and a
reason, a merge moves every reference and is reverting-able, and a coordinate must be inside
the city and carry a source URL.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.database import connect, initialize, snapshot
from backend.main import create_app
from backend import venues as venue_store
from crawler.venue_duplicates import (
    ALIAS_PATH,
    detect,
    distance_km,
    looks_like_address,
    normalize,
)
from crawler.venues import reset_cache


def venue(venue_id: str, name: str, *, coordinates=None, address=None) -> dict:
    return {
        "id": venue_id,
        "name": name,
        "address": address,
        "districtId": None,
        "districtDemo": False,
        "coordinates": coordinates,
    }


def coords(lng: float, lat: float) -> dict:
    return {
        "lng": lng,
        "lat": lat,
        "system": "GCJ-02",
        "status": "Verified",
        "sourceUrl": "https://ditu.amap.com/place/TEST",
    }


def event(event_id: str, venue_id: str | None) -> dict:
    return {"id": event_id, "name": f"event {event_id}", "venueId": venue_id}


# --- normalisation and detection ------------------------------------------------

def test_normalisation_ignores_punctuation_and_region_prefixes():
    assert normalize("苏州文化艺术中心/金鸡湖音乐厅") == normalize(
        "苏州文化艺术中心·金鸡湖音乐厅"
    )
    # A row named with a whole address line still CONTAINS the venue name, which is the
    # signal the detector reports. It is deliberately not reduced to a clean name, because
    # rewriting an address into a venue name would invent data.
    full = normalize("苏州 姑苏区 苏州开明大戏院 观前街北局11号")
    assert normalize("苏州开明大戏院") in full
    assert "姑苏区" not in full, "a district token is not part of the identity"


def test_address_like_names_are_flagged_not_matched_on_address_text():
    assert looks_like_address("苏州 姑苏区 苏州开明大戏院 观前街北局11号")
    assert looks_like_address("东环路711")
    assert not looks_like_address("苏州开明大戏院")


def test_exact_and_containment_signals_are_reported_with_evidence():
    venues = [
        venue("b", "苏州开明大戏院"),
        venue("a", "开明大戏院"),
        venue("c", "独墅湖影剧院"),
    ]
    usage = {"a": 2, "b": 5, "c": 1}
    found = detect(venues, usage)
    assert len(found) == 1
    candidate = found[0]
    assert candidate.signal == "containment"
    # The row carrying more events is proposed as the one to keep.
    assert candidate.canonical_id == "b" and candidate.alias_id == "a"
    assert candidate.canonical_events == 5 and candidate.alias_events == 2


def test_unrelated_venues_are_not_proposed():
    venues = [venue("a", "独墅湖影剧院"), venue("b", "苏州博物馆")]
    assert detect(venues, {}) == []


def test_proximity_is_a_weaker_signal_that_says_so():
    venues = [
        venue("a", "苏州狮山大剧院", coordinates=coords(120.5, 31.29)),
        venue("b", "众戏剧文化艺术空间", coordinates=coords(120.502, 31.291)),
    ]
    found = detect(venues, {})
    assert len(found) == 1
    assert found[0].signal == "proximity"
    assert any("names do not match" in n for n in found[0].notes)


def test_distance_is_none_when_either_venue_lacks_coordinates():
    assert distance_km(coords(120.1, 31.1), None) is None
    assert distance_km(None, coords(120.1, 31.1)) is None


# --- merging --------------------------------------------------------------------

@pytest.fixture
def seeded(tmp_path):
    """A database with two rows for one venue, events on both, and no aliases declared."""
    db = tmp_path / "venues.sqlite3"
    alias_file = tmp_path / "venue_aliases.json"
    alias_file.write_text(json.dumps({"version": 1, "aliases": []}), encoding="utf-8")
    initialize(db)
    with connect(db) as con:
        # The source row comes first: events reference it and foreign keys are enforced.
        con.execute(
            "INSERT INTO sources VALUES(?,?,?,?,?,?)",
            (
                "venue-suzhou-orchestra",
                "test",
                "venue",
                0,
                None,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        for row in (
            venue("keep", "苏州开明大戏院", coordinates=coords(120.62, 31.31)),
            venue("dup", "开明大戏院"),
        ):
            con.execute(
                "INSERT INTO venues(id,payload) VALUES(?,?)",
                (row["id"], json.dumps(row, ensure_ascii=False)),
            )
        # "keep" carries the coordinates and most events, so it is the natural target; the
        # shorthand row "dup" carries the rest and is the duplicate.
        for index, venue_id in enumerate(("keep", "keep", "dup")):
            event_id = f"evt-{index}"
            payload = {
                "id": event_id,
                "name": f"event {index}",
                "venueId": venue_id,
                "demo": False,
            }
            con.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    payload["name"],
                    "culture",
                    "2026-11-01",
                    None,
                    venue_id,
                    None,
                    "venue-suzhou-orchestra",
                    "Needs Review",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
    reset_cache()
    return db, alias_file


def test_merge_moves_every_reference_and_removes_the_duplicate_row(seeded):
    db, alias_file = seeded
    result = venue_store.merge(
        db,
        alias_id="dup",
        canonical_id="keep",
        reviewer="rm",
        reason="same theatre, official page address matches",
        alias_path=alias_file,
    )
    assert result["merged"] and result["events_moved"] == 1

    snap = snapshot(db)
    assert {e["venueId"] for e in snap["events"]} == {"keep"}
    assert not any(v["id"] == "dup" for v in snap["venues"])
    # The decision is recorded, not just applied.
    edits = venue_store.venue_edits(db)
    assert edits and edits[0]["kind"] == "merge" and edits[0]["reviewer"] == "rm"
    # An event that now sits at the canonical venue has its reference settled.
    with connect(db) as con:
        approved = con.execute(
            "SELECT COUNT(*) FROM review_decisions WHERE field='venueId'"
        ).fetchone()[0]
    assert approved == 1


def test_merge_applies_to_later_crawls_through_the_alias_file(seeded):
    db, alias_file = seeded
    venue_store.merge(
        db,
        alias_id="dup",
        canonical_id="keep",
        reviewer="rm",
        reason="same theatre",
        alias_path=alias_file,
    )
    document = json.loads(alias_file.read_text(encoding="utf-8"))
    assert document["aliases"][0]["alias_id"] == "dup"
    assert document["aliases"][0]["canonical_id"] == "keep"


def test_merge_requires_a_named_reviewer_and_a_reason(seeded):
    db, alias_file = seeded
    with pytest.raises(ValueError, match="reviewer"):
        venue_store.merge(
            db,
            alias_id="dup",
            canonical_id="keep",
            reviewer="   ",
            reason="x",
            alias_path=alias_file,
        )
    with pytest.raises(ValueError, match="itself"):
        venue_store.merge(
            db,
            alias_id="keep",
            canonical_id="keep",
            reviewer="rm",
            reason="x",
            alias_path=alias_file,
        )


def test_merge_can_be_reverted(seeded):
    db, alias_file = seeded
    venue_store.merge(
        db,
        alias_id="dup",
        canonical_id="keep",
        reviewer="rm",
        reason="same theatre",
        alias_path=alias_file,
    )
    venue_store.merge(
        db,
        alias_id="dup",
        canonical_id="keep",
        reviewer="rm",
        reason="revert: they are two different halls after all",
        alias_path=alias_file,
        revert=True,
    )
    document = json.loads(alias_file.read_text(encoding="utf-8"))
    assert document["aliases"] == []
    assert venue_store.venue_edits(db)[0]["kind"] == "merge_reverted"


# --- coordinates ----------------------------------------------------------------

def test_coordinate_requires_bounds_and_provenance(seeded):
    db, _ = seeded
    with pytest.raises(ValueError, match="Suzhou"):
        venue_store.set_coordinates(
            db,
            venue_id="dup",
            lng=116.4,
            lat=39.9,
            source_url="https://ditu.amap.com/place/X",
            reviewer="rm",
        )
    with pytest.raises(ValueError, match="source URL"):
        venue_store.set_coordinates(
            db, venue_id="dup", lng=120.62, lat=31.31, source_url="", reviewer="rm"
        )
    with pytest.raises(ValueError, match="reviewer"):
        venue_store.set_coordinates(
            db,
            venue_id="dup",
            lng=120.62,
            lat=31.31,
            source_url="https://ditu.amap.com/place/X",
            reviewer=" ",
        )
    with pytest.raises(ValueError, match="GCJ-02"):
        venue_store.set_coordinates(
            db,
            venue_id="dup",
            lng=120.62,
            lat=31.31,
            source_url="https://ditu.amap.com/place/X",
            reviewer="rm",
            system="WGS-84",
        )


def test_coordinate_is_stored_with_its_source_and_recorded(seeded):
    db, _ = seeded
    venue_store.set_coordinates(
        db,
        venue_id="dup",
        lng=120.625335,
        lat=31.309339,
        source_url="https://ditu.amap.com/place/B0TEST",
        reviewer="rm",
        note="checked the theatre frontage on the AMap place page",
    )
    venue_row = next(v for v in snapshot(db)["venues"] if v["id"] == "dup")
    assert venue_row["coordinates"]["lng"] == 120.625335
    assert venue_row["coordinates"]["sourceUrl"] == "https://ditu.amap.com/place/B0TEST"
    assert venue_row["coordinates"]["status"] == "Verified"
    edit = venue_store.venue_edits(db)[0]
    assert edit["kind"] == "coordinates" and edit["reviewer"] == "rm"


def test_coordinate_targets_list_venues_that_need_one(seeded):
    db, _ = seeded
    targets = {t["id"]: t for t in venue_store.coordinate_targets(db)}
    assert targets["keep"]["has_coordinates"] is True
    assert targets["dup"]["has_coordinates"] is False
    assert targets["dup"]["events"] == 1


# --- API ------------------------------------------------------------------------

def test_api_exposes_and_writes_venue_maintenance(seeded, monkeypatch):
    db, alias_file = seeded
    # The API resolves the alias file per request, so point it at this test's mapping
    # instead of the tracked repository file.
    monkeypatch.setenv("MENDUNER_VENUE_ALIASES", str(alias_file))
    with TestClient(create_app(db)) as client:
        duplicates = client.get("/venues/duplicates").json()
        assert any(d["alias_id"] == "dup" for d in duplicates)

        needed = client.get("/venues/coordinates/needed").json()
        assert any(t["id"] == "dup" and not t["has_coordinates"] for t in needed)

        bad = client.post(
            "/venues/coordinates",
            json={
                "venue_id": "dup",
                "lng": 10.0,
                "lat": 10.0,
                "source_url": "https://ditu.amap.com/place/X",
                "reviewer": "rm",
            },
        )
        assert bad.status_code == 400 and "Suzhou" in bad.json()["detail"]

        ok = client.post(
            "/venues/coordinates",
            json={
                "venue_id": "dup",
                "lng": 120.625335,
                "lat": 31.309339,
                "source_url": "https://ditu.amap.com/place/B0TEST",
                "reviewer": "rm",
            },
        )
        assert ok.status_code == 200

        merged = client.post(
            "/venues/merge",
            json={
                "alias_id": "dup",
                "canonical_id": "keep",
                "reviewer": "rm",
                "reason": "same theatre",
            },
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["events_moved"] == 1

        assert any(e["kind"] == "merge" for e in client.get("/venues/edits").json())
