"""Venue duplicate detection and explicit merging.

Detection only ever PROPOSES. Nothing merges without a human decision recorded against it,
because a wrong merge silently moves events to the wrong place and is invisible afterwards.
Each candidate therefore carries the signal that produced it, so a reviewer can judge rather
than trust a score:

  exact        the two names are identical after normalisation and region stripping
  containment  one normalised name contains the other
  proximity    both carry coordinates less than MERGE_DISTANCE_KM apart

Signals are advisory. Two venues in one building are not one venue, so proximity alone is
deliberately weaker than a name signal, and a venue whose recorded "name" is really a full
address line is reported as such instead of being matched on its address text.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ALIAS_PATH = Path(__file__).with_name("venue_aliases.json")


def default_alias_path() -> Path:
    """The alias file in use. ``MENDUNER_VENUE_ALIASES`` overrides it, so a test or a
    staging database can keep its own mappings instead of editing the tracked file."""
    override = os.environ.get("MENDUNER_VENUE_ALIASES")
    return Path(override) if override else REPO_ALIAS_PATH


ALIAS_PATH = REPO_ALIAS_PATH

MERGE_DISTANCE_KM = 0.3

# Region prefixes and address tails are not part of a venue's identity.
REGION_TOKEN = re.compile(r"^[\u4e00-\u9fff]{2,4}(?:市|区|县|镇)$")
ADDRESS_TAIL = re.compile(
    r"[\u4e00-\u9fff]{0,8}(?:路|街|巷|大道|弄|号|大厦|广场|园区|村|镇)?[\d]+号?.*$"
)
STRIP_CHARS = re.compile(r"[\s·・/／\-—()（）「」【】]+")
HAS_DIGIT = re.compile(r"\d")

# A bare region name is not a venue, and it is not an alias of one either.
#
# The official-article extractor reads the leading 单位： prefix of a title as the venue. A
# city-wide event is titled 太仓市:捡个秋天·太仓漫游季, so 太仓市 became a venue row. That row
# then "contained" 太仓市博物馆 and 太仓市图书馆 and was proposed as an alias of both, which
# would have merged three unrelated places into one. The row is a misclassification rather
# than a duplicate, so containment against it must never merge.
REGION_NAME = re.compile(r"^[\u4e00-\u9fff]{2,4}(?:省|市|区|县|镇|乡|街道)$")

# A generic room/location word carries no venue identity on its own.
#
# A row named 展厅 ("exhibition hall") was proposed as an alias of 苏州市文联文艺家展厅,
# 定慧寺巷口凤凰街旅游咨询中心3楼展厅 and 常熟市文化艺术中心展厅 at once. Those are three
# different places, and the real venue was named only in the address field
# (假日街7号嘉德·宥爱艺术中心2号). One short generic word cannot identify a venue, so it is
# never merged as an alias; such a row needs a human to say what it is.
GENERIC_VENUE_WORD = re.compile(
    r"^(?:展厅|展馆|剧场|剧场|剧院|音乐厅|艺术中心|文化中心|活动中心|体育中心|体育馆|"
    r"图书馆|博物馆|美术馆|景区|古镇|广场|中心|会场|会场|现场|场馆|礼堂|多功能厅)$"
)


def normalize(name: str | None) -> str:
    """Identity form of a venue name: no spacing, punctuation, region or address tail."""
    text = STRIP_CHARS.sub("", name or "")
    tokens = [t for t in re.split(r"[\s]+", name or "") if t.strip()]
    if len(tokens) > 1:
        tokens = [t for t in tokens if not REGION_TOKEN.match(t)]
        text = STRIP_CHARS.sub("", "".join(tokens))
    return text


def looks_like_address(name: str | None) -> bool:
    """True when a venue row's name is really a whole address line.

    The official-article extractor stores the place phrase verbatim, so a few rows are named
    ``苏州 姑苏区 苏州开明大戏院 观前街北局11号``. Such a row is not a second venue; it is the
    same venue recorded badly, and it must be resolved by a human rather than matched on the
    address substring.
    """
    if not name:
        return False
    if HAS_DIGIT.search(name):
        return True
    return len([t for t in name.split() if t.strip()]) >= 3


def is_region_name(name: str | None) -> bool:
    """True when a row's name is only an administrative region, i.e. not a venue at all."""
    return bool(REGION_NAME.fullmatch((name or "").strip()))


def is_generic_venue_word(name: str | None) -> bool:
    """True when a row's name is a generic room word that cannot identify a venue alone."""
    return bool(GENERIC_VENUE_WORD.fullmatch((name or "").strip()))


# A exact match is stronger evidence than a substring, and among substring matches the one
# whose alias carries the most events is the one worth a reviewer's time first.
_SIGNAL_RANK = {"exact": 0, "containment": 1, "proximity": 2}


def _candidate_rank(candidate: "Candidate") -> tuple:
    return (_SIGNAL_RANK.get(candidate.signal, 9), -candidate.alias_events, candidate.alias_name)


def distance_km(a: dict, b: dict) -> float | None:
    if not a or not b:
        return None
    try:
        lat1, lng1, lat2, lng2 = a["lat"], a["lng"], b["lat"], b["lng"]
    except (KeyError, TypeError):
        return None
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lng2 - lng1)
    h = (
        math.sin(dl / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dn / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, h)))


@dataclass
class Candidate:
    alias_id: str
    alias_name: str
    alias_events: int
    canonical_id: str
    canonical_name: str
    canonical_events: int
    canonical_coordinates: bool
    signal: str
    distance_km: float | None
    alias_looks_like_address: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "alias_id": self.alias_id,
            "alias_name": self.alias_name,
            "alias_events": self.alias_events,
            "canonical_id": self.canonical_id,
            "canonical_name": self.canonical_name,
            "canonical_events": self.canonical_events,
            "canonical_has_coordinates": self.canonical_coordinates,
            "signal": self.signal,
            "distance_km": None if self.distance_km is None else round(self.distance_km, 3),
            "alias_looks_like_address": self.alias_looks_like_address,
            "notes": self.notes,
        }


def detect(venues: list[dict], usage: dict[str, int]) -> list[Candidate]:
    """Propose merge candidates. ``usage`` maps venue id to how many events reference it.

    Three guards keep the proposal list worth reviewing, because each one was a real false
    positive on the live data:

    * A row whose name is only a region (太仓市) is a misclassification, not a duplicate, so
      it is never offered as an alias of the venues whose names happen to start with it.
    * A row whose name is a generic word (展厅) is never offered as an alias at all, because
      the same word matched three unrelated places.
    * Each alias is offered against at most one canonical. Containment is not symmetric and
      a single short row could otherwise be proposed against several longer ones, which made
      the list look like it had more agreement than it did.
    """
    candidates: list[Candidate] = []
    seen: set[frozenset[str]] = set()
    for i, a in enumerate(venues):
        for b in venues[i + 1 :]:
            pair = frozenset({a["id"], b["id"]})
            if pair in seen:
                continue
            # A bare region name is not a venue; never merge through it in either direction.
            if is_region_name(a["name"]) or is_region_name(b["name"]):
                seen.add(pair)
                continue
            na, nb = normalize(a["name"]), normalize(b["name"])
            a_addr, b_addr = looks_like_address(a["name"]), looks_like_address(b["name"])
            signal = None
            notes: list[str] = []
            if na and na == nb:
                signal = "exact"
            elif na and nb and (na in nb or nb in na):
                # Only the shorter name can be the alias; a generic word identifies nothing.
                shorter = a if len(na) <= len(nb) else b
                if is_generic_venue_word(shorter["name"]):
                    seen.add(pair)
                    continue
                signal = "containment"
                if a_addr or b_addr:
                    notes.append(
                        "one of these rows records a whole address line as its venue name"
                    )
            distance = distance_km(a.get("coordinates"), b.get("coordinates"))
            if signal is None and distance is not None and distance < MERGE_DISTANCE_KM:
                signal = "proximity"
                notes.append("same coordinates, but the names do not match")
            if signal is None:
                continue
            seen.add(pair)
            # Which row survives is an identity decision, and the one that carries geometry
            # or more events is the better survivor. Coordinates outrank event count: a row
            # with one event and a verified AMap record is harder to reconstruct than a row
            # with six events and no geometry, and only one of the two is recoverable.
            a_has, b_has = bool(a.get("coordinates")), bool(b.get("coordinates"))
            if a_has != b_has:
                canonical, alias = (a, b) if a_has else (b, a)
            elif usage.get(a["id"], 0) >= usage.get(b["id"], 0):
                canonical, alias = a, b
            else:
                canonical, alias = b, a
            candidates.append(
                Candidate(
                    alias_id=alias["id"],
                    alias_name=alias["name"],
                    alias_events=usage.get(alias["id"], 0),
                    canonical_id=canonical["id"],
                    canonical_name=canonical["name"],
                    canonical_events=usage.get(canonical["id"], 0),
                    canonical_coordinates=bool(canonical.get("coordinates")),
                    signal=signal,
                    distance_km=distance,
                    alias_looks_like_address=looks_like_address(alias["name"]),
                    notes=notes,
                )
            )

    # One alias, one proposal. Keeping the best-scoring candidate for each alias is what
    # makes the list a set of decisions rather than a set of strings that co-occur.
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        current = best.get(candidate.alias_id)
        if current is None or _candidate_rank(candidate) < _candidate_rank(current):
            best[candidate.alias_id] = candidate
    candidates = list(best.values())
    order = {"exact": 0, "containment": 1, "proximity": 2}
    candidates.sort(key=lambda c: (order.get(c.signal, 9), -c.alias_events, c.alias_name))
    return candidates


def load_aliases(path: Path | None = None) -> dict:
    path = path or default_alias_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "aliases": []}


def write_alias(*, alias_id: str, canonical_id: str, name: str, reason: str,
                evidence_url: str | None, path: Path | None = None,
                canonical_row: dict | None = None) -> None:
    """Record one alias -> canonical mapping.

    ``canonical_row`` is the canonical venue as it should appear in the reference set. It is
    not optional in practice: the publish pipeline refuses to repoint an event at a canonical
    venue it cannot find in ``canonical_venue_rows()``, because doing so would leave an event
    referencing a venue id that did not exist. The first aliases in this repository were
    written by hand and carried the row; aliases written by ``merge()`` did not, so a merge
    recorded through the API produced an alias that the next crawl would reject with
    "Venue alias points at a canonical venue that is not declared".

    Passing the survivor's own payload here keeps every alias in one shape, and the row is
    copied verbatim from the database rather than reconstructed from the name.
    """
    path = path or default_alias_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    document = load_aliases(path)
    rows = [
        row for row in document.get("aliases", []) if row.get("alias_id") != alias_id
    ]
    row = {
        "alias_id": alias_id,
        "canonical_id": canonical_id,
        "name": name,
        "reason": reason,
    }
    if evidence_url:
        row["evidence_url"] = evidence_url
    if canonical_row:
        row["canonical_row"] = canonical_row
    rows.append(row)
    document["aliases"] = rows
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    from crawler import venues as venues_module

    venues_module.reset_cache()
