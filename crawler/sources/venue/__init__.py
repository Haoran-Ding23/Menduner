import json
from crawler.sources.base import RealSource


class VenueSource(RealSource):
    source_id = "venue-suzhou-orchestra"
    source_name = "苏州交响乐团官方演出栏目"
    kind = "venue"
    source_url = "https://www.szsorch.com/shows-ticketing.html"

    def collect(self):
        # Public GET used by the venue's own page, without token/authentication.
        url = f"https://www.szsorch.com/api/getMusicData/2026-27-music-sea50n/1?pageNum=0&pageSize={self.max_items}"
        items = []
        try:
            page = self.fetch(url)
            items.append(
                self.item(
                    page,
                    key="schedule-context",
                    is_event=False,
                    extractor="orchestra_json",
                )
            )
            for row in json.loads(page.content).get("content", [])[: self.max_items]:
                items.append(
                    self.item(
                        page,
                        key=str(row["id"]),
                        extractor="orchestra_json",
                        locator=str(row["id"]),
                    )
                )
            if len(items) == 1:
                self.warnings.append("Public schedule contains no event records")
        except Exception as exc:
            self.errors.append({"url": url, "error": str(exc)})
        return items


from .expo import ExpoVenueSource
from .sscac import SscacVenueSource
