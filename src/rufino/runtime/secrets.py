from typing import Protocol, runtime_checkable

import keyring
import keyring.errors


class SecretNotFound(Exception):
    """Raised when a secret is requested but does not exist in the store."""


@runtime_checkable
class SecretStore(Protocol):
    """Abstract secret store. Backends: macOS Keychain, Linux Secret Service, in-memory."""

    def get(self, service: str, account: str) -> str: ...
    def set(self, service: str, account: str, value: str) -> None: ...
    def delete(self, service: str, account: str) -> None: ...


class InMemorySecretStore:
    """In-memory backend. For tests and ephemeral use only — NOT for production."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get(self, service: str, account: str) -> str:
        try:
            return self._store[(service, account)]
        except KeyError:
            raise SecretNotFound(f"No secret for service={service!r} account={account!r}")

    def set(self, service: str, account: str, value: str) -> None:
        self._store[(service, account)] = value

    def delete(self, service: str, account: str) -> None:
        self._store.pop((service, account), None)


class KeyringSecretStore:
    """Real backend using the `keyring` library.

    On macOS uses Keychain. On Linux uses Secret Service (gnome-keyring / kwallet).
    """

    def get(self, service: str, account: str) -> str:
        value = keyring.get_password(service, account)
        if value is None:
            raise SecretNotFound(f"No secret for service={service!r} account={account!r}")
        return value

    def set(self, service: str, account: str, value: str) -> None:
        keyring.set_password(service, account, value)

    def delete(self, service: str, account: str) -> None:
        try:
            keyring.delete_password(service, account)
        except keyring.errors.PasswordDeleteError:
            pass  # idempotent
