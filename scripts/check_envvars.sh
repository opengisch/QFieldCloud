#!/bin/bash -e

python3 scripts/check_envvars.py .env.example --docker-compose-dir . --ignored-varnames CONFIG_PATH DEBUG_DEBUGPY_APP_PORT DEBUG_DEBUGPY_WORKER_WRAPPER_PORT LETSENCRYPT_EMAIL LETSENCRYPT_RSA_KEY_SIZE LETSENCRYPT_STAGING
