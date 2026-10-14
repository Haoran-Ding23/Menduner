"""Public HTML schedule investigation; token/header APIs are never called."""
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from crawler.sources.event_platform.public_access import PublicAccessSource, public_https, blocked_page


class ExpoVenueSource(PublicAccessSource):
    source_id = 'venue-suzhou-expo'
    source_name = '苏州国际博览中心官方展会日程'
    kind = 'venue'
    source_url = crawl_url = 'https://www.suzhouexpo.com/zhanhuiricheng-389.html'

    @staticmethod
    def is_public_url(url):
        parts = urlparse(url)
        return (public_https(url, 'www.suzhouexpo.com') and not parts.query
                and parts.path in ('/index.aspx', '/zhanhuiricheng-389.html'))

    def collect(self):
        items = []
        self.investigation = {'scope': 'public schedule HTML only', 'protected_api_requests': 0,
                              'token_header_detected': False, 'template_placeholders_detected': False}
        for url in (self.crawl_url, 'https://www.suzhouexpo.com/index.aspx'):
            try:
                page = self.public_page(url)
                items.append(self.item(page, extractor='context', is_event=False))
                soup = BeautifulSoup(page.content, 'html.parser')
                scripts = '\n'.join(s.get_text() for s in soup.select('script:not([src])'))
                self.investigation['token_header_detected'] |= bool(
                    re.search(r'headers\s*:[\s\S]{0,300}?token', scripts, re.I))
                self.investigation['template_placeholders_detected'] |= bool(
                    '{{' in page.content or soup.select('[v-for]'))
                if blocked_page(page.content):
                    self.errors.append({'url': page.url, 'error': 'Access wall; no login/CAPTCHA/API attempt'})
                    break
            except Exception as exc:
                self.errors.append({'url': url, 'error': str(exc)})
                break
        self.warnings.append(
            'No validated static schedule records. Template years/placeholders are not events. '
            'Dynamic token/header APIs were not requested.'
        )
        return [*self.policy_items, *items]
