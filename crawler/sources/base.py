from crawler.schema import CollectedItem
from crawler.http import PublicClient


class RealSource:
    mock = False
    source_id: str
    source_name: str
    kind: str
    source_url: str
    # Populated by the CLI from the registry. ``None`` means the source's authority is
    # unknown, which the auto-verification rule treats as non-authoritative (fail closed).
    trust_level: str | None = None
    # The extraction method key recorded for this source's event items, when it has one.
    extractor: str | None = None

    def __init__(self, client=None, max_items=3):
        self.client = client or PublicClient()
        self.max_items = max_items
        self.errors = []
        self.warnings = []
        self.pages_collected = 0
        self.request_attempts = 0

    def item(self, page, *, key=None, extractor="jsonld", is_event=True, locator=None):
        return CollectedItem(
            item_key=key or page.url,
            original_url=page.url,
            source_name=self.source_name,
            crawl_time=page.crawl_time,
            raw_content=page.content,
            mock=False,
            extractor=extractor,
            is_event=is_event,
            locator=locator,
            request_metadata=page.metadata,
        )

    def fetch(self, url):
        start = len(self.client.requests)
        try:
            page = self.client.get(url)
            self.pages_collected += 1
            return page
        finally:
            self.request_attempts += len(self.client.requests) - start
