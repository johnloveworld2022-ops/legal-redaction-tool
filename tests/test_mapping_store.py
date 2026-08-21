import json
import subprocess

import pytest
from core.mapping_store import MappingStore
from core.subprocess_utils import SubprocessTimeoutError


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


def test_non_44_keychain_failure_raises_instead_of_silently_regenerating_key(store, monkeypatch):
    # Any find-generic-password failure OTHER than "genuinely not found"
    # (exit code 44) -- a locked keychain, a denied access prompt, a
    # transient error -- must never be treated the same as "no key yet."
    # Falling through to key generation in that case would overwrite an
    # existing key via `-U` and permanently orphan an already-encrypted
    # mapping.json.enc. Found via external security review.
    class FakeResult:
        returncode = 51  # arbitrary non-44, non-zero code
        stdout = ""
        stderr = "keychain is locked"

    calls = []

    def fake_run_subprocess(args, **kwargs):
        calls.append(args)
        return FakeResult()

    monkeypatch.setattr("core.mapping_store.run_subprocess", fake_run_subprocess)

    with pytest.raises(RuntimeError):
        store._get_or_create_key()

    # must not have attempted to add/overwrite a key after the failed read
    assert not any("add-generic-password" in call for call in calls)


def test_keychain_calls_go_through_the_timeout_wrapper(store, monkeypatch):
    # mapping_store must not bypass subprocess_utils -- a hung/prompting
    # `security` call needs to be killable, same as every other external
    # command in this tool.
    calls = []

    def fake_run_subprocess(args, **kwargs):
        calls.append((args, kwargs))
        raise SubprocessTimeoutError(args, kwargs.get("timeout", 10))

    monkeypatch.setattr("core.mapping_store.run_subprocess", fake_run_subprocess)

    with pytest.raises(SubprocessTimeoutError):
        store._get_or_create_key()

    assert len(calls) == 1
    assert "timeout" in calls[0][1]
