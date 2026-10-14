"""Bounded public GETs: robots, same-host redirects, backoff, no login or tokens."""

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

    def _request(self, url, *, is_robots=False):
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
                with self.client.stream("GET", url) as streamed:
                    status = streamed.status_code
                    chunks = []
                    size = 0
                    for chunk in streamed.iter_bytes():
                        size += len(chunk)
                        if size > MAX_PAGE_BYTES:
                            self.requests.append(dict(
                                url=url, status=streamed.status_code,
                                attempt=attempt + 1, robots=is_robots,
                                error="Page exceeds the 2 MB prototype limit",
                            ))
                            raise ValueError("Page exceeds the 2 MB prototype limit")
                        chunks.append(chunk)
                    # iter_bytes already decompressed the body; do not decode it twice.
                    headers = dict(streamed.headers)
                    headers.pop("content-encoding", None)
                    headers.pop("content-length", None)
                    response = httpx.Response(
                        streamed.status_code, headers=headers,
                        content=b"".join(chunks), request=streamed.request,
                    )
                self.requests.append(
                    dict(
                        url=url,
                        status=response.status_code,
                        attempt=attempt + 1,
                        robots=is_robots,
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
                         robots=is_robots, error=str(exc))
                )
                raise
            except httpx.TransportError:
                self.requests.append(
                    dict(url=url, status=None, attempt=attempt + 1, robots=is_robots)
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

    def get(self, url, *, allowed_redirect=None):
        parts = self._public_page_url(url)
        original_scheme = parts.scheme
        original_host = parts.hostname
        for _ in range(5):
            policy = self._policy(url)
            response = self._request(url)
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
                target_parts = self._public_page_url(target)
                if (target_parts.port or 443) != (parts.port or 443):
                    raise RuntimeError("Redirect changes source port; review manually")
                url = target
                continue
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("Page exceeds the 2 MB prototype limit")
            media = response.headers.get("content-type", "")
            if not any(t in media for t in ("html", "json", "text/plain")):
                raise ValueError("Unsupported page content type")
            now = datetime.now(timezone.utc)
            metadata = {
                "status": response.status_code,
                "bytes": len(response.content),
                "robots": policy,
            }
            self.pages.append(
                {"url": str(response.url), **metadata, "crawl_time": now.isoformat()}
            )
            return Page(str(response.url), response.text, now, media, metadata)
        raise RuntimeError("Too many redirects")
