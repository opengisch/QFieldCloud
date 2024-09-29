#!/bin/bash

GITHUB_ACTIONS_CACHE_KEY_LIST=`gh actions-cache list -B refs/pull/972/merge | awk '{ print $1 }'`
echo $GITHUB_ACTIONS_CACHE_KEY_LIST
for GITHUB_ACTIONS_CACHE_KEY in $GITHUB_ACTIONS_CACHE_KEY_LIST; do
  gh actions-cache delete $GITHUB_ACTIONS_CACHE_KEY --confirm
  echo "Deleting cache key $GITHUB_ACTIONS_CACHE_KEY"
done
echo
echo "Cache deleted"
