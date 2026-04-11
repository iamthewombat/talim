"""Stub NanoClaw — local intent router that decides whether to forward to Talim."""

from nanoclaw.router import classify_intent, route_message, Intent

__all__ = ["classify_intent", "route_message", "Intent"]
