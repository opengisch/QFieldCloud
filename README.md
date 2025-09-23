# QFieldCloud

QFieldCloud is a Django based service designed to synchronize projects and data between QGIS (+ QFieldSync plugin) and QField.

QFieldCloud allows seamless synchronization of your field data with your spatial infrastructure with change tracking, team management and online-offline work capabilities in QField.


## Hosted solution

If you're interested in quickly getting up and running, we suggest subscribing to the version hosted by OPENGIS.ch at https://qfield.cloud. This is also the instance that is integrated by default into QField.
<a href="https://qfield.cloud"><img alt="QFieldCloud logo" src="https://qfield.cloud/img/logo_horizontal_embedded_font.svg" width="100%"/></a>


## Documentation

QField and QFieldCloud documentation is deployed [here](https://docs.qfield.org).


## Feature requests and issue reports

If you are interested in upcoming developments, or you want to suggest a new feature, please visit our ideas platform at [ideas.qfield.org](https://ideas.qfield.org).
Here, you can submit a new request or upvote existing ones.
To expedite developments by funding a feature, please email us at sales@qfield.cloud.

For questions about using the hosted service at [app.qfield.cloud](https://app.qfield.cloud), submit a ticket to our dedicated support platform at [tickets.qfield.cloud](https://tickets.qfield.cloud).

For self-hosted issues, please use the GitHub issues at https://github.com/opengisch/qfieldcloud/issues .


## Development


### Clone the repository

Clone the repository and all its submodules:

    git clone --recurse-submodules git@github.com:opengisch/QFieldCloud.git

To fetch upstream development, don't forget to update the submodules too:

    git pull --recurse-submodules  && git submodule update --recursive


### Launch a local instance

1. Copy the `.env.example` into `.env` file:

```shell
cp .env.example .env
```

2. Change the `ENVIRONMENT` variable to `development`.

```shell
ENVIRONMENT=development
```

3. Build development images and run the containers:

```shell
docker compose up -d --build
```

The command will read the `docker-compose*.yml` files specified in the `COMPOSE_FILE` variable from the `.env` file. Then Django built-in server will be directly reachable at `http://localhost:8011` or through `nginx` at `https://localhost`.
You should avoid using the Django's built-in server and better always develop and test QFieldCloud through the `nginx` [reverse proxy with SSL](#add-root-certificate).

4. (OPTIONAL) In case you have a database dump, you can directly load some data in your development database.

```shell
psql 'service=localhost.qfield.cloud' < ./qfc_dump_20220304.sql
```

5. Run Django database migrations.

```shell
docker compose exec app python manage.py migrate
```

6. And collect the static files (CSS, JS etc):

```shell
docker compose run app python manage.py collectstatic --noinput
```

7. Now you can get started by adding your super user that has access to the Django Admin interface:

```shell
docker compose run app python manage.py createsuperuser --username super_user --email super@user.com
```

8. If QFieldCloud needs to be translated, you can compile the translations using Django's tooling:

```shell
docker compose run --user root app python manage.py compilemessages
```


### Troubleshooting

To verify the instance is working fine, you can check using the healthcheck endpoint and make sure the `database` and `storage` keys have `ok` status:

```shell
curl https://localhost/api/v1/status/
```

If there is some kind of problem, first check the `nginx` and `app` logs, usually they contain the most of the relevant information.

```shell
docker compose logs nginx app
```


### Accessing the database

Sometimes we should inspect the database contents.
It is stored in the `postgres_data` volume and managed via the `db` container.

One can connect to the database via running the `psql` command within the `db` container:

    docker compose exec -it db psql -U qfieldcloud_db_admin -d qfieldcloud_db

Or by creating `~/.pg_service.conf` in their user home directory and appending:

    [localhost.qfield.cloud]
    host=localhost
    dbname=qfieldcloud_db
    user=qfieldcloud_db_admin
    port=5433
    password=3shJDd2r7Twwkehb
    sslmode=disable

    [test.localhost.qfield.cloud]
    host=localhost
    dbname=test_qfieldcloud_db
    user=qfieldcloud_db_admin
    port=5433
    password=3shJDd2r7Twwkehb
    sslmode=disable

And then connecting to the database via:

    psql 'service=localhost.qfield.cloud'


### Dependencies

QFieldCloud uses [`pip-compile`](https://pypi.org/project/pip-tools/) to manage it's dependencies.
All dependencies are listed in `requirements*.in` files.
When a `pip` a dependency is changed, the developer should produce the new `requirements*.txt` files.

    docker compose run --rm pipcompile

Alternatively, one can create only a `requirements.txt` file for a single `requirements.in`:

    docker compose run --rm pipcompile pip-compile --no-strip-extras -o requirements/requirements_worker_wrapper.txt requirements/requirements_worker_wrapper.in

### Tests

Rebuild the docker compose stack with the `docker-compose.override.test.yml` file added to the `COMPOSE_FILE` environment variable:

    export COMPOSE_FILE=docker-compose.yml:docker-compose.override.standalone.yml:docker-compose.override.test.yml
    # (Re-)build the app service to install necessary test utilities (requirements_test.txt)
    docker compose up -d --build
    docker compose run app python manage.py migrate
    docker compose run app python manage.py collectstatic --noinput

You can then run all the unit and functional tests:

    docker compose run app python manage.py test --keepdb

To run only a test module (e.g. `test_permission.py`):

    docker compose run app python manage.py test --keepdb qfieldcloud.core.tests.test_permission

To run a specific test:

    docker compose run app python manage.py test --keepdb qfieldcloud.core.tests.test_permission.QfcTestCase.test_collaborator_project_takeover

<details>
<summary>
Instructions to have a test instance running in parallel to a dev instance
</summary>
Create an <code>.env.test</code> file with the following variables that override the ones in <code>.env</code>:

    ENVIRONMENT=test
    QFIELDCLOUD_HOST=nginx
    DJANGO_SETTINGS_MODULE=qfieldcloud.settings
    STORAGE_ENDPOINT_URL=http://172.17.0.1:8109
    MINIO_API_PORT=8109
    MINIO_BROWSER_PORT=8110
    WEB_HTTP_PORT=8101
    WEB_HTTPS_PORT=8102
    HOST_POSTGRES_PORT=8103
    HOST_GEODB_PORT=8107
    MEMCACHED_PORT=11212
    QFIELDCLOUD_DEFAULT_NETWORK=qfieldcloud_test_default
    QFIELDCLOUD_SUBSCRIPTION_MODEL=subscription.Subscription
    DJANGO_DEV_PORT=8111
    SMTP4DEV_WEB_PORT=8112
    SMTP4DEV_SMTP_PORT=8125
    SMTP4DEV_IMAP_PORT=8143
    COMPOSE_PROJECT_NAME=qfieldcloud_test
    COMPOSE_FILE=docker-compose.yml:docker-compose.override.standalone.yml:docker-compose.override.test.yml
    DEBUG_APP_DEBUGPY_PORT=5781
    DEBUG_WORKER_WRAPPER_DEBUGPY_PORT=5780
    DEMGEN_PORT=8201

Build the test docker compose stack:

    docker compose --env-file .env --env-file .env.test up -d --build
    docker compose --env-file .env --env-file .env.test run app python manage.py migrate
    docker compose --env-file .env --env-file .env.test run app python manage.py collectstatic --noinput

You can then launch the tests:

    docker compose --env-file .env --env-file .env.test run app python manage.py test --keepdb

Don't forget to update the `port` value in [`[test.localhost.qfield.cloud]` in your `.pg_service.conf` file](#accessing-the-database).

</details>

### Debugging

> [!NOTE]
> This section gives examples for VSCode, please adapt to your IDE.

QFieldCloud source code ships with the required dependencies and configurations for debugging.
For local development you use `docker-compose.override.local.yml` with `DEBUG=True` in the `.env` file, in that case `debugpy` is ready to use.
The VSCode debugger will attach to the debugger in the container as configured in `.vscode/launch.json`.

There are two debugger configurations: for `app` and for `worker_wrapper` services.
The debugger can triggered with `F5`.

The default debugger configuration would not pause on boostrapping operations (module imports, class/function definitions etc).

To make sure the debugger is running before any application code is running, you have several options.

1. You can debug interactively by adding this snippet anywhere in the code.

```python
import debugpy
debugpy.listen(("0.0.0.0", 5680))
print("debugpy waiting for debugger... 🐛")
debugpy.wait_for_client()  # optional
```

2. Alternativley, prefix your commands with `python -m debugpy --listen 0.0.0.0:5680 --wait-for-client`. Note the exposed port here might be different from your local configuration.

```shell
    docker compose run --rm -p 5680:5680 app python -m debugpy --listen 0.0.0.0:5680 --wait-for-client manage.py test
    docker compose run --rm -p 5681:5681 worker_wrapper python -m debugpy --listen 0.0.0.0:5681 --wait-for-client manage.py test
```

3. Or permanently change the command in `docker-compose.override.local.yml` to add the `--wait-for-client`.

To add breakpoints in vendor modules installed via `pip` or `apt`, you need a copy of their source code on your host machine.
The easiest way to achieve that is do actual copy of them:

```
docker compose cp app:/usr/local/lib/python3.10/site-packages/ docker-app/site-packages
```

Then uncomment the respective parts of `pathMappings` and `justMyCode` in `.vscode/launch.json`.
Identify them by searching for "debug vendor modules" in the file.

Do not forget to copy the site packages every time any of the `requirements*.txt` files are changed!


## Add root certificate

QFieldCloud will automatically generate a certificate and its root certificate in `./conf/nginx/certs`.
However, you need to trust the root certificate first,
so other programs (e.g. curl) can create secure connection to the local QFieldCloud instance.

On Debian/Ubuntu, copy the root certificate to the directory with trusted certificates. Note the extension has been changed to `.crt`:

    sudo cp ./conf/nginx/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt

Trust the newly added certificate:

    sudo update-ca-certificates

Connecting with `curl` should return no errors:
    curl https://localhost:8002/

### Remove the root certificate

If you want to remove or change the root certificate, you need to remove the root certificate file and refresh the list of certificates:

    sudo rm /usr/local/share/ca-certificates/rootCA.crt
    sudo update-ca-certificates --fresh

Now connecting with `curl` should fail with a similar error:

    $ curl https://localhost:8002/

    curl: (60) SSL certificate problem: unable to get local issuer certificate
    More details here: https://curl.haxx.se/docs/sslcerts.html

    curl failed to verify the legitimacy of the server and therefore could not
    establish a secure connection to it. To learn more about this situation and
    how to fix it, please visit the web page mentioned above.

## Code style

Code style done with [`precommit`](https://pre-commit.com):

    pip install pre-commit
    # install pre-commit hook
    pre-commit install


## Deployment

### Launch a server instance

> [!CAUTION]
> QFieldCloud is designed to work with externally managed services for it's database (PostgreSQL), Object Storage (S3) and mailing provider.
>
> For small self-hosted environments you may run QFieldCloud on a single server using `docker-compose.override.standalone.yml`, but this is **entirely at your own risk**.
>
> The maintainers of this repository do not recommend and do not guarantee that the standalone version will always work between versions, and will close all issues regarding standalone deployment without further explanation.

Copy the `.env.example` into `.env` file:

    cp .env.example .env
    vi .env

Do not forget to set `DEBUG=0` and to adapt `COMPOSE_FILE` environment variable to not load local development configurations.

Run and build the docker containers:

    docker compose up -d --build

Run the django database migrations:

    docker compose exec app python manage.py migrate

Collect the static files:

    docker compose exec app python manage.py collectstatic

### Using certificate from Let's Encrypt

By default, QFieldCloud is using a self-signed certificate. For production use you should use a valid certificate.

Note you want to change the `LETSENCRYPT_EMAIL`, `LETSENCRYPT_RSA_KEY_SIZE` and `LETSENCRYPT_STAGING` variables in `.env`.

On a server with a public domain, you can get a certificate issued by Let's Encrypt using certbot running the following command:

    ./scripts/init_letsencrypt.sh

The certificates will be renewed automatically.

To use this Let's Encrypt certificate within QFieldCloud you just need to uncomment the following lines in your `.env`:

    QFIELDCLOUD_TLS_CERT=/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/fullchain.pem
    QFIELDCLOUD_TLS_KEY=/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/privkey.pem

You can also use your own certificates by placing them in `conf/nginx/certs/` and changing `QFIELDCLOUD_TLS_CERT` and `QFIELDCLOUD_TLS_KEY` accordingly.
Don't forget to create your Diffie-Hellman parameters.

### Additional NGINX config

You can add additional config to nginx placing files in `conf/nginx/config.d/` ending with `.conf`. They will be included in the main `nginx.conf`.

## Infrastructure

Based on this example
<https://testdriven.io/blog/dockerizing-django-with-postgres-gunicorn-and-nginx/>

### Ports

| service       | port  | configuration        | local              | development        | production         |
|---------------|-------|----------------------|--------------------|--------------------|--------------------|
| nginx http    | 80    | WEB_HTTP_PORT        | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| nginx https   | 443   | WEB_HTTPS_PORT       | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| django http   | 8011  | DJANGO_DEV_PORT      | :white_check_mark: | :x:                | :x:                |
| postgres      | 5433  | HOST_POSTGRES_PORT   | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| memcached     | 11211 | MEMCACHED_PORT       | :white_check_mark: | :x:                | :x:                |
| geodb         | 5432  | HOST_GEODB_PORT      | :white_check_mark: | :white_check_mark: | :x:                |
| minio API     | 8009  | MINIO_API_PORT       | :white_check_mark: | :x:                | :x:                |
| minio browser | 8010  | MINIO_BROWSER_PORT   | :white_check_mark: | :x:                | :x:                |
| smtp web      | 8012  | SMTP4DEV_WEB_PORT    | :white_check_mark: | :x:                | :x:                |
| smtp          | 25    | SMTP4DEV_SMTP_PORT   | :white_check_mark: | :x:                | :x:                |
| imap          | 143   | SMTP4DEV_IMAP_PORT   | :white_check_mark: | :x:                | :x:                |

### Logs

Docker logs are managed by docker in the default way. To read the logs:

    docker compose logs


For great `nginx` logs, use:

    QFC_JQ='[.ts, .ip, (.method + " " + (.status|tostring) + " " + (.resp_time|tostring) + "s"), .uri, "I " + (.request_length|tostring) + " O " + (.resp_body_size|tostring), "C " + (.upstream_connect_time|tostring) + "s", "H " + (.upstream_header_time|tostring) + "s", "R " + (.upstream_response_time|tostring) + "s", .user_agent] | @tsv'
    docker compose logs nginx -f --no-log-prefix | grep ':"nginx"' | jq -r $QFC_JQ


### Geodb

The geodb (database for the users projects data) is installed on
separated machines (db1.qfield.cloud, db2.qfield.cloud, db3&#x2026;)
and they are load balanced and available through the
db.qfield.cloud address.

There is a template database called
`template_postgis` that is used to create the databases for the
users. The template db has the following extensions installed:

-   fuzzystrmatch
-   plpgsql
-   postgis
-   postgis<sub>tiger</sub><sub>geocoder</sub>
-   postgis<sub>topology</sub>

### Storage

You can use either the integrated `minio` object storage, or use an external provider (e. g. S3) with versioning enabled. Check the corresponding `STORAGE_*` environment variables for more info.

### Database

QFieldCloud requires a PostgreSQL/PostGIS database persisting it's own data.
The recommended and only supported way is to use an external to the docker-compose stack PostgreSQL/PostGIS database.
Check the corresponding `POSTGRES_*` environment variables for more info.

> [!CAUTION]
> For local development and testing you can use the `db` service in `docker-compose.standalone.yml`.

If a local PostGIS is running and hosting QFieldCloud's data, check the `POSTGIS_IMAGE_VERSION` for controlling the version of the PostgreSQL/PostGIS backend.
[These commands](https://gist.github.com/gounux/2c0779fcb22e512cbdc613eb78200571) can help in order to migrate the local PG service from a major version to another one.
Migration to a newer database version is a risky operation to your data, so prepare and test the backup of the `postgres_data` volume.

## Collaboration

Contributions welcome!

Any PR including the `[WIP]` should be:
- able to be checked-out without breaking the stack;
- the specific feature being developed/modified should be testable locally (does not mean it should work correctly).

## Resources

-   [QField Cloud "marketing" page](https://qfield.cloud)
-   [API Swagger doc](https://app.qfield.cloud/swagger/)
-   [API status page](http://status.qfield.cloud/)
