"""把 SQLite 里的活动/场馆/地区/酒店同步进 Neo4j。

## 定位

SQLite 是唯一事实源。Neo4j 只是它的**派生视图**：图坏了就重跑同步修好，绝不允许在图里改数据
再指望数据库跟上。因此每次同步都是「按数据库重建」，而不是增量补丁。

## 图模型

    (:District {id,name,kind})
    (:Venue    {id,name,districtId,verified})
    (:Hotel    {id,name,districtId,star})
    (:Event    {id,name,startDate,endDate,district,status})

    (Event)-[:HELD_AT]->(Venue)
    (Event)-[:IN_DISTRICT]->(District)
    (Venue)-[:IN_DISTRICT]->(District)
    (Hotel)-[:IN_DISTRICT]->(District)

关系只画数据里**写着**的东西：活动没挂场馆就不画 HELD_AT，场馆没有地区就不画 IN_DISTRICT。

    python -X utf8 -m backend.graph_sync                 # 只打印将要写入的统计
    python -X utf8 -m backend.graph_sync --apply         # 写入 NEO4J_URI 指向的库
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

BATCH = 500


def build_graph(db_path: Path) -> dict:
    """Read the database and return the nodes/edges to write. Pure, so it is testable alone."""
    nodes: dict[str, list[dict]] = {"District": [], "Venue": [], "Hotel": [], "Event": []}
    edges: list[dict] = []

    with connect(db_path) as con:
        for row in con.execute("SELECT id, payload FROM districts"):
            payload = json.loads(row["payload"])
            nodes["District"].append({
                "id": row["id"],
                "name": payload.get("name"),
                "kind": payload.get("kind"),
            })
        for row in con.execute("SELECT id, payload FROM venues"):
            payload = json.loads(row["payload"])
            coordinates = payload.get("coordinates") or {}
            venue = {
                "id": row["id"],
                "name": payload.get("name"),
                "districtId": payload.get("districtId") or payload.get("district"),
                "verified": coordinates.get("status") == "Verified",
            }
            nodes["Venue"].append(venue)
            if venue["districtId"]:
                edges.append({"from": "Venue", "id": venue["id"],
                              "rel": "IN_DISTRICT", "to": "District", "toId": venue["districtId"]})
        for row in con.execute("SELECT id, payload FROM hotels"):
            payload = json.loads(row["payload"])
            star = (payload.get("officialStar") or payload.get("star") or {}).get("level")
            hotel = {
                "id": row["id"],
                "name": payload.get("name"),
                "districtId": payload.get("districtId"),
                "star": star,
            }
            nodes["Hotel"].append(hotel)
            if hotel["districtId"]:
                edges.append({"from": "Hotel", "id": hotel["id"],
                              "rel": "IN_DISTRICT", "to": "District", "toId": hotel["districtId"]})
        for row in con.execute(
            "SELECT id, name, startDate, endDate, venue, district, verification_status FROM events"
        ):
            event = {
                "id": row["id"],
                "name": row["name"],
                "startDate": row["startDate"],
                "endDate": row["endDate"],
                "district": row["district"],
                "status": row["verification_status"],
            }
            nodes["Event"].append(event)
            if row["venue"]:
                edges.append({"from": "Event", "id": event["id"],
                              "rel": "HELD_AT", "to": "Venue", "toId": row["venue"]})
            if row["district"]:
                edges.append({"from": "Event", "id": event["id"],
                              "rel": "IN_DISTRICT", "to": "District", "toId": row["district"]})
    return {"nodes": nodes, "edges": edges}


def _write(graph: dict, uri: str, user: str, password: str) -> None:
    from neo4j import GraphDatabase  # imported lazily: a dry run must not need the driver

    driver = GraphDatabase.driver(uri, auth=(user, password))
    labels = list(graph["nodes"])
    with driver.session() as session:
        # Rebuild rather than patch: the graph is derived, so stale nodes are a bug, not history.
        session.run("MATCH (n) DETACH DELETE n")
        for label in labels:
            rows = graph["nodes"][label]
            for start in range(0, len(rows), BATCH):
                session.run(
                    f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row",
                    rows=rows[start:start + BATCH],
                )
        for edge in graph["edges"]:
            session.run(
                f"MATCH (a:{edge['from']} {{id: $fromId}}) "
                f"MATCH (b:{edge['to']} {{id: $toId}}) "
                f"MERGE (a)-[:{edge['rel']}]->(b)",
                fromId=edge["id"], toId=edge["toId"],
            )
    driver.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else database_path()
    graph = build_graph(db_path)
    for label, rows in graph["nodes"].items():
        print(f"  {label}: {len(rows)}")
    print(f"  关系: {len(graph['edges'])}")
    for rel, count in _rel_counts(graph["edges"]).items():
        print(f"    {rel}: {count}")

    if not args.apply:
        print("  模式: 只报告（加 --apply 写入 Neo4j）")
        return 0

    uri = os.environ.get("NEO4J_URI")
    if not uri:
        print("  缺少 NEO4J_URI")
        return 2
    _write(graph, uri, os.environ.get("NEO4J_USER", "neo4j"),
           os.environ.get("NEO4J_PASSWORD", ""))
    print("  已写入 Neo4j")
    return 0


def _rel_counts(edges: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge["rel"]] = counts.get(edge["rel"], 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
