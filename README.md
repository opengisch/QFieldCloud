# QFieldCloud

QFieldCloud is a Django based service designed to synchronize projects and data between QGIS (+ QFieldSync plugin) and QField.

QFieldCloud allows seamless synchronization of your field data with your spatial infrastructure with change tracking, team management and online-offline work capabilities in QField.

# Hosted solution
If you're interested in quickly getting up and running, we suggest subscribing to the version hosted by OPENGIS.ch at https://qfield.cloud. This is also the instance that is integrated by default into QField.
<a href="https://qfield.cloud"><img alt="QFieldCloud logo" src="https://qfield.cloud/img/logo_horizontal.svg" width="100%"/></a>


## Documentation

System documentation is [here](https://github.com/opengisch/qfieldcloud/blob/master/docs/system_documentation.org).

Documentation about how QFieldCloud file's storage works is [here](https://github.com/opengisch/qfieldcloud/blob/master/docs/storage.org).

Permissions documentation is [here](https://github.com/opengisch/qfieldcloud/blob/master/docs/permissions.org).


## Development

### Launch a local instance

Copy the `.env.example` into `.env` file and configure it to your
desire with a good editor:

    cp .env.example .env
    emacs .env

Link or copy `docker-compose.local.yaml` into `docker-compose.override.yaml`:

    ln -s docker-compose.local.yaml docker-compose.override.yaml

To build development images and run the containers:

    docker-compose up -d --build

It will read `docker-compose.yml` and `docker-compose.override.yml`
and start a django built-in server at `http://localhost:8000`.

Run the django database migrations.

    docker-compose exec app python manage.py migrate

You can check if everything seems to work correctly using the
`status` command:

    docker-compose exec app python manage.py status


### Tests

To run all the unit and functional tests (on a throwaway test
database and a throwaway test storage directory):

    docker-compose run app python manage.py test

To run only a test module (e.g. `test_permission.py`)

    docker-compose run app python manage.py test qfieldcloud.core.tests.test_permission


### Code style

Code style done with precommit

    pip install pre-commit
    # install pre-commit hook
    pre-commit install


## Deployment


### Servers

QFieldCloud is published on two servers:

-   <https://dev.qfield.cloud/> This is a testing instance for new
    features.
-   <https://app.qfield.cloud/> This is the production instance. At
    the moment the deploy is done manually.

On the servers, we need only the `docker-compose.yml` and not the
"override" one. There are no mounted folders. To apply changes,
the docker image must be re-built.


### Launch a server instance

Copy the `.env.example` into `.env` file and configure it to your
desire with a good editor

    cp .env.example .env
    emacs .env

Create the directory for qfieldcloud logs and supervisor socket file

    mkdir /var/local/qfieldcloud

Run and build the docker containers

    # dev server:
    docker-compose -f docker-compose.yml -f docker-compose.override.dev.yml up -d --build

    # prod server
    docker-compose -f docker-compose.yml -f docker-compose.override.dev.yml up -d --build

Run the django database migrations

    docker-compose -f docker-compose.yml -f docker-compose.override.dev.yml exec app python manage.py migrate


### Infrastructure

Based on this example
<https://testdriven.io/blog/dockerizing-django-with-postgres-gunicorn-and-nginx/>


### Logs

Docker logs are managed by docker in the default way. To read the logs:

    docker-compose -f docker-compose.yml -f docker-compose.override.dev.yml logs


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

## Resources

-   [QField Cloud "marketing" page](https://qfield.cloud)
-   [API Swagger doc](https://app.qfield.cloud/swagger/)
-   [API status page](http://status.qfield.cloud/)
