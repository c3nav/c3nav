#!/usr/bin/env bash
bash -c 'source .env && docker compose exec -T postgres psql $C3NAV_DATABASE_NAME -U postgres'
