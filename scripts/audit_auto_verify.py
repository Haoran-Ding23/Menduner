"""Audit the provenance of every stored field evidence row.

Answers: for each (source, extractor method), how many rows exist, and how many would
satisfy a proposed "authoritative source + deterministic extraction" auto-verification
rule. Read-only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/data/menduner.sqlite3")

# Source trust by source_id prefix. Official government / venue sources are the
# authoritative tier; commercial aggregators and community platforms are not.
AUTHORITATIVE_PREFIX = ("government-", "venue-", "tourism-")

# Deterministic extraction: the value is read from an explicit machine field or an
# explicit labelled field, not inferred by a heuristic rule.
DETERMINISTIC_METHOD = re.compile(
    r"explicit|itemprop|JSON-LD|SSR\.|_source_|attributeMapSingle|api|"
    r"labelled_|named_place|detail_page_heading",
    re.I,
)
# Method markers that mean "a rule guessed this", never auto-verifiable.
HEURISTIC_METHOD = re.compile(
    r"rule|heuristic|keyword|default|fallback|category|guess|inferred",
    re.I,
)

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

sources = {r["id"]: r for r in con.execute("SELECT id FROM sources")}

rows = list(con.execute(
    """SELECT e.id, e.event_id, e.field_name, e.value, e.source, e.source_url,
              e.confidence, e.verification_status, f.payload, r.source_id
       FROM crawler_evidence e
       LEFT JOIN evidence f ON f.id = e.id
       LEFT JOIN crawler_raw_items r ON r.id = e.raw_item_id"""
))
print(f"crawler_evidence rows: {len(rows)}\n")

per_method = Counter()
eligible = Counter()
blocked_reasons = Counter()

for r in rows:
    method = ""
    try:
        meta = json.loads(r["payload"] or "{}")
        method = str(meta.get("method") or "")
    except Exception:
        pass
    extractor = "crawler"
    key = f"{extractor} | {method or '(no method recorded)'}"
    per_method[key] += 1

    authoritative = str(r["source"] or "").startswith(AUTHORITATIVE_PREFIX)
    if not authoritative:
        blocked_reasons["source not authoritative"] += 1
        continue
    if not r["source_url"]:
        blocked_reasons["no source URL"] += 1
        continue
    if r["value"] in (None, "", "null"):
        blocked_reasons["empty value"] += 1
        continue
    if HEURISTIC_METHOD.search(method):
        blocked_reasons[f"heuristic method: {method[:40]}"] += 1
        continue
    if method and not DETERMINISTIC_METHOD.search(method):
        blocked_reasons[f"unclassified method: {method[:40]}"] += 1
        continue
    eligible[r["field_name"]] += 1

print("== rows by extraction method (top 30) ==")
for k, n in per_method.most_common(30):
    print(f"  {n:5d}  {k[:110]}")

print("\n== rows that WOULD auto-verify, by field ==")
for k, n in eligible.most_common():
    print(f"  {n:5d}  {k}")
print(f"  TOTAL eligible: {sum(eligible.values())} of {len(rows)}")

print("\n== why rows were NOT eligible (top 15) ==")
for k, n in blocked_reasons.most_common(15):
    print(f"  {n:5d}  {k}")

print("\n== sources present in crawler_evidence ==")
for s, n in Counter(r["source"] for r in rows).most_common():
    tier = "AUTHORITATIVE" if str(s).startswith(AUTHORITATIVE_PREFIX) else "aggregator"
    print(f"  {n:5d}  {s:34s} {tier}")
con.close()
