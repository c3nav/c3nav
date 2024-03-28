#!/usr/bin/env bash
set -e

cd /app
# enable python virtual env
. /app/env/bin/activate

# number of workers for guicorn, we coppy the value of UWSGI_WORKERS if it is not set
export WEB_CONCURRENCY="${WEB_CONCURRENCY:-$UWSGI_WORKERS}"

automigrate() {
  AUTOMIGRATE="${C3NAV_AUTOMIGRATE:no}"
  if [[ "$AUTOMIGRATE" == "yes" || "$AUTOMIGRATE" == "true" ]]; then
    echo "Running migrations as automigrate is enabled. Set \"C3NAV_AUTOMIGRATE\" to \"no\" or \"false\" to disable."
    python manage.py migrate
  fi
}

case "$1" in
web)
  automigrate
  exec /app/env/bin/uwsgi --master \
    --wsgi "c3nav.wsgi" \
    --pythonpath "/app/src" \
    --enable-threads --ignore-sigpipe --disable-logging --need-app \
    --stats ":5000" \
    --stats-http \
    --http "0.0.0.0:8000"
  ;;
webstatic)
  automigrate
  exec /app/env/bin/uwsgi --master \
    --wsgi "c3nav.wsgi" \
    --pythonpath "/app" \
    --enable-threads --ignore-sigpipe --disable-logging --need-app \
    --static-map "${C3NAV_STATIC_URL:-/static}=${C3NAV_STATIC_ROOT:-/app/c3nav/static.dist}" \
    --static-safe "/app/c3nav/static" \
    --stats ":5000" \
    --stats-http \
    --http "0.0.0.0:8000"
  ;;
web-async)
  automigrate
  exec daphne -b 0.0.0.0 -p 8000 --no-server-name ${*:2} c3nav.asgi:application
  ;;
webstatic-async)
  automigrate
  exec daphne -b 0.0.0.0 -p 8000 --no-server-name ${*:2} c3nav.asgi:static_app
  ;;
worker)
  exec celery -A c3nav worker --max-tasks-per-child 300 --concurrency 2 -l INFO -E
  ;;
worker_healthcheck)
  exec celery -A c3nav inspect ping -d "celery@${HOSTNAME}"
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
