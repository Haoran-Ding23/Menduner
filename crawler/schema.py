"""Raw collection contract and unified event schema. No automatic verification."""

from datetime import date, datetime
from typing import Literal, Protocol
from urllib.parse import urlparse
from pydantic import BaseModel, Field, model_validator


class CollectedItem(BaseModel):
    item_key: str = Field(min_length=1)
    original_url: str
    source_name: str = Field(min_length=1)
    crawl_time: datetime
    raw_content: str = Field(min_length=1)
    mock: bool = False
    extractor: str = "jsonld"
    is_event: bool = True
    locator: str | None = None
    request_metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_origin(self):
        url = urlparse(self.original_url)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ValueError("Original URL must be absolute HTTP(S)")
        if not self.crawl_time.tzinfo:
            raise ValueError("Crawl time must include timezone")
        return self


class FieldClaim(BaseModel):
    confidence: float = Field(default=0.0, ge=0, le=1)
    status: Literal[
        "Verified", "Unverified", "Missing", "Conflicting", "Needs Review"
    ] = "Unverified"
    method: str = "deterministic_extraction"
    snippet: str | None = None
    candidates: list[str] = Field(default_factory=list)


class UnifiedEvent(BaseModel):
    event_id: str = Field(min_length=1)
    event_name: str = Field(min_length=1)
    category: Literal[
        "business", "culture", "education", "sports", "folk", "government", "others"
    ]
    start_date: date | None
    end_date: date | None
    venue: str | None
    location: str | None
    organizer: str | None
    source_url: str
    city: str | None = None
    venue_id: str | None = None
    district_id: str | None = None
    field_evidence: dict[str, FieldClaim] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ordered_interval(self):
        if self.end_date and (not self.start_date or self.end_date < self.start_date):
            raise ValueError("Invalid event date interval")
        return self


class SourceAdapter(Protocol):
    source_id: str
    source_name: str
    kind: str
    source_url: str

    def collect(self) -> list[CollectedItem]: ...
