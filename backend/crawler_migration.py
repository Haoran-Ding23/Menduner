"""Additive, idempotent V1.4 migration. Existing API tables and columns are unchanged."""


def migrate(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS crawler_jobs (
      id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
      status TEXT NOT NULL, report TEXT);
    CREATE TABLE IF NOT EXISTS crawler_attempts (
      job_id TEXT NOT NULL REFERENCES crawler_jobs(id), source_id TEXT NOT NULL,
      status TEXT NOT NULL, error TEXT, accepted INTEGER NOT NULL DEFAULT 0,
      rejected INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_id, source_id));
    CREATE TABLE IF NOT EXISTS crawler_raw_items (
      id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES crawler_jobs(id),
      source_id TEXT NOT NULL REFERENCES sources(id), item_key TEXT NOT NULL,
      original_url TEXT NOT NULL, source_name TEXT NOT NULL, crawl_time TEXT NOT NULL,
      raw_content TEXT NOT NULL, mock INTEGER NOT NULL CHECK(mock IN (0,1)),
      validation_status TEXT NOT NULL, error TEXT);
    CREATE TABLE IF NOT EXISTS crawler_observations (
      source_id TEXT NOT NULL REFERENCES sources(id), item_key TEXT NOT NULL,
      event_id TEXT NOT NULL REFERENCES events(id), raw_item_id TEXT NOT NULL REFERENCES crawler_raw_items(id),
      normalized_json TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(source_id, item_key));
    CREATE TABLE IF NOT EXISTS crawler_unified_events (
      event_id TEXT PRIMARY KEY REFERENCES events(id), fingerprint TEXT,
      normalized_json TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS crawler_fingerprint_idx ON crawler_unified_events(fingerprint);
    CREATE TABLE IF NOT EXISTS crawler_evidence (
      id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id), field_name TEXT NOT NULL,
      value TEXT, source TEXT NOT NULL REFERENCES sources(id), source_url TEXT NOT NULL,
      confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
      raw_item_id TEXT NOT NULL REFERENCES crawler_raw_items(id), verification_status TEXT NOT NULL);
    """)
    upgrade_real_flag(con)


def upgrade_real_flag(con):
    """SQLite cannot ALTER a CHECK constraint. Preserve V1.4 raw IDs and FK targets."""
    import re

    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='crawler_raw_items'"
    ).fetchone()["sql"]
    if not re.search(r"CHECK\s*\(\s*mock\s*=\s*1\s*\)", sql, re.I):
        return
    if con.in_transaction:
        raise RuntimeError("Raw migration must run outside an active transaction")
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        con.executescript("""BEGIN IMMEDIATE;
        CREATE TABLE crawler_raw_items_v15 (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES crawler_jobs(id),
          source_id TEXT NOT NULL REFERENCES sources(id), item_key TEXT NOT NULL,
          original_url TEXT NOT NULL, source_name TEXT NOT NULL, crawl_time TEXT NOT NULL,
          raw_content TEXT NOT NULL, mock INTEGER NOT NULL CHECK(mock IN (0,1)),
          validation_status TEXT NOT NULL, error TEXT);
        INSERT INTO crawler_raw_items_v15 SELECT * FROM crawler_raw_items;
        DROP TABLE crawler_raw_items;
        ALTER TABLE crawler_raw_items_v15 RENAME TO crawler_raw_items;
        COMMIT;""")
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")
    if con.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError("Migration foreign key validation failed")
