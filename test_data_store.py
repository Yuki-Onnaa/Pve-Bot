from datetime import datetime, timedelta


def test_load_returns_empty_dict_when_file_missing(store):
    assert store.load_data() == {}


def test_save_then_load_roundtrip(store):
    store.save_data({"123": {"vouches": 2}})
    assert store.load_data() == {"123": {"vouches": 2}}


def test_data_txn_persists_mutation(store):
    with store.data_txn() as data:
        data["counter"] = 5
    assert store.load_data()["counter"] == 5


def test_ip_ban_and_unban(store):
    assert store.is_ip_banned("1.2.3.4") is False
    store.ban_ip("1.2.3.4", user_id=42)
    assert store.is_ip_banned("1.2.3.4") is True
    store.unban_ip("1.2.3.4")
    assert store.is_ip_banned("1.2.3.4") is False


def test_expired_ip_ban_is_lifted(store):
    past = (datetime.now() - timedelta(minutes=1)).isoformat()
    store.ban_ip("5.6.7.8", user_id=1, expires_at=past)
    assert store.is_ip_banned("5.6.7.8") is False


def test_ip_log_lookup_both_directions(store):
    store.log_ip(10, "9.9.9.9")
    store.log_ip(11, "9.9.9.9")
    assert store.get_ips_for_user(10) == ["9.9.9.9"]
    assert sorted(store.get_users_for_ip("9.9.9.9")) == ["10", "11"]


def test_fingerprint_ban_and_hwid_ban(store):
    store.ban_fingerprint("fp-abc", user_id=7)
    store.ban_hwid("hw-xyz", user_id=7)
    assert store.is_fingerprint_banned("fp-abc") is True
    assert store.is_hwid_banned("hw-xyz") is True
    assert store.is_fingerprint_banned("other") is False
