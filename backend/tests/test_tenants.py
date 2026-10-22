"""Tenants and the private ledger.

The value of this module is what it refuses and what it cannot leak, so the tests are mostly
about isolation rather than about storage.
"""
import sqlite3

import pytest

from backend import tenants
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    tenants.create_tenant(path, tenant_id="hotel-a", name="A 酒店")
    tenants.create_tenant(path, tenant_id="hotel-b", name="B 酒店")
    return path


@pytest.fixture
def base(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


# --- the id becomes a filename, so it is validated ---------------------------------

@pytest.mark.parametrize("bad", [
    "../menduner", "a", "Hotel-A", "hotel_a", "hotel a", "", "..", "hotel/a",
])
def test_a_tenant_id_that_could_escape_the_directory_is_refused(bad):
    with pytest.raises(ValueError, match="Invalid tenant id"):
        tenants.tenant_db_path("/tmp/data", bad)


def test_a_normal_tenant_id_resolves_inside_the_tenants_directory(tmp_path):
    path = tenants.tenant_db_path(tmp_path, "hotel-a")
    assert path.parent.name == "tenants"
    assert path.name == "hotel-a.sqlite3"


# --- one file per hotel, and they do not see each other ----------------------------

def test_two_tenants_get_two_separate_files(base):
    a = tenants.tenant_db_path(base, "hotel-a")
    b = tenants.tenant_db_path(base, "hotel-b")
    assert a != b


def test_what_one_hotel_uploads_is_invisible_to_another(base):
    """The isolation guarantee, stated as a test."""
    with tenants.open_tenant_db(base, "hotel-a") as con:
        tenants.record_metric(con, metric="occupancy_pct", period_start="2026-10-01",
                              value=82.5, uploaded_by="a-manager")
    with tenants.open_tenant_db(base, "hotel-b") as con:
        assert tenants.read_metrics(con) == []


def test_reading_the_same_tenant_sees_what_was_written(base):
    with tenants.open_tenant_db(base, "hotel-a") as con:
        tenants.record_metric(con, metric="adr", period_start="2026-10-01",
                              value=620.0, uploaded_by="a-manager")
    with tenants.open_tenant_db(base, "hotel-a") as con:
        rows = tenants.read_metrics(con)
    assert len(rows) == 1
    assert rows[0]["value"] == 620.0
    assert rows[0]["uploaded_by"] == "a-manager"


# --- who belongs to which hotel ---------------------------------------------------

def test_an_account_belongs_to_exactly_one_hotel(db):
    tenants.add_member(db, tenant_id="hotel-a", login="manager", role="owner")
    with pytest.raises(ValueError, match="cannot read two hotels"):
        tenants.add_member(db, tenant_id="hotel-b", login="manager")


def test_adding_the_same_member_twice_is_harmless(db):
    tenants.add_member(db, tenant_id="hotel-a", login="manager")
    tenants.add_member(db, tenant_id="hotel-a", login="manager")
    assert [m["login"] for m in tenants.members_of(db, "hotel-a")] == ["manager"]


def test_several_accounts_can_share_one_hotel(db):
    """A store manager and their staff all see the same ledger."""
    tenants.add_member(db, tenant_id="hotel-a", login="manager", role="owner")
    tenants.add_member(db, tenant_id="hotel-a", login="staff-1")
    tenants.add_member(db, tenant_id="hotel-a", login="staff-2")
    assert len(tenants.members_of(db, "hotel-a")) == 3


def test_tenant_of_login_resolves_the_session_identity(db):
    tenants.add_member(db, tenant_id="hotel-a", login="manager")
    assert tenants.tenant_of_login(db, "manager") == "hotel-a"
    assert tenants.tenant_of_login(db, "nobody") is None


def test_a_member_cannot_be_added_to_an_unknown_tenant(db):
    with pytest.raises(ValueError, match="Unknown tenant"):
        tenants.add_member(db, tenant_id="hotel-z", login="someone")


def test_a_tenant_cannot_be_created_twice(db):
    with pytest.raises(ValueError, match="already exists"):
        tenants.create_tenant(db, tenant_id="hotel-a", name="A 酒店 (again)")


def test_an_unsupported_role_is_refused(db):
    with pytest.raises(ValueError, match="role must be one of"):
        tenants.add_member(db, tenant_id="hotel-a", login="x", role="admin")


# --- the private ledger refuses what it cannot trace ------------------------------

def test_an_unknown_metric_is_refused(base):
    with open_db(base, "hotel-a") as con:
        with pytest.raises(ValueError, match="metric must be one of"):
            tenants.record_metric(con, metric="revenue", period_start="2026-10-01",
                                  value=1.0, uploaded_by="a")


def open_db(base, tenant_id):
    """Named distinctly from database.connect: a local connect shadowed it and the tests
    that reached for the main database silently called this instead."""
    return tenants.open_tenant_db(base, tenant_id)


def test_an_upload_must_name_who_uploaded_it(base):
    with tenants.open_tenant_db(base, "hotel-a") as con:
        with pytest.raises(ValueError, match="who uploaded it"):
            tenants.record_metric(con, metric="adr", period_start="2026-10-01",
                                  value=1.0, uploaded_by="  ")


def test_an_impossible_period_is_refused(base):
    with tenants.open_tenant_db(base, "hotel-a") as con:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            tenants.record_metric(con, metric="adr", period_start="2026-13-40",
                                  value=1.0, uploaded_by="a")


def test_a_non_numeric_value_is_refused(base):
    with tenants.open_tenant_db(base, "hotel-a") as con:
        with pytest.raises(ValueError, match="must be a number"):
            tenants.record_metric(con, metric="adr", period_start="2026-10-01",
                                  value="620", uploaded_by="a")


def test_a_metric_can_carry_its_channel_and_room_type(base):
    with tenants.open_tenant_db(base, "hotel-a") as con:
        tenants.record_metric(con, metric="channel_share", period_start="2026-10-01",
                              value=31.5, channel="携程", uploaded_by="a")
        row = tenants.read_metrics(con)[0]
    assert row["channel"] == "携程"


# --- every account ends up owning a hotel -----------------------------------------

def test_an_account_gets_a_tenant_named_after_its_hotel(db):
    account = {"id": "acct-1", "login": "manager", "name": "王经理", "hotel": "苏州洲际酒店"}
    tenant = tenants.ensure_tenant_for_account(db, account)
    assert tenants.tenant_of_login(db, "manager") == tenant
    with connect(db) as con:
        name = con.execute("SELECT name FROM tenants WHERE id=?", (tenant,)).fetchone()["name"]
    assert name == "苏州洲际酒店"


def test_an_account_without_a_hotel_name_still_gets_a_labelled_tenant(db):
    account = {"id": "acct-2", "login": "staff", "name": "李四", "hotel": None}
    tenant = tenants.ensure_tenant_for_account(db, account)
    with connect(db) as con:
        name = con.execute("SELECT name FROM tenants WHERE id=?", (tenant,)).fetchone()["name"]
    assert "李四" in name and "待补" in name


def test_ensuring_a_tenant_twice_does_not_create_a_second_one(db):
    """Idempotent, so a retried registration or a re-run backfill is harmless."""
    account = {"id": "acct-3", "login": "manager3", "name": "张三", "hotel": "A 酒店"}
    first = tenants.ensure_tenant_for_account(db, account)
    second = tenants.ensure_tenant_for_account(db, account)
    assert first == second
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM tenants").fetchone()[0] >= 2  # fixture's two


def test_the_tenant_id_is_derived_from_the_account_so_it_is_stable(db):
    account = {"id": "acct-stable", "login": "stable", "name": "x", "hotel": None}
    assert tenants.tenant_id_for_account("acct-stable") == \
        tenants.tenant_id_for_account("acct-stable")
    # And it must satisfy the filename rule the accessor enforces.
    tenants.tenant_db_path(db.parent, tenants.tenant_id_for_account("acct-stable"))


def test_two_accounts_get_two_separate_ledgers(db, tmp_path):
    base = tmp_path / "private"
    base.mkdir()
    a = tenants.ensure_tenant_for_account(
        db, {"id": "acct-a", "login": "a-login", "name": "a", "hotel": "A"})
    b = tenants.ensure_tenant_for_account(
        db, {"id": "acct-b", "login": "b-login", "name": "b", "hotel": "B"})
    assert a != b
    with tenants.open_tenant_db(base, a) as con:
        tenants.record_metric(con, metric="adr", period_start="2026-10-01",
                              value=600.0, uploaded_by="a-login")
    with tenants.open_tenant_db(base, b) as con:
        assert tenants.read_metrics(con) == []


def test_an_account_without_id_or_login_is_refused(db):
    with pytest.raises(ValueError, match="needs an id and a login"):
        tenants.ensure_tenant_for_account(db, {"id": "", "login": "x"})



# --- the private table holds no price recommendation ------------------------------

def test_the_private_schema_holds_no_forecast_or_recommendation_column(base):
    with tenants.open_tenant_db(base, "hotel-a") as con:
        columns = {r[1] for r in con.execute("PRAGMA table_info(private_metrics)")}
    assert columns == {
        "id", "metric", "period_start", "period_end", "channel", "room_type", "value",
        "uploaded_by", "uploaded_at", "source_file",
    }
    for forbidden in ("price", "recommend", "forecast", "predict"):
        assert not any(forbidden in c for c in columns)
