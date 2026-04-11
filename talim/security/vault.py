"""In-memory credential vault and HMAC signer (WP-26).

Architecture §6.5: exchange credentials should be loaded once at startup,
held in process memory, and only ever exposed through a `sign(payload)`
interface. Callers (e.g. `CcxtExchange`) never see the raw secret after
`load_from_env()` returns.

The vault is intentionally minimal — no rotation hooks, no remote KMS — but
the API is shaped so a future implementation can drop in without changing
call sites.
"""

from __future__ import annotations

import hmac
import hashlib
import os
from dataclasses import dataclass


class VaultError(RuntimeError):
    """Raised when the vault is misconfigured or queried for absent keys."""


@dataclass(frozen=True)
class PublicCredential:
    """The fields a caller is allowed to see — never includes the secret."""

    exchange: str
    api_key: str


class Vault:
    """Holds secrets in a private dict and signs payloads on demand."""

    def __init__(self) -> None:
        # The leading underscore is enforced by code review and by the lack of
        # any public accessor — no `get_secret`, no `__getitem__`.
        self._secrets: dict[str, bytes] = {}
        self._public: dict[str, PublicCredential] = {}

    @classmethod
    def load_from_env(cls, exchanges: list[str]) -> "Vault":
        """Load credentials for each named exchange from env vars.

        Looks for `<EXCHANGE>_API_KEY` / `<EXCHANGE>_API_SECRET` (matching
        the existing `load_credentials` convention). Missing keys raise
        VaultError immediately so the process fails closed at startup.
        """
        vault = cls()
        for ex in exchanges:
            prefix = ex.upper()
            api_key = os.environ.get(f"{prefix}_API_KEY")
            api_secret = os.environ.get(f"{prefix}_API_SECRET")
            if not api_key or not api_secret:
                raise VaultError(
                    f"missing credentials for {ex}: "
                    f"set {prefix}_API_KEY and {prefix}_API_SECRET"
                )
            vault._secrets[ex] = api_secret.encode("utf-8")
            vault._public[ex] = PublicCredential(exchange=ex, api_key=api_key)
        return vault

    def has(self, exchange: str) -> bool:
        return exchange in self._secrets

    def public(self, exchange: str) -> PublicCredential:
        if exchange not in self._public:
            raise VaultError(f"no credentials loaded for {exchange}")
        return self._public[exchange]

    def sign(self, exchange: str, payload: str | bytes) -> str:
        """Return a hex HMAC-SHA256 signature of `payload` using the secret.

        The raw secret never leaves this method — callers receive the digest.
        """
        if exchange not in self._secrets:
            raise VaultError(f"no credentials loaded for {exchange}")
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return hmac.new(
            self._secrets[exchange], payload, hashlib.sha256
        ).hexdigest()
