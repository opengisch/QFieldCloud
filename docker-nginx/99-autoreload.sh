#!/bin/sh
while :; do
    sleep 6h
    nginx -t && nginx -s reload
done &
