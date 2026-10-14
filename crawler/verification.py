"""Automatic field verification rule.

V1.6.2 and earlier applied a blanket rule: nothing extracted from the web was ever
marked ``Verified``, and every uncertain value was left for a human. That rule made the
status vocabulary meaningless — a deterministically extracted date from an official
government page and a guessed category from a community aggregator both ended up as
``Needs Review`` — and it made the map path unreachable, because the frontend only plots
an event whose venue reference is ``Verified``.

The rule implemented here is narrower and evidence-based:

    a field claim may be auto-verified only when BOTH hold
      (1) AUTHORITY  - the claim comes from an official government or official venue
                       source (registry trust_level OFFICIAL_GOVERNMENT / OFFICIAL_VENUE), and
      (2) DETERMINISM - the value was read from an explicit machine field or an explicit
                       labelled field on that page, not produced by a heuristic rule.

Everything else stays ``Needs Review`` / ``Unverified`` and is queued for human review on
the Evidence page. Aggregators (commercial platforms, media, community/UGC) are never
auto-verified, no matter how cleanly their pages parse, because the claim is theirs and
not the organiser's.

This module is deliberately pure: it takes plain values and returns a decision, so the
rule can be tested exhaustively without a database or network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Registry trust levels that count as authoritative for a factual claim.
AUTHORITATIVE_TRUST_LEVELS = frozenset({"OFFICIAL_GOVERNMENT", "OFFICIAL_VENUE"})

# Frontend field name -> event field name.
FACTUAL_FIELDS = frozenset(
    {"event_name", "start_date", "end_date", "venue", "location", "organizer"}
)

# Extraction methods that read a value straight off the page. The adapters name these
# ``explicit_*`` / ``official_*`` (e.g. ``explicit_leading_event_date``,
# ``explicit_labelled_opening_date``), which is the codebase's own marker for "this value
# was read from an explicit field or label". A closed allow-list was tried first and was
# wrong: it silently left real, deterministic dates unverified because their method name
# had not been enumerated.
DETERMINISTIC_PREFIXES = ("explicit_", "official_")
# Methods that read a structured machine field rather than page text. Kept explicit because
# their names do not follow the prefix convention.
DETERMINISTIC_METHODS = frozenset(
    {
        "JSON-LD.event_datetime",
        "detail_page_heading",
        "named_place_before_source_street_part",
        "attributeMapSingle.time.value",
    }
)

# A method whose text matches this is a rule/guess even if it also looks explicit
# (e.g. ``explicit_title_keyword_to_category_rule``). Never auto-verifiable. Checked
# before the prefixes, so an ``explicit_..._rule`` name can never slip through.
HEURISTIC_MARKER = re.compile(r"rule|heuristic|guess|inferred|fallback|default", re.I)

# Non-claims: a response URL is provenance, and a reference id is derived from another
# field. Verifying either would dress up bookkeeping as a fact.
NON_FACTUAL_FIELDS = frozenset(
    {"source_url", "venue_id", "district_id", "category", "field_evidence"}
)

AUTO_ORIGIN = "auto:official_deterministic"
# A venue reference may be verified when the venue NAME it was derived from is itself
# verified, because then the binding joins two established facts rather than asserting a
# new one. This is what lets a venue's verified geography reach the itinerary.
BINDING_ORIGIN = "auto:verified_venue_binding"
# Methods that mean "this venue row was chosen because it is the row for that exact name".
BINDING_METHODS = frozenset(
    {
        "derived_reference_id_from_explicit_venue_name",
        "canonical_duplicate_venue_identity",
    }
)
AGGREGATOR_ORIGIN = "pending:aggregator_source"
HEURISTIC_ORIGIN = "pending:heuristic_extraction"
UNSUPPORTED_ORIGIN = "pending:no_deterministic_evidence"


@dataclass(frozen=True)
class Decision:
    """Outcome of the auto-verification rule for one field claim."""

    status: str
    origin: str
    reason: str

    @property
    def verified(self) -> bool:
        return self.status == "Verified"


def is_authoritative(trust_level: str | None) -> bool:
    return bool(trust_level) and trust_level in AUTHORITATIVE_TRUST_LEVELS


def is_deterministic(method: str | None) -> bool:
    if not method:
        return False
    if HEURISTIC_MARKER.search(method):
        return False
    if method.startswith(DETERMINISTIC_PREFIXES):
        return True
    return method in DETERMINISTIC_METHODS


def decide(
    *,
    field: str,
    value,
    method: str | None,
    trust_level: str | None,
    mock: bool = False,
    existing_status: str | None = None,
    status_fallback: str = "Needs Review",
) -> Decision:
    """Return the verification decision for one extracted field claim.

    ``existing_status`` is honoured when it is ``Conflicting``: a within-source
    contradiction must never be auto-verified, whatever the source's authority.
    ``status_fallback`` is the status kept for a field that is not auto-verifiable at all
    (for example ``city``), so the decision normalises a claim without erasing it.
    """
    if mock:
        return Decision("Unverified", "pending:mock_source", "synthetic source is never verified")
    if value is None or value == "" or value == "null":
        return Decision(
            "Needs Review" if existing_status == "Conflicting" else "Missing",
            UNSUPPORTED_ORIGIN,
            "no value was extracted",
        )
    if existing_status == "Conflicting":
        return Decision(
            "Conflicting",
            HEURISTIC_ORIGIN,
            "the source contradicts itself on this field; a human decides",
        )
    if field in NON_FACTUAL_FIELDS:
        return Decision(
            status_fallback, UNSUPPORTED_ORIGIN, f"{field} is a derived value, not a fact claim"
        )
    if field not in FACTUAL_FIELDS:
        return Decision(
            status_fallback, UNSUPPORTED_ORIGIN, f"{field} is not an auto-verifiable factual field"
        )
    if not is_authoritative(trust_level):
        return Decision(
            "Needs Review",
            AGGREGATOR_ORIGIN,
            f"source trust level {trust_level or 'unknown'} is not official; queued for human review",
        )
    if not is_deterministic(method):
        return Decision(
            "Needs Review",
            HEURISTIC_ORIGIN,
            f"extraction method {method or 'unknown'} is not deterministic; queued for human review",
        )
    return Decision(
        "Verified",
        AUTO_ORIGIN,
        f"{method} on an {trust_level} source",
    )


def verify_venue_binding(
    *,
    reference_method: str | None,
    venue_status: str | None,
    trust_level: str | None,
    current_status: str,
) -> Decision | None:
    """Verify an event's venue reference when both halves of the binding are established.

    A venue reference is a derived id, so under the field rule alone it can never be
    verified — which is why a venue's verified geography could never reach an itinerary.
    The gap is honest to close only when BOTH halves hold:

      * the venue NAME claim is already ``Verified`` (or is being auto-verified here), so the
        place itself is established by an official source; and
      * the reference id was derived deterministically from that exact name.

    A heuristic-derived reference, an unverified name, a non-official publisher or a human
    rejection all leave the reference pending. Returns ``None`` when the binding does not
    qualify, so the caller keeps whatever the field rule decided.
    """
    if current_status == "Verified":
        return None
    if not is_authoritative(trust_level):
        return None
    if venue_status not in ("Verified",):
        return None
    if not reference_method:
        return None
    # The binding rule is about the LINK being deterministic from the name, not about who
    # published the page. An aggregator correctly may not decide on its own authority
    # whether an exhibition happens at 苏州国际博览中心 — that is the venue's fact — but once
    # the venue identity is established, resolving the name to that venue row is a
    # deterministic derivation and can be verified as a link.
    if reference_method not in BINDING_METHODS:
        return None
    return Decision(
        "Verified",
        BINDING_ORIGIN,
        "venue name is verified and this reference was derived from that exact name",
    )
