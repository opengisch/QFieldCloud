#!/bin/bash

function waitForServices() {
    python wait_for_services.py
}

waitForServices

exec "$@"
