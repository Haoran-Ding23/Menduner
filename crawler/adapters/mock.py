import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from backend.models import EventRecord

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'

@dataclass
class CollectedSource:
    id: str
    name: str
    kind: str
    records: list[dict]
    mock: bool = True
    source_url: str | None = None

class SourceAdapter(Protocol):
    def collect(self) -> CollectedSource: ...

class OfficialVenueAdapter:
    """Mock venue calendar with flat title/begin/finish fields."""
    def collect(self):
        raw = json.loads((FIXTURES / 'official_venue.json').read_text(encoding='utf-8'))
        records = [EventRecord.model_validate(dict(row['details'], id=row['event_id'], name=row['title'],
                   startDate=row['begin'], endDate=row['finish'], demo=True)).model_dump(mode='json') for row in raw]
        return CollectedSource('mock-venue', 'MOCK · 官方场馆适配器', 'official_venue', records)

class GovernmentEventAdapter:
    """Mock government bulletin with nested date and activity fields."""
    def collect(self):
        raw = json.loads((FIXTURES / 'government.json').read_text(encoding='utf-8'))
        records = [EventRecord.model_validate(dict(row['details'], id=row['activity']['id'], name=row['activity']['name'],
                   startDate=row['dates']['start'], endDate=row['dates']['end'], demo=True)).model_dump(mode='json') for row in raw['items']]
        return CollectedSource('mock-government', 'MOCK · 政府活动适配器', 'government', records)
