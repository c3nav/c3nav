#!/bin/bash
set -e

cd /c3nav/src
export DATA_DIR=/data/
NUM_WORKERS=10

if [ ! -d /data/logs ]; then
    mkdir /data/logs;
fi
if [ ! -d /data/media ]; then
    mkdir /data/media;
fi

ls /data/map

python3 manage.py migrate --noinput
python3 manage.py loadmap -y

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

if [ "$1" == "checkmap" ]; then
    echo ""
    echo "### checking map..."
    exec python3 manage.py checkmap
fi

if [ "$1" == "editor" ]; then
    echo ""
    echo "### starting editor..."
    exec python3 manage.py runserver 0.0.0.0:8000
fi

if [ "$1" == "build" ]; then
    echo ""
    echo "### rendering map..."
    python3 manage.py rendermap

    echo ""
    echo "### building graph..."
    exec python3 manage.py buildgraph
fi

if [ "$1" == "all" ]; then
    echo ""
    echo "### rendering map..."
    python3 manage.py rendermap

    echo ""
    echo "### building graph..."
    python3 manage.py buildgraph

    echo ""
    echo "### running server..."
    exec python3 manage.py runserver 0.0.0.0:8000
fi

echo "Specify argument: webworker|taskworker|checkmap|editor|build|all"
exit 1
