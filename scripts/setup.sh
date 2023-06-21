#!/usr/bin/bash

echo "Overriding Compose files..."
ln -s docker-compose.override.local.yml docker-compose.override.yml

echo "Rewriting .env..."
cp .env.example .env
sed -ri 's/^COMPOSE_FILE=(.*)/COMPOSE_FILE=\1:docker-compose.override.test.yml/g' .env
eval $(egrep "^[^#;]" .env | xargs -d'\n' -n1 | sed -E 's/(\w+)=(.*)/export \1='"'"'\2'"'"'/g')

echo "Checking environment..."
# uncomment these lines if running locally
# export IMG_REG_REPO=ghcr.io/opengisch/qfieldcloud
# export IMG_HEAD_SHA=split-test.05d3e46131062853216f6dc24d5085f2595899db
# docker compose config > config.txt

if [[ -z "$IMG_REG_REPO" ]]
then 
    echo "IMG_REG_REPO found empty!"
    exit 1
else
    echo "Using $IMG_REG_REPO".
fi

if [[ -z "$IMG_HEAD_SHA" ]]
then 
    echo "IMG_HEAD_SHA found empty!"
    exit 1
else
    echo "Using $IMG_HEAD_SHA".
fi

echo "Pulling images..."
docker compose pull
docker images

echo "Setting artifacts up..."
mkdir -m 777 tests_artifacts

echo "Running Compose..."
docker compose up -d --no-build

echo "Checking migrations..."
docker compose exec app python manage.py makemigrations --check --noinput

echo "Migrating..."
docker compose exec app python manage.py migrate --noinput

echo "Collecting static files..."
docker compose exec app python manage.py collectstatic --noinput
