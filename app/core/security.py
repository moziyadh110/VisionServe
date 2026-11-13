"""API key generation and hashing.

Keys look like vs_<prefix>_<secret>. The prefix (8 hex chars) is stored in plain
text so we can find the row quickly; the full key is stored only as a SHA-256 hash,
so a leaked database doesn't leak usable keys. A fast hash is fine here (unlike
passwords) because the secret is 256 random bits: brute-forcing it is hopeless.
"""

import hashlib
import secrets

KEY_TAG = "vs"
PREFIX_LEN = 8


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, key_hash). The full key is shown to the user once."""
    prefix = secrets.token_hex(PREFIX_LEN // 2)
    secret = secrets.token_urlsafe(32)
    key = f"{KEY_TAG}_{prefix}_{secret}"
    return key, prefix, hash_key(key)


def parse_prefix(key: str) -> str | None:
    """Extract the lookup prefix, or None if the key isn't shaped like ours."""
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_TAG or len(parts[1]) != PREFIX_LEN or not parts[2]:
        return None
    return parts[1]
