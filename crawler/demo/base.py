import json
from datetime import datetime, timezone
from pathlib import Path
from crawler.schema import CollectedItem


class FixtureSource:
    """Independent fixture reader. Reserved .invalid URLs are synthetic provenance."""

    mock = True
    source_id: str
    source_name: str
    kind: str
    source_url: str
    fixture: Path

    def rows(self, data):
        raise NotImplementedError

    def key(self, row):
        raise NotImplementedError

    def collect(self):
        data = json.loads(self.fixture.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        return [
            CollectedItem(
                item_key=self.key(row),
                original_url=f"{self.source_url}/{self.key(row)}",
                source_name=self.source_name,
                crawl_time=now,
                raw_content=json.dumps(row, ensure_ascii=False),
                mock=True,
                extractor="demo",
            )
            for row in self.rows(data)
        ]
