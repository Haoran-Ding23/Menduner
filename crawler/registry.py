"""Small validated source inventory; source identity is separate from fact verification."""
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
        if self.detail_urls:
            if self.adapter != 'damai':
                raise ValueError('Explicit detail seeds are supported only for the dedicated Damai adapter')
            from crawler.sources.event_platform.damai import DamaiSource
            if any(not DamaiSource.is_public_url(u) or urlparse(u).hostname != 'detail.damai.cn' for u in self.detail_urls):
                raise ValueError('Only canonical HTTPS Damai item URLs are permitted as detail seeds')
        if self.crawl_status == 'FAILED' and not self.reason:
            raise ValueError('FAILED source must include a reason')
        return self


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
