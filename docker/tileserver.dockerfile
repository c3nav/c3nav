# syntax=docker/dockerfile:1.24@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
FROM ubuntu:26.04@sha256:f3d28607ddd78734bb7f71f117f3c6706c666b8b76cbff7c9ff6e5718d46ff64 AS base
ARG BASE_IMAGE_NAME=ubuntu:26.04
ARG BASE_IMAGE_DIGEST=sha256:f3d28607ddd78734bb7f71f117f3c6706c666b8b76cbff7c9ff6e5718d46ff64
ARG TARGETARCH

LABEL org.opencontainers.image.base.name="docker.io/library/$BASE_IMAGE_NAME" \
      org.opencontainers.image.base.digest="$BASE_IMAGE_DIGEST" \
      org.opencontainers.image.source="https://github.com/c3nav/c3nav" \
      org.opencontainers.image.url="https://c3nav.de" \
      org.opencontainers.image.authors="c3nav team"

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    rm /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.14=3.14.4-1 \
    # renovate: srcname=python3.14
    libpython3.14=3.14.4-1 \
    # renovate: srcname=python3.14
    python3.14-venv=3.14.4-1 \
    # renovate: srcname=python-pip
    python3-pip=25.1.1+dfsg-1ubuntu2 \
    curl=8.18.0-1ubuntu2.1 \
    # renovate: srcname=pcre2
    libpcre2-posix3=10.46-1build1 \
    # renovate: srcname=libmemcached
    libmemcached11t64=1.1.4-1.1build5 \
    tzdata=2026a-3ubuntu1 \
    ca-certificates=20260223 \
    # renovate: srcname=libzstd
    zstd=1.5.7+dfsg-3 \
    # renovate: srcname=libxcrypt
    libcrypt1=1:4.5.1-1


FROM base AS builder
RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.12ubuntu2 \
    # renovate: srcname=python3.14
    python3.14-dev=3.14.4-1 \
    libpcre2-dev=10.46-1build1 \
    # renovate: srcname=libmemcached
    libmemcached-dev=1.1.4-1.1build5 \
    # renovate: srcname=libxcrypt
    libcrypt-dev=1:4.5.1-1


# https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"

# https://github.com/astral-sh/uv-docker-example/blob/main/Dockerfile
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_DEV=1

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --only-group tileserver && \
    uv pip install uwsgi

COPY . /app
WORKDIR /app

FROM base AS final
ARG COMMIT
RUN groupadd -r -g 500 c3nav && useradd -r -u 500 -g 500 -G www-data c3nav
RUN mkdir /data && chown -R c3nav:c3nav /data
VOLUME /data

COPY --link --chown=500:500 /src /app
COPY --from=builder --chown=500:500 /app/.venv /app/.venv

ENV C3NAV_DEBUG="" \
    C3NAV_LOGLEVEL="INFO" \
    C3NAV_DATA_DIR="/data" \
    C3NAV_RELOAD_INTERVAL="60" \
    C3NAV_VERSION="${COMMIT}" \
    UWSGI_WORKERS="4"

# The following environment variables need to be set to start the tileserver
# C3NAV_UPSTREAM_BASE
# C3NAV_TILE_SECRET or C3NAV_TILE_SECRET_FILE
# C3NAV_MEMCACHED_SERVER
#
# This are additional optional variables
# C3NAV_LOGFILE
# C3NAV_HTTP_AUTH

USER c3nav
WORKDIR /app
EXPOSE 8000 5000
HEALTHCHECK --start-period=10s --interval=10s --timeout=1s CMD curl -f http://localhost:8000/health/ready || exit 1
CMD ["/app/.venv/bin/uwsgi", "--master", \
     "--wsgi", "c3nav.tileserver.wsgi", \
     "--pythonpath", "/app/src", \
     "--enable-threads", "--ignore-sigpipe", "--disable-logging", "--need-app", \
     "--stats", ":5000", "--stats-http", \
     "--http", "0.0.0.0:8000"]
