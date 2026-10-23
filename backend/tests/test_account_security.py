"""账号安全：改密码与会话撤销。

这些行为是「密码泄露之后能自救」的那一环，所以测的重点不是接口通不通，而是：
改密码必须让其他会话失效、必须校验当前密码、撤销会话不能越权到别人的账号。
"""
import pytest

from backend import accounts
from backend.database import connect, initialize


@pytest.fixture
def con(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as connection:
        yield connection


def make_account(con, login="hotel-a", password="secret-pass-1"):
    invite = accounts.create_invite(
        con, plan="pro", trial_days=14, max_uses=1, note=None,
        created_by="test", expires_in_days=None,
    )
    account, token = accounts.register(
        con, invite_code=invite["code"], login=login, password=password,
        name="王经理", hotel="测试酒店",
    )
    return account, token


def test_password_change_keeps_the_caller_and_ends_the_rest(con):
    account, token = make_account(con)
    other = accounts.create_session(con, account["id"])
    third = accounts.create_session(con, account["id"])

    current = accounts.session_account(con, token)
    accounts.change_password(con, account=current, current_password="secret-pass-1",
                             new_password="brand-new-9", keep_token=token)

    assert accounts.session_account(con, token) is not None, "调用者自己的会话必须保留"
    assert accounts.session_account(con, other) is None, "其他会话必须失效"
    assert accounts.session_account(con, third) is None
    # The new password works, the old one does not (authenticate refuses with PermissionError).
    assert accounts.authenticate(con, login="hotel-a", password="brand-new-9") is not None
    with pytest.raises(PermissionError):
        accounts.authenticate(con, login="hotel-a", password="secret-pass-1")


def test_wrong_current_password_changes_nothing(con):
    account, token = make_account(con)
    current = accounts.session_account(con, token)
    with pytest.raises(ValueError, match="当前密码不正确"):
        accounts.change_password(con, account=current, current_password="wrong",
                                 new_password="brand-new-9", keep_token=token)
    # Password still works, session still alive.
    assert accounts.authenticate(con, login="hotel-a", password="secret-pass-1") is not None
    assert accounts.session_account(con, token) is not None


def test_reusing_the_same_password_is_refused(con):
    account, token = make_account(con)
    current = accounts.session_account(con, token)
    with pytest.raises(ValueError, match="不能与当前密码相同"):
        accounts.change_password(con, account=current, current_password="secret-pass-1",
                                 new_password="secret-pass-1", keep_token=token)


def test_short_new_password_is_refused(con):
    account, token = make_account(con)
    current = accounts.session_account(con, token)
    with pytest.raises(ValueError, match="至少 8 位"):
        accounts.change_password(con, account=current, current_password="secret-pass-1",
                                 new_password="short", keep_token=token)


def test_sessions_list_marks_the_caller(con):
    account, token = make_account(con)
    accounts.create_session(con, account["id"])
    rows = accounts.list_sessions(con, account["id"], token)
    assert len(rows) == 2
    assert sum(row["current"] for row in rows) == 1
    for row in rows:
        assert len(row["id"]) == 16
        # The stored value is a hash; the printed id is a prefix and never the token itself.
        assert row["id"] != token


def test_revoke_one_session_by_id(con):
    account, token = make_account(con)
    other = accounts.create_session(con, account["id"])
    target = next(row for row in accounts.list_sessions(con, account["id"], token)
                  if not row["current"])
    assert accounts.revoke_session(con, account["id"], target["id"]) is True
    assert accounts.session_account(con, other) is None
    assert accounts.session_account(con, token) is not None


def test_cannot_revoke_another_accounts_session(con):
    first, token = make_account(con, login="hotel-a")
    second, second_token = make_account(con, login="hotel-b")
    target = next(row for row in accounts.list_sessions(con, second["id"], second_token)
                  if row["current"])
    # Same request shape, different account: nothing may be removed.
    assert accounts.revoke_session(con, first["id"], target["id"]) is False
    assert accounts.session_account(con, second_token) is not None


def test_revoke_rejects_a_garbage_id(con):
    account, _ = make_account(con)
    with pytest.raises(ValueError, match="会话标识无效"):
        accounts.revoke_session(con, account["id"], "ab")
