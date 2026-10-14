# Menduner 当前项目快照

打包日期：2026-10-13
分支：feature/crawler-v1.5
最近提交：a94e445

此包含当前磁盘上的全部 Git 管理源码及以下尚未提交的修改：
M crawler/http.py
 M crawler/pipeline/__init__.py
 M crawler/run.py

V1.5 真实采集器已有前次运行报告：docs/CRAWLER_V1.5_REPORT.md。最新三个工作区修改涉及 HTTP 请求边界、采集审计统计及证据更新，本次未在完整依赖环境中复测。

运行与安装：README_SETUP.md、README_LOCAL_WINDOWS.md、crawler/README.md。

本包不含 .git、密钥、本地 SQLite 数据库、虚拟环境、node_modules 和前端构建产物。安装后按 README_SETUP.md 初始化，运行真实采集以生成数据库。

## V1.5 stabilization review — 2026-10-13

Reviewed pending crawler changes; corrected HTTP decoding-error audit, repeated-item extraction identity, reused-adapter counters/diagnostics, and mixed canonical date validation. Python 3.14.8: 40 crawler + 8 backend tests pass; 46 live HTTP API checks pass. Core-source repeat: Success, 12 retained real-source events, 120 field evidence records, no MOCK/DEMO. Optional expo audit remains Partial. Frontend unchanged. See docs/V1.5_STABILIZATION_REVIEW.md. This package still has no .git or local database; no commit was made.

## V1.6 CityEvent source expansion — 2026-10-13

Source registry: ten supplied Tier 1 websites, two retained V1.5 sources, manual-only 苏州发布 (WeChat). Live Tier 1 result: Partial; 20 fetched pages, 6 accepted/stored events, 60 field evidence records, 7 sources FAILED with reasons. Python 3.14.8: 63 crawler + 8 backend tests and 34 HTTP API checks pass. Frontend, API routes, database schema and evidence architecture unchanged. See docs/CRAWLER_V1.6.md and docs/V1.6_SOURCE_COVERAGE_REPORT.md. No Git commit or push; archive still excludes .git and local databases.

## V1.6 priority refinement — 2026-10-13

Dedicated public Damai Event JSON-LD adapter and opt-in city evidence added; Huodongjia/Expo verification now uses explicit fail-closed permission checks. Focused live result: all three FAILED, 2 permitted Expo HTML pages, 6 Context/policy raw records, 0 additional events/evidence. Python 3.14.8: 89 crawler + 8 backend tests and 24 HTTP checks pass; synthetic test records are separate from live totals. Frontend/backend implementation, SQLite DDL, dependencies and other sources unchanged. See docs/V1.6_PRIORITY_SOURCE_REVIEW.md.
