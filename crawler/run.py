"""Production entry point: bounded real public sources only."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from backend.database import database_path
from crawler.http import PublicClient
from crawler.sources import SOURCES
from crawler.pipeline import run_pipeline
from crawler.registry import REGISTRY_PATH, load_registry, tier1_keys
from crawler.coverage import attach_coverage

# Detail-page budget per source. This bounds requests, not pages: the registry's sources
# range from 1 public page to a 150-row exhibition schedule, so a single fixed depth either
# starves the rich sources or over-fetches the thin ones. Pagination stays bounded inside
# each adapter. The cap is explicit and the limit is checked, not silent.
#
# Raised from 40 to 240 on 2026-10-15. The old ceiling was binding on the largest official
# source rather than protecting anything: the Suzhou festival calendar alone held 197
# not-yet-ended records within pages 1-35, and a run could publish only 40 of them. Each
# adapter still chooses its own depth and stop condition, so thin sources are unaffected.
MAX_ITEMS_CAP = 240


def main():
    parser = argparse.ArgumentParser(
        description="Menduner V1.6 bounded public event collection (no demo fallback)"
    )
    parser.add_argument("--source", choices=["all", *SOURCES], default="all")
    parser.add_argument("--db", type=Path, default=database_path())
    parser.add_argument(
        "--max-items",
        type=int,
        default=12,
        help=f"1-{MAX_ITEMS_CAP} detail records per source; each adapter bounds its own pagination",
    )
    # Selecting the rich official calendars needs more than the small exploratory default.
    # 197 not-yet-ended records sat within pages 1-35 of the Suzhou festival calendar alone,
    # so --deep raises the per-source budget in one flag instead of a long --max-items value.
    parser.add_argument(
        "--deep",
        action="store_true",
        help=f"collect up to {MAX_ITEMS_CAP} detail records per source instead of the default",
    )
    parser.add_argument(
        "--tier1", action="store_true", help="Attempt the ten CityEvent Tier 1 sources"
    )
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH, help="Source registry and last-observed status")
    parser.add_argument("--coverage-report", type=Path, help="Write source coverage JSON")
    args = parser.parse_args()
    if not 1 <= args.max_items <= MAX_ITEMS_CAP:
        parser.error(f"--max-items must be 1-{MAX_ITEMS_CAP}")
    per_source_items = MAX_ITEMS_CAP if args.deep else args.max_items
    client = None
    try:
        definitions = load_registry(args.registry)
        # HTTPS is required for every host unless its registry row explicitly opted into
        # plain HTTP (allow_plain_http), which also records the integrity limitation.
        plain_http_hosts = {
            urlparse(d.crawl_url).hostname
            for d in definitions
            if d.allow_plain_http and d.crawl_url
        }
        client = PublicClient(plain_http_hosts=plain_http_hosts)
        by_key = {d.adapter: d for d in definitions if d.adapter}
        if any(key not in SOURCES for key in by_key):
            parser.error("Registry names an unsupported adapter")
        if args.source != "all" and args.source not in by_key:
            parser.error("Selected source is not registered")
        if args.tier1 and args.source != "all":
            parser.error("--tier1 selects the ten sources; use --source separately")
        keys = (tier1_keys(args.registry) if args.tier1 else
                [d.adapter for d in sorted(definitions, key=lambda d: d.priority)
                 if d.adapter and (args.source == d.adapter or args.source == "all")])
        adapters = []
        for key in keys:
            definition = by_key[key]
            adapter = SOURCES[key](client=client, max_items=per_source_items)
            if adapter.source_id != definition.source_id:
                parser.error("Registry source ID does not match adapter ownership")
            adapter.require_events = (
                definition.tier == 1
                if definition.require_events is None
                else definition.require_events
            )
            # The auto-verification rule gates on registered source authority, so the
            # trust level must travel with the adapter rather than be re-inferred later.
            adapter.trust_level = definition.trust_level
            if hasattr(adapter, "detail_urls"):
                adapter.detail_urls = definition.detail_urls
            if hasattr(adapter, "listing_url"):
                adapter.listing_url = definition.crawl_url
            if hasattr(adapter, "crawl_url"):
                adapter.crawl_url = definition.crawl_url
            adapters.append(adapter)
        report = run_pipeline(args.db, adapters, request_client=client)
        if "jobId" in report and "attempts" in report:
            attach_coverage(args.db, report, registry_path=args.registry, output=args.coverage_report)
        print(json.dumps(report, ensure_ascii=False))
        # 0 = every source succeeded, 2 = the run completed but some sources did not.
        #
        # The distinction is kept because it is useful to a human and to a script. It is NOT
        # left to mean "the service failed": some sources are permanently uncollectable and are
        # documented as such (damai disallows its search page in robots.txt; SIPAC and Subao
        # publish no extractable event date). The systemd unit therefore declares
        # SuccessExitStatus=2, and per-source outcomes live in crawl_runs/crawl_alerts where a
        # real regression is supposed to be noticed.
        return 0 if report["status"] == "Success" else 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
