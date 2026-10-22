"""Bounded Tier 1 public web adapters. No browser, login, token or app endpoints."""
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from crawler.registry import page_url, route_channel
from crawler.sources.base import RealSource

EVENT_WORDS = re.compile(r'音乐会|演唱会|艺术周|文化节|展览|特展|文博会|博览会|讲座|嘉年华|盛典|活动')


class ArticleListSource(RealSource):
    """A government/media publisher read through its own server-rendered listing routes.

    One source is one organization, and an organization publishes its event announcements
    under several channel routes (活动信息, 通知公告, 工作动态, ...). ``listing_url`` remains the
    primary entry recorded in ``crawl_url``; ``extra_listing_urls`` are additional approved
    routes on the same host, assigned by the CLI from the registry row. Every route is read
    under the same bounded contract: same host, HTTPS, robots consulted first, at most
    ``max_items`` detail pages across the whole source, and a route that yields no supported
    detail link is recorded in ``errors`` rather than passed over silently.
    """

    require_events = True
    listing_url: str
    # Assigned from the registry row's `listing_urls`. Empty means the source has one route.
    extra_listing_urls: tuple[str, ...] = ()
    # Assigned from the registry row's `listing_pages` / `route_page_pattern`. One page means the
    # route itself, exactly as before; more pages means the source's own pager is followed by the
    # template its markup advertises (".../hdxx/list.shtml" -> ".../hdxx/list_2.shtml").
    listing_pages: int = 1
    route_page_pattern: str | None = None
    detail_pattern: str
    extractor = 'official_article_v16'
    filter_titles = True

    def listing_routes(self):
        """Every approved listing URL, primary route first, then the registered extras.

        A source is one publisher and one publisher's feed is paged, so each route expands into
        at most ``listing_pages`` page URLs — page 1 being the route itself. The page grammar is
        the source's own (``.../hdxx/list.shtml`` -> ``.../hdxx/list_2.shtml``), and nothing is
        inferred about a page that does not exist: a page that is absent is recorded in
        ``errors`` like any other route failure.
        """
        routes = []
        for route in (self.listing_url, *self.extra_listing_urls):
            if not route or route in routes:
                continue
            routes.extend(page for page in self.route_pages(route) if page not in routes)
        return routes

    def route_channel(self, route):
        """The path segments a registered route occupies inside ``route_page_pattern``."""
        if not self.route_page_pattern:
            return None
        return route_channel(self.route_page_pattern, route)

    def route_pages(self, route):
        """``[route]``, or the route plus its further registered pages, in page order."""
        channel = self.route_channel(route)
        if self.listing_pages < 2 or not channel:
            return [route]
        return [page_url(self.route_page_pattern, channel, page)
                for page in range(1, self.listing_pages + 1)]

    def detail_links(self, page):
        """Same-host links on one listing page that match this source's detail pattern."""
        soup = BeautifulSoup(page.content, 'html.parser')
        links = []
        for node in soup.select('a[href]'):
            href = node['href']
            # A CMS that wraps attributes across lines hands back a list, not a string.
            if not isinstance(href, str) or not href.strip():
                continue
            url = urljoin(page.url, href)
            parts = urlparse(url)
            if (parts.scheme == 'https' and parts.hostname == urlparse(page.url).hostname
                    and re.fullmatch(self.detail_pattern, parts.path)
                    and (not self.filter_titles or EVENT_WORDS.search(node.get_text(' ', strip=True)))
                    and url not in links):
                links.append(url)
        return links

    def detail_budget(self, route_count):
        """``max_items`` split across the configured routes.

        The primary route is the source's own activity feed and takes half the budget; the
        remaining registered routes share the rest, one detail each when the budget is tight.
        The budget is a detail-page count for the whole source, not a per-route count, so adding
        a route can never multiply the requests the source makes, and a route whose links were
        already published by another route does not consume a slot of its own (see ``collect``).
        """
        if route_count <= 0:
            return []
        if route_count == 1:
            return [self.max_items]
        primary = max(1, self.max_items // 2)
        others = self.max_items - primary
        base, remainder = divmod(others, route_count - 1)
        return [primary] + [base + (1 if index < remainder else 0)
                            for index in range(route_count - 1)]

    def collect(self):
        items = []
        routes = self.listing_routes()
        per_route_links = []
        for route in routes:
            try:
                page = self.fetch(route)
            except Exception as exc:
                self.errors.append({'url': route, 'error': str(exc)})
                per_route_links.append([])
                continue
            items.append(self.item(page, key='listing-context:' + route, is_event=False,
                                   extractor='context'))
            found = self.detail_links(page)
            if not found:
                self.errors.append({
                    'url': page.url,
                    'error': 'No supported public event detail links in this bounded listing'})
            per_route_links.append(found)
        # One pass per route over the queued links, bounded by that route's share. A link that
        # another route already published is skipped, so a shared "top story" is one event, not
        # two, and a route whose links were all duplicates does not consume the whole budget.
        chosen = []
        budgets = self.detail_budget(len(routes))
        for depth in range(max((len(links) for links in per_route_links), default=0)):
            for index, links in enumerate(per_route_links):
                if depth >= budgets[index]:
                    continue
                if depth < len(links) and links[depth] not in chosen:
                    chosen.append(links[depth])
        for url in chosen[:self.max_items]:
            try:
                items.append(self.item(self.fetch(url), extractor=self.extractor))
            except Exception as exc:
                self.errors.append({'url': url, 'error': str(exc)})
        return items


class SIPACSource(ArticleListSource):
    source_id = 'government-sipac'
    source_name = 'Suzhou Industrial Park (SIPAC)'
    kind = 'government'
    source_url = 'http://www.sipac.gov.cn/'
    listing_url = 'https://www.sipac.gov.cn/'
    detail_pattern = r'/szgyyq/(?:jsdt|mtjj)/\d{6}/[a-f0-9]{32}\.shtml'


class CultureTourismSource(ArticleListSource):
    filter_titles = False
    source_id = 'government-suzhou-culture-tourism'
    source_name = 'Suzhou Culture and Tourism Bureau'
    kind = 'government'
    source_url = 'http://wglj.suzhou.gov.cn/'
    listing_url = 'https://wglj.suzhou.gov.cn/szwhgdhlyj/hdxx/list.shtml'
    detail_pattern = r'/szwhgdhlyj/hdxx/\d{6}/[a-f0-9]{32}\.shtml'


class SubaoSource(ArticleListSource):
    source_id = 'media-subao'
    source_name = 'Subao News'
    kind = 'media'
    source_url = 'https://www.subaonet.com/'
    listing_url = 'https://www.subaonet.com/list/szwl/'
    detail_pattern = r'/20\d{2}/(?:szwh|szwl)/\d{4}/[A-Za-z0-9]+\.html'
    extractor = 'media_article_v16'


class OlympicSource(RealSource):
    source_id = 'venue-suzhou-olympic'
    source_name = 'Suzhou Olympic Sports Centre'
    source_url = 'https://www.szosc.cn/'
    kind = 'venue'
    require_events = True
    listing_url = 'https://www.szosc.cn/index.php/Activity/index.html'
    feed_url = 'https://www.szosc.cn/Activity/gethd.html?limit=0'

    def collect(self):
        items = []
        try:
            listing = self.fetch(self.listing_url)
            items.append(self.item(listing, key='listing-context', is_event=False, extractor='context'))
            # This public GET is explicitly used by the official listing's own JS.
            if '/Activity/gethd.html' not in listing.content:
                raise ValueError('Official listing no longer identifies the approved public feed')
            feed = self.fetch(self.feed_url)
            items.append(self.item(feed, key='feed-context', is_event=False, extractor='context'))
            records = json.loads(feed.content).get('lists')
            if not isinstance(records, list) or not records:
                raise ValueError('Official public feed returned no event records')
            seen = set()
            for row in records[:self.max_items]:
                key = str(row.get('id', ''))
                if not re.fullmatch(r'[1-9]\d{0,8}', key):
                    self.errors.append({'url': feed.url, 'error': 'Invalid public event ID; no request made'})
                    continue
                if key in seen:
                    continue
                seen.add(key)
                url = 'https://www.szosc.cn/Activity/xx/id/' + key
                try:
                    items.append(self.item(self.fetch(url), key=key, extractor='olympic_detail'))
                except Exception as exc:
                    self.errors.append({'url': url, 'error': str(exc)})
        except Exception as exc:
            self.errors.append({'url': self.listing_url, 'error': str(exc)})
        return items


from crawler.sources.event_platform.huodongjia import HuodongjiaSource


from crawler.sources.event_platform.damai import DamaiSource

# The audit-only handler that used to serve 苏州文化艺术中心 is gone: the host is a
# client-rendered shell, but the shell's own published JavaScript calls a public JSON API that
# carries the whole performance calendar, so the source now extracts real events in
# crawler/sources/venue/sscac.py. 苏州国际博览中心 (crawler/sources/venue/expo.py) moved the
# same way.

# China Exhibition Network is no longer an audit-only handler: the supplied city route
# was a 404 page and the venue schedule page carries real dated exhibitions, so it has a
# dedicated extraction adapter in crawler/sources/exhibition/cnena.py.
