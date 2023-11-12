#!/usr/bin/env bash
set -e

PROJDIR="$(dirname "$(dirname "$(readlink -f "$0")")")"
cd "$PROJDIR"
COMMIT="$(git rev-parse HEAD)"
docker buildx build -f docker/Dockerfile --load -t "ghcr.io/c3nav/c3nav:${COMMIT}" .
