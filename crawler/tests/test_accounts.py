"""Customer accounts: invite-code trials, sessions, offline payment requests and activation.

These are product accounts (password hash + session cookie), not the operator HTTP-Basic accounts
in backend/auth.py. The behaviour that matters most: the effective plan is derived from the dates
on every request, and only an operator confirming an offline payment opens a paid period.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import accounts
from backend.database import connect, initialize
from backend.main import create_app

ADMIN = {"X-Menduner-Login": "test-admin"}
REVIEWER = {"X-Menduner-Login": "test-reviewer"}
VIEWER = {"X-Menduner-Login": "test-viewer"}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    initialize(path)
    yield path


@pytest.fixture(autouse=True)
def clear_login_throttle():
    accounts._failures.clear()
    yield
    accounts._failures.clear()


@pytest.fixture
def client(db):
    with TestClient(create_app(db)) as test_client:
        yield test_client


def make_invite(client, **overrides) -> str:
    payload = {"plan": "pro", "trial_days": 28, "max_uses": 1, "expires_in_days": 30}
    payload.update(overrides)
    response = client.post("/admin/invites", headers=ADMIN, json=payload)
    assert response.status_code == 200, response.text
    return response.json()["invite"]["code"]


def register(client, code, login="hotel-a", password="secret-pass-1", name="王经理"):
    return client.post("/account/register", json={
        "invite_code": code, "login": login, "password": password, "name": name,
        "hotel": "测试酒店",
    })


def test_only_an_admin_can_create_invites(client):
    assert client.post("/admin/invites", json={"plan": "pro"}).status_code == 401
    assert client.post("/admin/invites", headers=VIEWER, json={"plan": "pro"}).status_code == 403
    assert client.post("/admin/invites", headers=REVIEWER, json={"plan": "pro"}).status_code == 403
    response = client.post("/admin/invites", headers=ADMIN, json={"plan": "pro", "trial_days": 21})
    assert response.status_code == 200
    invite = response.json()["invite"]
    assert invite["plan"] == "pro" and invite["status"] == "open"
    assert invite["code"].startswith("MND-")


def test_register_with_an_invite_starts_a_trial_and_signs_in(client):
    code = make_invite(client, trial_days=28)
    response = register(client, code)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authenticated"] is True
    account = body["account"]
    assert account["login"] == "hotel-a" and account["plan"] == "pro"
    assert account["status"] == "trial"
    assert client.cookies.get(accounts.SESSION_COOKIE)
    # The invite is single-use by default; a second registration with it is refused.
    second = register(client, code, login="hotel-b", name="李经理")
    assert second.status_code == 400
    assert "用完" in second.json()["detail"]


def test_registration_validates_the_entire_form(client):
    code = make_invite(client)
    assert register(client, "MND-0000-0000").status_code == 400  # unknown code
    assert register(client, code, login="ab").status_code == 400  # login too short
    assert register(client, code, password="short").status_code == 400
    assert register(client, code, name="").status_code == 422
    register(client, code)
    # A second account cannot take the same login.
    other = make_invite(client)
    assert register(client, other, login="HOTEL-A").status_code == 409


def test_login_logout_and_the_self_view(client):
    code = make_invite(client)
    register(client, code)
    assert client.post("/account/logout").json()["authenticated"] is False
    assert client.get("/account").json()["authenticated"] is False
    wrong = client.post("/account/login", json={"login": "hotel-a", "password": "wrong-pass"})
    assert wrong.status_code == 401
    ok = client.post("/account/login", json={"login": "hotel-a", "password": "secret-pass-1"})
    assert ok.status_code == 200
    assert ok.json()["account"]["login"] == "hotel-a"
    assert client.get("/account").json()["authenticated"] is True


def test_the_plan_is_derived_from_the_dates_not_the_row(client, db):
    code = make_invite(client, trial_days=28)
    register(client, code)
    assert client.get("/account").json()["account"]["plan"] == "pro"

    # Move the trial into the past: the row still says pro, the effective plan must be free.
    with connect(db) as con:
        con.execute("UPDATE customer_accounts SET trial_ends_at=?",
                    ("2020-01-01T00:00:00+00:00",))
    body = client.get("/account").json()
    assert body["account"]["status"] == "expired"
    assert body["account"]["plan"] == "free"


def test_an_expired_session_no_longer_authenticates(client, db):
    code = make_invite(client)
    register(client, code)
    with connect(db) as con:
        con.execute("UPDATE customer_sessions SET expires_at=?", ("2020-01-01T00:00:00+00:00",))
    assert client.get("/account").json()["authenticated"] is False


def test_offline_payment_request_and_admin_confirmation(client):
    code = make_invite(client, trial_days=7)
    register(client, code)
    client.post("/account/logout")
    anonymous = client.post("/account/orders", json={"plan": "pro", "months": 3})
    assert anonymous.status_code == 401
    client.post("/account/login", json={"login": "hotel-a", "password": "secret-pass-1"})

    request = client.post("/account/orders", json={
        "plan": "pro", "months": 3, "note": "对公转账，发票开公司",
    })
    assert request.status_code == 200, request.text
    order = request.json()["order"]
    assert order["amountCny"] == 980 * 3
    assert order["status"] == "pending"
    # Nothing is unlocked by filing the request.
    assert client.get("/account").json()["account"]["status"] == "trial"

    pending = client.get("/admin/orders?status=pending", headers=ADMIN).json()["orders"]
    assert [row["id"] for row in pending] == [order["id"]]
    assert pending[0]["accountLogin"] == "hotel-a"

    confirmed = client.post(f"/admin/orders/{order['id']}/confirm", headers=ADMIN)
    assert confirmed.status_code == 200, confirmed.text
    account = client.get("/account").json()["account"]
    assert account["status"] == "active"
    assert account["plan"] == "pro"
    assert account["subscriptionEndsAt"] > "2026-01-01"

    # A confirmed order cannot be confirmed twice.
    again = client.post(f"/admin/orders/{order['id']}/confirm", headers=ADMIN)
    assert again.status_code == 409


def test_an_operator_can_cancel_a_pending_request(client):
    code = make_invite(client)
    register(client, code)
    order = client.post("/account/orders", json={"plan": "enterprise", "months": 1}).json()["order"]
    assert order["amountCny"] == 780
    cancelled = client.post(f"/admin/orders/{order['id']}/cancel", headers=ADMIN)
    assert cancelled.status_code == 200
    assert cancelled.json()["order"]["status"] == "cancelled"
    assert client.get("/admin/orders?status=pending", headers=ADMIN).json()["orders"] == []


def test_customer_management_is_admin_only(client):
    assert client.get("/admin/accounts").status_code == 401
    assert client.get("/admin/accounts", headers=REVIEWER).status_code == 403
    assert client.get("/admin/accounts", headers=VIEWER).status_code == 403
    code = make_invite(client)
    register(client, code)
    listed = client.get("/admin/accounts", headers=ADMIN).json()["accounts"]
    assert len(listed) == 1
    assert listed[0]["login"] == "hotel-a"
    assert listed[0]["plan"] == "pro"
    assert listed[0]["pendingOrders"] == 0


def test_invite_lists_show_usage_and_expiry(client):
    code = make_invite(client, max_uses=2, trial_days=14)
    register(client, code)
    invites = client.get("/admin/invites", headers=ADMIN).json()["invites"]
    row = next(item for item in invites if item["code"] == code)
    assert row["used_count"] == 1 and row["status"] == "open"
    register(client, code, login="hotel-b", name="李经理")
    row = next(item for item in client.get("/admin/invites", headers=ADMIN).json()["invites"]
               if item["code"] == code)
    assert row["status"] == "used"


def test_repeated_wrong_passwords_are_throttled(client):
    code = make_invite(client)
    register(client, code)
    client.post("/account/logout")
    for _ in range(accounts.MAX_LOGIN_FAILURES):
        response = client.post("/account/login",
                               json={"login": "hotel-a", "password": "wrong-pass"})
        assert response.status_code == 401
    locked = client.post("/account/login",
                         json={"login": "hotel-a", "password": "secret-pass-1"})
    assert locked.status_code == 401
    assert "次数过多" in locked.json()["detail"]


def test_password_hashing_round_trip():
    stored = accounts.hash_password("secret-pass-1")
    assert stored.startswith("pbkdf2_sha256$")
    assert accounts.verify_password("secret-pass-1", stored)
    assert not accounts.verify_password("secret-pass-2", stored)
    assert not accounts.verify_password("secret-pass-1", "garbage")


def test_calendar_month_arithmetic():
    from datetime import datetime, timezone
    start = datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert accounts.add_months(start, 1).month == 2
    assert accounts.add_months(start, 1).day == 28
    assert accounts.add_months(start, 12) == datetime(2027, 1, 31, tzinfo=timezone.utc)
