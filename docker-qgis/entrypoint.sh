#!/usr/bin/env bash

case "$1" in
    "export")
        xvfb-run python3 qgis_caller.py "$@"
        ;;
    "apply-delta")
        xvfb-run python3 apply_deltas.py "${@:2}"
        ;;
    *)
    echo "You have failed to specify what to do correctly."
    exit 1
    ;;
esac
