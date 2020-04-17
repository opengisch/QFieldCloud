ARG QGIS_VERSION=latest
FROM qgis/qgis:${QGIS_VERSION}
MAINTAINER Mario Baranzini <mario@opengis.ch>

RUN apt-get update \
    && apt-get install -y \
         python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY ./docker-qgis/requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

COPY ./docker-qgis/entrypoint.sh /
COPY ./docker-qgis/qgis_caller.py /

COPY ./docker-qgis/qfieldsync /
ENV PYTHONPATH="/qfieldsync/qfieldsync:${PYTHONPATH}"

ENV LANG=C.UTF-8

WORKDIR /