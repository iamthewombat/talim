"""Tests for the credential vault and signer (WP-26)."""

from __future__ import annotations

import hmac
import hashlib

import pytest

from talim.security.vault import Vault, VaultError


def test_load_from_env_populates_public_and_secrets(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "pubkey-abc")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret-xyz")
    v = Vault.load_from_env(["binance"])
    assert v.has("binance")
    assert v.public("binance").api_key == "pubkey-abc"


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_API_SECRET", raising=False)
    with pytest.raises(VaultError):
        Vault.load_from_env(["bybit"])


def test_sign_is_deterministic_hmac_sha256(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "topsecret")
    v = Vault.load_from_env(["binance"])
    sig = v.sign("binance", "GET /orders timestamp=1")
    expected = hmac.new(
        b"topsecret", b"GET /orders timestamp=1", hashlib.sha256
    ).hexdigest()
    assert sig == expected
    # Idempotent — same input → same digest.
    assert v.sign("binance", "GET /orders timestamp=1") == sig


def test_no_public_secret_accessor():
    v = Vault()
    # The vault deliberately exposes no `get_secret` / no `__getitem__`.
    assert not hasattr(v, "get_secret")
    assert not hasattr(v, "__getitem__")
