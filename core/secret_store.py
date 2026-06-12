"""Encrypted local secret storage for Web console managed credentials."""
from __future__ import annotations

import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_SECRET_NAME_RE = re.compile(r"^[a-z0-9_.-]+$")


class EncryptedSecretStore:
    """Small Fernet-backed secret store scoped to the plugin data directory.

    This prevents plaintext API keys from landing in public config, logs, or API
    responses. The local master key is stored beside the encrypted payload, so
    this is at-rest hygiene rather than protection from full filesystem access.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._key_path = self._root / "master.key"

    def get_secret(self, name: str) -> str:
        path = self._secret_path(name)
        if not path.exists():
            return ""
        try:
            token = path.read_bytes()
            return self._fernet().decrypt(token).decode("utf-8")
        except (OSError, InvalidToken, UnicodeDecodeError):
            return ""

    def set_secret(self, name: str, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            self.delete_secret(name)
            return
        self._root.mkdir(parents=True, exist_ok=True)
        token = self._fernet().encrypt(cleaned.encode("utf-8"))
        path = self._secret_path(name)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(token)
        _chmod_private(tmp)
        tmp.replace(path)
        _chmod_private(path)

    def delete_secret(self, name: str) -> None:
        try:
            self._secret_path(name).unlink()
        except FileNotFoundError:
            return

    def has_secret(self, name: str) -> bool:
        return bool(self.get_secret(name))

    def masked_secret(self, name: str) -> str:
        return _mask(self.get_secret(name))

    def _fernet(self) -> Fernet:
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._key_path.exists():
            self._key_path.write_bytes(Fernet.generate_key())
            _chmod_private(self._key_path)
        return Fernet(self._key_path.read_bytes())

    def _secret_path(self, name: str) -> Path:
        if not _SECRET_NAME_RE.match(name):
            raise ValueError(f"invalid secret name: {name!r}")
        return self._root / f"{name}.secret"


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


__all__ = ["EncryptedSecretStore"]
