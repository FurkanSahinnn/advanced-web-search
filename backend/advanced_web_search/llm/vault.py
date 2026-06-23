"""
Encrypted credential vault for cloud / self-hosted LLM API keys, plus the
non-secret runtime LLM overrides that the Settings UI can now edit.

Why this exists
---------------
Cloud API keys used to be readable ONLY from ``.env`` / the process environment.
This module lets the UI manage them instead, while keeping them encrypted at
rest: each key is sealed with AES-256-GCM under a key derived from a user
**master password** (PBKDF2-HMAC-SHA256). The master password is NEVER
persisted — the derived key lives only in process memory after an explicit
``unlock()`` and is dropped on ``lock()`` or process restart.

Graceful degradation (so nothing breaks for existing users):
  * No master password set  -> vault is "not configured"; cloud keys fall back
    to the environment exactly like before.
  * Configured but locked   -> the encrypted keys can't be read; we again fall
    back to the environment. The UI shows which providers HAVE a stored key
    (names are not secret) and offers an "unlock" prompt.
  * Unlocked                 -> the decrypted keys live in memory and take
    precedence over the environment.

Storage (all JSON rows in ``app_settings``; no schema change — stays additive):
  ``vault_meta``    -> {"v":1,"kdf":"pbkdf2-sha256","iterations":N,
                        "salt":b64,"verifier":{"n":b64,"ct":b64},
                        "providers":[<secret names with a stored key>]}
  ``vault_secrets`` -> {"<name>":{"n":b64,"ct":b64}, ...}  (ciphertext only)

Non-secret runtime overrides (plaintext ``app_settings``), editable in the UI:
  ``active_llm``      -> {"kind":"auto|cloud|ollama|custom","provider":<name?>}
  ``ollama_base_url`` -> str
  ``local_model``     -> str
  ``custom_endpoint`` -> {"base_url":str,"model":str}   (OpenAI-compatible)

Secrets are stored under provider names (``anthropic`` ... ``openrouter``) plus
the special name ``custom`` for the self-hosted endpoint's optional key.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Any

from ..config import get_settings

_log = logging.getLogger("advanced_web_search.vault")

# Provider name -> raw environment variable read as the fallback key. The order
# mirrors config.available_cloud_providers (preference order for auto-routing).
CLOUD_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

_KDF_ITERATIONS = 480_000  # OWASP-recommended floor for PBKDF2-HMAC-SHA256
_SALT_BYTES = 32           # 256-bit salt (above the 128-bit floor) for a persisted salt
_MIN_PASSWORD_LEN = 8      # minimum master-password length, enforced server-side
_VERIFY_CONST = b"advanced-web-search-vault-v1"
_CUSTOM = "custom"  # secret name for the self-hosted endpoint's API key

# In-memory unlock state (process-lifetime; never persisted). Guarded by a lock
# so a concurrent unlock/lock can't tear the cache.
_state_lock = threading.RLock()
_derived_key: bytes | None = None
_secrets_cache: dict[str, str] | None = None

# Throttle online password guessing: each consecutive wrong unlock adds an
# escalating delay (PBKDF2 already costs ~100ms; this raises the cost further).
# Reset to zero on a successful unlock. Strictly local, but cheap insurance.
_unlock_failures = 0
_MAX_UNLOCK_DELAY = 5.0


# --------------------------------------------------------------------------- #
# Low-level crypto (cryptography imported lazily so a missing wheel only breaks
# vault setup, never the whole app import).
# --------------------------------------------------------------------------- #

def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def _encrypt(key: bytes, plaintext: str) -> dict[str, str]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return {"n": _b64e(nonce), "ct": _b64e(ct)}


def _decrypt(key: bytes, blob: dict[str, str]) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    pt = AESGCM(key).decrypt(_b64d(blob["n"]), _b64d(blob["ct"]), None)
    return pt.decode("utf-8")


# --------------------------------------------------------------------------- #
# DB helpers (app_settings); repositories imported lazily to avoid DB-at-import.
# --------------------------------------------------------------------------- #

def _get(key: str) -> Any:
    try:
        from ..db import repositories

        return repositories.get_setting(key)
    except Exception:
        return None


def _put(key: str, value: Any) -> None:
    from ..db import repositories

    repositories.set_setting(key, value)


def _delete(key: str) -> None:
    try:
        from ..db import repositories

        repositories.delete_setting(key)
    except Exception:
        pass


def _meta() -> dict | None:
    m = _get("vault_meta")
    return m if isinstance(m, dict) else None


def _secrets_blob() -> dict:
    b = _get("vault_secrets")
    return b if isinstance(b, dict) else {}


# --------------------------------------------------------------------------- #
# Vault lifecycle
# --------------------------------------------------------------------------- #

def is_configured() -> bool:
    """True once a master password has been set (verifier present)."""
    m = _meta()
    return bool(m and m.get("verifier") and m.get("salt"))


def is_unlocked() -> bool:
    with _state_lock:
        return _derived_key is not None


def secret_names() -> list[str]:
    """Names of all stored secrets (incl. ``custom``), even while locked."""
    m = _meta()
    if not m:
        return []
    return [str(n) for n in (m.get("providers") or [])]


def cloud_providers_with_keys() -> list[str]:
    """Cloud provider names that have an encrypted key stored (not ``custom``)."""
    return [n for n in secret_names() if n in CLOUD_ENV]


def has_custom_key() -> bool:
    return _CUSTOM in secret_names()


def setup(master_password: str) -> dict:
    """Set the master password the first time. Auto-unlocks on success.

    Returns ``{"ok": bool, "error": str|None}``. Refuses if already configured
    or if the password is empty.
    """
    global _derived_key, _secrets_cache
    if len(master_password or "") < _MIN_PASSWORD_LEN:
        return {"ok": False, "error": f"password must be at least {_MIN_PASSWORD_LEN} characters"}
    if is_configured():
        return {"ok": False, "error": "vault already configured"}
    try:
        salt = os.urandom(_SALT_BYTES)
        key = _derive(master_password, salt, _KDF_ITERATIONS)
        verifier = _encrypt(key, _VERIFY_CONST.decode("latin-1"))
        _put(
            "vault_meta",
            {
                "v": 1,
                "kdf": "pbkdf2-sha256",
                "iterations": _KDF_ITERATIONS,
                "salt": _b64e(salt),
                "verifier": verifier,
                "providers": [],
            },
        )
        _put("vault_secrets", {})
        with _state_lock:
            _derived_key = key
            _secrets_cache = {}
        return {"ok": True, "error": None}
    except Exception as exc:  # e.g. cryptography not installed
        return {"ok": False, "error": str(exc) or exc.__class__.__name__}


def unlock(master_password: str) -> dict:
    """Verify the master password and load all secrets into memory."""
    global _derived_key, _secrets_cache, _unlock_failures
    m = _meta()
    if not m or not m.get("verifier") or not m.get("salt"):
        return {"ok": False, "error": "vault not configured"}

    def _fail() -> dict:
        # Escalating back-off slows online guessing (the server is local, but a
        # short password shouldn't be brute-forceable in seconds).
        global _unlock_failures
        _unlock_failures += 1
        time.sleep(min(_unlock_failures * 0.5, _MAX_UNLOCK_DELAY))
        return {"ok": False, "error": "wrong password"}

    try:
        key = _derive(master_password, _b64d(m["salt"]), int(m.get("iterations", _KDF_ITERATIONS)))
        # Verifies the password: a wrong key raises InvalidTag here.
        if _decrypt(key, m["verifier"]) != _VERIFY_CONST.decode("latin-1"):
            return _fail()
        cache: dict[str, str] = {}
        corrupt: list[str] = []
        for name, blob in _secrets_blob().items():
            try:
                cache[name] = _decrypt(key, blob)
            except Exception:
                # A single entry that fails authentication (tampered/corrupt
                # ciphertext) is skipped — but surfaced, never silently hidden.
                corrupt.append(name)
                _log.warning("vault: stored key %r failed to decrypt (corrupt/tampered)", name)
        with _state_lock:
            _derived_key = key
            _secrets_cache = cache
        _unlock_failures = 0
        out: dict = {"ok": True, "error": None}
        if corrupt:
            out["corrupt_entries"] = corrupt
        return out
    except Exception:
        # InvalidTag (wrong password) and any other failure look the same to
        # the caller — we never reveal which.
        return _fail()


def lock() -> None:
    """Drop the derived key + decrypted secrets from memory."""
    global _derived_key, _secrets_cache
    with _state_lock:
        _derived_key = None
        _secrets_cache = None


def change_password(old_password: str, new_password: str) -> dict:
    """Re-key the vault: verify old password, re-encrypt everything under new."""
    global _derived_key, _secrets_cache
    if not new_password:
        return {"ok": False, "error": "empty new password"}
    res = unlock(old_password)
    if not res["ok"]:
        return res
    try:
        with _state_lock:
            secrets = dict(_secrets_cache or {})
        salt = os.urandom(_SALT_BYTES)
        key = _derive(new_password, salt, _KDF_ITERATIONS)
        new_blob = {name: _encrypt(key, val) for name, val in secrets.items()}
        _put(
            "vault_meta",
            {
                "v": 1,
                "kdf": "pbkdf2-sha256",
                "iterations": _KDF_ITERATIONS,
                "salt": _b64e(salt),
                "verifier": _encrypt(key, _VERIFY_CONST.decode("latin-1")),
                "providers": list(secrets.keys()),
            },
        )
        _put("vault_secrets", new_blob)
        with _state_lock:
            _derived_key = key
            _secrets_cache = secrets
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc) or exc.__class__.__name__}


def reset() -> None:
    """Forgot-password escape hatch: wipe the vault and every stored key."""
    global _unlock_failures
    _delete("vault_meta")
    _delete("vault_secrets")
    _unlock_failures = 0
    lock()


# --------------------------------------------------------------------------- #
# Key management (require an unlocked vault)
# --------------------------------------------------------------------------- #

def set_key(name: str, value: str) -> dict:
    """Encrypt + store a secret under ``name`` (a provider name or ``custom``)."""
    global _secrets_cache
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "missing name"}
    if not value:
        return {"ok": False, "error": "empty key"}
    with _state_lock:
        key = _derived_key
    if key is None:
        return {"ok": False, "error": "vault locked"}
    try:
        blob = _secrets_blob()
        blob[name] = _encrypt(key, value)
        _put("vault_secrets", blob)
        m = _meta() or {}
        names = [n for n in (m.get("providers") or []) if n != name] + [name]
        m["providers"] = names
        _put("vault_meta", m)
        with _state_lock:
            if _secrets_cache is None:
                _secrets_cache = {}
            _secrets_cache[name] = value
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc) or exc.__class__.__name__}


def delete_key(name: str) -> dict:
    """Remove a stored secret. Allowed only while unlocked (UI manages keys)."""
    global _secrets_cache
    if not is_unlocked():
        return {"ok": False, "error": "vault locked"}
    try:
        blob = _secrets_blob()
        blob.pop(name, None)
        _put("vault_secrets", blob)
        m = _meta() or {}
        m["providers"] = [n for n in (m.get("providers") or []) if n != name]
        _put("vault_meta", m)
        with _state_lock:
            if _secrets_cache is not None:
                _secrets_cache.pop(name, None)
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc) or exc.__class__.__name__}


def _cache_get(name: str) -> str | None:
    with _state_lock:
        if _secrets_cache is None:
            return None
        return _secrets_cache.get(name)


# --------------------------------------------------------------------------- #
# Effective key resolution (vault-unlocked  >  environment)
# --------------------------------------------------------------------------- #

def effective_cloud_key(provider: str) -> str | None:
    """The key actually usable for a cloud provider right now (vault > env)."""
    val = _cache_get(provider)
    if val:
        return val
    env = CLOUD_ENV.get(provider)
    return os.getenv(env) if env else None


def effective_custom_key() -> str | None:
    """The self-hosted endpoint's key (vault only; never read from env)."""
    return _cache_get(_CUSTOM)


def available_cloud_providers() -> list[str]:
    """Cloud providers usable right now (vault key if unlocked, else env)."""
    return [name for name in CLOUD_ENV if effective_cloud_key(name)]


def _last4(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    return s[-4:] if len(s) >= 4 else "••••"


def key_status(provider: str) -> dict:
    """Non-secret status for a cloud provider's key, for the UI.

    Returns ``{"key_set":bool,"key_source":"vault"|"env"|None,"key_hint":last4}``.
    The hint (last 4 chars) is only ever derived from a key we can already read
    in cleartext (an env key, or a vault key while unlocked) — never from
    ciphertext, so a locked vault reveals nothing but the fact a key exists.
    """
    if provider in secret_names():
        return {
            "key_set": True,
            "key_source": "vault",
            "key_hint": _last4(_cache_get(provider)),  # None while locked
        }
    env = CLOUD_ENV.get(provider)
    env_val = os.getenv(env) if env else None
    if env_val:
        return {"key_set": True, "key_source": "env", "key_hint": _last4(env_val)}
    return {"key_set": False, "key_source": None, "key_hint": None}


# --------------------------------------------------------------------------- #
# Non-secret runtime overrides (active selection, endpoints) — DB > env default
# --------------------------------------------------------------------------- #

def current_active_llm() -> dict:
    a = _get("active_llm")
    if isinstance(a, dict) and a.get("kind") in {"auto", "cloud", "ollama", "custom"}:
        return a
    return {"kind": "auto", "provider": None}


def set_active_llm(kind: str, provider: str | None = None) -> None:
    kind = kind if kind in {"auto", "cloud", "ollama", "custom"} else "auto"
    _put("active_llm", {"kind": kind, "provider": provider})


def current_ollama_base_url() -> str:
    v = _get("ollama_base_url")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return get_settings().ollama_base_url


def set_ollama_base_url(url: str) -> None:
    _put("ollama_base_url", (url or "").strip())


def current_local_model() -> str | None:
    v = _get("local_model")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return get_settings().local_model


def set_local_model(model: str | None) -> None:
    _put("local_model", (model or "").strip() or None)


def current_custom_endpoint() -> dict:
    e = _get("custom_endpoint")
    if isinstance(e, dict):
        return {"base_url": e.get("base_url") or "", "model": e.get("model") or ""}
    return {"base_url": "", "model": ""}


def set_custom_endpoint(base_url: str | None, model: str | None) -> None:
    _put(
        "custom_endpoint",
        {"base_url": (base_url or "").strip(), "model": (model or "").strip()},
    )
