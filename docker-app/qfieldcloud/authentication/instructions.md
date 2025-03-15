# Instructions

```bash
git clone git@github.com:opengisch/QFieldCloud.git
cd QFieldCloud
git checkout feat/oidc-qfield-testing

cd docker-app/certs/
./makecerts.sh
cd ../..

cp .env.example .env
vim .env
```

Set or change the following settings:

```bash
QFIELDCLOUD_IDP_GOOGLE_CLIENT_ID="736186946600-94a7l05bb9lg5rv0ganupr2oai2otubr.apps.googleusercontent.com"

# Secret posted in chat
QFIELDCLOUD_IDP_GOOGLE_CLIENT_SECRET="<secret>"

# Instead of 192.168.1.61 add the IP of your mobile device, or whichever extenal devices
# you want to access QFC from
DJANGO_ALLOWED_HOSTS="localhost 127.0.0.1 0.0.0.0 app nginx 192.168.1.61"

# To avoid reusing a possibly existing database
COMPOSE_PROJECT_NAME=qfieldcloud-sso
```

```bash
docker compose up --build
```

## In a new tab
```
docker compose exec app python manage.py migrate
docker compose run app python manage.py collectstatic --noinput
docker compose run app python manage.py createsuperuser --username super_user --email super@localhost
```

## First tests
- Visit https://localhost/ and accept certificate
- Log in with super_user
- Log out

## Test QFC Web SSO
- Visit https://localhost/admin/login/?next=/admin/
- You should see "Or use a third-party" and "Google" as an option below the username/password fields
- Log in using Google, and your @opengis.ch account
- Since it redirects you to the admin page, you should now be authenticated, but see the message "You are authenticated as <yourname>, but are not authorized to access this page. Would you like to login to a different account?"
- So, logout by visiting https://localhost/accounts/logout
- Visit https://localhost/admin and log in as `super_user` again, using username/password
- In `Core > People` you should find your new user account. Select it, and set both `[x] Superuser status` and `[x] Staff status` and Save.
- Log out from the `super_user` account again
- Now select `Log in with Google` again - you should now be logged in to the admin panel with your @opengis.ch user

-> Basic WebSSO works

## Test provider list endpoint

```
# Trailing slash after `providers/` is required!
curl -X GET -H "Accept: application/json"  'http://localhost:8011/api/v1/auth/providers/'
```

Should give you a JSON response like this:

```json
[
  { "type": "credentials",
    "id": "credentials",
    "name": "Username / Password"
  },
  {
    "type": "oauth2",
    "id": "google",
    "name": "Google",
    "grant_flow_name": "Authorization Code",
    "grant_flow": 0,
    "scope": "openid profile email",
    "pkce_enabled": false,
    "token_url": "https://oauth2.googleapis.com/token",
    "refresh_token_url": "https://oauth2.googleapis.com/token",
    "request_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "redirect_host": "localhost",
    "redirect_port": 7070,
    "redirect_url": "",
    "client_id": "736186946600-94a7l05bb9lg5rv0ganupr2oai2otubr.apps.googleusercontent.com",
    "client_secret": "REDACTED",
    "extra_tokens": { "id_token": "X-QFC-ID-Token" }
  }
]
```

## Test QGIS auth config

- Create a new auth config in QGIS based on the info from the `api/v1/auth/providers/` endpoint.
- Create a new WMS connection with the following settings:
    - Name: QFC Fake WMS
    - URL: http://localhost:8011/fake_wms/
    - Authentication: Config created above
- Again, the trailing slash after `fake_wms/` is required!
- Refreshing the "QFC Fake WMS" connection should trigger the OIDC flow from QGIS, and you should then see a (fake) layer group with two layers in it

-> QGIS Authentication middleware works

## Setting up Keycloak as an IDP

- If you haven't already, create the certificates:
  - Ensure you have the `keytool` command available on your host (if not, install a Java runtime)
  - Generate the certificates:
  ```bash
  cd docker-app/certs/
  ./makecerts.sh
  cd ../..
  ```

- Import the certificates into your system's / browser's trust store
  - Import the root CA certificate

    - Linux:
    ```bash
    sudo apt-get install -y ca-certificates
    sudo cp docker-app/certs/rootCA.crt /usr/local/share/ca-certificates/ninjas-rootCA.crt
    sudo update-ca-certificates
    ```
    - macOS:
      - Double click `docker-app/certs/rootCA.crt` and import it into the system keychain.
      - Set it to "Always Trust" in the trust settings.

  - Import the client certificate:

    - Linux:
      - Install `docker-app/certs/fredFlintstone.p12` into your browser's certificate store:
        - Chromium
          - Settings > Security > Advanced > Manage certificates > Your certificates > Import
        - Firefox
          - Go go about:config
          - Set `security.remember_cert_checkbox_default_setting` to `false` (better for testing)
          - Settings > Privacy & Security > Security > Certificates > View Certificates > Your Certificates > Import
      - Pick `fredFlintstone.p12` (no password)

    - macOS:
      - Double click `fredFlintstone.p12` and import it into the system keychain.

- Add the following to your `.env`:
  ```bash
  QFIELDCLOUD_IDP_KEYCLOAK_CLIENT_ID="qfc-pkce"
  ```

- Add keycloak to your `/etc/hosts`:
  ```
  127.0.0.1   keycloak
  ```
  (This is currently needed because both the docker container and the browser
  on your host need to connect to keycloak using the same hostname. The
  hostname `localhost` only is correct in the context of the host, but inside
  the docker container it obviously means the refers to the loopback interface
  of the container itself. `keycloak` is correct inside the container, but
  not available on the host, unless manually added to `/etc/hosts`.)

- When you visit QFC at https://localhost now, you should see Keycloak as a provider
- Clicking on it should send you to the KC "Ninjas" realm login page
- If your certs are installed correctly, your browser should now prompt you to present a client certificate
- Selecting to authenticate with Fred Flintstone's cert should log you into KC without password


## Notes

(not needed for setup, just so that my silly brain doesn't forget)

### Exporting Keycloak realms

- Export keycloak realms:
  - Stop keycloak container
  - `docker compose run --entrypoint "/opt/keycloak/bin/kc.sh export --dir /tmp/export --users realm_file" keycloak`
  - Find the exported realm(s) in `keycloak/export/` on the host

### Manually setting up OIDC client

- Visit http://localhost:7080/
 - Log in with `admin` / `admin`
 - Create a new realm:
   - Click on the top left, where it says "Keycloak" and "master", then select "Create realm"
   - Realm name: `ninjas`
 - Create a user:
   - Select "Users", then "Create new user"
   - Email verified: On
   - Username: lukasgraf
   - Email: lukas@example.org
   - First name: Lukas
   - Last name: Graf
 - Set a password for the user:
   - Select "Credentials" and set a password
   - Temporary: Off

 - Create a client:
   - Select "Clients", then "Create client"
   - Client type: OpenID Connect
   - Client ID: `qfc`
   - Always display in UI: On
   - Next
   - Client authenticaton: On
   - Leave "Authorization" disabled
   - Enable just "[x] Standard Flow" in "Authentication Flows"
   - Next
   - Add the following URLs to "Valid Redirect URIs":
     - `http://localhost:8011/*`
     - `https://localhost/*`
   - Add the following URLs to "Web Origins":
     - `http://localhost:8011`
     - `https://localhost`
   - Save
   - Go to the "Credentials" tab of the client
   - Display and note the "Client Secret"

   - Add the following to your `.env`:
     ```bash
     QFIELDCLOUD_IDP_KEYCLOAK_CLIENT_ID="qfc"
     QFIELDCLOUD_IDP_KEYCLOAK_CLIENT_SECRET="<secret>"