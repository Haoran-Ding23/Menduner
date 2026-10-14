from pathlib import Path
from crawler.demo.base import FixtureSource


class VenueSource(FixtureSource):
    source_id = "mock-venue"
    source_name = "MOCK · Venue source"
    kind = "venue"
    source_url = "https://suzhou-venue.example.invalid/calendar"
    fixture = Path(__file__).with_name("venue.json")

    def rows(self, data):
        return data

    def key(self, row):
        return str(row["event_id"])
