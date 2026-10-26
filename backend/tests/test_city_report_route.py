"""城市周报导出的鉴权测试（GPT Round 2 验收第 6 项）。

导出接口是本次最大风险点，所以这里测的是**权限边界**，不是文件格式：
  * 未登录必须 401，不能靠"GET 只读"就放行；
  * 已登录可以下载，且内容是 xlsx；
  * 非法地区返回 400，而不是一份看似完整的空报表。
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend import accounts
from backend.database import connect, initialize, database_path
from backend.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "main.sqlite3"
    initialize(db_path)
    monkeypatch.setenv("MENDUNER_DB_PATH", str(db_path))
    with connect(db_path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "官方来源", "government", 0, "https://a.test/x",
                     "2026-10-01T00:00:00+00:00"))
        con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                    ("taicang", json.dumps({"id": "taicang", "name": "太仓市",
                                            "kind": "county_city", "parentId": None},
                                           ensure_ascii=False)))
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e1", "测试活动", "culture", "2026-10-20", None, None, "taicang", "s1",
             "Needs Review", "{}"),
        )
    app = create_app()
    return TestClient(app), db_path


def register(db_path, login="hotel-a", password="secret-pass-1"):
    with connect(db_path) as con:
        invite = accounts.create_invite(
            con, plan="pro", trial_days=14, max_uses=1, note=None,
            created_by="test", expires_in_days=None,
        )
        _account, token = accounts.register(
            con, invite_code=invite["code"], login=login, password=password,
            name="王经理", hotel="测试酒店",
        )
    return token


def test_requires_login(client):
    http, _db = client
    response = http.get("/reports/city/taicang.xlsx")
    assert response.status_code == 401, response.text


def test_logged_in_download_is_xlsx(client):
    http, db_path = client
    token = register(db_path)
    http.cookies.set(accounts.SESSION_COOKIE, token)
    response = http.get("/reports/city/taicang.xlsx",
                        params={"start": "2026-10-19", "end": "2026-10-25"})
    assert response.status_code == 200, response.text
    assert response.content[:2] == b"PK"          # xlsx 是 zip 容器
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert "%E5%A4%AA%E4%BB%93%E5%B8%82" in disposition  # 文件名含「太仓市」的 URL 编码


def test_unknown_district_is_400(client):
    http, db_path = client
    token = register(db_path)
    http.cookies.set(accounts.SESSION_COOKIE, token)
    response = http.get("/reports/city/no-such.xlsx")
    assert response.status_code == 400
    assert "地区不存在" in response.text


def test_oversized_range_is_400(client):
    http, db_path = client
    token = register(db_path)
    http.cookies.set(accounts.SESSION_COOKIE, token)
    response = http.get("/reports/city/taicang.xlsx",
                        params={"start": "2020-01-01", "end": "2026-12-31"})
    assert response.status_code == 400
    assert "区间过长" in response.text
