#!/usr/bin/env bash
set -e

if [[ -z "$1" ]]; then
  echo "usage:"
  echo "$0 [databasename]"
  exit 1
fi
database="$1"

echo "Fetching database ${database} from production and loading it into the docker compose deployment"
PG_CLUSTER_PRIMARY_POD=$(kubectl -n c3nav get pod -o name -l postgres-operator.crunchydata.com/cluster=c3nav,postgres-operator.crunchydata.com/role=master)
kubectl exec -n c3nav ${PG_CLUSTER_PRIMARY_POD} --container database -- pg_dump -U postgres -n public -c -O -x "${database}" | \
docker exec -i c3nav-postgres-1 psql -U postgres "${database}"
