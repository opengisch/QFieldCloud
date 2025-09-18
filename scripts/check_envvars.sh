#!/bin/bash -e

python3 scripts/check_envvars.py .env.example --docker-compose-dir . --ignored-varnames DEBUG_APP_DEBUGPY_PORT DEBUG_WORKER_WRAPPER_DEBUGPY_PORT DEBUG_QGIS_DEBUGPY_PORT
