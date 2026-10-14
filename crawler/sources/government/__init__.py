from crawler.sources.base import RealSource


class SuzhouGovernmentSource(RealSource):
    source_id = "government-suzhou"
    source_name = "苏州市人民政府公开活动报道"
    kind = "government"
    source_url = "https://www.suzhou.gov.cn/"
    seeds = (
        "https://www.suzhou.gov.cn/szsrmzf/szyw/202610/0ba8650590584318b6c3051171a8c539.shtml",
        "https://www.suzhou.gov.cn/szsrmzf/wtly/202609/b211ae650d744fb69943e5fb88524f48.shtml",
    )

    def collect(self):
        items = []
        for url in self.seeds[: self.max_items]:
            try:
                items.append(self.item(self.fetch(url), extractor="government_article"))
            except Exception as exc:
                self.errors.append({"url": url, "error": str(exc)})
        return items
