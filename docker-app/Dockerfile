##########################
# BUILDER                #
##########################

# pull a builder image, the same as the base
FROM python:3.10.8-slim-buster as build

# Disable annoying pip version check, we don't care if pip is slightly older
ARG PIP_DISABLE_PIP_VERSION_CHECK 1

# Do not create and use redundant cache dir in the current user home
ARG PIP_NO_CACHE_DIR 1

# install psycopg2 requirements
RUN apt update && apt install -y libpq-dev python3-dev gcc

# install dependencies
COPY ./requirements.txt .
RUN pip3 install -r requirements.txt

# save 60 MB of data... Safe to delete according to botocore contributor https://github.com/boto/botocore/issues/1629#issuecomment-451309885
RUN ls -Q /usr/local/lib/python3.10/site-packages/botocore/data | grep -xv "endpoints.json" | xargs rm -rf

##########################
# BASE                   #
##########################

# pull official base image
FROM python:3.10.8-slim-buster as base

# set work directory
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
# check `build` stage for more info
# NOTE while using ARG would be more appropriate, the following vars would have to be redifined for each build stage.
ENV PIP_DISABLE_PIP_VERSION_CHECK 1
ENV PIP_NO_CACHE_DIR 1

# install dependencies
RUN apt update && apt-get install -y \
# GeoDjango as recommended at https://docs.djangoproject.com/en/4.1/ref/contrib/gis/install/geolibs/#installing-geospatial-libraries
    binutils libproj-dev gdal-bin \
# needed for Django's `manage.py makemessages`
    gettext \
# for development purposes only (optional dependency for `django-extensions`)
    graphviz

# copy the dependencies
COPY --from=build /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/

# install debug dependencies
ARG DEBUG_BUILD
RUN if [ "$DEBUG_BUILD" = "1" ]; then pip3 install debugpy; fi

# add app group
RUN addgroup --system app && adduser --system app --ingroup app

# create the appropriate directories
RUN mkdir staticfiles
RUN mkdir mediafiles

# create an empty JSON fixture for the sole purpose of Django's testserver
RUN echo '{}' > fixture.json

# Do not uncomment unless you want to share the user id between the host and the container
# RUN groupmod -g 1000 app
# RUN usermod -u 1000 app

COPY ./entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

##########################
# WEBSERVER RUNTIME      #
##########################

# a separate stage for webserver runtime environment
FROM base as webserver_runtime
ENV LOGGER_SOURCE=app
COPY ./requirements_runtime.txt .
RUN pip3 install -r requirements_runtime.txt
EXPOSE 8000

COPY . .
RUN chown -R app:app .
USER app

##########################
# WEBSERVER TEST         #
##########################

# a separate stage for webserver test environment
FROM base as webserver_test
ENV LOGGER_SOURCE=app
COPY ./requirements_test.txt .
RUN pip3 install -r requirements_test.txt
EXPOSE 8000

COPY . .
RUN chown -R app:app .
USER app

##########################
# WORKER WRAPPER RUNTIME #
##########################

# a separate stage for worker wrapper runtime environment
FROM base as worker_wrapper_runtime
ENV LOGGER_SOURCE=worker_wrapper
COPY ./requirements_worker_wrapper.txt .
RUN pip3 install -r requirements_worker_wrapper.txt

COPY . .
RUN chown -R app:app .
USER app
