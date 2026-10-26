"""地理层级测试（审核 F05）。

重点：
  * 行政区与商业商圈必须能分别识别，功能区单列；
  * 父级未知的商圈进未归属，**不做推断**；
  * 汇总只做加法，同一实体只计一次，父级数字 = 自身 + 子级；
  * 行政编码与商圈自身 id 是两个字段（审核要求不能把 adcode 当商圈唯一身份）。
"""
import json

import pytest

from backend import geo
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        districts = [
            {"id": "suzhou", "name": "苏州市", "kind": "city", "level": 0, "parentId": None},
            {"id": "gusu", "name": "姑苏区", "kind": "district", "level": 1, "parentId": "suzhou",
             "adminCode": "320508"},
            {"id": "taicang", "name": "太仓市", "kind": "county_city", "level": 1,
             "parentId": "suzhou", "adminCode": "320585"},
            {"id": "district-观前", "name": "观前", "kind": "business_area", "parentId": "gusu",
             "adminCode": "320508", "matchLevel": "regeo·addressComponent",
             "coordinates": {"lng": 120.62, "lat": 31.31}},
            {"id": "district-太仓", "name": "太仓", "kind": "business_area", "parentId": "taicang",
             "coordinates": {"lng": 121.1, "lat": 31.45}},
            {"id": "district-某某镇", "name": "某某镇", "kind": "subdistrict"},
            {"id": "district-unassigned", "name": "未归入商圈"},
            {"id": "zone-yuanqu", "name": "工业园区", "kind": "functional_zone", "parentId": "suzhou"},
        ]
        for district in districts:
            con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                        (district["id"], json.dumps(district, ensure_ascii=False)))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("v1", json.dumps({"id": "v1", "name": "场馆", "districtId": "gusu"})))
        con.execute("INSERT INTO hotels(id,payload) VALUES(?,?)",
                    ("h1", json.dumps({"id": "h1", "name": "酒店", "districtId": "district-观前"})))
        for index, district in enumerate(["gusu", "gusu", "taicang", "district-unassigned"]):
            con.execute(
                "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
                "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f"e{index}", f"活动{index}", "culture", "2026-11-01", None, "v1", district,
                 "s1", "Needs Review", "{}"),
            )
    return path


def test_administrative_and_commercial_are_distinct():
    assert geo.is_administrative("district") is True
    assert geo.is_administrative("county_city") is True
    assert geo.is_commercial("business_area") is True
    assert geo.is_commercial("district") is False
    # 功能区是运营分区，两类都不属于
    assert geo.is_administrative("functional_zone") is False
    assert geo.is_commercial("functional_zone") is False


def test_level_detection_marks_inference_source():
    assert geo.level_of({"kind": "business_area"}) == ("business_area", "kind 字段")
    level, source = geo.level_of({"id": "district-unassigned"})
    assert level == "unassigned"
    assert "推断" in source or "未归属" in source


def test_coverage_counts_each_entity_once(db):
    result = geo.coverage(db)
    assert result["counts"]["events"] == 4
    assert result["counts"]["venues"] == 1
    assert result["counts"]["hotels"] == 1
    # 两个事件挂在姑苏区、一个挂太仓市、一个挂未归入商圈
    assert result["byLevel"]["district"]["events"] == 2
    assert result["byLevel"]["county_city"]["events"] == 1
    assert result["byLevel"]["business_area"]["hotels"] == 1


def test_unresolved_business_areas_are_reported_not_inferred(db):
    result = geo.coverage(db)
    names = [item["name"] for item in result["unresolved"]]
    assert "某某镇" in names          # 没有 parentId 的街道
    assert "观前" not in names        # 已经有父级
    assert all(item["reason"] for item in result["unresolved"])


def test_tree_groups_children_under_administrative_parents(db):
    tree = geo.build_tree(db)
    suzhou = next(root for root in tree["roots"] if root["id"] == "suzhou")
    gusu = next(child for child in suzhou["children"] if child["id"] == "gusu")
    assert [child["id"] for child in gusu["children"]] == ["district-观前"]
    assert gusu["totals"]["events"] == 2          # 自身直接挂载
    assert gusu["totals"]["hotels"] == 1          # 来自子级商圈


def test_tree_put_parentless_business_area_into_unassigned(db):
    tree = geo.build_tree(db)
    children = [child["id"] for child in tree["unassigned"]["children"]]
    assert "district-某某镇" in children
    # 未归属分组里必须是缺父级的那些，不能混入已有父级的
    assert "district-观前" not in children


def test_admin_code_is_separate_from_business_area_identity(db):
    tree = geo.build_tree(db)
    suzhou = next(root for root in tree["roots"] if root["id"] == "suzhou")
    gusu = next(child for child in suzhou["children"] if child["id"] == "gusu")
    guanqian = gusu["children"][0]
    # 商圈自身 id 与行政编码是两个字段：观前用的是姑苏区的 adcode，但它不是姑苏区
    assert guanqian["id"] == "district-观前"
    assert guanqian["adminCode"] == "320508"
    assert guanqian["level"] == "business_area"
    assert guanqian["identityKind"] == "commercial"


def test_rollup_is_additive_and_does_not_double_count(db):
    tree = geo.build_tree(db)
    root_events = sum(root["totals"]["events"] for root in tree["roots"])
    unassigned_events = tree["unassigned"]["totals"]["events"]
    assert root_events + unassigned_events == 4
