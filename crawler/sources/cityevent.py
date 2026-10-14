"""Bounded Tier 1 public web adapters. No browser, login, token or app endpoints."""
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from crawler.sources.base import RealSource

EVENT_WORDS = re.compile(r'音乐会|演唱会|艺术周|文化节|展览|特展|文博会|博览会|讲座|嘉年华|盛典|活动')


class ArticleListSource(RealSource):
    require_events = True
    listing_url: str
    detail_pattern: str
    extractor = 'official_article_v16'
    filter_titles = True

    def collect(self):
        items = []
        try:
            page = self.fetch(self.listing_url)
            items.append(self.item(page, key='listing-context', is_event=False, extractor='context'))
            soup = BeautifulSoup(page.content, 'html.parser')
            links = []
            for node in soup.select('a[href]'):
                url = urljoin(page.url, node['href'])
                parts = urlparse(url)
                if (parts.scheme == 'https' and parts.hostname == urlparse(page.url).hostname
                        and re.fullmatch(self.detail_pattern, parts.path)
                        and (not self.filter_titles or EVENT_WORDS.search(node.get_text(' ', strip=True))) and url not in links):
                    links.append(url)
            if not links:
                self.errors.append({'url': page.url, 'error': 'No supported public event detail links in this bounded listing'})
            for url in links[:self.max_items]:
                try:
                    items.append(self.item(self.fetch(url), extractor=self.extractor))
                except Exception as exc:
                    self.errors.append({'url': url, 'error': str(exc)})
        except Exception as exc:
            self.errors.append({'url': self.listing_url, 'error': str(exc)})
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


class PublicPageAuditSource(RealSource):
    """Attempt only the approved public page; unsupported sources publish nothing."""
    require_events = True
    reason = 'No reliable static event records; source requires manual review'
    crawl_url: str

    def collect(self):
        try:
            page = self.fetch(self.crawl_url)
            self.errors.append({'url': page.url, 'error': self.reason})
            return [self.item(page, key='audit-context', is_event=False, extractor='context')]
        except Exception as exc:
            self.errors.append({'url': self.crawl_url, 'error': str(exc)})
            return []


class ArtsCentreSource(PublicPageAuditSource):
    source_id = 'venue-suzhou-arts'
    source_name = 'Suzhou Culture and Arts Centre'
    kind = 'venue'
    # Verified 2026-10-13: the supplied www.suzhoupcc.com does not resolve (NXDOMAIN).
    # www.sscac.com.cn is the real official host, but it is a Nuxt shell that serves an
    # empty state payload (state:{list:{list:[]}}) with no event data in the HTML.
    source_url = crawl_url = 'https://www.sscac.com.cn/'
    reason = ('Official host publishes no event data in the served HTML (client-rendered '
              'Nuxt shell with an empty state payload); its events are reachable via the '
              'visitsz tourism portal instead')


from crawler.sources.event_platform.huodongjia import HuodongjiaSource


from crawler.sources.event_platform.damai import DamaiSource

# China Exhibition Network is no longer an audit-only handler: the supplied city route
# was a 404 page and the venue schedule page carries real dated exhibitions, so it has a
# dedicated extraction adapter in crawler/sources/exhibition/cnena.py.
