#!/bin/bash
set -e

cd /c3nav/src
export DATA_DIR=/data/
NUM_WORKERS=10

if [ ! -d /data/logs ]; then
    mkdir /data/logs;
fi

ls /data/map

python manage.py migrate --noinput

if [ "$1" == "webworker" ]; then
    exec gunicorn c3nav.wsgi \
        --name c3nav \
        --workers $NUM_WORKERS \
        --max-requests 1200 \
        --max-requests-jitter 50 \
        --log-level=info \
        --bind=unix:/tmp/c3nav.sock
fi

if [ "$1" == "taskworker" ]; then
    export C_FORCE_ROOT=True
    exec celery -A c3nav worker -l info
fi

if [ "$1" == "loadmap" ]; then
    echo ""
    echo "### loading map..."
    exec python manage.py loadmap -y
fi

if [ "$1" == "checkmap" ]; then
    echo ""
    echo "### checking map..."
    exec python manage.py checkmap
fi

if [ "$1" == "editor" ]; then
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

    echo ""
    echo "### chowning /data/…"
    USER_ID=${LOCAL_USER_ID:-9001}
    exec chown -R $USER_ID $DATA_DIR
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
    USER_ID=${LOCAL_USER_ID:-9001}
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

echo "Specify argument: webworker|taskworker|loadmap|checkmap|editor|build|all"
exit 1
