from crawler.schema import UnifiedEvent


def validate(values, references):
    event = UnifiedEvent.model_validate(values)
    for field, resource in [("venue_id", "venues"), ("district_id", "districts")]:
        value = getattr(event, field)
        if value and value not in {r["id"] for r in references[resource]}:
            raise ValueError(f"Unknown {field}: {value}")
    return event
