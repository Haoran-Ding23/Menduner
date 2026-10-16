"""Places around a venue — the source's own POI records, classified by the source's own type.

The knowledge graph connects an event to its venue, and the venue to what actually surrounds it:
hotels (``hotels``), restaurants and public transport (``places``). This module owns the second
one: the table, and the rule that turns an AMap POI's declared type string into a graph kind.

Two boundaries decide everything here, and both come from what AMap itself publishes:

1. **Only the declared type classifies a row.** Every POI carries
   ``type = "大类;中类;小类"`` (``餐饮服务;咖啡厅;咖啡厅``, ``交通设施服务;地铁站;地铁站``). A row is
   kept only when that string names one of the categories the graph draws, and its subtype is
   the source's own words — never a guess from the name.
2. **Facilities of a station are not the station.** AMap returns a metro station's entrances,
   a railway station's platforms, ticket halls and waiting rooms as separate POIs. Asking "how do
   I get here" must answer with the station, so ``出入口``/``站台``/``售票``/``候车室``/``进站口``
   entries are dropped, and so are 直升机场/停机坪 (not passenger transport) and 港口码头 (the
   sightseeing piers along 金鸡湖, which are tourism rather than access).

Coverage is a *sample around venues that hold events*, not a city POI database: the enrichment
script queries AMap per venue and stores what it finds, so a place far from every event venue is
absent by construction. The row keeps the AMap place URL it came from, so any consumer can open
the same record.
"""

RESTAURANT_ROOT = "餐饮服务"

# ``(second level, third level)`` -> graph subtype, read straight off AMap's declared type.
# 餐饮相关场所 is AMap's own name for food places it does not classify further (food courts,
# stalls); it stays a restaurant, with the source's wording kept as the subtype.
RESTAURANT_SUBTYPES = (
    "中餐厅", "外国餐厅", "快餐厅", "休闲餐饮场所", "咖啡厅", "茶艺馆", "冷饮店",
    "糕饼店", "甜品店", "餐饮相关场所",
)
# AMap's middle category -> (graph subtype, the third-level values that are the facility itself
# rather than one of its parts). 机场相关 is the middle category for both the airport and the city
# air terminals, which is why the graph subtype is simply 机场.
TRANSIT_SUBTYPES = {
    "地铁站": ("地铁站", ("地铁站",)),
    "轻轨站": ("轻轨站", ("轻轨站",)),
    "公交车站": ("公交车站", ("公交车站", "公交车站相关")),
    "火车站": ("火车站", ("火车站",)),
    "长途汽车站": ("长途汽车站", ("长途汽车站",)),
    "机场相关": ("机场", ("飞机场", "机场相关")),
}
KINDS = ("restaurant", "transport")

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
  id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS places_kind_idx ON places(json_extract(payload, '$.kind'));
"""


def ensure_schema(con):
    """Additive and idempotent, like every other resource table in this database."""
    con.executescript(SCHEMA)


def classify(declared_type):
    """``(kind, subtype)`` for an AMap POI's declared type string, else None.

    ``"交通设施服务;地铁站;出入口"`` -> None (a station entrance, not the station) while
    ``"交通设施服务;地铁站;地铁站"`` -> ``("transport", "地铁站")``.
    """
    if not isinstance(declared_type, str):
        return None
    parts = [part.strip() for part in declared_type.split(";") if part.strip()]
    if len(parts) < 2:
        return None
    root, middle, last = parts[0], parts[1], (parts[2] if len(parts) > 2 else parts[1])
    if root == RESTAURANT_ROOT:
        if middle in RESTAURANT_SUBTYPES:
            return "restaurant", middle
        return None
    if root == "交通设施服务":
        allowed = TRANSIT_SUBTYPES.get(middle)
        if allowed and last in allowed[1]:
            return "transport", allowed[0]
    return None
