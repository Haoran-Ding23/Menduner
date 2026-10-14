"""Dedicated Damai event adapter for robots-permitted public HTML only."""
from urllib.parse import urlparse, parse_qs
import re
import httpx

from .public_access import PublicAccessSource, public_https, blocked_page


class DamaiSource(PublicAccessSource):
    source_id = 'platform-damai-suzhou'
    source_name = 'Damai Suzhou'
    kind = 'event_platform'
    source_url = crawl_url = 'https://search.damai.cn/'
    detail_urls = ()

    @staticmethod
    def is_public_url(url):
        parts = urlparse(url)
        if public_https(url, 'search.damai.cn'):
            return parts.path in ('', '/') and not parts.query
        if public_https(url, 'detail.damai.cn') and parts.path == '/item.htm':
            query = parse_qs(parts.query, keep_blank_values=True)
            return (set(query) == {'id'} and len(query['id']) == 1
                    and re.fullmatch(r'[1-9]\d{5,14}', query['id'][0]) is not None)
        return False

    def collect(self):
        items = []
        # A denied search route is never fetched. Independently configured detail URLs
        # are checked against THEIR host's robots rules, not used as a search bypass.
        try:
            page = self.public_page(self.crawl_url)
            items.append(self.item(page, key='search-context', extractor='context', is_event=False))
            if blocked_page(page.content):
                self.errors.append({'url': page.url, 'error': 'Search access wall; no login/CAPTCHA/private API attempt'})
            else:
                self.warnings.append('No search API or mobile-app discovery; detail collection uses explicit approved public URLs only')
        except Exception as exc:
            self.errors.append({'url': self.crawl_url, 'error': str(exc)})
        seen = set()
        for url in list(self.detail_urls)[:self.max_items]:
            if url in seen:
                continue
            seen.add(url)
            if not self.is_public_url(url) or urlparse(url).hostname != 'detail.damai.cn':
                self.errors.append({'url': url, 'error': 'Not an approved Damai item URL; no request made'})
                continue
            try:
                page = self.public_page(url)
                key = parse_qs(urlparse(page.url).query)['id'][0]
                items.append(self.item(page, key=key, extractor='damai_public_event'))
                if blocked_page(page.content):
                    self.errors.append({'url': page.url, 'error': 'Detail access wall; no login/CAPTCHA/private API attempt'})
                    break
            except (PermissionError, httpx.HTTPStatusError) as exc:
                self.errors.append({'url': url, 'error': str(exc)})
                if isinstance(exc, PermissionError) or exc.response.status_code in (401, 403, 429):
                    break  # Stop this host on policy/protection/rate-limit barriers.
            except Exception as exc:
                self.errors.append({'url': url, 'error': str(exc)})
                break
        if not self.detail_urls:
            self.errors.append({'url': self.crawl_url, 'error': 'No approved public detail URLs configured; no events invented from search results'})
        return [*self.policy_items, *items]
