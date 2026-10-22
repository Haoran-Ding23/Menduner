"""Small validated source inventory; source identity is separate from fact verification."""
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REGISTRY_PATH = Path(__file__).with_name('source_registry.yaml')
CATEGORIES = ('government', 'venue', 'event_platform', 'media', 'tourism',
              'sports', 'education', 'social_media')


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    category: Literal['government', 'venue', 'event_platform', 'media', 'tourism',
                      'sports', 'education', 'social_media']
    url: str | None
    crawl_url: str | None = None
    trust_level: Literal['OFFICIAL_GOVERNMENT', 'OFFICIAL_VENUE', 'COMMERCIAL_PLATFORM',
                         'SECONDARY_MEDIA', 'MANUAL_IDENTITY_CHECK']
    priority: int = Field(ge=1, le=3)
    crawl_status: Literal['NOT_ATTEMPTED', 'SUCCESS', 'PARTIAL', 'FAILED',
                         'MANUAL_VERIFICATION_REQUIRED'] = 'NOT_ATTEMPTED'
    tier: int = Field(ge=1, le=2)
    # Whether a run that publishes no event must be reported FAILED rather than a silent
    # SUCCESS. Defaults to the tier-1 contract so existing rows are unchanged, but it is
    # decoupled from `tier` because "--tier1 selects the ten supplied sources" and
    # "this source must prove it still works" are different questions.
    require_events: bool | None = None
    adapter: str | None
    implementation: Literal['event_extraction', 'public_page_audit', 'manual_only']
    # Additional approved listing routes on the same registered host. A source is an
    # organization, and one organization publishes its activity pages under several channel
    # routes; `crawl_url` stays the primary entry (and the registered original URL's
    # counterpart), while these are read in the same bounded run. Every route obeys the same
    # host, scheme and robots rules as `crawl_url`.
    listing_urls: list[str] = Field(default_factory=list)
    # The same-host detail-page path shape this source's listing links must match. When it is
    # set, the registry is the authority on the route shape rather than the adapter class.
    detail_pattern: str | None = None
    # How many pages of each registered listing route are read, page 1 being the route itself.
    # A CMS route is a feed that pushes the newest records onto page 1; if the source's own
    # pager advertises `list_N.shtml`, reading a bounded number of those pages is how the
    # source is read the way its own readers read it. It has to stay bounded: the largest
    # observed route advertises 534 pages and this crawler is a prototype, so the page count
    # is declared per source instead of being followed.
    listing_pages: int = Field(default=1, ge=1, le=10)
    # The page-URL template for the routes above: ``{c}`` stands for a route's own path segments
    # (everything between the registered host and the page number) and ``{n}`` for the 2-based
    # page number. Each registered route must round-trip through the template, so a template that
    # would point at a different channel or host is refused rather than fetched.
    route_page_pattern: str | None = None
    reason: str | None = None
    limitation: str | None = None
    # HTTPS is required for every web source by default. A host whose certificate is not
    # valid for its own hostname may be collected over plain HTTP only through this
    # explicit, per-source opt-in, which records the unverifiable-integrity limitation.
    allow_plain_http: bool = False
    last_checked: str | None = None
    topic: str | None = None
    platform: str | None = None
    status: str | None = None
    name: str | None = None
    detail_urls: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode='after')
    def boundaries(self):
        if self.category == 'social_media':
            if self.adapter is not None or self.implementation != 'manual_only':
                raise ValueError('Social media is manual-only; no crawler adapter')
            if self.crawl_status != 'MANUAL_VERIFICATION_REQUIRED':
                raise ValueError('Social media requires manual verification')
        else:
            if not self.adapter or not self.url or not self.crawl_url:
                raise ValueError('Web sources require an adapter, original URL and crawl URL')
            for url in (self.url, self.crawl_url):
                parts = urlparse(url)
                if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
                    raise ValueError('Invalid public source URL')
            if urlparse(self.crawl_url).hostname != urlparse(self.url).hostname or urlparse(self.crawl_url).port not in (None, 443):
                raise ValueError('Crawl URL must stay on the registered host and HTTPS port')
            scheme = urlparse(self.crawl_url).scheme
            if scheme == 'http' and not self.allow_plain_http:
                raise ValueError('Use HTTPS for event collection; retain supplied HTTP URL as metadata')
            if scheme not in ('http', 'https'):
                raise ValueError('Crawl URL must be HTTP or HTTPS')
            if scheme == 'http' and not self.limitation:
                raise ValueError('Plain-HTTP collection must record its integrity limitation')
            for extra in self.listing_urls:
                parts = urlparse(extra)
                if (parts.scheme != scheme or parts.hostname != urlparse(self.crawl_url).hostname
                        or parts.port not in (None, 443)
                        or parts.username or parts.password
                        or parts.fragment):
                    raise ValueError(
                        'Every additional listing route must stay on the registered host, '
                        'transport and port')
            if len(set(self.listing_urls)) != len(self.listing_urls):
                raise ValueError('Duplicate additional listing route')
            if self.crawl_url in self.listing_urls:
                raise ValueError('The primary crawl URL is not repeated as an extra route')
            if self.detail_pattern is not None:
                try:
                    re.compile(self.detail_pattern)
                except re.error as exc:
                    raise ValueError('detail_pattern is not a valid regular expression: ' + str(exc))
            if self.route_page_pattern is not None:
                if self.listing_pages < 2:
                    raise ValueError(
                        'route_page_pattern is only meaningful when listing_pages reads more '
                        'than page 1')
                # The page placeholder is either `{n}` or `{_n}`, never both and never absent:
                # removing the underscore form leaves either exactly one `{n}` or none.
                without_underscore_pages = self.route_page_pattern.replace('{_n}', '')
                if (self.route_page_pattern.count('{c}') != 1
                        or without_underscore_pages.count('{n}') not in (0, 1)
                        or (without_underscore_pages.count('{n}') == 0
                            and '{_n}' not in self.route_page_pattern)):
                    raise ValueError(
                        'route_page_pattern must carry exactly one {c} segment placeholder and '
                        'exactly one page placeholder ({n}, or {_n} where page 1 prints no '
                        'number)')
                for known in (self.crawl_url, *self.listing_urls):
                    channel = route_channel(self.route_page_pattern, known)
                    if channel is None or page_url(self.route_page_pattern, channel, 1) != known:
                        raise ValueError(
                            'route_page_pattern does not describe the registered route ' + known)
                for page in range(2, self.listing_pages + 1):
                    sample = page_url(self.route_page_pattern, 'sample/channel', page)
                    sample_parts = urlparse(sample)
                    if (sample_parts.scheme != scheme
                            or sample_parts.hostname != urlparse(self.crawl_url).hostname
                            or sample_parts.port not in (None, 443)
                            or sample_parts.username or sample_parts.password
                            or sample_parts.fragment or not sample_parts.path):
                        raise ValueError(
                            'route_page_pattern must resolve to an absolute path on the '
                            'registered host and transport')
        if self.detail_urls:
            if self.adapter != 'damai':
                raise ValueError('Explicit detail seeds are supported only for the dedicated Damai adapter')
            from crawler.sources.event_platform.damai import DamaiSource
            if any(not DamaiSource.is_public_url(u) or urlparse(u).hostname != 'detail.damai.cn' for u in self.detail_urls):
                raise ValueError('Only canonical HTTPS Damai item URLs are permitted as detail seeds')
        if self.crawl_status == 'FAILED' and not self.reason:
            raise ValueError('FAILED source must include a reason')
        return self


def page_url(pattern, channel, page):
    """Build one page URL from the template, or '' when the template is unusable.

    ``{_n}`` is the page number in the form a CMS uses when page 1 carries no number at all:
    ``list{_n}.shtml`` is ``list.shtml`` for page 1, ``list_2.shtml`` for page 2 and
    ``list_3.shtml`` for page 3 — which is what wglj's own pager does. ``{n}`` is the bare
    number for a pager that always prints it (``?page={n}``).
    """
    if not pattern or channel is None:
        return ''
    return (pattern.replace('{c}', channel)
            .replace('{_n}', '' if int(page) == 1 else '_' + str(page))
            .replace('{n}', str(page)))


def route_channel(pattern, route):
    """The ``{c}`` value that reproduces ``route`` from ``pattern``, or None.

    The template is the only thing that turns one registered route into its further pages, so
    the same match is used when the registry validates the row and when the adapter expands it.
    The page placeholder is anchored at the end, so a page-1 route and its further pages can
    share one grammar (``.../hdxx/list.shtml`` and ``.../hdxx/list_2.shtml``).
    """
    if not pattern or '{c}' not in pattern or ('{n}' not in pattern and '{_n}' not in pattern):
        return None
    head, _, tail = pattern.partition('{c}')
    tail = tail.replace('{_n}', '').replace('{n}', '1')
    if not route.startswith(head) or not route.endswith(tail):
        return None
    channel = route[len(head):len(route) - len(tail)] if tail else route[len(head):]
    return channel or None


def load_registry(path=REGISTRY_PATH):
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != '1.6':
        raise ValueError('Expected V1.6 source registry')
    records = [SourceDefinition.model_validate(row) for row in data['sources']]
    for field in ('source_id', 'adapter'):
        values = [getattr(r, field) for r in records if getattr(r, field) is not None]
        if len(values) != len(set(values)):
            raise ValueError(f'Duplicate registry {field}')
    return records


def tier1_keys(path=REGISTRY_PATH):
    return [r.adapter for r in sorted(load_registry(path), key=lambda r: r.priority)
            if r.tier == 1 and r.adapter]
