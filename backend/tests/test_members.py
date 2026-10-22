"""成员与角色：谁能看，谁能改。

酒店内部所有账号看同一份账，但上传会改变记录，所以只留给负责人。这是最保守的读法；
要放宽只需改 __init__ 里的 can_manage。
"""
import pytest

from backend import tenants
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    return path


@pytest.fixture
def base(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


def seed(db, base, tenant="hotel-a", owner="owner-a", members=()):
    tenants.create_tenant(db, tenant_id=tenant, name="A 酒店")
    tenants.add_member(db, tenant_id=tenant, login=owner, role="owner")
    for login in members:
        tenants.add_member(db, tenant_id=tenant, login=login, role="member")
    return tenant


def test_only_an_owner_may_manage(db, base):
    seed(db, base, members=["staff-a"])
    assert tenants.can_manage(db, "hotel-a", "owner-a") is True
    assert tenants.can_manage(db, "hotel-a", "staff-a") is False
    assert tenants.can_manage(db, "hotel-a", "someone-else") is False


def test_role_of_is_scoped_to_the_tenant(db, base):
    seed(db, base)
    assert tenants.role_of(db, "hotel-a", "owner-a") == "owner"
    assert tenants.role_of(db, "hotel-b", "owner-a") is None


def test_members_share_one_ledger_but_only_the_owner_uploads(db, base):
    """This is the product rule stated as a test."""
    seed(db, base, members=["staff-a"])
    with tenants.open_tenant_db(base, "hotel-a") as con:
        tenants.record_metric(con, metric="adr", period_start="2026-10-01",
                              value=600.0, uploaded_by="owner-a")
    with tenants.open_tenant_db(base, "hotel-a") as con:
        rows = tenants.read_metrics(con)
    # Both accounts see the same rows; nothing is filtered by who uploaded them.
    assert len(rows) == 1
    assert tenants.can_manage(db, "hotel-a", "staff-a") is False


def test_an_owner_cannot_remove_themselves(db, base):
    seed(db, base)
    with pytest.raises(ValueError, match="不能移除自己"):
        tenants.remove_member(db, tenant_id="hotel-a", login="owner-a",
                              acting_login="owner-a")


def test_removing_a_member_leaves_the_owner(db, base):
    seed(db, base, members=["staff-a"])
    tenants.remove_member(db, tenant_id="hotel-a", login="staff-a", acting_login="owner-a")
    assert [m["login"] for m in tenants.members_of(db, "hotel-a")] == ["owner-a"]


def test_removing_someone_who_is_not_a_member_is_refused(db, base):
    seed(db, base)
    with pytest.raises(ValueError, match="不是本店成员"):
        tenants.remove_member(db, tenant_id="hotel-a", login="stranger",
                              acting_login="owner-a")


# --- joining: the colleague already owns an empty hotel ---------------------------

def test_joining_moves_an_account_out_of_its_own_empty_hotel(db, base):
    """Registration gives every account a hotel, so joining has to tidy that one away."""
    seed(db, base)
    tenants.create_tenant(db, tenant_id="hotel-staff", name="staff 自建")
    tenants.add_member(db, tenant_id="hotel-staff", login="staff-a", role="owner")

    tenants.join_tenant(db, base, tenant_id="hotel-a", login="staff-a")

    assert tenants.tenant_of_login(db, "staff-a") == "hotel-a"
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM tenants WHERE id='hotel-staff'"
                           ).fetchone()[0] == 0
    # The old ledger file is gone with it.
    assert not tenants.tenant_db_path(base, "hotel-staff").exists()


def test_joining_is_refused_when_the_account_already_has_data(db, base):
    """Deleting a hotel that holds records would destroy data nobody agreed to lose."""
    seed(db, base)
    tenants.create_tenant(db, tenant_id="hotel-staff", name="staff 自建")
    tenants.add_member(db, tenant_id="hotel-staff", login="staff-a", role="owner")
    with tenants.open_tenant_db(base, "hotel-staff") as con:
        tenants.record_metric(con, metric="adr", period_start="2026-10-01",
                              value=600.0, uploaded_by="staff-a")

    with pytest.raises(ValueError, match="已有自己的酒店数据"):
        tenants.join_tenant(db, base, tenant_id="hotel-a", login="staff-a")
    # And nothing was destroyed by the failed attempt.
    assert tenants.tenant_of_login(db, "staff-a") == "hotel-staff"
    with tenants.open_tenant_db(base, "hotel-staff") as con:
        assert len(tenants.read_metrics(con)) == 1


def test_joining_a_hotel_you_already_belong_to_is_a_noop(db, base):
    seed(db, base, members=["staff-a"])
    result = tenants.join_tenant(db, base, tenant_id="hotel-a", login="staff-a")
    assert result["tenant_id"] == "hotel-a"
    assert result["role"] == "member"


def test_a_member_joins_as_a_member_not_an_owner(db, base):
    seed(db, base)
    tenants.create_tenant(db, tenant_id="hotel-staff", name="staff 自建")
    tenants.add_member(db, tenant_id="hotel-staff", login="staff-a", role="owner")
    tenants.join_tenant(db, base, tenant_id="hotel-a", login="staff-a")
    assert tenants.role_of(db, "hotel-a", "staff-a") == "member"
    assert tenants.can_manage(db, "hotel-a", "staff-a") is False
