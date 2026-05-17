import pytest
import keyring
from rufino.runtime.secrets import (
    SecretStore,
    InMemorySecretStore,
    KeyringSecretStore,
    SecretNotFound,
)


def test_store_and_retrieve_secret():
    store = InMemorySecretStore()
    store.set("rufino-test", "user", "my-secret-value")
    assert store.get("rufino-test", "user") == "my-secret-value"


def test_get_missing_secret_raises():
    store = InMemorySecretStore()
    with pytest.raises(SecretNotFound):
        store.get("rufino-test", "user")


def test_delete_secret():
    store = InMemorySecretStore()
    store.set("rufino-test", "user", "v")
    store.delete("rufino-test", "user")
    with pytest.raises(SecretNotFound):
        store.get("rufino-test", "user")


def test_delete_missing_secret_is_idempotent():
    store = InMemorySecretStore()
    store.delete("nonexistent", "user")  # no exception


def test_protocol_compliance():
    store = InMemorySecretStore()
    assert isinstance(store, SecretStore)


def _has_real_keyring() -> bool:
    backend = keyring.get_keyring()
    name = type(backend).__name__
    return name not in ("Keyring", "fail.Keyring")


@pytest.mark.skipif(not _has_real_keyring(), reason="No real keyring backend available")
def test_keyring_backend_roundtrip():
    store = KeyringSecretStore()
    service = "rufino-test-foundation-task4"
    account = "test-user"

    try:
        store.set(service, account, "hello-rufino")
        assert store.get(service, account) == "hello-rufino"
    finally:
        store.delete(service, account)
