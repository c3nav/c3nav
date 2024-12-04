# syntax=docker/dockerfile:1.6@sha256:ac85f380a63b13dfcefa89046420e1781752bab202122f8f50032edf31be0021
FROM ubuntu:noble-20241118.1@sha256:80dd3c3b9c6cecb9f1667e9290b3bc61b78c2678c02cbdae5f0fea92cc6734ab as base
ARG BASE_IMAGE_NAME=ubuntu:noble-20241118.1
ARG BASE_IMAGE_DIGEST=sha256:80dd3c3b9c6cecb9f1667e9290b3bc61b78c2678c02cbdae5f0fea92cc6734ab
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
    python3.12=3.12.3-1ubuntu0.3 \
    # renovate: srcname=python3.12
    libpython3.12=3.12.3-1ubuntu0.3 \
    # renovate: srcname=python3.12
    python3.12-venv=3.12.3-1ubuntu0.3 \
    # renovate: srcname=python-pip
    python3-pip=24.0+dfsg-1ubuntu1.1 \
    # renovate: srcname=postgresql-16
    libpq5=16.6-0ubuntu0.24.04.1 \
    # renovate: srcname=postgresql-16
    postgresql-client-16=16.6-0ubuntu0.24.04.1 \
    curl=8.5.0-2ubuntu10.5 \
    # renovate: srcname=pcre3
    libpcre3=2:8.39-15build1 \
    # renovate: srcname=librsvg
    librsvg2-2=2.58.0+dfsg-1build1 \
    # renovate: srcname=librsvg
    gir1.2-rsvg-2.0=2.58.0+dfsg-1build1 \
    # renovate: srcname=cairo
    libcairo2=1.18.0-3build1 \
    libgirepository-1.0-1=1.80.1-1 \
    # renovate: srcname=libmemcached
    libmemcached11t64=1.1.4-1.1build3 \
    gettext \
    tzdata=2024a-3ubuntu1.1 \
    ca-certificates=20240203 \
    zstd=1.5.5+dfsg2-2build1.1
ENV PATH="/usr/lib/postgresql/16/bin/:$PATH"


FROM base as builder
RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.10ubuntu1 \
    # renovate: srcname=python3.12
    python3.12-dev=3.12.3-1ubuntu0.3 \
    libpcre3-dev=2:8.39-15build1 \
    # renovate: srcname=postgresql-16
    libpq-dev=16.6-0ubuntu0.24.04.1 \
    # renovate: srcname=cairo
    libcairo2-dev=1.18.0-3build1 \
    libgirepository1.0-dev=1.80.1-1 \
    # renovate: srcname=libmemcached \
    libmemcached-dev=1.1.4-1.1build3


RUN mkdir /app
WORKDIR /app

RUN --mount=type=cache,target=/pip-cache \
    --mount=type=bind,source=/src/requirements,target=/app/requirements \
    python3.12 -m venv env && \
    . /app/env/bin/activate && \
    pip install --cache-dir /pip-cache --upgrade pip wheel && \
    pip install --cache-dir /pip-cache \
    -r requirements/production.txt \
    -r requirements/htmlmin.txt \
    -r requirements/postgres.txt \
    -r requirements/redis.txt \
    -r requirements/memcached.txt \
    -r requirements/rsvg-pygobject.txt \
    -r requirements/sentry.txt \
    -r requirements/metrics.txt \
    -r requirements/uwu.txt \
    -r requirements/sso.txt \
    -r requirements/server-asgi.txt && \
    pip install --cache-dir /pip-cache uwsgi django_extensions

FROM base as final
ARG COMMIT
RUN groupadd -r -g 500 c3nav && useradd -r -u 500 -g 500 -G www-data c3nav
RUN mkdir /data /etc/c3nav && chown -R c3nav:c3nav /data /etc/c3nav
VOLUME /data

COPY --link --chown=500:500 /src /app
COPY --from=builder --chown=500:500 /app/env /app/env
COPY --chown=root:root --chmod=0755 /docker/entrypoint.sh /usr/bin/entrypoint

ENV C3NAV_DEBUG="" \
    C3NAV_LOGLEVEL="INFO" \
    C3NAV_DATA_DIR="/data" \
    C3NAV_AUTOMIGRATE="yes" \
    C3NAV_VERSION="${COMMIT}" \
    MPLBACKEND="agg" \
    UWSGI_WORKERS="4" \
    PATH="/app/env/bin/:$PATH"

USER c3nav
WORKDIR /app

RUN /app/env/bin/python manage.py makemessages --ignore "site-packages" -l en_UW && \
    /app/env/bin/python genuwu.py && \
    /app/env/bin/python manage.py compilemessages --ignore "site-packages" && \
    /app/env/bin/python manage.py collectstatic -l --no-input && \
    /app/env/bin/python manage.py compress && \
    rm -r /data/*

EXPOSE 8000 5000
#HEALTHCHECK --start-period=5s --interval=10s --timeout=1s CMD curl -f http://localhost:8000/check || exit 1
ENTRYPOINT ["/usr/bin/entrypoint"]
CMD ["web"]
