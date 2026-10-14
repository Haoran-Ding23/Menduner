"""Duplicate venue identity resolution.

Two source pages can describe the same physical venue in slightly different words, which
produced two venue rows for one place: one carrying verified AMap coordinates and one
carrying the events. That split is what kept verified geography from ever reaching an
event, because the map resolves coordinates through the event's venue reference.

Collapsing them is a venue-IDENTITY decision, not a fact rewrite: the rows share a name, a
city and an address, and the mapping file records the evidence for each collapse. Nothing
is inferred at runtime — only an explicit, reviewed mapping applies, and an unknown id is
returned unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from crawler.venue_duplicates import default_alias_path

ALIAS_PATH = Path(__file__).with_name("venue_aliases.json")

_cache: dict[Path, dict[str, str]] = {}


def _load(path: Path | None = None) -> dict[str, str]:
    """Load an alias mapping, cached per resolved path.

    Caching per path (rather than one global) lets a test or a staging run point at its own
    mapping through MENDUNER_VENUE_ALIASES without poisoning the repository mapping.
    """
    resolved = Path(path) if path is not None else default_alias_path()
    if resolved in _cache:
        return _cache[resolved]
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _cache[resolved] = {}
        return _cache[resolved]
    _cache[resolved] = {
        row["alias_id"]: row["canonical_id"]
        for row in document.get("aliases", [])
        if row.get("alias_id") and row.get("canonical_id")
    }
    return _cache[resolved]


def canonical_venue_id(venue_id: str | None, path: Path | None = None) -> str | None:
    """The canonical id for a venue reference, or the input unchanged when unmapped."""
    if not venue_id:
        return venue_id
    return _load(path).get(venue_id, venue_id)


def canonical_venue_rows(path: Path | None = None) -> list[dict]:
    """The canonical venue records declared alongside the aliases.

    A crawl that repoints an event at a canonical venue must also make that venue part of
    the reference set, otherwise validation rejects the event for an unknown venue.
    """
    resolved = Path(path) if path is not None else default_alias_path()
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        row["canonical_row"]
        for row in document.get("aliases", [])
        if isinstance(row.get("canonical_row"), dict)
    ]


def alias_ids(path: Path | None = None) -> set[str]:
    return set(_load(path))


def reset_cache() -> None:
    """Test hook: drop the memoised mappings."""
    _cache.clear()
