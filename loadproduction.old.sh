#!/bin/sh
export C3NAV_CONFIG=/home/laura/Projekte/c3nav/data/c3nav.cfg
ssh root@34c3.c3nav.de "c3nav-manage 34c3 dumpdata mapdata --format json | gzip" | gunzip > production.json
python src/manage.py loaddata --app mapdata production.json
# rm production.json
