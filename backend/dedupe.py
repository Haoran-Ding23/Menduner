"""跨来源活动去重。

## 数据里的真实情况（先看数据再定规则）

生产库 436 条活动里有 22 组同名事件，但**绝大多数不是重复，是不同场次**：
「苏州文化艺术中心:维罗妮卡的房间」有 7 条，是 7 个周末的演出；
「周庄古镇:只此周庄」有 5 条，是 5 个档期。把它们合并成一条是错的——酒店要看到的是
「这周有几场」，不是「这年有一部戏」。

真正的跨来源重复长这样：
「第三十三届中国汽车工程学会年会暨展览会」两条，日期完全相同（10-27~10-30），
一条来自平台来源、一条来自社区来源，其中一条还没挂场馆。

## 因此规则分四种，只有第一种自动合并

| 情况 | 判定 | 处理 |
|---|---|---|
| 同名称 + 同场馆（或一边缺场馆）+ 日期重叠 | **重复** | 自动合并，保留全部来源 |
| 同名称 + 同场馆 + 日期不重叠 | **不同场次** | 不合并 |
| 同名称 + 不同场馆 + 日期重叠 | **巡演候选** | 不合并，进人工确认 |
| 名称高度相似但不完全相同 + 同场馆 + 日期重叠 | **模糊候选** | 不合并，进人工确认 |

场馆名写在活动名前面（「苏州文化艺术中心:维罗妮卡的房间」）时会被剥掉再比较，
否则跨来源「带前缀 / 不带前缀」的写法永远匹配不上。

## 身份是派生字段，可重算

`events.canonical_id` 每次运行都从零重算：同一活动的一组成员都指向同一条规范记录
（规范记录指向自己）。因此重复执行是幂等的，撤销就是把列清空或重跑。
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from backend.database import connect

# 中文标点、空格、全角字符统一掉；保留数字与字母，因为它们区分「第 33 届」这类不同届次。
_PUNCT = re.compile(r"[\s\u3000·・•\-—–_/\\|,，、;；。.!！?？\"'“”‘’()（）\[\]【】《》<>〈〉+*#~]+")
_VENUE_SPLIT = re.compile(r"[:：]")

# 名称核心相似度阈值：只用于「候选」，不用于自动合并。
FUZZY_THRESHOLD = 0.86


def normalize(text: str | None) -> str:
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text)
    return _PUNCT.sub("", folded).lower()


def strip_venue_prefix(name: str, venue_names: set[str]) -> str:
    """把「场馆:活动名」拆开，返回活动名部分。

    只有当冒号前的片段确实像场馆时才拆，否则「主题:副标题」这种写法会被误切。
    """
    if not name:
        return ""
    parts = _VENUE_SPLIT.split(name, 1)
    if len(parts) != 2:
        return name
    head, tail = parts[0].strip(), parts[1].strip()
    if not tail:
        return name
    head_key = normalize(head)
    looks_like_venue = any(
        head_key and (head_key in normalize(v) or normalize(v) in head_key) for v in venue_names
    )
    return tail if looks_like_venue else name


@dataclass
class EventRow:
    id: str
    name: str
    start: str | None
    end: str | None
    venue: str | None
    source: str | None
    district: str | None = None


@dataclass
class Cluster:
    canonical: str
    members: list[str] = field(default_factory=list)
    reason: str = ""


def load_events(db_path: Path) -> tuple[list[EventRow], set[str]]:
    with connect(db_path) as con:
        venue_names = set()
        for row in con.execute("SELECT payload FROM venues"):
            name = json.loads(row["payload"]).get("name")
            if name:
                venue_names.add(name)
        events = [
            EventRow(
                id=row["id"], name=row["name"] or "", start=row["startDate"],
                end=row["endDate"], venue=row["venue"], source=row["source"],
                district=row["district"],
            )
            for row in con.execute(
                "SELECT id,name,startDate,endDate,venue,source,district FROM events"
            )
        ]
    return events, venue_names


def _span(event: EventRow) -> tuple[str, str] | None:
    if not event.start:
        return None
    end = event.end or event.start
    return (event.start, end) if end >= event.start else None


def _overlaps(a: EventRow, b: EventRow) -> bool:
    sa, sb = _span(a), _span(b)
    if not sa or not sb:
        # 没有日期的记录无法证明是同一场，也不该被自动合并。
        return False
    return sa[0] <= sb[1] and sb[0] <= sa[1]


def _similar(a: str, b: str) -> float:
    """字符二元组 Jaccard。够用来发现「同一活动不同写法」，不够精确所以只产候选。"""
    if not a or not b:
        return 0.0
    grams = lambda text: {text[i:i + 2] for i in range(max(1, len(text) - 1))}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / len(ga | gb) if (ga | gb) else 0.0


def classify(a: EventRow, b: EventRow, venue_names: set[str]) -> str | None:
    """返回 None（无关）、"duplicate"（可自动合并）或候选原因字符串。"""
    name_a = normalize(strip_venue_prefix(a.name, venue_names))
    name_b = normalize(strip_venue_prefix(b.name, venue_names))
    if not name_a or not name_b:
        return None

    exact = name_a == name_b
    if not exact and _similar(name_a, name_b) < FUZZY_THRESHOLD:
        return None

    same_venue = a.venue == b.venue and a.venue is not None
    one_missing = (a.venue is None) != (b.venue is None)
    overlaps = _overlaps(a, b)

    if exact and (same_venue or one_missing) and overlaps:
        return "duplicate"
    if exact and same_venue and not overlaps:
        return None  # 不同场次：同一部戏的多个档期，不是重复
    if exact and not same_venue and not one_missing and overlaps:
        return "巡演候选：同名同日期但场馆不同，需人工确认"
    if not exact and overlaps and (same_venue or one_missing):
        return "名称相似且日期重叠，需人工确认"
    return None


def build_clusters(events: list[EventRow], venue_names: set[str]) -> tuple[list[Cluster], list[dict]]:
    """并查集把可自动合并的活动连成簇，其余可疑的成对返回。"""
    parent = {event.id: event.id for event in events}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    by_name: dict[str, list[EventRow]] = defaultdict(list)
    for event in events:
        key = normalize(strip_venue_prefix(event.name, venue_names))
        if key:
            by_name[key].append(event)

    candidates: list[dict] = []
    for group in by_name.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                verdict = classify(group[i], group[j], venue_names)
                if verdict == "duplicate":
                    union(group[i].id, group[j].id)
                elif verdict:
                    candidates.append({
                        "a": group[i].id, "b": group[j].id,
                        "aName": group[i].name, "bName": group[j].name,
                        "aSource": group[i].source, "bSource": group[j].source,
                        "reason": verdict,
                    })

    grouped: dict[str, list[EventRow]] = defaultdict(list)
    for event in events:
        grouped[find(event.id)].append(event)

    clusters = []
    for root, members in grouped.items():
        if len(members) < 2:
            continue
        # 规范记录确定性选取：优先挂在场馆的、其次日期最长的、最后按 id 排序，保证重跑结果一致。
        members.sort(key=lambda e: (e.venue is None, -(len(e.end or e.start or "")), e.id))
        clusters.append(Cluster(
            canonical=members[0].id,
            members=[member.id for member in members],
            reason=f"{len(members)} 条不同来源的记录指向同一活动（名称+场馆+日期重叠）",
        ))
    return clusters, candidates


def apply(db_path: Path, clusters: list[Cluster]) -> int:
    """写入 canonical_id 并返回被归并的成员数（不含规范记录自身）。幂等：先清空再写。"""
    with connect(db_path) as con:
        con.execute("UPDATE events SET canonical_id = id")
        merged = 0
        for cluster in clusters:
            for member in cluster.members:
                if member == cluster.canonical:
                    continue
                con.execute("UPDATE events SET canonical_id=? WHERE id=?", (cluster.canonical, member))
                merged += 1
        return merged


def summary(db_path: Path) -> dict:
    events, venue_names = load_events(db_path)
    clusters, candidates = build_clusters(events, venue_names)
    merged = sum(len(cluster.members) - 1 for cluster in clusters)
    return {
        "events": len(events),
        "clusters": len(clusters),
        "mergedMembers": merged,
        "remainingIdentities": len(events) - merged,
        "candidates": len(candidates),
        "clusterDetail": [
            {"canonical": c.canonical, "members": c.members, "reason": c.reason}
            for c in clusters
        ],
        "candidateDetail": candidates,
    }
