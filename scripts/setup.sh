#!/usr/bin/bash

# Symlink overrides
ln -s docker-compose.override.local.yml docker-compose.override.yml

# Check envars
./check_envvars.sh

# Rewrite .env
cp .env.example .env
sed -ri 's/^COMPOSE_FILE=(.*)/COMPOSE_FILE=\1:docker-compose.override.test.yml/g' .env
eval $(egrep "^[^#;]" .env | xargs -d'\n' -n1 | sed -E 's/(\w+)=(.*)/export \1='"'"'\2'"'"'/g')

# Pull, print images
docker compose pull
docker images

# Setup artifacts
mkdir -m 777 tests_artifacts

# Setup Compose and Django (without building since we are pulling everything)
docker compose up -d --no-build
docker compose exec app python manage.py makemigrations --check
docker compose exec app python manage.py collectstatic --noinput
