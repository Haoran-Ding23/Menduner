**Latest V1.6 priority refinement:** [Damai adapter, Huodongjia verification and Expo investigation](V1.6_PRIORITY_SOURCE_REVIEW.md). No additional live events were collected; current limitations remain explicit. **Latest source expansion:** [V1.6.5 — expanding the crawlable activity sources (Suzhou)](V1.6.5_SOURCE_EXPANSION.md), which records the routes added on 2026-10-15, the twelve candidates refused with their exact failing check, and the two host-side blocks (苏州博物馆's malformed `Cache Control` header and 活动行's verification wall). The descriptions below record the original V1.6 baseline.

# V1.6 CityEvent source expansion

The existing public GET → raw content → deterministic extraction → field evidence → SQLite → FastAPI architecture is retained. Frontend and API routes are unchanged. This is a bounded source network, not a large-scale scraping system.

## Registry

`crawler/source_registry.yaml` registers the ten supplied Tier 1 websites, the two retained V1.5 sources (orchestra and Shanghai Concerts), and one manual-only WeChat record: 苏州发布. Every record contains source_name, category, url, trust_level, priority and crawl_status. Web records add a stable source_id, explicit HTTPS crawl_url, adapter, implementation mode, reason and last_checked.

Three optional fields describe a source whose publisher runs a multi-channel, paged site, added 2026-10-15 (see [V1.6.5](V1.6.5_SOURCE_EXPANSION.md)). `listing_urls` are additional approved routes on the same registered host; `listing_pages` is how many pages of each route are read, page 1 being the route itself; `route_page_pattern` is the page-URL template, `{c}` for the route's own path segments and `{n}` (or `{_n}` where the pager leaves page 1 unnumbered) for the page number. Every derived page must resolve to the registered host, transport and port, and the template must reproduce every registered route, so a template can never widen the crawl. The page count is declared rather than followed: the largest route observed advertises 534 pages. The detail budget stays a source-wide count — the primary activity feed keeps half of `--max-items` and the remaining routes share the rest — so adding a route cannot multiply requests.

The eight permitted categories are government, venue, event_platform, media, tourism, sports, education and social_media. China Exhibition Network uses event_platform with topic=exhibition; Olympic Sports Centre uses venue with topic=sports; the bureau uses government with topic=tourism. Unspecified sports/education/tourism sites are not invented merely to fill categories.

Trust levels describe source identity/role and collection priority, not fact verification or calibrated probabilities. The supplied Arts Centre domain is marked MANUAL_IDENTITY_CHECK until its identity/access can be validated. No source auto-promotes event fields to Verified.

## Run

Install the authoritative dependencies using the existing backend/.venv. The only added package is PyYAML==6.0.3, also recorded in environment.yml.

```bash
python -m pip install -r backend/requirements.txt
python -m crawler.run --tier1 --max-items 3 --db /absolute/path/to/isolated.sqlite3 --coverage-report docs/crawler-v16-coverage.json
python -m crawler.run --source olympic --max-items 3 --db /absolute/path/to/isolated.sqlite3
python -m crawler.inspect --db /absolute/path/to/isolated.sqlite3
python -m pytest crawler/tests backend/tests -q
```

On Windows use the existing `backend\.venv\Scripts\python.exe` interpreter from the repository root. `--max-items` remains 1–40 for the current sources (the V1.6 baseline ceiling was 1–5); pagination is bounded per source by the registry's `listing_pages`, never followed to the end. `--tier1` attempts exactly the ten supplied sources. Existing `--source government|venue|event_platform|expo` aliases remain available, alongside sipac, culture_tourism, olympic, arts, huodongjia, damai, subao and cnena. Default `all` includes every registered web handler. WeChat has no selectable adapter. `--registry` can select a separate validated registry for tests or local status tracking. *(Updated 2026-10-15: expo and arts are no longer audit-only and the `--include-expo` flag is gone — see [V1.6.4_JS_RENDERED_VENUES.md](V1.6.4_JS_RENDERED_VENUES.md).)*

Each collection run updates only attempted registry records, with the last observed status and reason. The optional JSON report is also retained in the existing crawler_jobs report column. No database migration or new API endpoint is introduced. Exit codes remain 0=Success and 2=Partial/Failed.

## Collection and extraction

- Suzhou Government retains its V1.5 bounded official-article adapter.
- SIPAC and the Culture and Tourism Bureau use public same-host article links. The bureau starts from its activity-information section and, since 2026-10-15, reads the first three pages of it: the section's own pager advertises 293 pages, so page 1 alone held roughly one item in ten. Its other dated channels (文旅要闻 / 工作动态 / 通知公告) are crawlable but their rows carry no event wording, so they are documented in [V1.6.5](V1.6.5_SOURCE_EXPANSION.md) and deliberately not registered. Only one named event with an explicit leading body date and explicit event year is accepted. Publication metadata, footer dates, historical biography dates and relative yesterday/recently are not converted to event dates. Month/day plus an explicitly named event year is Needs Review. Roundups lacking sufficient context are retained raw and rejected.
- Olympic Sports Centre uses the first page of the public GET feed `/Activity/gethd.html?limit=0`, which its own official activity page explicitly invokes. It follows at most max-items numeric detail IDs and extracts the labelled activity date and location. No pagination, ticket purchase, login, app, token or private endpoint is used. Multi-venue tournaments keep the full location text and venue=null; no combined fictional venue or coordinates are created.
- Subao uses bounded same-host culture article links and source-specific selectors. Only explicit dated single-event reports qualify. Stories with only relative dates or ambiguous multi-city dates are rejected; news publication dates do not substitute for event dates.
- Expo, Arts Centre, Huodongjia, Damai and China Exhibition Network began as explicit public-page audit handlers. Huodongjia, Damai, cnena and — since 2026-10-15 — Expo and Arts Centre are validated event extractors: the two venues serve a client-rendered shell whose own published JavaScript calls a public JSON calendar, which is what they now read (see [V1.6.4_JS_RENDERED_VENUES.md](V1.6.4_JS_RENDERED_VENUES.md)). An audit handler retains permitted accessible pages as Context and records FAILED with the actual access/unsupported-extraction reason. Robots refusal stops before the event body. No handler follows protected/private/app endpoints, solves challenges or fabricates records.

The existing client enforces robots, TLS validation, host boundaries, request spacing, response size and bounded retry rules. HTTP URLs from the supplied list remain in registry metadata; event requests use explicit same-host HTTPS endpoints. Cross-host redirects are still rejected.

The tourism portal (`tourism-visitsz-festival`) reads the 节庆日历 and, since 2026-10-15, also the portal's own 最新资讯 column and its 活动预告 detail route `festival-preview.aspx?id=NNNNN`, which serves the identical 来源/时间/地点 skeleton — that is where the portal publishes coming exhibitions whose 地点 is explicit (拙政园, 苏州博物馆, 吴文化博物馆, 天平山). The column's own `div.date` is a publication date and is never read as an event date; a portal that stops serving the column only sets the attempt's `news_column_absent` counter and cannot change the calendar's own success or failure.

## Evidence and failed sources

Accepted items continue through the existing normalized schema, stable source/item identity, conservative deduplication and per-source publication transactions. Raw URL, original content and crawl timestamp are stored in crawler_raw_items. Extracted values, snippets, extraction methods, confidence and raw_item_id remain in the existing observation/evidence structure. Missing organiser, address, district, coordinates and end date stay null unless explicitly stated.

A Tier 1 source that publishes no reliable event is FAILED even if its public page returned HTTP 200. Accessible Context and rejected raw material remain available through crawler.inspect. Failed refreshes retain previous event observations. Inaccessible sources have no fabricated raw body; their request/job audit and failure reason remain available.

WeChat's registry record contains name=苏州发布, platform=WeChat and status=Manual verification required. It is metadata only; there is no WeChat crawler or automatic publication path.

## Coverage meanings

- registeredSources: all inventory records, including manual-only.
- implementedSources: web handlers, explicitly split into eventExtractionAdapters and auditOnlyAdapters. An audit handler is not an operational event scraper.
- successfulPages: successfully fetched public HTML/JSON pages, including lists and Context; excludes robots requests. HTTP success does not imply a valid event.
- failedSources: attempted sources with FAILED in this job, including zero accepted records.
- eventsExtracted: accepted source-event observations successfully published in this job, distinct from total unique eventsStored.
- evidenceGenerated: current field evidence whose raw record belongs to this job, distinct from currentEventEvidenceRecords across the database. A failed refresh can generate zero new evidence while old evidence remains.

The checked-in registry/report are dated observations of one limited run. They do not promise complete Suzhou coverage, upcoming-event coverage or continuing site availability. Live results are in V1.6_SOURCE_COVERAGE_REPORT.md and crawler-v16-coverage.json. The two retained V1.5 sources were not fetched by the ten-source Tier 1 run.
