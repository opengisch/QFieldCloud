#!/bin/bash

if [[ ! -d ./docker-nginx/certs ]]; then
   echo "Please start script in dir qfieldcloud by command ./scripts/init_mkcert.sh. Exiting!"
   exit 1
fi

set -e

# read and export the variables from the .env file for the duration of this script
set -o allexport
source .env
set +o allexport


echo "### Creating certificates ${QFIELDCLOUD_HOST}-key.pem and ${QFIELDCLOUD_HOST}.pem for host ${QFIELDCLOUD_HOST} in ./docker-nginx/certs"

export COMPOSE_FILE="docker-compose.localhost.yml"

docker compose up -d --build

# QFieldCloud will automatically generate a certificate and it's root certificate in ./docker-nginx/certs.
# However, you need to trust the root certificate first, so other programs (e.g. curl) can create secure connection to the local QFieldCloud instance.

echo "On Debian/Ubuntu, the root certificate is copied to the directory with trusted certificates. Note the extension has been changed to .crt:"
sleep 1

echo "Running command: sudo cp ./docker-nginx/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt"
sudo cp ./docker-nginx/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt

echo "Trust the newly added certificate: sudo update-ca-certificates"
sudo update-ca-certificates

echo "Stopping container qfieldcloud-mkcert-1"
docker stop qfieldcloud-mkcert-1

echo "Unset COMPOSE_FILE"
unset COMPOSE_FILE
echo ${COMPOSE_FILE}

echo "Deleting container qfieldcloud-mkcert-1"
docker container rm qfieldcloud-mkcert-1

echo "After deploying nginx connecting to localhost with curl should return no errors: curl https://localhost:8002/"
