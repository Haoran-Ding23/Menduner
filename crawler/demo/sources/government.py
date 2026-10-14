from pathlib import Path
from crawler.demo.base import FixtureSource


class SuzhouGovernmentSource(FixtureSource):
    source_id = "mock-government"
    source_name = "MOCK · Suzhou government source"
    kind = "government"
    source_url = "https://suzhou-government.example.invalid/events"
    fixture = Path(__file__).with_name("government.json")

    def rows(self, data):
        return data["items"]

    def key(self, row):
        return str(row["activity"]["id"])
