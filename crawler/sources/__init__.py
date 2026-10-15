from .government import SuzhouGovernmentSource
from .venue import VenueSource, ExpoVenueSource, SscacVenueSource
from .event_platform import EventPlatformSource
from .cityevent import (SIPACSource, CultureTourismSource, OlympicSource,
                        HuodongjiaSource, DamaiSource, SubaoSource)
from .tourism import VisitszSource
from .community.douban import DoubanSource
from .exhibition.cnena import CnenaSource

# Existing aliases remain valid. No social-media adapter is registered.
SOURCES = {
    "government": SuzhouGovernmentSource,
    "venue": VenueSource,
    "event_platform": EventPlatformSource,
    "expo": ExpoVenueSource,
    "sipac": SIPACSource,
    "culture_tourism": CultureTourismSource,
    "olympic": OlympicSource,
    "arts": SscacVenueSource,
    "huodongjia": HuodongjiaSource,
    "damai": DamaiSource,
    "subao": SubaoSource,
    "cnena": CnenaSource,
    "visitsz": VisitszSource,
    "douban": DoubanSource,
}
