import re

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


class TaicangCultureSource(RealSource):
    """太仓市文体广电和旅游局's 太仓文化 column, which does publish event notices.

    This is the answer to "太仓 has almost no events". The county-level city's own portal is
    the only official channel that lists its exhibitions with a date range, a venue and the
    publishing bureau, and it was missed the first time because the section is reachable only
    through 政务服务 > 专题服务 > 文化教育, and its listing path (`zwfw_list.shtml`) is not
    guessable from the article URLs alone.

    Each article is a 展讯 with the shape
        展览日期： 2026.10.20 — 11.20
        展览地点：太仓美术馆 4 号展厅
    which is exactly the two fields the calendar needs, stated by the authority rather than
    inferred. The listing paginates as `zwfw_list_2.shtml` .. `zwfw_list_14.shtml`; the last
    page is short and the one after it is empty, so a page without links ends the walk.
    """

    source_id = "government-taicang-culture"
    source_name = "太仓市文体广电和旅游局·太仓文化栏目"
    kind = "government"
    source_url = "https://www.taicang.gov.cn/taicang/tcwh/zwfw_list.shtml"
    extractor = "taicang_culture"

    # The first page, kept as a plain string because the CLI assigns the registry's crawl_url
    # to adapters that expose `listing_url` as data. The per-page URL is built by page_url(),
    # which is deliberately not called listing_url() so that assignment cannot replace it.
    listing_url = "https://www.taicang.gov.cn/taicang/tcwh/zwfw_list.shtml"
    listing_base = "https://www.taicang.gov.cn/taicang/tcwh/zwfw_list"
    detail_pattern = re.compile(r"^/taicang/tcwh/20\d{4}/[0-9a-f]{20,}\.shtml$")
    page_cap = 14
    # A page that yields no detail links means the archive has ended; stop rather than
    # requesting 14 pages of the same fallback document.
    empty_page_limit = 1

    def page_url(self, page_number: int) -> str:
        suffix = "" if page_number == 1 else f"_{page_number}"
        return f"{self.listing_base}{suffix}.shtml"

    def _links(self, content: bytes, base_url: str) -> list[str]:
        from urllib.parse import urljoin, urlparse

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")
        out: list[str] = []
        for node in soup.select("a[href]"):
            url = urljoin(base_url, node["href"])
            parts = urlparse(url)
            if parts.scheme == "https" and parts.hostname == "www.taicang.gov.cn" \
                    and self.detail_pattern.fullmatch(parts.path) and url not in out:
                out.append(url)
        return out

    def collect(self):
        items = []
        seen: set[str] = set()
        collected = 0
        empty_pages = 0

        for page_number in range(1, self.page_cap + 1):
            if collected >= self.max_items:
                break
            url = self.page_url(page_number)
            try:
                page = self.fetch(url)
            except Exception as exc:
                self.errors.append({"url": url, "error": str(exc)})
                break

            # Keep the listing page itself as context, the same way every other adapter does,
            # so the index behind a set of events can be re-read later.
            items.append(self.item(page, key=f"listing-{page_number}", is_event=False,
                                   extractor="context"))

            links = [link for link in self._links(page.content, page.url) if link not in seen]
            if not links:
                empty_pages += 1
                if empty_pages >= self.empty_page_limit:
                    self.warnings.append({
                        "url": url,
                        "warning": f"no further event links after page {page_number}; "
                                   f"stopped at {page_number - 1} listing page(s)",
                    })
                    break
                continue
            empty_pages = 0

            for detail_url in links:
                if collected >= self.max_items:
                    break
                seen.add(detail_url)
                try:
                    items.append(self.item(self.fetch(detail_url),
                                           extractor=self.extractor))
                    collected += 1
                except Exception as exc:
                    self.errors.append({"url": detail_url, "error": str(exc)})

        return items
