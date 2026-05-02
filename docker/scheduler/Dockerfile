FROM debian:bookworm-slim
ARG SUPERCRONIC_VERSION=0.2.33
ARG TARGETARCH
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && arch="$TARGETARCH" \
    && case "$arch" in amd64) arch=amd64 ;; arm64) arch=arm64 ;; arm) arch=armv7 ;; *) echo "unsupported arch: $arch" >&2; exit 1 ;; esac \
    && curl -fsSL -o /usr/local/bin/supercronic "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${arch}" \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/local/bin/supercronic"]
