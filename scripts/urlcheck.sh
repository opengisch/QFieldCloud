#!/bin/bash

SCRIPT_DIR=$(dirname "$0")
case $SCRIPT_DIR in
"/"*) ;;

".")
	SCRIPT_DIR=$(pwd)
	;;
*)
	SCRIPT_DIR=$(pwd)/$(dirname "$0")
	;;
esac

echo "Scanning URLs used in ${SCRIPT_DIR}/../docker-app"

urls=$(grep --exclude "*.po" -rEho "https://[A-Za-z\.]+qfield.(cloud|org)[^ <>\\\"')]+" ${SCRIPT_DIR}/../docker-app | sort -u)

if [ -z "$urls" ]; then
	echo "No URLs found."
	exit 0
fi

echo "------------------------"

has_404=0
skip_urls=(
	"https://app.qfield.cloud/schemas/project-seed-20251201.json"
)

for url in $urls; do
	should_skip=0
	for skip_url in "${skip_urls[@]}"; do
		if [ "$url" = "$skip_url" ]; then
			should_skip=1
			break
		fi
	done

	if [ "$should_skip" -eq 1 ]; then
		echo "[---] ⏭️ SKIPPED   : $url"
		continue
	fi

	status_code=$(curl -s -L -m 10 -o /dev/null -w "%{http_code}" "$url")
	if [ "$status_code" = "404" ]; then
		echo "[404] ❌ NOT FOUND : $url"
		has_404=1
	elif [ "$status_code" = "200" ]; then
		echo "[200] ✅ OK        : $url"
	elif [ "$status_code" = "000" ]; then
		echo "[000] ⚠️ TIMEOUT   : $url (Failed to connect)"
	else
		echo "[$status_code] ℹ️ OTHER     : $url"
	fi
done

echo "------------------------"

if [ "$has_404" -eq 0 ]; then
	echo "✅ Check completed successfully: No 404 errors found."
	exit 0
fi

echo "❌ Check completed with failures: One or more 404 errors were detected."
exit 1
