"""地理层级：把「市级 / 县级市·区 / 功能区 / 街道 / 商业商圈」分开表达。

## 审核（F05）指出的问题

线上把不同层级混在同一个维度里：商圈比较表里同时出现太仓市、常熟市、姑苏区，
酒店页把太仓市放在「商圈」的位置上。结果是「按区」和「按商圈」的指标无法分别解释，
城市周报也可能因为层级混用而漏数或重复计数。

数据实情（本地生产副本，2026-10-26）：

    districts 共 39 条：城市 1、县级市 4、区 5、街道 8、商业商圈 20、未归入 1
    事件挂载：区 244、市 117、县级市 69 —— 事件几乎全挂在**行政单元**上
    酒店挂载：商业商圈 13、街道 2、县级市 4 —— 酒店挂在**商圈**上
    商圈与街道**没有 parentId**，行政区也**没有 adminCode**

这解释了为什么「商圈比较」表里全是行政区：事件本身就没有商圈归属。所以正确做法不是
把行政区改名叫商圈，而是把两类分开展示，并把没有商圈的明确标为「未归属」。

## 本模块的职责

  * `level_of`：把 district 归到唯一层级，缺字段时按 kind 推断，推断结果标注来源；
  * `build_tree`：按 parentId 组织成树，**父级未知的放进 unassigned 分组**，不猜；
  * `coverage`：按层级统计事件/场馆/酒店的挂载数量，保证同一实体只计一次；
  * `rollup`：自下而上汇总时只做加法，父级数字 = 子级之和 + 自身直接挂载。

不改表结构：行政编码、父级、匹配级别都写进 districts.payload，并记录来源字段
（`parentSource`/`adminCodeSource`），因此可回退、可追溯。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from backend.database import connect

# 层级编号：数字越大越细。功能区（functional_zone）与行政区并列，不与任何一级混用。
LEVELS: dict[str, int] = {
    "city": 0,            # 地级市
    "county_city": 1,     # 县级市
    "district": 1,        # 市辖区
    "functional_zone": 1, # 功能区（如工业园区），运营分区，不等于行政区
    "subdistrict": 2,     # 街道 / 镇
    "business_area": 3,   # 商业商圈
    "unassigned": 9,      # 未归属
}

LEVEL_LABELS: dict[str, str] = {
    "city": "地级市",
    "county_city": "县级市",
    "district": "市辖区",
    "functional_zone": "功能区",
    "subdistrict": "街道/镇",
    "business_area": "商业商圈",
    "unassigned": "未归属",
}

# 行政 vs 商业：这是审核要求分开的两个维度。功能区单独一类，不并入行政区。
IDENTITY_KIND: dict[str, str] = {
    "city": "administrative",
    "county_city": "administrative",
    "district": "administrative",
    "subdistrict": "administrative",
    "functional_zone": "operational",
    "business_area": "commercial",
    "unassigned": "unknown",
}


def level_of(district: dict) -> tuple[str, str]:
    """返回 (层级, 判定来源)。只有 kind 缺失时才需要推断，推断一律标注。"""
    kind = district.get("kind")
    if kind in LEVELS:
        return kind, "kind 字段"
    # 老数据里有一条 kind 缺失的「未归入商圈」占位记录。
    identifier = str(district.get("id") or "")
    if identifier.endswith("unassigned"):
        return "unassigned", "id 后缀推断"
    return "unassigned", "无 kind 字段，按未归属处理"


def is_administrative(level: str) -> bool:
    return IDENTITY_KIND.get(level) == "administrative"


def is_commercial(level: str) -> bool:
    return IDENTITY_KIND.get(level) == "commercial"


def ancestors(district_id: str, districts: dict[str, dict]) -> list[str]:
    """沿 parentId 向上，返回 [父, 祖父, ...]。遇到环或断链立即停止，不猜测。"""
    chain: list[str] = []
    seen = {district_id}
    current = districts.get(district_id)
    while current:
        parent_id = current.get("parentId")
        if not parent_id or parent_id in seen or parent_id not in districts:
            break
        chain.append(parent_id)
        seen.add(parent_id)
        current = districts.get(parent_id)
    return chain


def admin_root(district_id: str, districts: dict[str, dict]) -> str | None:
    """最近的行政祖先（含自身）。商圈若没有父级，返回 None —— 由调用方放进未归属。"""
    chain = [district_id, *ancestors(district_id, districts)]
    for identifier in chain:
        district = districts.get(identifier) or {}
        level, _ = level_of(district)
        if is_administrative(level) and identifier != district_id:
            return identifier
    district = districts.get(district_id) or {}
    level, _ = level_of(district)
    return district_id if is_administrative(level) else None


def load(db_path: Path) -> tuple[dict[str, dict], dict[str, int], dict[str, int], dict[str, int]]:
    """读取地区、事件、场馆、酒店，返回 (districts, event_counts, venue_counts, hotel_counts)。"""
    with connect(db_path) as con:
        districts = {
            row["id"]: json.loads(row["payload"])
            for row in con.execute("SELECT id, payload FROM districts")
        }
        events = Counter(row[0] for row in con.execute("SELECT district FROM events"))
        venues = Counter(
            json.loads(row["payload"]).get("districtId")
            for row in con.execute("SELECT payload FROM venues")
        )
        hotels = Counter(
            json.loads(row["payload"]).get("districtId")
            for row in con.execute("SELECT payload FROM hotels")
        )
    return districts, dict(events), dict(venues), dict(hotels)


def coverage(db_path: Path) -> dict:
    """按层级统计挂载情况，以及父级未知（未归属）的数量。

    这是审核要求「按区与按商圈的指标可以分别解释」的基础：先能说清每个层级各挂了多少实体。
    """
    districts, events, venues, hotels = load(db_path)
    by_level: dict[str, dict[str, int]] = defaultdict(
        lambda: {"districts": 0, "events": 0, "venues": 0, "hotels": 0}
    )
    unresolved: list[dict] = []
    for identifier, district in districts.items():
        level, source = level_of(district)
        bucket = by_level[level]
        bucket["districts"] += 1
        bucket["events"] += events.get(identifier, 0)
        bucket["venues"] += venues.get(identifier, 0)
        bucket["hotels"] += hotels.get(identifier, 0)
        if level in ("business_area", "subdistrict") and not district.get("parentId"):
            unresolved.append({
                "id": identifier,
                "name": district.get("name"),
                "level": level,
                "hasCoordinates": (district.get("coordinates") or {}).get("lng") is not None,
                "reason": "缺少父级行政区（高清逆地理编码未返回 parentId）",
            })
    orphan_events = events.get(None, 0)
    orphan_venues = venues.get(None, 0)
    return {
        "byLevel": {level: dict(values) for level, values in by_level.items()},
        "labels": LEVEL_LABELS,
        "unresolved": unresolved,
        "unattached": {
            "events": orphan_events,
            "venues": orphan_venues,
            "hotels": hotels.get(None, 0),
        },
        "counts": {
            "districts": len(districts),
            "events": sum(events.values()),
            "venues": sum(venues.values()),
            "hotels": sum(hotels.values()),
        },
    }


def build_tree(db_path: Path) -> dict:
    """组织成树：行政区按 parentId，商业商圈与街道挂到最近的行政祖先；挂不上的进 unassigned。

    规则（审核要求）：父级未知不做推断，直接放进未归属分组，并在返回里给出原因。
    """
    districts, events, venues, hotels = load(db_path)
    display = lambda identifier: (districts.get(identifier) or {}).get("name") or identifier

    nodes: dict[str, dict] = {}
    for identifier, district in districts.items():
        level, source = level_of(district)
        nodes[identifier] = {
            "id": identifier,
            "name": district.get("name"),
            "level": level,
            "levelLabel": LEVEL_LABELS[level],
            "identityKind": IDENTITY_KIND[level],
            "levelSource": source,
            "parentId": district.get("parentId"),
            "adminCode": district.get("adminCode"),
            "adminCodeSource": district.get("adminCodeSource"),
            "matchLevel": district.get("matchLevel"),
            "coordinates": district.get("coordinates"),
            "counts": {
                "events": events.get(identifier, 0),
                "venues": venues.get(identifier, 0),
                "hotels": hotels.get(identifier, 0),
            },
            "children": [],
        }

    roots: list[dict] = []
    unassigned_children: list[dict] = []
    for identifier, node in nodes.items():
        parent_id = node["parentId"]
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        elif node["level"] in ("subdistrict", "business_area"):
            # 父级未知：不猜，放进未归属分组
            unassigned_children.append(node)
        else:
            roots.append(node)

    def rollup(node: dict) -> dict[str, int]:
        total = dict(node["counts"])
        for child in node["children"]:
            child_total = rollup(child)
            for key in total:
                total[key] += child_total[key]
        node["totals"] = total
        return total

    for root in roots:
        rollup(root)
    for child in unassigned_children:
        rollup(child)

    unassigned = {
        "id": "unassigned",
        "name": f"未归属（{len(unassigned_children)} 个商圈/街道缺父级行政区）",
        "level": "unassigned",
        "levelLabel": LEVEL_LABELS["unassigned"],
        "identityKind": "unknown",
        "children": unassigned_children,
        "counts": {"events": 0, "venues": 0, "hotels": 0},
        "totals": {
            key: sum(child["totals"][key] for child in unassigned_children)
            for key in ("events", "venues", "hotels")
        },
    }

    roots.sort(key=lambda item: (LEVELS[item["level"]], item["name"] or ""))
    return {
        "roots": roots,
        "unassigned": unassigned,
        "labels": LEVEL_LABELS,
        "note": (
            "行政区（市 / 县级市 / 区 / 街道）与商业商圈分开表达；功能区单列。"
            "父级未知的商圈放进未归属，不做推断。"
        ),
        "display": {"sample": [display(root["id"]) for root in roots[:3]]},
    }
