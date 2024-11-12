This directory will contain the self-signed certificates automatically created by `mkcert`.

You can also place your custom certificates.

To make use of the any of the certificates in this directory, make sure you adjust the values of `QFIELDCLOUD_TLS_CERT` and `QFIELDCLOUD_TLS_KEY` environment variables.
This directory is accessible in the `nginx` container at `/etc/nginx/certs/`.
