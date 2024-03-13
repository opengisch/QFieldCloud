FROM qgis/qgis:final-3_34_4

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
ENV XDG_RUNTIME_DIR=/root
# allow local development for `libqfieldsync`, requires `/libqfieldsync` to be a mounted host directory
ENV PYTHONPATH=/libqfieldsync:${PYTHONPATH}

# upgrade `pip`. If not upgraded, installing from GitHub repo (needed for `libqfieldsync`) will result in UNKNOWN package.
RUN pip3 install --upgrade pip

# Install regular dependencies that rarely change
COPY requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

# Install `libqfieldsync` dependecy since it changes more frequently compared to regular dependencies
COPY requirements_libqfieldsync.txt /tmp/
RUN pip3 install --use-deprecated=legacy-resolver -r /tmp/requirements_libqfieldsync.txt

COPY schemas schemas
COPY qfc_worker qfc_worker
COPY entrypoint.py .

ENTRYPOINT ["/bin/sh", "-c", "/usr/bin/xvfb-run -a \"$@\"", ""]
