"""Approve venueId only where the source itself named the venue and the match is unambiguous.

## The rule, and why it is narrow

An event's venue link is drawn on the map only when that relation is Verified. The Taicang
crawl produced 123 events whose venue came from a labelled line - 展览地点：太仓美术馆 - and
the pipeline recorded it as `derived_reference_id_from_explicit_venue_name` with
`Needs Review`. `bulk_review` deliberately refuses to approve venueId because nobody can
verify a reference id by reading a page. That reasoning is right in general and does not
apply here, because this is not a judgement about an opaque id: the source states the venue's
name, and the name resolves to a place whose coordinates a human already verified.

So four conditions must all hold, and any one of them failing leaves the event in the queue:

  1. the claim's method is the pipeline's derivation from an explicit venue name, so the name
     came from the source and not from a keyword guess;
  2. the stated name equals the matched venue's name exactly - not a substring, not a fuzzy
     match, so 太仓美术馆 cannot resolve to 太仓市美术馆;
  3. exactly one venue in that district carries that name, so the reference is unambiguous;
  4. that venue already has Verified GCJ-02 coordinates, so a human has already stood behind
     the place itself.

What this approves is the *link* between an event and a venue the reviewer has not seen; it
does not claim the event's dates, category or anything else, and every approval records the
Four conditions and the source snippet so the decision can be re-read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import connect
from crawler import review

DB = Path(os.environ.get(
    "MENDUNER_DB_PATH",
    "/srv/menduner/data/menduner.sqlite3" if Path("/srv/menduner/data/menduner.sqlite3").exists()
    else ROOT / "backend" / "data" / "menduner.sqlite3",
))
REVIEWER = "menduner-lead"
METHOD = "derived_reference_id_from_explicit_venue_name"

ap = argparse.ArgumentParser()
ap.add_argument("--db", type=Path, default=DB)
ap.add_argument("--district", default="taicang")
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()


def verified_coords(venue: dict) -> bool:
    co = venue.get("coordinates") or {}
    return (
        co.get("status") == "Verified"
        and co.get("system") == "GCJ-02"
        and isinstance(co.get("lng"), (int, float))
        and isinstance(co.get("lat"), (int, float))
        and bool(co.get("sourceUrl"))
    )


with connect(args.db) as con:
    venues = {}
    for row in con.execute("SELECT id, payload FROM venues"):
        venues[row["id"]] = json.loads(row["payload"])
    # name -> venues carrying it in this district, so condition 3 is a lookup rather than a scan
    by_name: dict[str, list[str]] = {}
    for vid, payload in venues.items():
        if payload.get("districtId") != args.district:
            continue
        name = (payload.get("name") or "").strip()
        if name:
            by_name.setdefault(name, []).append(vid)

    events = {}
    for row in con.execute(
        "SELECT id, venue, district FROM events WHERE district=? AND venue IS NOT NULL",
        (args.district,),
    ):
        events[row["id"]] = {"venue": row["venue"], "district": row["district"]}

    claims = []
    for row in con.execute(
        "SELECT event_id, payload FROM evidence WHERE field='venueId'"
    ):
        if row["event_id"] not in events:
            continue
        payload = json.loads(row["payload"])
        if payload.get("status") == "Verified":
            continue
        claims.append((row["event_id"], payload))

print(f"库: {args.db}")
print(f"地区: {args.district}   事件 {len(events)}   待查 venueId 声称 {len(claims)}")
print()

approve: list[dict] = []
refused: dict[str, int] = {}


def refuse(reason: str) -> None:
    refused[reason] = refused.get(reason, 0) + 1


for event_id, payload in claims:
    if payload.get("method") != METHOD:
        refuse("method 不是「来源显式场馆名派生」")
        continue
    stated = (payload.get("snippet") or "").strip()
    venue_id = payload.get("value")
    venue = venues.get(venue_id)
    if not stated or not venue:
        refuse("没有来源场馆名或场馆不存在")
        continue
    if (venue.get("name") or "").strip() != stated:
        refuse("来源场馆名与所匹配场馆的名字不完全一致")
        continue
    candidates = by_name.get(stated, [])
    if len(candidates) != 1:
        refuse(f"同区同名场馆有 {len(candidates)} 个，不唯一")
        continue
    if not verified_coords(venue):
        refuse("该场馆没有已核验坐标")
        continue
    approve.append({
        "event_id": event_id,
        "venue_id": venue_id,
        "venue_name": stated,
        "note": (
            f"窄规则通过：来源以「展览地点：」明确写出场馆名「{stated}」；"
            f"与场馆记录名称完全一致；该区同名场馆唯一；场馆坐标已核验"
        ),
    })

print(f"=== 满足全部条件: {len(approve)} 条 ===")
seen_names: dict[str, int] = {}
for item in approve:
    seen_names[item["venue_name"]] = seen_names.get(item["venue_name"], 0) + 1
for name, count in sorted(seen_names.items(), key=lambda kv: -kv[1]):
    print(f"  {name:16s} {count} 条")
print()
print("=== 拒绝原因 ===")
for reason, count in sorted(refused.items(), key=lambda kv: -kv[1]):
    print(f"  {count:4d}  {reason}")

if not args.apply:
    print()
    print("  DRY RUN：未写入。加 --apply 执行")
    sys.exit(0)

print()
print("=== 记录决策并重建事件 ===")
from backend.main import reproject_event

now = datetime.now(timezone.utc).isoformat()
ok = fail = 0
for item in approve:
    try:
        with connect(args.db) as con:
            review.record(
                con,
                event_id=item["event_id"],
                field="venueId",
                decision=review.APPROVE,
                reviewed_value=item["venue_id"],
                reviewer=REVIEWER,
                note=item["note"],
                decided_at=now,
            )
        reproject_event(args.db, item["event_id"])
        ok += 1
    except Exception as exc:
        fail += 1
        if fail <= 3:
            print(f"  ! {item['event_id']}  {type(exc).__name__}: {exc}")

print(f"  已批准 {ok}，失败 {fail}")

with connect(args.db) as con:
    n = con.execute(
        "SELECT COUNT(*) FROM evidence WHERE field='venueId' AND verification_status='Verified'"
    ).fetchone()[0]
    print(f"  全库 venueId 已核验: {n}")
    print(f"  integrity: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  foreign_key: {len(con.execute('PRAGMA foreign_key_check').fetchall())} 个问题")
