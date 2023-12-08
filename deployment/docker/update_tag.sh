#!/usr/bin/env bash

sed -i "s/C3NAV_TAG=.*/C3NAV_TAG=$(git rev-parse HEAD)/g" .env
