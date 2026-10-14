from .government import SuzhouGovernmentSource
from .venue import VenueSource
from .event_platform import EventPlatformSource

SOURCES = {
    "government": SuzhouGovernmentSource,
    "venue": VenueSource,
    "event_platform": EventPlatformSource,
}
