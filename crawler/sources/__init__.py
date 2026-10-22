from .government import SuzhouGovernmentSource, TaicangCultureSource
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
    # 太仓 publishes its own exhibition notices; the county-level cities were previously only
    # reachable through the city-wide tourism calendar, which barely lists them.
    "taicang_culture": TaicangCultureSource,
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
