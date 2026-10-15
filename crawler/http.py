"""Bounded public requests: robots, same-host redirects, backoff, no login or credentials.

Every source is read exactly the way a browser reads it. The two client-rendered venue
sources need the JSON endpoint their own published JavaScript calls, which is why a
bounded public POST and the host's own static channel header (published by the host in
its public ``config.js``, never a user credential) are supported here. Authorization,
Cookie and every other credential-style header stay impossible: see ``PUBLIC_JSON_HEADERS``.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx

USER_AGENT = (
    "MendunerEventResearch/1.5 (academic prototype; limited public event pages)"
)
MAX_PAGE_BYTES = 2_000_000
MAX_WAIT_SECONDS = 5
# Hosts whose event calendar is rendered client-side must be read through the same JSON API
# their own published JavaScript calls. That API is public, but two of them expect the
# request shape a browser sends rather than a bare GET: one POSTs a small JSON filter body
# and one sends the static channel header the host ships in its own public config.js.
# No other request header may be attached to a public collection request, so a credential
# (Authorization, Cookie, ...) can never be introduced by an adapter.
PUBLIC_JSON_HEADERS = frozenset({"access-token", "content-type", "accept"})


@dataclass
class Page:
    url: str
    content: str
    crawl_time: datetime
    content_type: str
    metadata: dict


class PublicClient:
    def __init__(
        self, *, transport=None, retries=2, interval=1.0, timeout=20, sleep=time.sleep,
        plain_http_hosts=(),
    ):
        self.client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )
        self.retries = retries
        self.interval = interval
        self.sleep = sleep
        # HTTPS is the default transport for every host. A host may only be collected over
        # plain HTTP when the source registry explicitly opts in (allow_plain_http), in
        # which case its unverifiable response integrity is recorded on that source row.
        self.plain_http_hosts = frozenset(h for h in (plain_http_hosts or ()) if h)
        self.robots = {}
        self.last_request = {}
        self.host_intervals = {}
        self.requests = []
        self.pages = []

    def close(self):
        self.client.close()

    def audit_since(self, request_start=0, page_start=0):
        requests = self.requests[request_start:]
        return dict(
            httpRequests=len(requests),
            robotsRequests=sum(r["robots"] for r in requests),
            retriedRequests=sum(r["attempt"] > 1 for r in requests),
            pageLog=self.pages[page_start:],
        )

    @staticmethod
    def _public_url(url, *, schemes=("https",)):
        parts = urlparse(url)
        if (
            parts.scheme not in schemes
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            raise ValueError("Only public URLs without credentials are supported")
        return parts

    def _public_page_url(self, url, *, schemes=("http", "https")):
        """Same boundary as ``_public_url``, but plain HTTP is permitted only for hosts
        that the registry explicitly allow-listed. Every other host stays HTTPS-only, so
        passing the wider scheme set here does not widen access for anyone else."""
        parts = self._public_url(url, schemes=schemes)
        if parts.scheme == "http" and parts.hostname not in self.plain_http_hosts:
            raise ValueError(
                "Only public URLs without credentials are supported"
            )
        return parts

    def _request(self, url, *, is_robots=False, method="GET", json_body=None, headers=None):
        host = urlparse(url).netloc
        for attempt in range(self.retries + 1):
            wait = self.host_intervals.get(host, self.interval) - (
                time.monotonic() - self.last_request.get(host, 0)
            )
            if wait > 0:
                self.sleep(wait)
            self.last_request[host] = time.monotonic()
            status = None
            try:
                with self.client.stream(
                    method, url, json=json_body, headers=headers
                ) as streamed:
                    status = streamed.status_code
                    chunks = []
                    size = 0
                    for chunk in streamed.iter_bytes():
                        size += len(chunk)
                        if size > MAX_PAGE_BYTES:
                            self.requests.append(dict(
                                url=url, status=streamed.status_code,
                                attempt=attempt + 1, robots=is_robots, method=method,
                                error="Page exceeds the 2 MB prototype limit",
                            ))
                            raise ValueError("Page exceeds the 2 MB prototype limit")
                        chunks.append(chunk)
                    # iter_bytes already decompressed the body; do not decode it twice.
                    headers_out = dict(streamed.headers)
                    headers_out.pop("content-encoding", None)
                    headers_out.pop("content-length", None)
                    response = httpx.Response(
                        streamed.status_code, headers=headers_out,
                        content=b"".join(chunks), request=streamed.request,
                    )
                self.requests.append(
                    dict(
                        url=url,
                        status=response.status_code,
                        attempt=attempt + 1,
                        robots=is_robots,
                        method=method,
                    )
                )
                if (
                    response.status_code in (408, 429, 500, 502, 503, 504)
                    and attempt < self.retries
                ):
                    delay = response.headers.get("Retry-After")
                    if delay and (not delay.isdigit() or int(delay) > MAX_WAIT_SECONDS):
                        raise RuntimeError(
                            "Server requests a longer retry delay; stop and retry later"
                        )
                    self.sleep(int(delay) if delay else 0.5 * 2**attempt)
                    continue
                return response
            except httpx.DecodingError as exc:
                # A response was received even when its compressed body is invalid.
                # Keep the attempt in the audit; this is not a transport retry.
                self.requests.append(
                    dict(url=url, status=status, attempt=attempt + 1,
                         robots=is_robots, method=method, error=str(exc))
                )
                raise
            except httpx.TransportError:
                self.requests.append(
                    dict(url=url, status=None, attempt=attempt + 1, robots=is_robots,
                         method=method)
                )
                if attempt == self.retries:
                    raise
                self.sleep(0.5 * 2**attempt)
        raise RuntimeError("Request exhausted")

    def _policy(self, url):
        parts = urlparse(url)
        base = parts.scheme + "://" + parts.netloc
        if base not in self.robots:
            robot_url = base + "/robots.txt"
            for _ in range(5):
                response = self._request(robot_url, is_robots=True)
                if not response.is_redirect:
                    break
                target = urljoin(robot_url, response.headers.get("Location", ""))
                target_parts = self._public_url(target, schemes=("http", "https"))
                # Same host AND the same implied port as the originating request.
                # The previous form allowed a different port whenever the host matched.
                if (
                    target_parts.hostname != parts.hostname
                    or (target_parts.port or 443) != (parts.port or 443)
                ):
                    raise RuntimeError(
                        "Robots redirect leaves configured host; review manually"
                    )
                robot_url = target
            else:
                raise RuntimeError("Too many robots redirects")
            if response.status_code in (401, 403) or response.status_code >= 500:
                raise RuntimeError(
                    "Robots policy unavailable/denied; no event request attempted"
                )
            parser = RobotFileParser()
            parser.set_url(base + "/robots.txt")
            if response.status_code == 200 and not response.text.lstrip().startswith(
                ("<", "<!")
            ):
                parser.parse(response.text.splitlines())
                label = "robots.txt"
            elif response.status_code in (200, 404, 410):
                parser.parse([])
                label = "no usable robots rules returned"
            else:
                raise RuntimeError(f"Unexpected robots status {response.status_code}")
            self.robots[base] = (parser, label)
        parser, label = self.robots[base]
        if not parser.can_fetch("MendunerEventResearch", url):
            raise RuntimeError("robots.txt disallows this URL")
        delay = parser.crawl_delay("MendunerEventResearch")
        if delay and delay > MAX_WAIT_SECONDS:
            raise RuntimeError("Robots requests a longer crawl delay; stop and retry later")
        self.host_intervals[parts.netloc] = max(self.interval, delay or 0)
        return label

    def _fetch(
        self,
        url,
        *,
        method="GET",
        json_body=None,
        request_headers=None,
        allowed_redirect=None,
        media=("html", "json", "text/plain"),
    ):
        """One bounded public request family: policy, redirects, size, media type, audit.

        ``get`` and ``request_json`` share this path so a public JSON API can never bypass
        the robots policy, the same-host/same-scheme redirect rules or the 2 MB cap that a
        public page already obeys.
        """
        parts = self._public_page_url(url)
        original_scheme = parts.scheme
        original_host = parts.hostname
        for _ in range(5):
            policy = self._policy(url)
            response = self._request(
                url, method=method, json_body=json_body, headers=request_headers
            )
            if response.is_redirect:
                target = urljoin(url, response.headers.get("Location", ""))
                if urlparse(target).hostname != original_host:
                    raise RuntimeError(
                        "Cross-host redirect rejected; review source configuration"
                    )
                if urlparse(target).scheme != original_scheme:
                    raise RuntimeError(
                        "Redirect changes transport scheme; review source configuration"
                    )
                if allowed_redirect is not None and not allowed_redirect(target):
                    raise RuntimeError("Redirect leaves approved public page routes; no target request made")
                if method != "GET":
                    # A redirected write-shaped request is replayed at a route nobody
                    # approved; only plain page GETs may follow a redirect.
                    raise RuntimeError(
                        "Redirected non-GET public request rejected; no target request made"
                    )
                target_parts = self._public_page_url(target)
                if (target_parts.port or 443) != (parts.port or 443):
                    raise RuntimeError("Redirect changes source port; review manually")
                url = target
                continue
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("Page exceeds the 2 MB prototype limit")
            served = response.headers.get("content-type", "")
            if not any(t in served for t in media):
                raise ValueError("Unsupported page content type")
            now = datetime.now(timezone.utc)
            metadata = {
                "status": response.status_code,
                "bytes": len(response.content),
                "robots": policy,
                "method": method,
            }
            self.pages.append(
                {"url": str(response.url), **metadata, "crawl_time": now.isoformat()}
            )
            return Page(str(response.url), response.text, now, served, metadata)
        raise RuntimeError("Too many redirects")

    def get(self, url, *, allowed_redirect=None, media=("html", "json", "text/plain")):
        """One bounded public page GET. ``media`` narrows or widens the accepted media types
        for a caller that deliberately reads a published asset (e.g. the JavaScript bundle a
        client-rendered source advertises its JSON API in) instead of an HTML page."""
        return self._fetch(url, allowed_redirect=allowed_redirect, media=media)

    def request_json(self, url, *, method="GET", json_body=None, headers=None,
                     allowed_redirect=None):
        """Bounded public JSON request through the same robots/redirect/audit boundary.

        Only GET and POST are available, a body requires POST, and the only headers a
        caller may attach are the host's own published channel header plus the content
        negotiation a browser would send (``PUBLIC_JSON_HEADERS``). Anything else — most
        importantly any credential — is refused before a request is built.
        """
        if method not in ("GET", "POST"):
            raise ValueError("Only public GET and POST are supported")
        if json_body is not None and method != "POST":
            raise ValueError("A JSON body requires POST")
        for name in (headers or {}):
            if str(name).lower() not in PUBLIC_JSON_HEADERS:
                raise ValueError(
                    "Unsupported public request header; no credential may be attached: "
                    + str(name)
                )
        return self._fetch(
            url,
            method=method,
            json_body=json_body,
            request_headers=headers,
            allowed_redirect=allowed_redirect,
            media=("json",),
        )
