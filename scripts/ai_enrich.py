"""Read stored evidence pages with DeepSeek and report extraction + cross-check results.

This never writes to a database. It is a measurement tool: run it, read the output, and decide
whether the model's readings are good enough to attach as suggestions.

    python scripts/ai_enrich.py --limit 5 --source government            # salvage attempt
    python scripts/ai_enrich.py --limit 20 --compare                     # cross-check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect  # noqa: E402
from crawler.ai.client import DeepSeek, DeepSeekError, load_api_key  # noqa: E402
from crawler.ai.enrich import compare, read_page  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")


def pick_pages(db: Path, *, source: str | None, limit: int, status: str | None) -> list[dict]:
    """Distinct pages to read, smallest first.

    The table is re-inserted on every crawl, so one URL appears many times; only the newest row
    per URL is used, otherwise the same page would be paid for repeatedly.
    """
    query = """
        SELECT r.source_id, r.original_url AS url, r.raw_content, r.validation_status
        FROM crawler_raw_items r
        JOIN (SELECT original_url, MAX(rowid) AS newest
              FROM crawler_raw_items GROUP BY original_url) n
          ON n.original_url = r.original_url AND n.newest = r.rowid
        WHERE r.raw_content IS NOT NULL
    """
    params: list = []
    if source:
        query += " AND r.source_id LIKE ?"
        params.append(f"{source}%")
    if status:
        query += " AND r.validation_status = ?"
        params.append(status)
    query += " ORDER BY LENGTH(r.raw_content) ASC LIMIT ?"
    params.append(limit)
    with connect(db) as con:
        return [dict(row) for row in con.execute(query, params)]


def stored_events(
    db: Path, limit: int, source: str | None, one_event_only: bool = False
) -> list[dict]:
    """One row per stored event, joined to the page it came from.

    The link is event -> crawler_observations.raw_item_id -> crawler_raw_items.raw_content.
    ``item_key`` cannot be used for this: it is a per-adapter identifier
    (``douban-event-35866026``, a schedule row number, …), not the URL.
    """
    query = """
        SELECT e.id AS event_id,
               e.payload AS event_payload,
               o.source_id,
               o.item_key,
               o.normalized_json,
               r.original_url AS url,
               r.raw_content,
               r.validation_status,
               (SELECT COUNT(DISTINCT o2.event_id)
                  FROM crawler_observations o2
                 WHERE o2.raw_item_id = o.raw_item_id) AS events_on_page
        FROM crawler_observations o
        JOIN crawler_raw_items r ON r.id = o.raw_item_id
        JOIN events e ON e.id = o.event_id
        WHERE r.raw_content IS NOT NULL AND LENGTH(r.raw_content) > 200
    """
    params: list = []
    if source:
        query += " AND o.source_id LIKE ?"
        params.append(f"{source}%")
    if one_event_only:
        # A cross-check compares one reading against one event, so a page carrying several
        # events cannot be checked this way and is excluded rather than producing fake
        # disagreements.
        query += """ AND (SELECT COUNT(DISTINCT o3.event_id) FROM crawler_observations o3
                          WHERE o3.raw_item_id = o.raw_item_id) = 1"""
    query += " ORDER BY LENGTH(r.raw_content) ASC LIMIT ?"
    params.append(limit)
    with connect(db) as con:
        rows = [dict(row) for row in con.execute(query, params)]

    for row in rows:
        document = {}
        try:
            document = json.loads(row.get("normalized_json") or "{}")
        except (ValueError, TypeError):
            document = {}
        try:
            payload = json.loads(row.get("event_payload") or "{}")
        except (ValueError, TypeError):
            payload = {}
        # What OUR extractor read from this page, for the cross-check.
        row["extracted"] = {
            "event_name": document.get("event_name") or payload.get("name"),
            "start_date": document.get("start_date") or payload.get("startDate"),
            "end_date": document.get("end_date") or payload.get("endDate"),
            "venue": document.get("venue") or payload.get("venueName"),
            "location": document.get("location") or payload.get("location"),
            "organizer": document.get("organizer") or payload.get("organizer"),
        }
    return rows


def describe(reading) -> None:
    if reading.error:
        print(f"    ERROR {reading.error}")
    elif not reading.is_event:
        print(f"    不是具体活动：{reading.note or '(无说明)'}")
    else:
        print(f"    is_event=True  certainty={reading.certainty}")
        for name, finding in reading.fields.items():
            if finding.present:
                print(f"      {name:12s} {str(finding.value)[:52]}")
                print(f"      {'':12s} 证据: {str(finding.evidence)[:70]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=5, help="how many pages to read")
    parser.add_argument("--source", help="restrict to a source id prefix")
    parser.add_argument(
        "--status",
        choices=("Rejected", "Context", "Published"),
        help="restrict to one validation status (ignored with --compare)",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", type=Path, help="write the full JSON results here")
    parser.add_argument(
        "--one-event-only",
        action="store_true",
        help="cross-check only pages that yielded exactly one event (required for a fair check)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="cross-check the model's reading against our extractor, per stored event",
    )
    args = parser.parse_args()

    key = load_api_key()
    if not key:
        print("No DEEPSEEK_API_KEY. Set the environment variable or add it to frontend/.env.local.")
        return 2
    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    if args.compare:
        pages = stored_events(args.db, args.limit, args.source, args.one_event_only)
    else:
        pages = pick_pages(args.db, source=args.source, limit=args.limit, status=args.status)
    if not pages:
        # Nothing to check is a normal state (a page may hold several events, so none may be
        # eligible), not a failure: a systemd unit must not report "Failed" on a healthy night.
        print("no eligible pages matched")
        return 0

    print(f"database : {args.db}")
    print(f"pages    : {len(pages)}")
    for page in pages:
        label = str(page.get("event_id") or page.get("validation_status") or "")[:16]
        print(
            f"   [{page['source_id'][:24]:24s}] {len(page['raw_content'] or ''):7d}B  "
            f"{label:16s} {page['url'][:54]}"
        )
    print()

    results = []
    agreed = disagreed = unreadable = skipped = 0
    with DeepSeek(api_key=key, model=args.model or "deepseek-flash") as client:
        for index, page in enumerate(pages, start=1):
            url = page["url"]
            print(f"--- [{index}/{len(pages)}] {url[:76]}")
            try:
                reading = read_page(client, url=url, html=page["raw_content"] or "")
            except DeepSeekError as exc:
                print(f"    ERROR {exc}")
                results.append({"url": url, "error": str(exc)})
                unreadable += 1
                continue

            describe(reading)
            entry = {"source_id": page["source_id"], "event_id": page.get("event_id")}
            entry.update(reading.as_dict())

            if args.compare and page.get("extracted"):
                # A cross-check is only meaningful when ONE event came from this page. A listing
                # endpoint or a schedule table carries many events, so comparing the model's
                # single reading against one arbitrary event produces a fake disagreement —
                # that is a fault in the comparison, not a finding about the data.
                if int(page.get("events_on_page") or 1) != 1:
                    print(
                        f"    ⊘ 跳过核对：该页面含 {page['events_on_page']} 个活动，"
                        "无法与单个活动逐字段比对"
                    )
                    entry["cross_check"] = {"skipped": "multi_event_page"}
                    skipped += 1
                    results.append(entry)
                    print()
                    continue
                delta = compare(reading, page["extracted"])
                entry["cross_check"] = delta
                entry["extracted"] = page["extracted"]
                if delta["disagree"]:
                    disagreed += 1
                    print("    ✗ 与提取器不一致：")
                    for name, detail in delta["disagree"].items():
                        print(f"        {name}: 提取器={str(detail['extractor'])[:32]}")
                        print(f"        {'':{len(name)}}  AI    ={str(detail['ai'])[:32]}")
                        print(f"        {'':{len(name)}}  证据  ={str(detail['ai_evidence'])[:50]}")
                else:
                    agreed += 1
                if delta["only_ai"]:
                    print(f"    + AI 读到、提取器没有: {list(delta['only_ai'])}")
                if delta["agree"]:
                    print(f"    ✓ 一致: {list(delta['agree'])}")
            results.append(entry)
            print()

    print("=" * 64)
    if args.compare:
        print(f"交叉核对: 一致 {agreed} / 不一致 {disagreed} / 读取失败 {unreadable} / 跳过(多活动页) {skipped}")
    print("用量:", json.dumps(client.usage.as_dict(), ensure_ascii=False))

    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
