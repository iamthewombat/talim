FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir requests>=2.32

COPY nanoclaw ./nanoclaw

# Stub keepalive — real NanoClaw is a separate codebase.
CMD ["python", "-c", "import time; print('nanoclaw stub up'); time.sleep(10**9)"]
