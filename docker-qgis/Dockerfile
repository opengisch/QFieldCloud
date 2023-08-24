FROM qgis/qgis:final-3_30_2 AS base

RUN apt-get update \
    && apt-get upgrade -y \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3-pip \
    xvfb \
    iputils-ping \
    glibc-tools \
    && apt-get clean

WORKDIR /usr/src/app

# crashes to STDERR
ENV LD_PRELOAD="/lib/x86_64-linux-gnu/libSegFault.so"
ENV SEGFAULT_SIGNALS="abrt segv"
ENV LIBC_FATAL_STDERR_=1

# other env
ENV LANG=C.UTF-8
ENV PYTHONPATH="/usr/src/app/lib:${PYTHONPATH}"
ENV XDG_RUNTIME_DIR=/root

COPY ./requirements.txt /tmp/
RUN pip3 install --upgrade pip
RUN pip3 install -r /tmp/requirements.txt

COPY entrypoint.py .
COPY ./apply_deltas.py ./lib/qfieldcloud/qgis/
COPY ./process_projectfile.py ./lib/qfieldcloud/qgis/
COPY ./utils.py ./lib/qfieldcloud/qgis/
COPY ./schemas/deltafile_01.json ./schemas/

ENTRYPOINT ["/bin/sh", "-c", "/usr/bin/xvfb-run -a \"$@\"", ""]

FROM base AS dev
# Install libqfieldsync in development mode (see https://setuptools.pypa.io/en/latest/userguide/development_mode.html)
ENTRYPOINT ["/bin/sh", "-c", "pip install -e /libqfieldsync && /usr/bin/xvfb-run -a \"$@\"", ""]
