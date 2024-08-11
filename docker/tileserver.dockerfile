# syntax=docker/dockerfile:1.6@sha256:ac85f380a63b13dfcefa89046420e1781752bab202122f8f50032edf31be0021
FROM ubuntu:lunar-20231128@sha256:5a828e28de105c3d7821c4442f0f5d1c52dc16acf4999d5f31a3bc0f03f06edd as base
ARG BASE_IMAGE_NAME=ubuntu:lunar-20231128
ARG BASE_IMAGE_DIGEST=sha256:5a828e28de105c3d7821c4442f0f5d1c52dc16acf4999d5f31a3bc0f03f06edd
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
    python3.11=3.11.4-1~23.04.2 \
    # renovate: srcname=python3.11
    libpython3.11=3.11.4-1~23.04.2 \
    # renovate: srcname=python3.11
    python3.11-venv=3.11.4-1~23.04.2 \
    # renovate: srcname=python-pip
    python3-pip=23.0.1+dfsg-1ubuntu0.2 \
    curl=7.88.1-8ubuntu2.4 \
    libpcre3=2:8.39-15 \
    tzdata=2023d-0ubuntu0.23.04 \
    ca-certificates=20230311ubuntu0.23.04.1 \
    zstd=1.5.4+dfsg2-4


FROM base as builder
RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.9ubuntu3 \
    # renovate: srcname=python3.11
    python3.11-dev=3.11.4-1~23.04.2 \
    libpcre3-dev=2:8.39-15


RUN mkdir /app
WORKDIR /app

RUN --mount=type=cache,target=/pip-cache \
    --mount=type=bind,source=/src/requirements-tileserver.txt,target=/app/requirements-tileserver.txt \
    python3.11 -m venv env && \
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
