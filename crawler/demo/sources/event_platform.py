from pathlib import Path
from crawler.demo.base import FixtureSource


class EventPlatformSource(FixtureSource):
    source_id = "mock-platform"
    source_name = "MOCK · Event platform source"
    kind = "event_platform"
    source_url = "https://city-events.example.invalid/events"
    fixture = Path(__file__).with_name("event_platform.json")

    def rows(self, data):
        return data["events"]

    def key(self, row):
        return str(row["id"])
