#!/usr/bin/env bash
bash -c 'source .env && docker compose exec postgres pg_dump $C3NAV_DATABASE_NAME -U postgres'
