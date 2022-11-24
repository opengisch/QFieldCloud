###########
# BUILDER #
###########

# pull a builder image, the same as the base
FROM python:3.10.8-slim-buster as build

# Disable annoying pip version check, we don't care if pip is slightly older
ARG PIP_DISABLE_PIP_VERSION_CHECK=1

# Do not craete and use redundant cache dir in the current user home
ARG PIP_NO_CACHE_DIR=1

# install psycopg2 requirements
RUN apt update && apt install -y libpq-dev python3-dev gcc

# install dependencies
COPY ./requirements.txt .
RUN pip3 install -r requirements.txt

# save 60 MB of data... Safe to delete according to botocore contributor https://github.com/boto/botocore/issues/1629#issuecomment-451309885
RUN ls -Q /usr/local/lib/python3.10/site-packages/botocore/data | grep -xv "endpoints.json" | xargs rm -rf


# pull official base image
FROM python:3.10.8-slim-buster as base

# set work directory
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install dependencies
RUN apt update \
    && apt install -y \
# required by PostGIS driver for Django
        python3-gdal \
# required by Fiona
        gdal-bin

# copy the dependencies
COPY --from=build /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/

# install debug dependencies
ARG DEBUG_BUILD
RUN if [ "$DEBUG_BUILD" = "1" ]; then pip install debugpy; fi

# copy project
COPY . .

# create the appropriate directories
RUN mkdir staticfiles
RUN mkdir mediafiles

# chown all the files to the app user
RUN addgroup --system app && adduser --system app --ingroup app
RUN chown -R app:app .
# RUN groupmod -g 1000 app
# RUN usermod -u 1000 app

EXPOSE 8000

# create an empty JSON fixture for the sole purpose of Django's testserver
RUN echo '{}' > fixture.json

# run entrypoint.prod.sh
COPY ./entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]


# a separate stage for webserver runtime environment
FROM base as webserver_runtime
COPY ./requirements_runtime.txt .
RUN pip3 install -r requirements_runtime.txt
USER app


# a separate stage for webserver test environment
FROM base as webserver_test
COPY ./requirements_test.txt .
RUN pip3 install -r requirements_test.txt
USER app


# a separate stage for worker wrapper runtime environment
FROM base as worker_wrapper_runtime
COPY ./requirements_worker_wrapper.txt .
RUN pip3 install -r requirements_worker_wrapper.txt
USER app
