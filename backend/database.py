"""Small SQLite store; each request uses its own connection and read snapshot."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / 'data' / 'menduner.sqlite3'

def database_path():
    return Path(os.environ.get('MENDUNER_DB_PATH', str(DEFAULT_DB))).resolve()

@contextmanager
def connect(path):
    con = sqlite3.connect(str(path), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    try:
        with con:
            yield con
    finally:
        con.close()

def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS sources (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
          mock INTEGER NOT NULL, source_url TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS venues (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hotels (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS districts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
          startDate TEXT, endDate TEXT, venue TEXT REFERENCES venues(id),
          district TEXT REFERENCES districts(id), source TEXT NOT NULL REFERENCES sources(id),
          verification_status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence (
          id TEXT PRIMARY KEY, event_id TEXT REFERENCES events(id) ON DELETE CASCADE,
          entity_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT,
          source_url TEXT, verification_status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS evidence_event_idx ON evidence(event_id);
        CREATE TABLE IF NOT EXISTS runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, updated_at TEXT NOT NULL,
          sources TEXT NOT NULL, event_count INTEGER NOT NULL);
        ''')

        from backend.crawler_migration import migrate
        migrate(con)

        # Attendance is a separate, human-collected dataset rather than part of the crawl
        # projection, so its table is created here alongside the other schemas instead of by
        # a crawler run. Places (restaurants and public transport around a venue) are the same
        # kind of resource as hotels: a table the enrichment script fills and the graph reads.
        from crawler import attendance, places
        attendance.ensure_schema(con)
        places.ensure_schema(con)

def aggregate_status(statuses):
    for value in ('Conflicting', 'Needs Review', 'Unverified', 'Missing'):
        if value in statuses:
            return value
    return 'Verified' if statuses else 'Missing'

def snapshot(path):
    with connect(path) as con:
        con.execute('BEGIN')
        events = [dict(json.loads(row['payload']), source=row['source'],
                       venue=row['venue'], district=row['district'],
                       verification_status=row['verification_status'])
                  for row in con.execute('SELECT * FROM events ORDER BY id')]
        evidence = [dict(json.loads(row['payload']), event_id=row['event_id'],
                         source_url=row['source_url'], verification_status=row['verification_status'])
                    for row in con.execute('SELECT * FROM evidence ORDER BY id')]
        resources = {name: [json.loads(row['payload']) for row in con.execute(f'SELECT payload FROM {name} ORDER BY id')]
                     for name in ('venues', 'hotels', 'districts', 'places')}
        sources = [dict(row) for row in con.execute('SELECT * FROM sources ORDER BY id')]
        last = con.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        counts = {status: sum(e['verification_status'] == status for e in events)
                  for status in ('Verified', 'Unverified', 'Missing', 'Conflicting', 'Needs Review')}
        status = {'sourceCount': len(sources), 'mockSourceCount': sum(s['mock'] for s in sources),
                  'eventCount': len(events), 'demoEventCount': sum(e['demo'] for e in events),
                  'verificationCounts': counts, 'lastUpdated': last['updated_at'] if last else None,
                  'revision': last['id'] if last else 0, 'sources': sources}
        return dict(events=events, evidence=evidence, **resources, updatedAt=status['lastUpdated'], status=status)
