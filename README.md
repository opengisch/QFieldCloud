# QFieldCloud

QFieldCloud is a Django based service designed to synchronize projects and data between QGIS (+ QFieldSync plugin) and QField.

QFieldCloud allows seamless synchronization of your field data with your spatial infrastructure with change tracking, team management and online-offline work capabilities in QField.

# Hosted solution

If you're interested in quickly getting up and running, we suggest subscribing to the version hosted by OPENGIS.ch at https://qfield.cloud. This is also the instance that is integrated by default into QField.
<a href="https://qfield.cloud"><img alt="QFieldCloud logo" src="https://qfield.cloud/img/logo_horizontal_embedded_font.svg" width="100%"/></a>


## Documentation

QField and QFieldCloud documentation is deployed [here](https://docs.qfield.org).


## Development

### Clone the repository

Clone the repository and all its submodules:

    git clone --recurse-submodules git@github.com:opengisch/qfieldcloud.git

To fetch upstream development, don't forget to update the submodules too:

    git pull --recurse-submodules  && git submodule update --recursive


### Launch a local instance

Copy the `.env.example` into `.env` file and configure it to your
desire with a good editor:

    cp .env.example .env
    emacs .env

To build development images and run the containers:

    docker compose up -d --build

It will read the `docker-compose*.yml` files specified in the `COMPOSE_FILE`
variable and start a django built-in server at `http://localhost:8011`.

Run the django database migrations.

    docker compose exec app python manage.py migrate

And collect the static files (CSS, JS etc):

    docker compose run app python manage.py collectstatic --noinput

You can check if everything seems to work correctly using the
`status` command:

    docker compose exec app python manage.py status

Now you can get started by adding the first user that would also be a super user:

    docker compose run app python manage.py createsuperuser --username super_user --email super@user.com

### Tests

To run all the unit and functional tests (on a throwaway test
database and a throwaway test storage directory):

    export COMPOSE_FILE=docker-compose.yml:docker-compose.override.local.yml:docker-compose.override.test.yml
    # (Re-)build the app service to install necessary test utilities (requirements_test.txt)
    docker compose up -d --build
    docker compose run app python manage.py migrate
    docker compose run app python manage.py test --keepdb

To run only a test module (e.g. `test_permission.py`)

    docker compose run app python manage.py test --keepdb qfieldcloud.core.tests.test_permission

### Debugging

> This section gives examples for VSCode, please adapt to your IDE)

If you are using the provided `docker-compose.override.local.yml`, then `debugpy` is automatically installed and configured for use.

Add the following to your IDE to connect (example given for VSCode's `.vscode/launch.json`, triggered with `F5`):

```
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "QFC debug app",
            "type": "python",
            "request": "attach",
            "justMyCode": false,
            "connect": {"host": "localhost", "port": 5678},
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}/docker-app/qfieldcloud",
                    "remoteRoot": "/usr/src/app/qfieldcloud"
                },
                {
                    "localRoot": "${workspaceFolder}/docker-app/site-packages",
                    "remoteRoot": "/usr/local/lib/python3.10/site-packages/"
                },
            ],
        },
        {
            "name": "QFC debug worker_wrapper",
            "type": "python",
            "request": "attach",
            "justMyCode": false,
            "connect": {"host": "localhost", "port": 5679},
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}/docker-app/qfieldcloud",
                    "remoteRoot": "/usr/src/app/qfieldcloud"
                },
                {
                    "localRoot": "${workspaceFolder}/docker-app/site-packages",
                    "remoteRoot": "/usr/local/lib/python3.10/site-packages/"
                },
            ],
        }
    ]
}
```

To add breakpoints in vendor modules installed via `pip` or `apt`, you need a copy of their source code.
The easiest way to achieve that is do actual copy of them:

```
docker compose cp app:/usr/local/lib/python3.10/site-packages/ docker-app/site-packages
```

The configuration for the vendor modules is the second object in the example `pathMappings` above, as well as setting `justMyCode` to `false`.

Do not forget to copy the site packages every time any of the `requirements.txt` files are changed!

If you are not using `docker-compose.override.local.yml`, there are other options.

You can debug interactively by adding this snippet anywhere in the code.
```python
import debugpy
debugpy.listen(("0.0.0.0", 5680))
print("debugpy waiting for debugger... 🐛")
debugpy.wait_for_client()  # optional
```

Or alternativley, prefix your commands with `python -m debugpy --listen 0.0.0.0:5680 --wait-for-client`.

    docker compose run -p 5680:5680 app python -m debugpy --listen 0.0.0.0:5680 --wait-for-client manage.py test
    docker compose run -p 5681:5681 worker_wrapper python -m debugpy --listen 0.0.0.0:5681 --wait-for-client manage.py test

Note if you run tests using the `docker-compose.test.yml` configuration, the `app` and `worker-wrapper` containers expose ports `5680` and `5681` respectively.


## Add root certificate

QFieldCloud will automatically generate a certificate and it's root certificate in `./config/nginx/certs`. However, you need to trust the root certificate first, so other programs (e.g. curl) can create secure connection to the local QFieldCloud instance.

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

### Code style

Code style done with precommit

    pip install pre-commit
    # install pre-commit hook
    pre-commit install


## Deployment

### Launch a server instance

Copy the `.env.example` into `.env` file and configure it to your
desire with a good editor

    cp .env.example .env
    emacs .env

Do not forget to set DEBUG=0 and to adapt COMPOSE_FILE to not load local
development configurations.

Create the directory for qfieldcloud logs and supervisor socket file

    mkdir /var/local/qfieldcloud

Run and build the docker containers

    docker compose up -d --build

Run the django database migrations

    docker compose exec app python manage.py migrate


## Create or renew a certificate using Let's Encrypt

If you are running the server on a server with a public domain, you can install Let's Encrypt certificate by running the following command:

    ./scripts/init_letsencrypt.sh

The same command can also be used to update an expired certificate.

Note you may want to change the `LETSENCRYPT_EMAIL`, `LETSENCRYPT_RSA_KEY_SIZE` and `LETSENCRYPT_STAGING` variables.

### Infrastructure

Based on this example
<https://testdriven.io/blog/dockerizing-django-with-postgres-gunicorn-and-nginx/>

### Ports

| service       | port  | configuration        | local              | development        | production         |
|---------------|-------|----------------------|--------------------|--------------------|--------------------|
| nginx http    | 80    | WEB_HTTP_PORT        | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| nginx https   | 443   | WEB_HTTPS_PORT       | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| django http   | 8011  | DJANGO_DEV_PORT      | :white_check_mark: | :x:                | :x:                |
| postgres      | 5433  | HOST_POSTGRES_PORT   | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| redis         | 6379  | REDIS_PORT           | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| memcached     | 11211 | MEMCACHED_PORT       | :white_check_mark: | :x:                | :x:                |
| geodb         | 5432  | HOST_POSTGRES_PORT   | :white_check_mark: | :white_check_mark: | :x:                |
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

## Collaboration

Contributions welcome!

Any PR including the `[WIP]` should be:
- able to be checked-out without breaking the stack;
- the specific feature being developed/modified should be testable locally (does not mean it should work correctly).

## Resources

-   [QField Cloud "marketing" page](https://qfield.cloud)
-   [API Swagger doc](https://app.qfield.cloud/swagger/)
-   [API status page](http://status.qfield.cloud/)
