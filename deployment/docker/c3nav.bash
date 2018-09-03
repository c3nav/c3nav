#!/bin/bash
#set -e

cd /opt/c3nav/src
export DATA_DIR=/data/

if [ -z "$@" ]; then
  echo "run manage.py"
  python3 /opt/c3nav/src/manage.py migrate
  rm -rf /opt/c3nav/src/c3nav/static.dist
  python3 /opt/c3nav/src/manage.py collectstatic
  python3 /opt/c3nav/src/manage.py compress
  echo "start celery"
  /usr/local/bin/celery multi start w1 w2 -A c3nav --pidfile=/var/run/c3nav/celery.pid --logfile=/var/log/c3nav/celery.log --loglevel=WARNING --concurrency=2 --beat &
  echo "start gunicorn"
  /usr/local/bin/gunicorn --workers 8 --bind unix:/var/run/c3nav/gunicorn-c3nav.sock c3nav.wsgi:application --log-level warning --access-logfile /dev/null &
  echo "start nginx"
  nginx -g "daemon off;"
else
  exec "$@"
fi
