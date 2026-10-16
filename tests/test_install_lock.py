"""install.lock 的加解密与格式校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from gefjon.errors import ConfigError
from gefjon.install_lock import (
    KdfParams,
    decrypt_dsn,
    encrypt_dsn,
    read_lock_file,
    write_lock_file,
)


def test_roundtrip() -> None:
    payload = encrypt_dsn("postgresql://u:p@h:5432/db", "app-secret")
    assert decrypt_dsn(payload, "app-secret") == "postgresql://u:p@h:5432/db"


def test_roundtrip_uses_per_file_salt() -> None:
    first = encrypt_dsn("dsn", "secret")
    second = encrypt_dsn("dsn", "secret")
    assert first["kdf"]["salt"] != second["kdf"]["salt"]
    assert first["nonce"] != second["nonce"]


def test_wrong_secret_raises() -> None:
    payload = encrypt_dsn("dsn", "secret")
    with pytest.raises(ConfigError, match="解密失败"):
        decrypt_dsn(payload, "other")


def test_kdf_is_scrypt_with_random_salt() -> None:
    payload = encrypt_dsn("dsn", "secret")
    assert payload["kdf"]["name"] == "scrypt"
    assert payload["version"] == 2
    assert payload["cipher"] == "AES-256-GCM"
    # 不再使用硬编码常量作为 salt
    assert payload["kdf"]["salt"]


def test_unknown_version_rejected() -> None:
    payload = encrypt_dsn("dsn", "secret")
    payload["version"] = 1
    with pytest.raises(ConfigError, match="版本"):
        decrypt_dsn(payload, "secret")


def test_unknown_cipher_rejected() -> None:
    payload = encrypt_dsn("dsn", "secret")
    payload["cipher"] = "ROT13"
    with pytest.raises(ConfigError, match="加密算法"):
        decrypt_dsn(payload, "secret")


def test_unknown_kdf_rejected() -> None:
    payload = encrypt_dsn("dsn", "secret")
    payload["kdf"]["name"] = "hmac-sha256"
    with pytest.raises(ConfigError, match="密钥派生"):
        decrypt_dsn(payload, "secret")


def test_tampered_ciphertext_rejected() -> None:
    payload = encrypt_dsn("dsn", "secret")
    raw = payload["dsn"]
    payload["dsn"] = ("A" if raw[0] != "A" else "B") + raw[1:]
    with pytest.raises(ConfigError):
        decrypt_dsn(payload, "secret")


def test_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "data" / "install.lock"
    payload = encrypt_dsn("sqlite:///x.db", "secret", params=KdfParams(n=2**12))
    write_lock_file(path, payload)

    assert path.is_file()
    assert decrypt_dsn(read_lock_file(path), "secret") == "sqlite:///x.db"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="不存在"):
        read_lock_file(tmp_path / "nope.lock")


def test_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.lock"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="合法 JSON"):
        read_lock_file(path)
