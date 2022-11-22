###########
# BUILDER #
###########

# pull official base image
FROM python:3.8.0-buster as builder

# set work directory
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install dependencies
RUN apt update \
    && apt install -y netcat python3-gdal

# install dependencies
COPY ./requirements.txt .
RUN find . -name "requirements*.txt" -type f -exec pip3 install -r '{}' ';'

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

# change to the app user
USER app

EXPOSE 8000

# create an empty JSON fixture for the sole purpose of Django's testserver
RUN echo '{}' > fixture.json

# run entrypoint.prod.sh
COPY ./entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
