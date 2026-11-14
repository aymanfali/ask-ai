from __future__ import annotations

import hashlib
import hmac

from ask_ai.core.config import Settings


def derive_application_key(settings: Settings, purpose: str) -> bytes:
    """Derive a purpose-specific key from SECRET_KEY using HMAC-SHA256.

    Domain separation prevents the JWT signer, OAuth session cookie signer, and
    CSRF token signer from sharing the same effective signing key.
    """
    master = settings.secret_key.get_secret_value().encode("utf-8")
    context = f"ask-ai:{purpose}:v1".encode("ascii")
    return hmac.new(master, context, hashlib.sha256).digest()
