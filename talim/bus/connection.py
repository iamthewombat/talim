"""Redis connection factory with retry logic."""

from __future__ import annotations

import os
import time

import redis


def get_redis_connection(
    url: str | None = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> redis.Redis:
    """Create a Redis connection with retry logic.

    Args:
        url: Redis URL. Defaults to REDIS_URL env var or redis://localhost:6379.
        max_retries: Number of connection attempts.
        retry_delay: Seconds between retries.

    Returns:
        A connected Redis client.
    """
    url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            client = redis.Redis.from_url(url, decode_responses=True)
            client.ping()
            return client
        except redis.ConnectionError as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    raise ConnectionError(
        f"Could not connect to Redis at {url} after {max_retries} attempts"
    ) from last_error
