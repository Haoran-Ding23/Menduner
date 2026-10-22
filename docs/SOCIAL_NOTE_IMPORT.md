# Social note import — the Xiaohongshu clue pool

**Date:** 2026-10-22. **Status:** import path implemented and tested (22 offline tests);
live collection requires the operator's own MediaCrawler session and a DeepSeek key.

Xiaohongshu publishes no content-search API (its open platform serves e-commerce
scenarios only), and this repository's own crawl boundary (robots-first, no login, no
CAPTCHA) cannot read it at all. The social layer is therefore a **manually authorised
import**: notes are collected out-of-band by `tools/MediaCrawler` under the operator's
own logged-in account, and `crawler/import_social.py` only reads that export — no HTTP
request, no login, no signature is ever produced by this repository.

## Licence boundary (read before collecting)

MediaCrawler is licensed **NON-COMMERCIAL LEARNING**: student/research use, small
volume, the operator's own account. The boundaries that keep this honest:

* a secondary (小号) account, never the operator's primary identity;
* at most one search round per day, tens of notes per round — a clue pool, not a mirror;
* notes only, **never comments** (personal-information exposure with no event value);
* if this project ever turns commercial, stop and re-source the data (千瓜/新红 or a
  data partnership) — scraping-then-selling platform data is the exact fact pattern of
  the 2024–2025 反不正当竞争 and 非法获取计算机信息系统数据 judgments.

## Collection (out of band, in `tools/MediaCrawler`)

Setup is already done: an independent Python 3.12 venv (never `backend\.venv`), the
Playwright Chromium installed into `tools/MediaCrawler/.pw-browsers`, Suzhou keywords
and the `jsonl` save option set in `config/base_config.py`, and `ENABLE_CDP_MODE = False`
so the crawler launches its own clean browser session instead of reaching for a
debug-port Chrome that is not running (the "端口不可用" error) or the operator's daily
profile where the primary account may be logged in.

```powershell
# Per round (double-clickable; pins the workspace-local browser/temp paths):
tools\MediaCrawler\run_xhs.cmd
```

Scan the QR code with the **secondary (小号) account**. `SAVE_LOGIN_STATE = True` keeps
that session in `browser_data/`, so the scan is a one-time step. The output lands in
`tools/MediaCrawler/data/xhs/` as `xhs_note_*.jsonl`, one JSON object per note
(`note_id`, `title`, `desc`, `time` (publish ms), `note_url`, `source_keyword`, masked
`nickname`).

## Import (this repository)

```powershell
.\backend\.venv\Scripts\python.exe -m crawler.import_social `
    --input tools\MediaCrawler\data\xhs\xhs_note_2026-10-22.jsonl `
    --db scratch.sqlite3
```

Without `DEEPSEEK_API_KEY` the command refuses and suggests `--no-ai` (store and
pre-screen only). With the key, each pre-screened note is read by the same
`crawler.ai.enrich` reader used on evidence pages, and every published field carries
`method="ai_note_extraction"`, `status="Needs Review"`, and the verbatim quote that
justifies it.

## Fail-closed rules (pinned by `crawler/tests/test_xiaohongshu_import.py`)

* **The publish timestamp is provenance, never an event date** — the same rule that
  keeps bureau news columns and library archives out of the event tables.
* The pre-screen (`prescreen`) demands an explicit Suzhou place signal plus a
  year-bearing date before any AI token is spent; a note failing it is retained as
  Context with the reason recorded.
* A field exists only when the reading carries an explicit value **and** its verbatim
  quote; `start_date` must be year-bearing — month/day is rejected, never repaired.
* The place must name Suzhou; anything else fails closed.
* The source registers no trust level, so `verification.decide` treats it as
  non-authoritative: every field lands in the existing human review queue
  (`/api/review/*`), and a reviewer's decision is bound to the value they saw —
  re-importing the same note keeps one event and never silently overwrites a review.
