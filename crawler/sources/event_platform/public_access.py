"""Fail-closed public-page access for the priority investigations only."""
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from crawler.http import Page, USER_AGENT, MAX_WAIT_SECONDS
from crawler.sources.base import RealSource


class PublicAccessSource(RealSource):
    require_events = True  # the gate is deliberately stricter than crawler.http._policy.
    # Default STRICT preserves the original fail-closed behaviour: an HTML (non-rules) body
    # at the robots URL is treated as an unusable policy and stops the source.
    # A source may set this True only when the handler is documented as publishing no
    # robots.txt at all (a catch-all soft-404), in which case HTTP 404/410-like
    # "no usable rules" semantics apply. A genuine denial (401/403, 5xx, redirect,
    # unexpected status) still stops the source either way.
    accept_soft_404_robots = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy_items = []
        self._policies = {}

    def is_public_url(self, url):
        raise NotImplementedError

    def approved_route(self, url):
        """Raise before ANY request is built when a URL is outside the approved routes."""
        if not self.is_public_url(url):
            raise ValueError('URL is outside the approved public entry/detail routes; no request made')

    def approved_policy(self, url):
        """The fail-closed robots policy for this URL's origin, or raise before fetching.

        Resolved once per origin and cached on the source, exactly as before. It is shared
        by ``public_page`` and ``public_json`` so a client-rendered source cannot reach its
        JSON API on a host whose policy already stopped the page request (or the reverse).
        """
        parts = urlparse(url)
        base = parts.scheme + '://' + parts.netloc
        if base not in self._policies:
            robots_url = base + '/robots.txt'
            # Only robots is requested at this stage. Redirects are NOT followed.
            response = self.client._request(robots_url, is_robots=True)
            now = datetime.now(timezone.utc)
            if response.text:
                page = Page(robots_url, response.text, now,
                            response.headers.get('content-type', 'text/plain'),
                            {'status': response.status_code, 'purpose': 'robots_policy_only'})
                self.policy_items.append(self.item(page, key='robots:' + base,
                                                   extractor='context', is_event=False))
            parser = RobotFileParser()
            parser.set_url(robots_url)
            if response.status_code in (404, 410):
                parser.parse([])
                label = 'robots absent (HTTP 404/410)'
            elif response.status_code == 200 and not response.text.strip():
                parser.parse([])
                label = 'empty robots.txt'
            elif (response.status_code == 200
                  and not response.text.lstrip().startswith('<')
                  and 'user-agent:' in response.text.lower()):
                parser.parse(response.text.splitlines())
                label = 'robots.txt'
            elif (response.status_code == 200
                  and response.text.lstrip().startswith('<')
                  and self.accept_soft_404_robots):
                # The host serves its catch-all HTML page at /robots.txt, i.e. it
                # publishes no rules at all. This is "no usable rules" (matching
                # crawler.http._policy), not a denial: nothing was disallowed.
                parser.parse([])
                label = 'no usable robots rules returned (HTML catch-all at /robots.txt)'
            else:
                reason = ('Robots policy unavailable: HTTP ' + str(response.status_code)
                          + (' redirect (not followed)' if response.is_redirect else
                             ' HTML/non-rules response' if response.status_code == 200 else '')
                          + '; no public page request made')
                self._policies[base] = reason
                raise PermissionError(reason)
            self._policies[base] = parser
            # The normal HTTP client uses the same checked policy, spacing and audit.
            self.client.robots[base] = (parser, label)
        policy = self._policies[base]
        if isinstance(policy, str):
            raise PermissionError(policy)
        # Explicit stop condition before ANY page request.
        if not policy.can_fetch(USER_AGENT, url):
            raise PermissionError('robots.txt disallows this URL; no public page request made')
        delay = policy.crawl_delay(USER_AGENT)
        if delay and delay > MAX_WAIT_SECONDS:
            raise PermissionError('Robots crawl delay exceeds bounded wait; no public page request made')
        self.client.host_intervals[parts.netloc] = max(self.client.interval, delay or 0)

    def public_page(self, url, allowed_redirect=None, media=None):
        # Fail closed by default: every redirect must still land on one of this source's
        # approved public routes. Omitting the argument must NOT disable that check — doing
        # so let a detail page redirect to an off-route URL (e.g. /login) and be fetched.
        if allowed_redirect is None:
            allowed_redirect = self.is_public_url
        self.approved_route(url)
        start = len(self.client.requests)
        try:
            self.approved_policy(url)
            page = self.client.get(
                url, allowed_redirect=allowed_redirect,
                media=tuple(media) if media else ("html", "json", "text/plain"),
            )
            self.pages_collected += 1
            return page
        finally:
            self.request_attempts += len(self.client.requests) - start

    def public_json(self, url, *, method='GET', json_body=None, headers=None):
        """Read one approved public JSON endpoint under the same fail-closed policy.

        Two registered venue sources serve an empty application shell and put their whole
        calendar behind the JSON endpoint their own published JavaScript calls. This method
        reaches exactly such an endpoint: the route allow-list, the robots policy, the
        redirect boundary, the 2 MB cap and the request audit are the ones ``public_page``
        already enforces. A POST body is a bounded public filter, and the only header this
        can carry is the host's own published channel header — never a credential.
        """
        self.approved_route(url)
        start = len(self.client.requests)
        try:
            self.approved_policy(url)
            page = self.client.request_json(
                url, method=method, json_body=json_body, headers=headers,
                allowed_redirect=self.is_public_url,
            )
            self.pages_collected += 1
            return page
        finally:
            self.request_attempts += len(self.client.requests) - start


def public_https(url, host):
    parts = urlparse(url)
    return (parts.scheme == 'https' and parts.hostname == host and parts.port in (None, 443)
            and parts.username is None and parts.password is None and not parts.fragment)


def blocked_page(content):
    # Access-wall text only; do not attempt login, challenges or protected APIs.
    from bs4 import BeautifulSoup
    import re
    soup = BeautifulSoup(content, 'html.parser')
    for node in soup.select('script,style'):
        node.decompose()
    body = soup.get_text(' ', strip=True)
    return bool(re.search(r'请先登录|登录后查看|访问验证|滑动验证|拖动滑块|人机验证|验证码验证|captcha|access denied', body, re.I))
