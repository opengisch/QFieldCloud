#!/bin/bash

set -e

# read and export the variables from the .env file for the duration of this script
set -o allexport
source .env
set +o allexport

CONFIG_PATH="${CONFIG_PATH:-'./conf'}"

if [ ! -e "$CONFIG_PATH/nginx/dhparams/dhparams4096.pem" ]; then
  echo "### Create DH parameters ..."
  openssl dhparam -out "$CONFIG_PATH/nginx/dhparams/dhparams4096.pem" 4096
  echo
fi

echo "### Requesting Let's Encrypt certificate for $QFIELDCLOUD_HOST ..."
domain_args="-d ${QFIELDCLOUD_HOST}"

# Enable staging mode if needed
if [ $LETSENCRYPT_STAGING != "0" ]; then staging_arg="--staging"; fi

docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $domain_args \
    --email $LETSENCRYPT_EMAIL \
    --rsa-key-size $LETSENCRYPT_RSA_KEY_SIZE \
    --agree-tos \
    --force-renewal" certbot

echo

chmod 755 "$CONFIG_PATH/nginx/99-autoreload.sh"

echo "### Reloading nginx ..."
docker compose exec nginx nginx -s reload
