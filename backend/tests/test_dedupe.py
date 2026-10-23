"""去重规则的测试。

数据里 22 组同名事件绝大多数是不同场次（维罗妮卡的房间 7 场、周庄 5 场），所以这里测的重点
不是「同名就合并」，而是**什么时候绝对不能合并**：

  * 同一部戏的不同档期不许合并；
  * 同一名称在不同场馆的同日活动（巡演）不许自动合并；
  * 没有日期的记录不许被自动合并；
  * 跨来源、同场馆、同日期必须合并，并且规范记录的选择要确定、重复执行要幂等。
"""
import json

import pytest

from backend import dedupe
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源一", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s2", "来源二", "tourism", 0, "https://b.test", "2026-10-01T00:00:00+00:00"))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("v-theatre", json.dumps({"id": "v-theatre", "name": "苏州文化艺术中心"})))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("v-expo", json.dumps({"id": "v-expo", "name": "苏州国际博览中心"})))
        # events.district 有外键，先建地区行，否则插入事件会违反约束。
        con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                    ("suzhou", json.dumps({"id": "suzhou", "name": "苏州市", "kind": "city"})))
    # canonical_id 列由迁移脚本添加；测试里直接建，模拟已经迁移过的库。
    with connect(path) as con:
        try:
            con.execute("ALTER TABLE events ADD COLUMN canonical_id TEXT")
        except Exception:
            pass
    return path


def add(db, event_id, name, start, end=None, venue=None, source="s1"):
    with connect(db) as con:
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload,canonical_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, name, "culture", start, end, venue, "suzhou", source,
             "Needs Review", "{}", event_id),
        )


def test_cross_source_same_venue_same_dates_is_a_duplicate(db):
    add(db, "e1", "第三十三届中国汽车工程学会年会暨展览会", "2026-10-27", "2026-10-30", "v-expo", "s1")
    add(db, "e2", "第三十三届中国汽车工程学会年会暨展览会", "2026-10-27", "2026-10-30", "v-expo", "s2")
    events, venues = dedupe.load_events(db)
    clusters, candidates = dedupe.build_clusters(events, venues)
    assert len(clusters) == 1
    assert set(clusters[0].members) == {"e1", "e2"}
    assert candidates == []


def test_same_name_same_venue_different_runs_are_not_duplicates(db):
    """一部戏的多个档期不是重复 —— 这是数据里最常见的情况。"""
    add(db, "r1", "苏州文化艺术中心:维罗妮卡的房间", "2026-10-16", "2026-10-18", "v-theatre")
    add(db, "r2", "苏州文化艺术中心:维罗妮卡的房间", "2026-10-23", "2026-10-25", "v-theatre")
    add(db, "r3", "苏州文化艺术中心:维罗妮卡的房间", "2026-10-30", "2026-11-01", "v-theatre")
    events, venues = dedupe.load_events(db)
    clusters, candidates = dedupe.build_clusters(events, venues)
    assert clusters == []
    assert candidates == []


def test_missing_venue_on_one_side_still_merges(db):
    add(db, "e1", "第三十三届中国汽车工程学会年会暨展览会", "2026-10-27", "2026-10-30", "v-expo", "s1")
    add(db, "e2", "第三十三届中国汽车工程学会年会暨展览会", "2026-10-27", "2026-10-30", None, "s2")
    events, venues = dedupe.load_events(db)
    clusters, _ = dedupe.build_clusters(events, venues)
    assert len(clusters) == 1


def test_tour_with_different_venues_is_a_candidate_not_a_merge(db):
    add(db, "t1", "原创音乐剧《海上音》", "2026-11-01", "2026-11-02", "v-theatre", "s1")
    add(db, "t2", "原创音乐剧《海上音》", "2026-11-01", "2026-11-02", "v-expo", "s2")
    events, venues = dedupe.load_events(db)
    clusters, candidates = dedupe.build_clusters(events, venues)
    assert clusters == []              # 巡演不自动合并
    assert len(candidates) == 1
    assert "巡演" in candidates[0]["reason"]


def test_venue_prefix_does_not_block_matching(db):
    """一个来源写全称、一个来源只写剧目名，必须能匹配上。"""
    add(db, "p1", "苏州文化艺术中心:近景魔术秀《奇幻秘社》", "2026-10-15", "2026-10-16", "v-theatre", "s1")
    add(db, "p2", "近景魔术秀《奇幻秘社》", "2026-10-15", "2026-10-16", "v-theatre", "s2")
    events, venues = dedupe.load_events(db)
    clusters, _ = dedupe.build_clusters(events, venues)
    assert len(clusters) == 1


def test_events_without_dates_are_never_auto_merged(db):
    add(db, "u1", "某个还没定档的活动", None, None, "v-expo", "s1")
    add(db, "u2", "某个还没定档的活动", None, None, "v-expo", "s2")
    events, venues = dedupe.load_events(db)
    clusters, _ = dedupe.build_clusters(events, venues)
    assert clusters == []


def test_apply_is_idempotent_and_canonical_points_to_itself(db):
    add(db, "e1", "同一活动", "2026-10-27", "2026-10-30", "v-expo", "s1")
    add(db, "e2", "同一活动", "2026-10-27", "2026-10-30", "v-expo", "s2")
    events, venues = dedupe.load_events(db)
    clusters, _ = dedupe.build_clusters(events, venues)

    first = dedupe.apply(db, clusters)
    second = dedupe.apply(db, clusters)
    assert first == second == 1  # 只有 1 个成员被归并，规范记录指向自己

    with connect(db) as con:
        rows = {row["id"]: row["canonical_id"] for row in con.execute("SELECT id, canonical_id FROM events")}
    canonical = clusters[0].canonical
    assert rows[canonical] == canonical
    other = next(member for member in clusters[0].members if member != canonical)
    assert rows[other] == canonical


def test_summary_reports_identity_counts(db):
    add(db, "e1", "同一活动", "2026-10-27", "2026-10-30", "v-expo", "s1")
    add(db, "e2", "同一活动", "2026-10-27", "2026-10-30", "v-expo", "s2")
    add(db, "r1", "某部戏", "2026-10-01", "2026-10-02", "v-theatre")
    add(db, "r2", "某部戏", "2026-10-08", "2026-10-09", "v-theatre")
    result = dedupe.summary(db)
    assert result["events"] == 4
    assert result["clusters"] == 1
    assert result["mergedMembers"] == 1
    assert result["remainingIdentities"] == 3   # 4 条记录，1 条被合并
