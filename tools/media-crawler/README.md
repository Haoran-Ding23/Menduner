# tools/media-crawler — Xiaohongshu collection toolchain

This folder holds the pieces of the social-note collection toolchain that belong to
**this repository**: the tuned MediaCrawler config, the Windows launchers, and the
bootstrap script. The upstream MediaCrawler clone itself (`tools/MediaCrawler/`) is
deliberately **not tracked**:

* MediaCrawler carries its own NON-COMMERCIAL LEARNING license — each machine fetches
  it from upstream rather than redistributing a vendored copy through this repo;
* the clone accumulates runtime state that must never reach git: `browser_data/`
  holds the secondary account's session cookies, `data/` holds crawled notes
  (third-party personal content), `.venv/`/`.pw-browsers/` are machine-local builds.

## Bootstrap a new machine

Prerequisites: git and Python 3.12. Double-click `setup_xhs.cmd`; it

1. clones upstream MediaCrawler into `tools/MediaCrawler/` (ghfast mirror, since
   github.com is unreachable without one on CN networks),
2. overlays `base_config.py` (Taicang-first keywords, CDP mode off, comment crawling
   off, per-keyword cap) and `run_xhs.cmd`,
3. builds `.venv` from `requirements.txt` (Tsinghua mirror) and downloads Chromium
   into `.pw-browsers/`,

all with caches and temp dirs pinned inside the clone folder — several machines deny
subprocess writes under the user profile (`AppData\Local`), so defaults never work.

Then double-click `tools/MediaCrawler/run_xhs.cmd`. The first run scans a QR code with
the secondary (小号) account; `SAVE_LOGIN_STATE` keeps the session in `browser_data/`,
so later runs go straight to searching. Collection always stays on a person's own
machine — the server never sees the account, only the exported `.jsonl` (see
[docs/SOCIAL_NOTE_IMPORT.md](../../docs/SOCIAL_NOTE_IMPORT.md)).

## Boundary

Small account, one round per day, notes only (comments are never fetched), exports go
to the review queue — the full licence-and-risk rationale lives in
[docs/SOCIAL_NOTE_IMPORT.md](../../docs/SOCIAL_NOTE_IMPORT.md). If this project ever
turns commercial, this toolchain stops and the data source is re-negotiated.
