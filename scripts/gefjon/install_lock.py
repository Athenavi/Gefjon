"""``data/install.lock`` 的加解密。

v2 格式（AES-256-GCM + scrypt）：

.. code-block:: json

    {
      "version": 2,
      "kdf": {"name": "scrypt", "n": 16384, "r": 8, "p": 1, "salt": "<base64>"},
      "cipher": "AES-256-GCM",
      "nonce": "<base64>",
      "dsn": "<base64>"
    }

与旧实现的区别：

* 密钥用 **scrypt** 派生，salt 每文件随机，而不是 ``HMAC(secret, 硬编码常量)``；
* 解密失败、格式未知、算法不认识时**抛异常**，绝不返回 None 让调用方静默回退；
* 不再依赖 ``base64.RawStdEncoding`` 的补位猜测，统一使用标准 base64。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import ConfigError

FORMAT_VERSION = 2
CIPHER_NAME = "AES-256-GCM"
KDF_NAME = "scrypt"

#: scrypt 参数（约 16 MiB 内存，适合配置文件解密场景）
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32
SALT_LENGTH = 16
NONCE_LENGTH = 12


@dataclass(frozen=True)
class KdfParams:
    n: int = SCRYPT_N
    r: int = SCRYPT_R
    p: int = SCRYPT_P

    def to_dict(self, salt: bytes) -> dict[str, Any]:
        return {
            "name": KDF_NAME,
            "n": self.n,
            "r": self.r,
            "p": self.p,
            "salt": _b64e(salt),
        }


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str, field: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"install.lock 的 {field} 不是合法 base64：{exc}") from exc


def derive_key(secret: str, salt: bytes, params: KdfParams) -> bytes:
    """用 scrypt 从 APP_SECRET 派生 AES-256 密钥。"""
    if not secret:
        raise ConfigError("APP_SECRET 为空，无法派生密钥")
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=params.n,
        r=params.r,
        p=params.p,
        dklen=KEY_LENGTH,
    )


def encrypt_dsn(dsn: str, secret: str, *, params: KdfParams | None = None) -> dict[str, Any]:
    """把 DSN 加密成 install.lock 的 payload（供配置向导使用）。"""
    params = params or KdfParams()
    salt = os.urandom(SALT_LENGTH)
    nonce = os.urandom(NONCE_LENGTH)
    key = derive_key(secret, salt, params)
    ciphertext = AESGCM(key).encrypt(nonce, dsn.encode("utf-8"), None)
    return {
        "version": FORMAT_VERSION,
        "kdf": params.to_dict(salt),
        "cipher": CIPHER_NAME,
        "nonce": _b64e(nonce),
        "dsn": _b64e(ciphertext),
    }


def decrypt_dsn(payload: dict[str, Any], secret: str) -> str:
    """解密 install.lock 的 payload。

    Raises:
        ConfigError: 格式、算法或 KDF 参数不受支持，或密文无法解密。
    """
    if not isinstance(payload, dict):
        raise ConfigError("install.lock 的内容必须是 JSON 对象")

    version = payload.get("version")
    if version != FORMAT_VERSION:
        raise ConfigError(
            f"install.lock 版本 {version!r} 不受支持（本版本只支持 {FORMAT_VERSION}）"
        )

    cipher = payload.get("cipher")
    if cipher != CIPHER_NAME:
        raise ConfigError(f"install.lock 使用了不支持的加密算法 {cipher!r}")

    kdf = payload.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("name") != KDF_NAME:
        raise ConfigError(f"install.lock 使用了不支持的密钥派生算法：{kdf!r}")

    try:
        params = KdfParams(n=int(kdf["n"]), r=int(kdf["r"]), p=int(kdf["p"]))
        salt = _b64d(str(kdf["salt"]), "kdf.salt")
        nonce = _b64d(str(payload["nonce"]), "nonce")
        ciphertext = _b64d(str(payload["dsn"]), "dsn")
    except KeyError as exc:
        raise ConfigError(f"install.lock 缺少必需字段：{exc}") from None

    key = derive_key(secret, salt, params)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception as exc:  # InvalidTag 等一律视为解密失败
        raise ConfigError(
            "install.lock 解密失败：APP_SECRET 不匹配或文件已损坏"
        ) from exc
    return plaintext.decode("utf-8")


def read_lock_file(path: Path) -> dict[str, Any]:
    """读取 install.lock 为 JSON 对象。"""
    if not path.exists():
        raise ConfigError(f"install.lock 不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"install.lock 不是合法 JSON：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取 install.lock：{exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("install.lock 的内容必须是 JSON 对象")
    return payload


def write_lock_file(path: Path, payload: dict[str, Any]) -> Path:
    """原子写入 install.lock（权限收紧到 0600）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path
