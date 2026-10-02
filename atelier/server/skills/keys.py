"""密钥存储：**只写不回传**（PRD F-C9 / F-I4）。

后端优先级：
1. 系统 keychain（macOS Keychain / Windows DPAPI / Linux libsecret），经 ``keyring``
2. 降级 ``var/secrets.enc``（AES-GCM，主密钥取 ``ATELIER_MASTER_KEY``）

三条硬规则：
- **只写不回传**：任何对外结构只给 ``sk-****3f7a`` 形式掩码，明文永不出本模块
- **留空不覆盖**：``set_secret(key, "")`` 保持原值不变（由调用方返回 ``unchanged: true``）
- **不落日志**：本模块不打印、不记录明文
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from atelier.server import paths

log = logging.getLogger("atelier.skills.keys")

KEYCHAIN_SERVICE = "Atelier"
SECRETS_FILE = "secrets.enc"
MASTER_KEY_ENV = "ATELIER_MASTER_KEY"
LOCAL_KEY_FILE = "secrets.key"


def mask_secret(value: str | None) -> str:
    """``sk-abc…3f7a`` → ``sk-****3f7a``。结果永不含完整明文。"""
    if not value:
        return ""
    v = value.strip()
    if not v:
        return ""
    tail = v[-4:]
    return f"{v[:3]}****{tail}" if len(v) > 10 else f"****{tail}"


@dataclass(frozen=True)
class SecretInfo:
    key_name: str
    masked: str
    source: str  # env | keychain | file
    platform: str | None = None
    updated_at: float | None = None

    def to_dict(self) -> dict:
        """对外结构：**只含掩码**，永不含明文。"""
        return {
            "key_name": self.key_name,
            "masked": self.masked,
            "source": self.source,
            "platform": self.platform,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------- 后端探测


def keyring_backend():
    try:
        import keyring
    except ImportError:
        return None
    try:
        keyring.get_keyring()
    except Exception as e:  # noqa: BLE001 — 无可用后端则降级
        log.warning("keyring backend unavailable, falling back to encrypted file: %s", e)
        return None
    return keyring


def secrets_path() -> Path:
    return paths.resolve_inside(paths.VAR, SECRETS_FILE)


def _master_key() -> bytes:
    """取主密钥：``ATELIER_MASTER_KEY`` → 派生 32 字节；未设置则本机生成并落 0600。"""
    env = os.environ.get(MASTER_KEY_ENV, "").strip()
    if env:
        # AES-GCM 只接受 128/192/256 bit，任意长度口令统一用 SHA-256 派生 256 bit
        return hashlib.sha256(env.encode("utf-8")).digest()
    kp = paths.resolve_inside(paths.VAR, LOCAL_KEY_FILE)
    if kp.exists():
        raw = kp.read_bytes()
        if len(raw) in (16, 24, 32):
            return raw
        return hashlib.sha256(raw).digest()
    log.warning(
        "%s 未设置，已在 %s 生成本机主密钥（仅本机有效，多机同步需显式设置该环境变量）",
        MASTER_KEY_ENV, kp,
    )
    key = os.urandom(32)
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_bytes(key)
    try:
        kp.chmod(0o600)
    except OSError as e:  # pragma: no cover — 某些文件系统不支持
        log.warning("chmod 0600 failed on %s: %s", kp, e)
    return key


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "缺少 cryptography，无法降级存储密钥。请安装：pip install cryptography"
        ) from e
    return AESGCM(_master_key())


def _read_file() -> dict:
    p = secrets_path()
    if not p.exists():
        return {"v": 1, "entries": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("secrets.enc unreadable: %s", e)
        return {"v": 1, "entries": {}}
    raw.setdefault("entries", {})
    return raw


def _write_file(data: dict) -> None:
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError as e:  # pragma: no cover
        log.warning("chmod 0600 failed on %s: %s", p, e)


# ---------------------------------------------------------------- 读写


def _pack(value: str, platform: str | None) -> str:
    return json.dumps(
        {"value": value, "platform": platform, "updated_at": time.time()}, ensure_ascii=False
    )


def _unpack(blob: str) -> tuple[str, str | None, float | None]:
    try:
        d = json.loads(blob)
        return str(d.get("value", "")), d.get("platform"), d.get("updated_at")
    except (json.JSONDecodeError, AttributeError):
        return blob, None, None


def get_secret(key_name: str) -> str | None:
    """按 env → keychain → 加密文件 顺序取值。返回明文，**仅供服务端内部使用**。"""
    env = os.environ.get(key_name, "").strip()
    if env:
        return env
    kr = keyring_backend()
    if kr is not None:
        try:
            blob = kr.get_password(KEYCHAIN_SERVICE, key_name)
        except Exception as e:  # noqa: BLE001
            log.error("keychain read failed for %s: %s", key_name, e)
            blob = None
        if blob:
            return _unpack(blob)[0]
    entry = _read_file()["entries"].get(key_name)
    if not entry:
        return None
    try:
        pt = _aesgcm().decrypt(base64.b64decode(entry["nonce"]), base64.b64decode(entry["ct"]), None)
        return _unpack(pt.decode())[0]
    except Exception as e:  # noqa: BLE001
        log.error("secrets.enc decrypt failed for %s: %s", key_name, e)
        return None


def set_secret(key_name: str, value: str, platform: str | None = None) -> SecretInfo:
    """写入密钥。**返回值只含掩码**。空值不在这里判断（由调用方判 unchanged）。"""
    if not value or not value.strip():
        raise ValueError("set_secret 不接受空值，留空不覆盖由调用方处理")
    kr = keyring_backend()
    backend = "keychain"
    if kr is not None:
        try:
            kr.set_password(KEYCHAIN_SERVICE, key_name, _pack(value, platform))
        except Exception as e:  # noqa: BLE001 — keychain 不可用则降级
            log.warning("keychain write failed for %s, falling back to file: %s", key_name, e)
            kr = None
    if kr is None:
        backend = "file"
        nonce = os.urandom(12)
        ct = _aesgcm().encrypt(nonce, _pack(value, platform).encode(), None)
        data = _read_file()
        data["entries"][key_name] = {
            "nonce": base64.b64encode(nonce).decode(),
            "ct": base64.b64encode(ct).decode(),
            "platform": platform,
            "updated_at": time.time(),
        }
        _write_file(data)
    log.info("secret stored: %s (backend=%s, mask=%s)", key_name, backend, mask_secret(value))
    return SecretInfo(
        key_name=key_name, masked=mask_secret(value), source=backend, platform=platform, updated_at=time.time()
    )


def delete_secret(key_name: str) -> bool:
    removed = False
    kr = keyring_backend()
    if kr is not None:
        try:
            kr.delete_password(KEYCHAIN_SERVICE, key_name)
            removed = True
        except Exception as e:  # noqa: BLE001 — 不存在也算成功
            log.debug("keychain delete %s: %s", key_name, e)
    data = _read_file()
    if data["entries"].pop(key_name, None) is not None:
        _write_file(data)
        removed = True
    return removed


def list_secrets(extra_keys: set[str] | None = None) -> list[SecretInfo]:
    """列出已配置密钥，**只给掩码**。含 env 提供的与技能声明需要的（``extra_keys``）。"""
    out: dict[str, SecretInfo] = {}
    wanted: set[str] = set(extra_keys or ())
    wanted.update(_read_file()["entries"])
    kr = keyring_backend()
    if kr is not None:
        try:
            for name in wanted:
                blob = kr.get_password(KEYCHAIN_SERVICE, name)
                if blob:
                    value, platform, updated = _unpack(blob)
                    out[name] = SecretInfo(name, mask_secret(value), "keychain", platform, updated)
        except Exception as e:  # noqa: BLE001
            log.error("keychain enumerate failed: %s", e)
    for name in wanted:
        if name in out:
            continue
        if os.environ.get(name, "").strip():
            out[name] = SecretInfo(name, mask_secret(os.environ[name]), "env", None, None)
            continue
        entry = _read_file()["entries"].get(name)
        if not entry:
            continue
        try:
            pt = _aesgcm().decrypt(base64.b64decode(entry["nonce"]), base64.b64decode(entry["ct"]), None)
            value, _p, updated = _unpack(pt.decode())
            out[name] = SecretInfo(name, mask_secret(value), "file", entry.get("platform"), updated)
        except Exception as e:  # noqa: BLE001
            log.error("secrets.enc decrypt failed for %s: %s", name, e)
    return sorted(out.values(), key=lambda s: s.key_name)


def missing_keys(required: list[str]) -> list[str]:
    """返回 ``required`` 中尚未配置的密钥名。"""
    return [k for k in required if not get_secret(k)]
