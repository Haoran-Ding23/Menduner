import sqlite3
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.database import initialize, snapshot
from backend.models import EvidenceRecord
from crawler.demo.adapters.mock import OfficialVenueAdapter, GovernmentEventAdapter
from crawler.demo.legacy import ingest

@pytest.fixture
def db(tmp_path):
    return tmp_path / 'events.sqlite3'

def adapters():
    return [OfficialVenueAdapter(), GovernmentEventAdapter()]

def test_empty_api_does_not_seed_or_invent_update(db):
    with TestClient(create_app(db)) as client:
        assert client.get('/events').json() == []
        assert client.get('/status').json()['lastUpdated'] is None
        assert client.get('/events/missing').status_code == 404
        assert client.get('/dataset').json()['status']['sourceCount'] == 0

def test_crawler_database_api_roundtrip_and_persistence(db):
    ingest(db, adapters())
    with TestClient(create_app(db)) as client:
        result = client.get('/dataset').json()
        assert result['status']['sourceCount'] == result['status']['mockSourceCount'] == 2
        assert result['status']['eventCount'] == result['status']['demoEventCount'] == 10
        assert result['status']['verificationCounts']['Verified'] == 0
        event = client.get('/events/demo-01').json()
        assert event['source'] == 'mock-venue'
        assert event['venue'] == event['venueId'] == 'v-expo'
        assert event['district'] == event['districtId'] == 'd-jinji'
        assert event['verification_status'] == 'Unverified'
        evidence = client.get('/evidence?event_id=demo-01').json()
        assert len(evidence) == 9
        assert all(e['event_id'] == 'demo-01' and e['source_url'] is None for e in evidence)
        assert client.get('/events/demo-02').json()['verification_status'] == 'Conflicting'
        for endpoint in ('events', 'venues', 'evidence', 'hotels', 'districts'):
            response = client.get('/' + endpoint)
            assert response.status_code == 200 and isinstance(response.json(), list)
    with TestClient(create_app(db)) as client:
        assert len(client.get('/events').json()) == 10

def test_repeat_ingestion_is_idempotent_and_records_new_revision(db):
    ingest(db, adapters())
    before = snapshot(db)
    ingest(db, adapters())
    after = snapshot(db)
    assert len(after['events']) == len(before['events']) == 10
    assert len(after['evidence']) == len(before['evidence'])
    assert after['status']['revision'] == before['status']['revision'] + 1
    assert after['status']['lastUpdated'] >= before['status']['lastUpdated']

def test_source_refresh_updates_values_removes_withdrawn_records_and_preserves_other_source(db):
    ingest(db, adapters())
    class Changed(OfficialVenueAdapter):
        def collect(self):
            source = super().collect()
            source.records = source.records[:1]
            source.records[0]['name'] = 'Changed synthetic event'
            return source
    ingest(db, [Changed()])
    result = snapshot(db)
    assert len(result['events']) == 6
    assert result['events'][0]['name'] == 'Changed synthetic event'
    assert next(e for e in result['evidence'] if e['entityId'] == 'demo-01' and e['field'] == 'name')['value'] == 'Changed synthetic event'
    assert not any(e['entityId'] == 'demo-03' for e in result['evidence'])
    assert len([e for e in result['events'] if e['source'] == 'mock-government']) == 5

def test_adapter_failure_does_not_partially_publish(db):
    ingest(db, adapters())
    before = snapshot(db)
    class Broken:
        def collect(self):
            raise RuntimeError('fixture read failed')
    with pytest.raises(RuntimeError):
        ingest(db, [OfficialVenueAdapter(), Broken()])
    assert snapshot(db) == before

def test_foreign_key_failure_rolls_back_whole_transaction(db):
    ingest(db, adapters())
    before = snapshot(db)
    class Broken(OfficialVenueAdapter):
        def collect(self):
            source = super().collect()
            source.records[0]['venueId'] = 'nonexistent'
            return source
    with pytest.raises(sqlite3.IntegrityError):
        ingest(db, [Broken()])
    assert snapshot(db) == before

def test_invalid_dates_rejected_before_writes(db):
    initialize(db)
    class Broken(OfficialVenueAdapter):
        def collect(self):
            source = super().collect()
            source.records[0]['startDate'] = '2026-02-30'
            return source
    with pytest.raises(ValueError):
        ingest(db, [Broken()])
    assert snapshot(db)['events'] == []

def test_mock_sources_never_promote_event_fields_to_verified(db):
    class PretendsVerified(OfficialVenueAdapter):
        def collect(self):
            source = super().collect()
            source.records[0]['demo'] = False
            source.records[0]['verification_status'] = 'Verified'
            return source
    ingest(db, [PretendsVerified()])
    event = snapshot(db)['events'][0]
    assert event['demo'] is True and event['verification_status'] != 'Verified'
    value = EvidenceRecord(id='x', entityId='e', field='name', value='A', status='Verified', method='manual', updatedAt='2026-10-12')
    assert value.status == 'Needs Review'
