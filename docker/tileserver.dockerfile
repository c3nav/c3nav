# syntax=docker/dockerfile:1.15@sha256:05e0ad437efefcf144bfbf9d7f728c17818408e6d01432d9e264ef958bbd52f3
FROM ubuntu:noble-20250404@sha256:1e622c5f073b4f6bfad6632f2616c7f59ef256e96fe78bf6a595d1dc4376ac02 as base
ARG BASE_IMAGE_NAME=ubuntu:noble-20250404
ARG BASE_IMAGE_DIGEST=sha256:1e622c5f073b4f6bfad6632f2616c7f59ef256e96fe78bf6a595d1dc4376ac02
ARG TARGETARCH

LABEL org.opencontainers.image.base.name="docker.io/library/$BASE_IMAGE_NAME" \
      org.opencontainers.image.base.digest="$BASE_IMAGE_DIGEST" \
      org.opencontainers.image.source="https://github.com/c3nav/c3nav" \
      org.opencontainers.image.url="https://c3nav.de" \
      org.opencontainers.image.authors="c3nav team"

ENV DEBIAN_FRONTEND noninteractive

RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    rm /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.12=3.12.3-1ubuntu0.5 \
    # renovate: srcname=python3.12
    libpython3.12=3.12.3-1ubuntu0.5 \
    # renovate: srcname=python3.12
    python3.12-venv=3.12.3-1ubuntu0.5 \
    # renovate: srcname=python-pip
    python3-pip=24.0+dfsg-1ubuntu1.1 \
    curl=8.5.0-2ubuntu10.6 \
    # renovate: srcname=pcre3
    libpcre3=2:8.39-15build1 \
    # renovate: srcname=libmemcached
    libmemcached11t64=1.1.4-1.1build3 \
    tzdata=2025b-0ubuntu0.24.04 \
    ca-certificates=20240203 \
    # renovate: srcname=libzstd
    zstd=1.5.5+dfsg2-2build1.1


FROM base as builder
RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.10ubuntu1 \
    # renovate: srcname=python3.12
    python3.12-dev=3.12.3-1ubuntu0.5 \
    libpcre3-dev=2:8.39-15build1 \
    # renovate: srcname=libmemcached
    libmemcached-dev=1.1.4-1.1build3


RUN mkdir /app
WORKDIR /app

RUN --mount=type=cache,target=/pip-cache \
    --mount=type=bind,source=/src/requirements-tileserver.txt,target=/app/requirements-tileserver.txt \
    python3.12 -m venv env && \
    . /app/env/bin/activate && \
    pip install --cache-dir /pip-cache --upgrade pip wheel && \
    pip install --cache-dir /pip-cache -r requirements-tileserver.txt && \
    pip install --cache-dir /pip-cache uwsgi

FROM base as final
ARG COMMIT
RUN groupadd -r -g 500 c3nav && useradd -r -u 500 -g 500 -G www-data c3nav
RUN mkdir /data && chown -R c3nav:c3nav /data
VOLUME /data

COPY --link --chown=500:500 /src /app
COPY --from=builder --chown=500:500 /app/env /app/env

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
CMD ["/app/env/bin/uwsgi", "--master", \
     "--wsgi", "c3nav.tileserver.wsgi", \
     "--pythonpath", "/app/src", \
     "--enable-threads", "--ignore-sigpipe", "--disable-logging", "--need-app", \
     "--stats", ":5000", "--stats-http", \
     "--http", "0.0.0.0:8000"]
