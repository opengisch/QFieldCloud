#!/bin/bash
set -e
set -o allexport; source .env; set +o allexport

echo "### Requesting Let's Encrypt certificate for $QFIELDCLOUD_HOST ..."
domain_args="-d ${QFIELDCLOUD_HOST}"

[ "${LETSENCRYPT_STAGING:-0}" != "0" ] && staging_arg="--staging" || staging_arg=""

dns_args="--dns-cloudflare --dns-cloudflare-credentials /etc/letsencrypt/credentials/cloudflare.ini --dns-cloudflare-propagation-seconds 120"

docker compose run --rm --entrypoint "\
  certbot certonly \
    $staging_arg \
    $dns_args \
    $domain_args \
    --non-interactive \
    --agree-tos \
    --email $LETSENCRYPT_EMAIL \
    --rsa-key-size $LETSENCRYPT_RSA_KEY_SIZE \
    --force-renewal" certbot

echo
echo '### Reloading nginx ...'
docker compose exec nginx nginx -s reload
