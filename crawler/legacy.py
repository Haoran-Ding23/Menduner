"""V1.3 ingestion retained for compatibility; new CLI uses pipeline V1.4."""
"""python -m crawler.run [--source all|official_venue|government] [--db PATH]."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from backend.database import aggregate_status, connect, database_path, initialize
from backend.models import EventRecord, EvidenceRecord
from crawler.adapters import ADAPTERS
from crawler.adapters.mock import FIXTURES

FIELDS = ('name', 'category', 'startDate', 'endDate', 'venueId', 'districtId', 'organizer', 'attendance', 'sponsor')

def ingest(path, adapters):
    # Collect and validate before writing. A failed adapter cannot partially update the database.
    batches = [adapter.collect() for adapter in adapters]
    timestamp = datetime.now(timezone.utc).isoformat()
    references = json.loads((FIXTURES / 'references.json').read_text(encoding='utf-8'))
    prior = json.loads((FIXTURES / 'evidence.json').read_text(encoding='utf-8'))
    event_ids = set()
    prepared = []
    for batch in batches:
        if not batch.mock:
            raise ValueError('This prototype only ingests mock adapters; real sources require an explicit verification workflow')
        for record in batch.records:
            event = EventRecord.model_validate(record).model_dump(mode='json')
            event['demo'] = True
            if event['id'] in event_ids:
                raise ValueError('Duplicate event ID in collection')
            event_ids.add(event['id'])
            fields = []
            for field in FIELDS:
                old = next((e for e in prior if e['entityId'] == event['id'] and e['field'] == field), {})
                status = old.get('status') if old.get('status') in ('Conflicting', 'Needs Review') else 'Unverified'
                value = old.get('value') if status == 'Conflicting' else event.get(field)
                fields.append(EvidenceRecord(id=f"{event['id']}:{field}", entityId=event['id'], field=field,
                              value=value, status=status, sourceUrl=None, sourceName=batch.name,
                              method='mock_adapter', updatedAt=timestamp,
                              sourceRole='venue' if batch.kind == 'official_venue' else 'government',
                              note='Synthetic fixture; no live official/government page was collected.').model_dump())
            prepared.append((batch, event, fields))
    initialize(path)
    with connect(path) as con:
        con.execute('BEGIN IMMEDIATE')
        for name, rows in references.items():
            for row in rows:
                con.execute(f'INSERT INTO {name}(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                            (row['id'], json.dumps(row, ensure_ascii=False)))
        for batch in batches:
            con.execute('INSERT INTO sources VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind, mock=excluded.mock, source_url=excluded.source_url, updated_at=excluded.updated_at',
                        (batch.id,batch.name,batch.kind,1,None,timestamp))
            con.execute('DELETE FROM events WHERE source=?', (batch.id,))
        for batch, event, fields in prepared:
            con.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (event['id'],event['name'],event['category'],event['startDate'],event['endDate'],event['venueId'],event['districtId'],batch.id,
                         aggregate_status([e['status'] for e in fields]),json.dumps(event,ensure_ascii=False)))
            for evidence in fields:
                put_evidence(con, evidence, event['id'])
        reference_ids = {r['id'] for rows in references.values() for r in rows}
        for evidence in prior:
            if evidence['entityId'] in reference_ids:
                put_evidence(con, EvidenceRecord.model_validate(evidence).model_dump(), None)
        con.execute('INSERT INTO runs(updated_at,sources,event_count) VALUES(?,?,?)',
                    (timestamp,json.dumps([b.id for b in batches]),len(prepared)))
    return {'eventsProcessed':len(prepared),'sourcesProcessed':len(batches),'updatedAt':timestamp,'mode':'MOCK'}

def put_evidence(con, evidence, event_id):
    con.execute('''INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                event_id=excluded.event_id, entity_id=excluded.entity_id, field=excluded.field,
                value=excluded.value, source_url=excluded.source_url, verification_status=excluded.verification_status,
                payload=excluded.payload''',
                (evidence['id'],event_id,evidence['entityId'],evidence['field'],json.dumps(evidence['value'],ensure_ascii=False),
                 evidence['sourceUrl'],evidence['status'],json.dumps(evidence,ensure_ascii=False)))

