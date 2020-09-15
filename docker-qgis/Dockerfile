ARG QGIS_VERSION=latest
FROM qgis/qgis:${QGIS_VERSION}
MAINTAINER Mario Baranzini <mario@opengis.ch>

# Temporary fix because current qgis image doesn't have supervisor installed
# So I rename the suprevisor, config, I install supervisor and I replace the
# original conf file
RUN mv /etc/supervisor/supervisord.conf /etc/supervisor/supervisord.conf.my

RUN apt-get update \
    && apt-get install -y \
         python3-pip \
         supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN mv /etc/supervisor/supervisord.conf.my /etc/supervisor/supervisord.conf

COPY ./docker-qgis/requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

COPY ./docker-qgis/entrypoint.py /
COPY ./docker-qgis/apply_deltas.py /
COPY ./docker-qgis/schemas/deltafile_01.json /schemas/

COPY ./docker-qgis/qfieldsync /
ENV PYTHONPATH="/qfieldsync/qfieldsync:${PYTHONPATH}"

ENV LANG=C.UTF-8

WORKDIR /

# Run supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]