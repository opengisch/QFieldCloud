#!/bin/bash -e

pipenv run python3 scripts/check_envvars.py .env.example --docker-compose-dir .
