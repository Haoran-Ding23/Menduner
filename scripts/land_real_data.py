"""Run the real crawl into the production database and report a compact summary.

This is the P1 landing step: real public sources are collected into
backend/data/menduner.sqlite3, replacing the synthetic mock/demo rows through the
crawler pipeline's own archive-then-clean path.

Usage: python scripts/land_real_data.py [--db path] [--max-items N]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "backend" / "data" / "menduner.sqlite3"))
    ap.add_argument("--max-items", default="3")
    args = ap.parse_args()

    cmd = [
        str(PYTHON), "-X", "utf8", "-m", "crawler.run",
        "--max-items", str(args.max_items),
        "--db", args.db,
    ]
    print("RUN:", " ".join(cmd), "\n")
    proc = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8"
    )
    if proc.stderr.strip():
        print("STDERR:", proc.stderr.strip()[:2000], "\n")
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print("UNCLEAR OUTPUT (exit", proc.returncode, ")")
        print(proc.stdout[:3000])
        return 1

    print("exit code          :", proc.returncode)
    print("status             :", report.get("status"))
    print("mode               :", report.get("mode"))
    print("demoArchive        :", report.get("demoArchive"))
    for key in (
        "sourcesProcessed", "pagesCollected", "rawRecordsCollected",
        "eventsProcessed", "eventsCreated", "eventsUpdated", "duplicatesDetected",
        "itemsRejected", "eventsStored", "evidenceRecordsGenerated",
        "httpRequests", "robotsRequests", "retriedRequests",
    ):
        print(f"{key:19s}: {report.get(key)}")

    print("\n-- per source --")
    for att in report.get("attempts", []):
        print(f"  {att.get('source'):38s} {att.get('status'):8s} "
              f"pages={att.get('pagesCollected')} accepted={att.get('accepted')} "
              f"rejected={att.get('rejected')}")
        if att.get("error"):
            print(f"      error: {str(att['error'])[:220]}")
        for warn in att.get("warnings", [])[:3]:
            print(f"      warn : {str(warn)[:200]}")

    cov = report.get("sourceCoverage", {})
    if cov:
        print("\n-- coverage --")
        for key in (
            "registeredSources", "implementedSources", "attemptedSources",
            "eventProducingSources", "eventsExtracted", "eventsStored",
            "evidenceGenerated",
        ):
            print(f"  {key:24s}: {cov.get(key)}")

    print("\n-- page log --")
    for page in report.get("pageLog", []):
        print(f"  [{page.get('status')}] {page.get('bytes'):>7} B  {page.get('url')}")

    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
