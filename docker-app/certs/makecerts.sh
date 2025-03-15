#!/bin/bash

exists () {
  type "$1" >/dev/null 2>/dev/null
}

if ! exists keytool; then
  echo "Can't find keytool in \$PATH. Please install a Java JRE/JDK."
  echo "For example:"
  echo "  sudo apt install default-jre"
  exit 1
fi

# RootCA Key and Certificate
if [ ! -f rootCA.key ]; then
    openssl req -nodes -x509 -sha256 -days 3650 -subj "/C=CH/O=Ninjas/OU=Ninjas Certificate Authority/CN=Ninjas Certificate Authority"  -newkey rsa:4096 -keyout rootCA.key -out rootCA.crt
fi

# Keycloak Server certificate
if [ ! -f keycloak.crt ]; then
    # Create keycloak key and CSR
    openssl req -new -newkey rsa:4096 -keyout keycloak.key -subj "/C=CH/O=Ninjas/OU=Ninjas Demo Keycloak Server/CN=Ninjas Demo Keycloak Server" -out keycloak.csr -nodes

    # Sign keycloak CSR
    openssl x509 -req -CA rootCA.crt -CAkey rootCA.key -in keycloak.csr -out keycloak.crt -days 365 -CAcreateserial -extfile keycloak.ext
fi

if [ ! -f fredFlintstone.crt ]; then
    # Client key and CSR
    openssl req -new -newkey rsa:4096 -nodes -addext "extendedKeyUsage = clientAuth" -addext "keyUsage = digitalSignature, keyEncipherment, dataEncipherment" -subj "/C=CH/O=Ninjas/OU=Users/CN=Fred Flintstone/emailAddress=fred.flintstone@example.org" -keyout fredFlintstone.key -out fredFlintstone.csr

    # Sign client CSR
    openssl x509 -req -CA rootCA.crt -CAkey rootCA.key -in fredFlintstone.csr -out fredFlintstone.crt -days 365 -CAcreateserial

    # Export client cert to P12
    # The 'legacy' variant may be needed to import on older Android versions
    # (if it keeps asking for a password (which is empty), try the 'legacy' variant)
    openssl pkcs12 -export -passout pass: -out fredFlintstone.p12 -name "fredFlintstone" -inkey fredFlintstone.key -in fredFlintstone.crt
    openssl pkcs12 -export -legacy -passout pass: -out fredFlintstone_legacy.p12 -name "fredFlintstone" -inkey fredFlintstone.key -in fredFlintstone.crt
fi

# Import certificates into KC server truststore
keytool -import -alias client-cert -file fredFlintstone.crt -keystore server.truststore -storepass changeit -noprompt
keytool -import -alias ca-cert -file rootCA.crt -keystore server.truststore -storepass changeit -noprompt
