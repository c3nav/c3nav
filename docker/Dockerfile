# syntax=docker/dockerfile:1.4
FROM ubuntu:lunar as base
ENV DEBIAN_FRONTEND noninteractive

RUN --mount=type=cache,target=/var/cache/apt --mount=type=tmpfs,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.11=3.11.2-6ubuntu0.1 \
    # renovate: srcname=python3.11
    libpython3.11=3.11.2-6ubuntu0.1 \
    # renovate: srcname=python3.11
    python3.11-venv=3.11.2-6ubuntu0.1 \
    # renovate: srcname=python-pip
    python3-pip=23.0.1+dfsg-1 \
    # renovate: srcname=postgresql-15
    libpq5=15.3-0ubuntu0.23.04.1 \
    # renovate: srcname=postgresql-15
    postgresql-client-15=15.3-0ubuntu0.23.04.1 \
    curl=7.88.1-8ubuntu2 \
    libpcre3=2:8.39-15 \
    # renovate: srcname=librsvg
    librsvg2-2=2.54.5+dfsg-1ubuntu2 \
    # renovate: srcname=librsvg
    gir1.2-rsvg-2.0=2.54.5+dfsg-1ubuntu2 \
    libgirepository-1.0-1=1.76.1-1 \
    tzdata=2023c-2exp1ubuntu1.1 \
    ca-certificates=20230311ubuntu0.23.04.1
ENV PATH="/usr/lib/postgresql/14/bin/:$PATH"


FROM base as builder
RUN --mount=type=cache,target=/var/cache/apt --mount=type=tmpfs,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.9ubuntu3 \
    # renovate: srcname=python3.11
    python3.11-dev=3.11.2-6ubuntu0.1 \
    libpcre3-dev=2:8.39-15 \
    # renovate: srcname=postgresql-15
    libpq-dev=15.3-0ubuntu0.23.04.1 \
    libgirepository1.0-dev=1.76.1-1


COPY --link /src /app
WORKDIR /app

RUN --mount=type=cache,target=/pip-cache \
    python3.11 -m venv env && \
    . /app/env/bin/activate && \
    pip install --cache-dir /pip-cache --upgrade pip wheel && \
    pip install --cache-dir /pip-cache \
    -r requirements/production.txt \
    -r requirements/htmlmin.txt \
    -r requirements/postgres.txt \
    -r requirements/redis.txt \
    -r requirements/rsvg.txt \
    -r requirements/server-asgi.txt && \
    pip install --cache-dir /pip-cache uwsgi

FROM base as final
RUN groupadd -r -g 500 c3nav && useradd -r -u 500 -g 500 -G www-data c3nav
RUN mkdir /data && chown -R c3nav:c3nav /data
VOLUME /data

COPY --link --chown=500:500 /src /app
COPY --from=builder --chown=500:500 /app/env /app/env
COPY --chown=root:root --chmod=0755 /docker/entrypoint.sh /usr/bin/entrypoint

ENV C3NAV_DEBUG="" \
    C3NAV_LOGLEVEL="info" \
    C3NAV_DATA_DIR="/data" \
    MPLBACKEND="agg" \
    UWSGI_WORKERS="8"

USER c3nav
WORKDIR /app

RUN /app/env/bin/python manage.py collectstatic -l --no-input && \
    /app/env/bin/python manage.py compress && \
    rm -r /data/*

EXPOSE 8000 5000
#HEALTHCHECK --start-period=5s --interval=10s --timeout=1s CMD curl -f http://localhost:8000/check || exit 1
ENTRYPOINT ["/usr/bin/entrypoint"]
CMD ["web"]
