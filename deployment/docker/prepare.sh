#!/usr/bin/env bash
set -e

COMMIT="$(git rev-parse HEAD)"

echo "creating data directory"
mkdir -p data

echo "making sure there is a c3nav.cfg in the data dir"
touch data/c3nav.cfg

echo "changing permissions to match container permissions"
set -x
sudo chgrp -R 500 data
sudo chmod -R g+rwX data
set +x

if [[ ! -f .env ]]; then
  echo "copying example env file"
  cp example.env .env
fi
echo "updating tag"
sed -i "s/C3NAV_TAG=.*/C3NAV_TAG=${COMMIT}/g" .env

echo "DONE! You can now run \"docker compose up\" to start a test instance"
