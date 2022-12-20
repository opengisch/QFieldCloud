#!/bin/bash -e

pipenv run pip install pyyaml
pipenv run python scripts/check_envvars.py .env.example --docker-compose-dir . --ignored-varnames CONFIG_PATH
