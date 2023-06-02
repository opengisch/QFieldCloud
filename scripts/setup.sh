#!/usr/bin/bash

echo "Symlink overrides"
ln -s docker-compose.override.local.yml docker-compose.override.yml

echo "Check envars"
./scripts/check_envvars.sh

echo "Rewrite .env"
cp .env.example .env
sed -ri 's/^COMPOSE_FILE=(.*)/COMPOSE_FILE=\1:docker-compose.override.test.yml/g' .env
eval $(egrep "^[^#;]" .env | xargs -d'\n' -n1 | sed -E 's/(\w+)=(.*)/export \1='"'"'\2'"'"'/g')

echo "Pull, print images"
docker compose pull
docker images

echo "Setup artifacts"
mkdir -m 777 tests_artifacts

echo "Setup Compose and Django (without building since we are pulling everything)"
docker compose up -d --no-build
docker compose exec app python manage.py makemigrations --check --noinput
docker compose exec app python manage.py collectstatic --noinput
