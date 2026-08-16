import json
import pytest
from core.mapping_store import MappingStore


@pytest.fixture
def store(tmp_path):
    # keychain_service is namespaced per-test so tests never collide with
    # a real case's key or with each other.
    s = MappingStore(
        path=tmp_path / "mapping.json.enc",
        keychain_service="法律脱敏工具-test-" + tmp_path.name,
    )
    yield s
    s.delete_key()


def test_roundtrip_encrypt_decrypt_returns_original_mapping(store):
    mapping = {"⟦人名001⟧": "张三", "⟦身份证002⟧": "110101199003072316"}
    store.save(mapping)
    loaded = store.load()
    assert loaded == mapping


def test_same_key_reused_across_separate_instances(tmp_path):
    service = "法律脱敏工具-test-reuse"
    store1 = MappingStore(path=tmp_path / "mapping.json.enc", keychain_service=service)
    mapping = {"⟦人名001⟧": "张三"}
    store1.save(mapping)

    # a fresh instance pointed at the same keychain service + file must
    # decrypt what the first instance wrote -- proves the key wasn't
    # silently regenerated, which would orphan the existing mapping.
    store2 = MappingStore(path=tmp_path / "mapping.json.enc", keychain_service=service)
    assert store2.load() == mapping
    store1.delete_key()  # cleanup keychain entry


def test_raw_file_on_disk_contains_no_plaintext_pii(store):
    mapping = {"⟦人名001⟧": "张三丰", "⟦电话002⟧": "13812345678"}
    store.save(mapping)
    raw_bytes = store.path.read_bytes()
    assert b"13812345678" not in raw_bytes
    assert "张三丰".encode("utf-8") not in raw_bytes


def test_load_missing_file_returns_empty_mapping(store):
    assert store.load() == {}
