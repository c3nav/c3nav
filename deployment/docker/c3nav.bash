#!/bin/bash
set -e

cd /c3nav/src
export DATA_DIR=/data/
NUM_WORKERS=10

if [ ! -d /data/logs ]; then
    mkdir /data/logs;
fi

ls /data/map

if [ "$1" == "webworker" ]; then
    while ! nc postgres 5432; do
        >&2 echo "Postgres is unavailable! waiting…"
        sleep 1
    done
    >&2 echo "Postgres is available! continuing…"

    while ! nc redis 6379; do
        >&2 echo "Redis is unavailable - sleeping"
        sleep 1
    done
    >&2 echo "Redis is available! continuing…"

    python manage.py migrate --noinput
    python manage.py loadmap -y
    mkdir -p /static.dist
    cp -r /c3nav/src/c3nav/static.dist/* /static.dist/

    exec gunicorn c3nav.wsgi \
        --name c3nav \
        --workers $NUM_WORKERS \
        --max-requests 1200 \
        --max-requests-jitter 50 \
        --log-level=info \
        --bind [::]:8000
fi

if [ "$1" == "taskworker" ]; then
    while ! nc postgres 5432; do
        >&2 echo "Postgres is unavailable! waiting…"
        sleep 1
    done
    >&2 echo "Postgres is available! continuing…"

    while ! nc redis 6379; do
        >&2 echo "Redis is unavailable - sleeping"
        sleep 1
    done
    >&2 echo "Redis is available! continuing…"

    export C_FORCE_ROOT=True
    exec celery -A c3nav worker -l info
fi

python manage.py migrate --noinput

if [ "$1" == "loadmap" ]; then
    echo ""
    echo "### loading map..."
    exec python manage.py loadmap -y
fi

if [ "$1" == "dumpmap" ]; then
    echo ""
    echo "### dumping map..."
    exec python manage.py dumpmap -y
fi

if [ "$1" == "check" ]; then
    echo ""
    echo "### checking map..."
    exec python manage.py checkmap
fi

if [ "$1" == "load_check" ]; then
    echo ""
    echo "### loading map..."
    python manage.py loadmap -y

    echo ""
    echo "### checking map..."
    exec python manage.py checkmap
fi

if [ "$1" == "runlocal" ]; then
    echo ""
    echo "### starting editor..."
    exec python manage.py runserver 0.0.0.0:8000
fi

if [ "$1" == "build" ]; then
    echo ""
    echo "### rendering map..."
    python manage.py rendermap

    echo ""
    echo "### building graph..."
    python manage.py buildgraph
fi

if [ "$1" == "load_build" ]; then
    echo ""
    echo "### loading map..."
    python manage.py loadmap -y

    echo ""
    echo "### rendering map..."
    python manage.py rendermap

    echo ""
    echo "### building graph..."
    python manage.py buildgraph

    echo ""
    echo "### chowning /data/…"
    USER_ID=${LOCAL_USER_ID:0}
    exec chown -R $USER_ID $DATA_DIR
fi

if [ "$1" == "all" ]; then
    echo ""
    echo "### loading map..."
    python manage.py loadmap -y

    echo ""
    echo "### rendering map..."
    python manage.py rendermap

    echo ""
    echo "### building graph..."
    python manage.py buildgraph

    echo ""
    echo "### running server..."
    exec python manage.py runserver 0.0.0.0:8000
fi

echo "Specify argument: webworker|taskworker|loadmap|dumpmap|check|load_check|runlocal|build|load_build|all"
exit 1
