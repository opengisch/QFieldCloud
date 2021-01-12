FROM ubuntu:20.04

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get -y install wget gpg && \
    wget -O - https://qgis.org/downloads/qgis-2020.gpg.key | gpg --import && \
    gpg --export --armor F7E06F06199EF2F2 | apt-key add - && \
    echo 'deb http://qgis.org/ubuntu focal main' > /etc/apt/sources.list.d/ubuntu-qgis.list


RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    qgis \
    python3-qgis \
    python3-qgis-common \
    python3-pip \
    supervisor \
    xvfb \
    && apt-get clean

COPY ./docker-qgis/requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

COPY ./docker-qgis/entrypoint.py /
COPY ./docker-qgis/apply_deltas.py /
COPY ./docker-qgis/schemas/deltafile_01.json /schemas/

COPY ./docker-qgis/libqfieldsync /libqfieldsync
ENV PYTHONPATH="/libqfieldsync:${PYTHONPATH}"

# Add supervisor service configuration script
COPY ./docker-qgis/supervisord.conf /etc/supervisor/

ENV LANG=C.UTF-8

WORKDIR /

# Run supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
