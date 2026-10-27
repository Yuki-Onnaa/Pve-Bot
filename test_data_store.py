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


def test_existing_json_file_is_migrated(store):
    import json, os
    legacy = {
        "123": {"pve": {"total_points": 5}},
        "_ip_bans": {"1.1.1.1": {"user_id": "9"}},
        "_ip_logs": {"2.2.2.2": {"123": "2026-01-01T00:00:00"}},
        "_hwid_logs": {"hw": {"123": "2026-01-01T00:00:00", "456": "2026-01-02T00:00:00"}},
    }
    with open(store.DATA_FILE, "w") as f:
        json.dump(legacy, f)
    assert store.load_data() == {"123": {"pve": {"total_points": 5}}, "_ip_bans": {"1.1.1.1": {"user_id": "9"}}}
    assert store.get_ips_for_user(123) == ["2.2.2.2"]
    assert sorted(store.get_users_for_hwid("hw")) == ["123", "456"]
    assert store.is_ip_banned("1.1.1.1") is True
    assert not os.path.exists(store.DATA_FILE)
    assert os.path.exists(store.DATA_FILE + ".migrated")


def test_failed_migration_does_not_leave_an_empty_store(store):
    import pytest
    with open(store.DATA_FILE, "w") as f:
        f.write("{not json")
    with pytest.raises(ValueError):
        store.load_data()
    with pytest.raises(ValueError):
        store.load_data()


def test_save_removes_deleted_keys_and_keeps_logs(store):
    store.save_data({"a": 1, "b": 2})
    store.log_ip(1, "3.3.3.3")
    with store.data_txn() as data:
        del data["a"]
        data["b"] = 3
    assert store.load_data() == {"b": 3}
    assert store.get_ips_for_user(1) == ["3.3.3.3"]


def test_save_only_writes_changed_rows(store):
    store.save_data({"a": {"x": 1}, "b": {"y": 2}})
    conn = store._db()
    writes = []
    conn.set_trace_callback(lambda sql: writes.append(sql) if sql.startswith(("INSERT", "DELETE")) else None)
    data = store.load_data()
    data["b"]["y"] = 3
    store.save_data(data)
    conn.set_trace_callback(None)
    assert len(writes) == 1 and "kv" in writes[0]


def test_export_import_roundtrip(store):
    store.save_data({"u": {"n": 1}})
    store.log_device(5, ip="4.4.4.4", fingerprint="fp", hwid="hw")
    snapshot = store.export_all()
    assert snapshot["_fingerprint_logs"]["fp"].keys() == {"5"}
    store.import_all({"other": True})
    assert store.load_data() == {"other": True}
    assert store.get_ips_for_user(5) == []
    store.import_all(snapshot)
    assert store.load_data() == {"u": {"n": 1}}
    assert store.get_hwids_for_user(5) == ["hw"]


def test_failed_txn_does_not_save(store):
    import pytest
    store.save_data({"n": 1})
    with pytest.raises(RuntimeError):
        with store.data_txn() as data:
            data["n"] = 2
            raise RuntimeError
    assert store.load_data() == {"n": 1}
