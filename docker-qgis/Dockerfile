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

COPY ./requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

WORKDIR /usr/src/app

COPY entrypoint.py .
COPY ./apply_deltas.py ./lib/qfieldcloud/qgis/
COPY ./process_projectfile.py ./lib/qfieldcloud/qgis/
COPY ./utils.py ./lib/qfieldcloud/qgis/
COPY ./schemas/deltafile_01.json ./lib/qfieldcloud/qgis/schemas/
COPY ./libqfieldsync ./lib/libqfieldsync

ENV PYTHONPATH="/usr/src/app/lib:${PYTHONPATH}"
ENV LD_PRELOAD="/lib/x86_64-linux-gnu/libSegFault.so"
ENV SEGFAULT_SIGNALS="abrt segv"
ENV LIBC_FATAL_STDERR_=1

# Add supervisor service configuration script
COPY ./supervisord.conf /etc/supervisor/

ENV LANG=C.UTF-8


# Run supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
