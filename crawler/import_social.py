"""Import manually collected social notes (MediaCrawler output) into the pipeline.

This is the entry point for the social-note clue pool. It performs no network access:
the notes were collected out-of-band under the operator's own account, and this command
only reads that export, pre-screens it, attaches the AI reading, and publishes every
candidate event into the existing review queue (never auto-verified).

Usage::

    python -m crawler.import_social --input data/xhs/xhs_note_2026.jsonl [--db scratch.sqlite3]

Without ``--no-ai`` the DeepSeek reader (``DEEPSEEK_API_KEY``, same configuration as
``crawler.ai``) produces the field readings. With ``--no-ai`` the export is stored
verbatim (prescreened candidates stay un-extracted and rejected with an explicit
reason) — useful to archive a crawl before configuring the key.
"""

import argparse
import json
import sys
from pathlib import Path

from backend.database import database_path
from crawler.ai.client import DeepSeek, load_api_key
from crawler.pipeline import run_pipeline
from crawler.sources.community.xiaohongshu import XiaohongshuImportAdapter


def main():
    parser = argparse.ArgumentParser(
        description="Import MediaCrawler social notes into the review queue (no auto-verification)"
    )
    parser.add_argument("--input", type=Path, required=True, help="MediaCrawler export (.jsonl or .csv)")
    parser.add_argument("--db", type=Path, default=database_path())
    parser.add_argument("--no-ai", action="store_true", help="Store and pre-screen only; skip LLM extraction")
    args = parser.parse_args()

    ai_client = None
    if not args.no_ai:
        key = load_api_key()
        if not key:
            print(
                "DEEPSEEK_API_KEY 未配置：无法抽取字段。"
                "先配置密钥重跑，或加 --no-ai 仅存原文与预筛结果。",
                file=sys.stderr,
            )
            return 2
        ai_client = DeepSeek(api_key=key)

    try:
        adapter = XiaohongshuImportAdapter(notes_path=args.input, ai_client=ai_client)
        report = run_pipeline(args.db, [adapter])
    finally:
        if ai_client is not None:
            ai_client.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    attempt = next((a for a in report["attempts"] if a["source"] == adapter.source_id), None)
    if attempt:
        print(
            f"\n预筛通过 {adapter.investigation.get('prescreenPassed', 0)} 条，"
            f"归档为线索 {adapter.investigation.get('prescreenContext', 0)} 条，"
            f"AI 读过 {adapter.investigation.get('aiReadings', 0)} 条；"
            f"发布 {attempt['accepted']} 条到待复核队列，拒绝 {attempt['rejected']} 条（原文均保留）。",
        )
    return 0 if report["status"] == "Success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
