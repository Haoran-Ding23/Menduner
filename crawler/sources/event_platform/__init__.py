from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from crawler.sources.base import RealSource


class EventPlatformSource(RealSource):
    source_id = "platform-shanghai-concerts"
    source_name = "上海乐历（苏州公开演出页面）"
    kind = "event_platform"
    source_url = "https://shanghaiconcerts.com/venues/suzhou-culture-arts-centre"

    def collect(self):
        items = []
        try:
            listing = self.fetch(self.source_url)
            items.append(self.item(listing, is_event=False, extractor="context"))
            soup = BeautifulSoup(listing.content, "html.parser")
            links = []
            for node in soup.select("a[href]"):
                url = urljoin(listing.url, node["href"])
                if (
                    urlparse(url).hostname == "shanghaiconcerts.com"
                    and urlparse(url).path.startswith("/concerts/")
                    and url not in links
                ):
                    links.append(url)
            if not links:
                self.warnings.append("No public concert detail links found")
            for url in links[: self.max_items]:
                try:
                    items.append(self.item(self.fetch(url), extractor="jsonld"))
                except Exception as exc:
                    self.errors.append({"url": url, "error": str(exc)})
        except Exception as exc:
            self.errors.append({"url": self.source_url, "error": str(exc)})
        return items
