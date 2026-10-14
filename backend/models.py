from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal['Verified', 'Unverified', 'Missing', 'Conflicting', 'Needs Review']

class EventRecord(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: Literal['business', 'culture', 'education', 'sports', 'folk', 'government', 'others']
    startDate: date | None
    endDate: date | None
    venueId: str | None
    districtId: str | None
    demo: bool

    @model_validator(mode='after')
    def dates_in_order(self):
        if self.endDate and (not self.startDate or self.endDate < self.startDate):
            raise ValueError('Invalid event date interval')
        return self

class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = Field(min_length=1)
    entityId: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: object = None
    status: Status
    sourceUrl: str | None = None
    sourceName: str | None = None
    method: str
    updatedAt: str

    @model_validator(mode='after')
    def preserve_uncertainty(self):
        if self.value is None or self.value == '':
            self.status = 'Missing'
        elif self.status == 'Verified' and not (self.sourceUrl or '').startswith(('https://', 'http://')):
            self.status = 'Needs Review'
        return self
