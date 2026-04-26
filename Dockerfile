FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install \
        "langgraph>=0.4" "langgraph-checkpoint-sqlite" \
        "langchain-core>=0.3" "pandas>=2.2" "numpy>=1.26" \
        "scikit-learn>=1.5" \
        "ccxt>=4.0" "redis>=5.0" \
        "fastapi>=0.115" "uvicorn>=0.34" \
        "discord.py>=2.4" "anthropic>=0.40" "httpx>=0.27" \
        "aiosqlite>=0.20" "pydantic>=2.9" "requests>=2.32" \
        "pyarrow>=17.0"

COPY talim ./talim
COPY strategies ./strategies
COPY config ./config
COPY scripts ./scripts

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/talim/health || exit 1

CMD ["uvicorn", "talim.api.bridge:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
