"""Reconnaissance probe for candidate event-source URLs (read-only, reviewer tool).

This is NOT the crawler. It exists to answer one question per candidate URL before a source
is registered in ``crawler/source_registry.yaml``:

    can this host be read the way the crawler reads it, and does the served response
    actually contain event records without executing JavaScript?

Deliberately independent of ``crawler.http.PublicClient``: that client intentionally refuses
plain HTTP for every host that has not opted in, and refuses any URL whose transport the
registry has not approved. Reconnaissance has to be able to test a candidate *before* the
registry says anything about it, so this tool implements the same checks separately and
records them. The crawler keeps its stricter boundary.

What is checked per candidate (no page body is written to disk):

  * TLS certificate verification ON and HTTP/2 OFF-by-default httpx client; redirects are
    followed by hand so the final URL and every hop are recorded;
  * ``/robots.txt`` status and the resulting rule for the project's own user agent;
  * HTTP status, content type, byte count and document title of the final page;
  * whether the body looks server-rendered or is a client-rendered shell: script and
    ``<a href>`` counts, visible-text length, presence of an ISO date next to a
    Chinese date, and JSON-looking script payloads;
  * every ``<script src>``, so a JSON endpoint the host's own bundle advertises can be
    found later by hand.

Usage (from the repository root, with the backend venv):

    .\\backend\\.venv\\Scripts\\python.exe scripts\\recon_event_sources.py --input candidates.json
    .\\backend\\.venv\\Scripts\\python.exe scripts\\recon_event_sources.py --url https://example.com/
    .\\backend\\.venv\\Scripts\\python.exe scripts\\recon_event_sources.py --links https://example.com/list/ --links-host example.com

``--json-out`` writes the per-URL results as machine-readable JSON. Nothing is installed,
nothing is authenticated, no credential or proxy is used, and the request rate is bounded
per host.

A site-published sitemap or feed reader was tried here and removed: across 29 Suzhou hosts it
produced two usable indexes, one of which only confirmed that its rows link to WeChat rather than
to its own pages. The bottleneck this project actually faces is how many page shapes an extractor
rule set can cover, not how many URLs are known, and no discovery mechanism addresses that.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "MendunerEventResearch/1.5 (academic prototype; limited public event pages)"
MAX_BYTES = 2_000_000
ROBOTS_UA = "MendunerEventResearch"
SCRIPT_SRC = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)
SCRIPT_TAG = re.compile(r"<script", re.I)
TITLE = re.compile(r"<title[^>]*>(.{0,300}?)</title>", re.I | re.S)
ANCHOR = re.compile(r"<a\s[^>]*href=", re.I)
TAG = re.compile(r"<[^>]+>")
SCRIPT_BLOCK = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
WHITESPACE = re.compile(r"\s+")
# A published calendar may write its date as 2026-10-20, 2026/10/20, 2026.10.20 or
# 2026年10月20日; all four are explicit dates, so the probe reports all four.
ISO_DATE = re.compile(r"\b20\d{2}-\d{1,2}-\d{1,2}\b")
SLASH_DATE = re.compile(r"\b20\d{2}/\d{1,2}/\d{1,2}\b")
DOT_DATE = re.compile(r"\b20\d{2}\.\d{1,2}\.\d{1,2}\b")
CN_DATE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
# Event pages name their own listing sections; these are the section words a Suzhou
# activity source actually uses. They are only reported, never used to invent a record.
EVENT_WORDS = ("活动", "演出", "展览", "展会", "赛事", "讲座", "音乐会", "话剧", "剧目",
               "排期", "日历", "预告", "开票", "购票", "演出信息")
# Frame/shell markers: a served page that only bootstraps a client app carries no records.
SHELL_MARKERS = ("__NUXT__", "__NEXT_DATA__", "window.__INITIAL_STATE__", "id=\"app\"",
                 "id='app'", "webpackJsonp", "/_nuxt/", "/_next/", "vite/")
API_HINTS = ("/api/", "api.", "graphql", "/ajax/", "/json")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def visible_text(html):
    """Roughly what a reader sees: script/style removed, tags stripped, whitespace folded."""
    return WHITESPACE.sub(" ", TAG.sub(" ", SCRIPT_BLOCK.sub(" ", html or ""))).strip()


def looks_client_rendered(html, text, script_count):
    if len(text) < 800 and script_count:
        return True
    lowered = (html or "")[:400_000]
    return any(marker in lowered for marker in SHELL_MARKERS)


def robots_report(client, scheme, netloc, timeout, sleep):
    """Fetch ``/robots.txt`` once, then report the rule for this project's agent."""
    url = scheme + "://" + netloc + "/robots.txt"
    report = {"url": url, "status": None, "rule": None, "crawl_delay": None,
              "error": None, "looks_like_html": False, "redirects": []}
    try:
        response, hops = fetch(client, url, timeout=timeout, sleep=sleep, follow=5)
    except Exception as exc:  # noqa: BLE001 - reconnaissance must record every failure
        report["error"] = str(exc)
        return report
    report["redirects"] = hops
    report["status"] = response.status_code
    body = response.text or ""
    if response.status_code == 200 and body.lstrip().startswith(("<", "<!")):
        report["looks_like_html"] = True
        body = ""
    if response.status_code in (401, 403) or response.status_code >= 500:
        report["rule"] = "policy unavailable/denied (crawler will refuse this host)"
        return report
    parser = RobotFileParser()
    parser.set_url(url)
    parser.parse([] if response.status_code in (404, 410, 200) and not body
                 else body.splitlines())
    report["rule"] = ("allows this URL" if parser.can_fetch(ROBOTS_UA, url.replace("/robots.txt", "/"))
                      else "DISALLOWS the site root")
    report["crawl_delay"] = parser.crawl_delay(ROBOTS_UA)
    return report


def fetch(client, url, *, timeout, sleep, follow):
    """GET with TLS verification on, redirects followed by hand, every hop recorded."""
    hops = []
    current = url
    for _ in range(follow + 1):
        response = client.get(current, timeout=timeout)
        if response.is_redirect:
            target = urljoin(current, response.headers.get("Location", ""))
            hops.append({"from": current, "status": response.status_code, "to": target})
            if urlparse(target).hostname != urlparse(url).hostname:
                raise RuntimeError("cross-host redirect: " + target)
            current = target
            sleep(0.5)
            continue
        return response, hops
    raise RuntimeError("too many redirects")


def probe(client, entry, *, timeout, sleep):
    url = entry["url"]
    parts = urlparse(url)
    result = {
        "name": entry.get("name"),
        "category": entry.get("category"),
        "city": entry.get("city", "suzhou"),
        "url": url,
        "host": parts.hostname,
        "scheme": parts.scheme,
        "note": entry.get("note"),
        "checked_at": now_iso(),
        "dns_ok": True,
        "tls_verified": None,
        "http_status": None,
        "final_url": None,
        "redirects": [],
        "content_type": None,
        "bytes": None,
        "title": None,
        "scripts": 0,
        "script_srcs": [],
        "anchors": 0,
        "text_chars": 0,
        "dates": {"iso": 0, "slash": 0, "dot": 0, "cn": 0},
        "event_words": [],
        "shell_markers": [],
        "api_hints": [],
        "client_rendered": None,
        "verdict": None,
        "error": None,
    }
    try:
        response, hops = fetch(client, url, timeout=timeout, sleep=sleep, follow=4)
    except httpx.ConnectError as exc:
        result["dns_ok"] = "name resolution" not in str(exc).lower()
        result["error"] = "connect failed: " + str(exc)
        result["verdict"] = "UNREACHABLE"
        return result
    except httpx.ConnectTimeout as exc:
        result["error"] = "connect timeout: " + str(exc)
        result["verdict"] = "UNREACHABLE"
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = type(exc).__name__ + ": " + str(exc)
        result["verdict"] = "ERROR"
        return result
    result["tls_verified"] = True
    result["redirects"] = hops
    result["http_status"] = response.status_code
    result["final_url"] = str(response.url)
    result["content_type"] = response.headers.get("content-type")
    result["bytes"] = len(response.content)
    kind = (result["content_type"] or "").lower()
    if "html" not in kind and "json" not in kind and "text" not in kind:
        result["verdict"] = "NOT_A_PAGE"
        return result
    text = response.text
    title = TITLE.search(text)
    result["title"] = WHITESPACE.sub(" ", title.group(1)).strip() if title else None
    result["scripts"] = len(SCRIPT_TAG.findall(text))
    result["script_srcs"] = SCRIPT_SRC.findall(text)[:15]
    result["anchors"] = len(ANCHOR.findall(text))
    flat = visible_text(text)
    result["text_chars"] = len(flat)
    result["dates"] = {
        "iso": len(ISO_DATE.findall(flat)),
        "slash": len(SLASH_DATE.findall(flat)),
        "dot": len(DOT_DATE.findall(flat)),
        "cn": len(CN_DATE.findall(flat)),
    }
    result["event_words"] = [w for w in EVENT_WORDS if w in flat]
    lowered = text[:400_000]
    result["shell_markers"] = [m for m in SHELL_MARKERS if m in lowered]
    result["api_hints"] = [h for h in API_HINTS if h in lowered]
    result["client_rendered"] = looks_client_rendered(text, flat, result["scripts"])
    dated = sum(result["dates"].values())
    if response.status_code != 200:
        result["verdict"] = "HTTP_" + str(response.status_code)
    elif result["client_rendered"] and dated == 0:
        result["verdict"] = "JS_SHELL"
    elif dated and result["event_words"]:
        result["verdict"] = "PROMISING"
    elif dated:
        result["verdict"] = "DATED_NO_EVENT_WORDS"
    else:
        result["verdict"] = "NO_DATES"
    return result


def links_report(client, url, *, timeout, sleep, allowed_host):
    """Every same-host ``<a href>`` with its anchor text, in page order.

    A listing route is only useful if it leads to per-event detail pages, so the reviewer
    needs the real hrefs rather than a count. Off-host links are recorded as counts only.
    Parsed with an HTML parser rather than a regex: published markup wraps attributes across
    lines (``<a\\n  href="..."\\n  target="_blank"\\n  >text</a\\n>``), which a single-line
    regex silently misses and would report as "this listing has no links".
    """
    from bs4 import BeautifulSoup

    try:
        response, _ = fetch(client, url, timeout=timeout, sleep=sleep, follow=4)
    except Exception as exc:  # noqa: BLE001 - reconnaissance records every failure
        return {"url": url, "error": str(exc), "links": []}
    soup = BeautifulSoup(response.text, "html.parser")
    base_url = str(response.url)
    links = []
    off_host = 0
    unusable = 0
    for node in soup.select("a[href]"):
        href = node["href"]
        if not isinstance(href, str):
            # This CMS wraps attributes across lines; an HTML parser then hands back the
            # attribute as a list rather than a string. Neither the reviewer nor a source
            # adapter can use such an href, and it is not the listing's real link shape.
            unusable += 1
            continue
        target = urljoin(base_url, href)
        if urlparse(target).hostname != allowed_host:
            off_host += 1
            continue
        links.append({"href": href, "url": target,
                      "text": WHITESPACE.sub(" ", node.get_text(" ", strip=True))[:120]})
    return {"url": base_url, "status": response.status_code, "links": links,
            "off_host_links": off_host, "unusable_hrefs": unusable}


def render(results, show_text):
    lines = []
    for row in results:
        lines.append("=" * 78)
        lines.append(f"{row.get('name')}  [{row.get('category')}]")
        lines.append(f"  url           {row['url']}")
        lines.append(f"  verdict       {row['verdict']}"
                     + (f"   error={row['error']}" if row["error"] else ""))
        if row["http_status"]:
            lines.append(f"  http          {row['http_status']} {row['content_type']}"
                         f"  {row['bytes']} bytes  final={row['final_url']}")
            lines.append(f"  title         {row['title']}")
            lines.append(f"  dates         iso={row['dates']['iso']} slash={row['dates']['slash']}"
                         f" dot={row['dates']['dot']} cn={row['dates']['cn']}"
                         f"   text={row['text_chars']} chars  scripts={row['scripts']}"
                         f"  anchors={row['anchors']}")
            lines.append(f"  event words   {','.join(row['event_words']) or '-'}")
            lines.append(f"  shell markers {','.join(row['shell_markers']) or '-'}")
            lines.append(f"  api hints     {','.join(row['api_hints']) or '-'}")
            if row["redirects"]:
                for hop in row["redirects"]:
                    lines.append(f"  redirect      {hop['status']} {hop['from']} -> {hop['to']}")
            if show_text and row["script_srcs"]:
                lines.append(f"  script srcs   {row['script_srcs'][:6]}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, action="append",
                        help="JSON file: [{\"name\":..,\"url\":..,\"category\":..}, ...]")
    parser.add_argument("--url", action="append", default=[],
                        help="Ad-hoc candidate URL (repeatable)")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between requests to one host")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--show-scripts", action="store_true")
    parser.add_argument("--links", action="append", default=[],
                        help="Also dump same-host anchors of this URL (repeatable)")
    parser.add_argument("--links-host", help="Host that --links anchors must stay on")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    candidates = []
    for path in args.input or []:
        candidates.extend(json.loads(Path(path).read_text(encoding="utf-8")))
    candidates.extend({"name": u, "url": u, "category": "adhoc"} for u in args.url)
    if not candidates and not args.links:
        parser.error("No candidates: pass --input FILE, --url URL or --links URL")
    if args.limit:
        candidates = candidates[:args.limit]

    results = []
    last_request = {}
    client = httpx.Client(
        follow_redirects=False, verify=True, timeout=args.timeout, headers={"User-Agent": USER_AGENT}
    )

    def sleep(seconds):
        time.sleep(max(0.0, seconds))

    try:
        for entry in candidates:
            host = urlparse(entry["url"]).netloc
            wait = args.interval - (time.monotonic() - last_request.get(host, 0.0))
            if wait > 0:
                sleep(wait)
            robots = robots_report(client, urlparse(entry["url"]).scheme, host, args.timeout, sleep)
            last_request[host] = time.monotonic()
            wait = args.interval - (time.monotonic() - last_request.get(host, 0.0))
            if wait > 0:
                sleep(wait)
            row = probe(client, entry, timeout=args.timeout, sleep=sleep)
            last_request[host] = time.monotonic()
            row["robots"] = robots
            results.append(row)
            print(f"{row['verdict']:<20} {row['url']}"
                  + (f"   robots={robots['status']} {robots['rule']}" if robots["status"] else
                     f"   robots error={robots['error']}"), flush=True)

        print()
        print(render(results, args.show_scripts))
        for url in args.links:
            host = args.links_host or urlparse(url).hostname
            report = links_report(client, url, timeout=args.timeout, sleep=sleep, allowed_host=host)
            print("\n" + "-" * 78)
            print(f"ANCHORS on {report['url']} (same host only: {host})")
            for link in report["links"]:
                print(f"  {link['text'][:50]:<52} {link['url']}")
            print(f"  ({len(report['links'])} same-host anchors, "
                  f"{report.get('off_host_links', 0)} off-host, "
                  f"{report.get('unusable_hrefs', 0)} unusable)")
    finally:
        client.close()

    if args.json_out:
        args.json_out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON written to {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
