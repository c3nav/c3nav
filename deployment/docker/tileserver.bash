#!/bin/bash
set -e

cd /opt/c3nav/src
export DATA_DIR=/data/


if [ -z "$@" ]; then
  export C3NAV_UPSTREAM_BASE=http://localhost/
  export C3NAV_TILE_SECRET_FILE=/opt/c3nav/data/.tile_secret
  export C3NAV_DATA_DIR=/opt/c3nav/tiledata

  nginx
  uwsgi --ini /etc/c3nav/c3nav-tiles.ini
else
  exec "$@"
fi
