**Latest V1.6 priority refinement:** [Damai adapter, Huodongjia verification and Expo investigation](V1.6_PRIORITY_SOURCE_REVIEW.md). No additional live events were collected; current limitations remain explicit. The descriptions below record the original V1.6 baseline.

# V1.6 CityEvent source expansion

The existing public GET → raw content → deterministic extraction → field evidence → SQLite → FastAPI architecture is retained. Frontend and API routes are unchanged. This is a bounded source network, not a large-scale scraping system.

## Registry

`crawler/source_registry.yaml` registers the ten supplied Tier 1 websites, the two retained V1.5 sources (orchestra and Shanghai Concerts), and one manual-only WeChat record: 苏州发布. Every record contains source_name, category, url, trust_level, priority and crawl_status. Web records add a stable source_id, explicit HTTPS crawl_url, adapter, implementation mode, reason and last_checked.

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

On Windows use the existing `backend\.venv\Scripts\python.exe` interpreter from the repository root. `--max-items` remains 1–5; there is no pagination. `--tier1` attempts exactly the ten supplied sources, including public-page audits. Existing `--source government|venue|event_platform|expo` aliases remain available, alongside sipac, culture_tourism, olympic, arts, huodongjia, damai, subao and cnena. Default `all` includes all registered web handlers except optional expo; `--include-expo` includes it. WeChat has no selectable adapter. `--registry` can select a separate validated registry for tests or local status tracking.

Each collection run updates only attempted registry records, with the last observed status and reason. The optional JSON report is also retained in the existing crawler_jobs report column. No database migration or new API endpoint is introduced. Exit codes remain 0=Success and 2=Partial/Failed.

## Collection and extraction

- Suzhou Government retains its V1.5 bounded official-article adapter.
- SIPAC and the Culture and Tourism Bureau use public same-host article links. The bureau starts from its activity-information section. Only one named event with an explicit leading body date and explicit event year is accepted. Publication metadata, footer dates, historical biography dates and relative yesterday/recently are not converted to event dates. Month/day plus an explicitly named event year is Needs Review. Roundups lacking sufficient context are retained raw and rejected.
- Olympic Sports Centre uses the first page of the public GET feed `/Activity/gethd.html?limit=0`, which its own official activity page explicitly invokes. It follows at most max-items numeric detail IDs and extracts the labelled activity date and location. No pagination, ticket purchase, login, app, token or private endpoint is used. Multi-venue tournaments keep the full location text and venue=null; no combined fictional venue or coordinates are created.
- Subao uses bounded same-host culture article links and source-specific selectors. Only explicit dated single-event reports qualify. Stories with only relative dates or ambiguous multi-city dates are rejected; news publication dates do not substitute for event dates.
- Expo, Arts Centre, Huodongjia, Damai and China Exhibition Network are explicit public-page audit handlers, not validated event extractors. They retain permitted accessible pages as Context and record FAILED with the actual access/unsupported-extraction reason. Robots refusal stops before the event body. Audit code never follows protected/private/app endpoints, solves challenges or fabricates records.

The existing client enforces robots, TLS validation, host boundaries, request spacing, response size and bounded retry rules. HTTP URLs from the supplied list remain in registry metadata; event requests use explicit same-host HTTPS endpoints. Cross-host redirects are still rejected.

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
