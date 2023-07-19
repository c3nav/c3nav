#!/usr/bin/env bash
set -e

cd /app
# enable python virtual env
. /app/env/bin/activate

case "$1" in
web)
  exec /app/env/bin/uwsgi --master \
    --wsgi "c3nav.wsgi" \
    --pythonpath "/app/src" \
    --enable-threads --ignore-sigpipe --disable-logging --need-app \
    --stats ":5000" \
    --http "0.0.0.0:8000"
  ;;
webstatic)
  exec /app/env/bin/uwsgi --master \
    --wsgi "c3nav.wsgi" \
    --pythonpath "/app/src" \
    --enable-threads --ignore-sigpipe --disable-logging --need-app \
    --static-map "${C3NAV_STATIC_URL:-/static}=${C3NAV_STATIC_ROOT:-/app/c3nav/static.dist}" \
    --static-safe "/app/c3nav/static" \
    --stats ":5000" \
    --http "0.0.0.0:8000"
  ;;
web-async)
  exec python -m uvicorn --host 0.0.0.0 --proxy-headers --no-server-header  ${*:2} c3nav.asgi:application
  ;;
webstatic-async)
  exec python -m uvicorn --host 0.0.0.0 --proxy-headers --no-server-header ${*:2} c3nav.asgi:static_app
  ;;
worker)
  exec celery -A c3nav worker --max-tasks-per-child 300 --concurrency 2 -l INFO -E
  ;;
beat)
  exec celery -A c3nav beat -l INFO
  ;;
manage)
  exec python manage.py ${*:2}
  ;;
migrate)
  exec python manage.py migrate ${*:2}
  ;;
python)
  exec python ${*:2}
  ;;
celery)
  exec celery -A c3nav ${*:2}
  ;;
**)
  exec bash -ec "$@"
esac
