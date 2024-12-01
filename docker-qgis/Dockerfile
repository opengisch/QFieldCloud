# NOTE if the ubuntu version is changed, also change it in `Suites:` in apt sources, and in `QGIS_VERSION`
FROM ubuntu:noble

# Install dependencies needed to add QGIS repository
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y gnupg software-properties-common wget

# Add QGIS GPG key
RUN wget -O /etc/apt/keyrings/qgis-archive-keyring.gpg https://download.qgis.org/downloads/qgis-archive-keyring.gpg

# Add QGIS repository
RUN echo "Types: deb deb-src\n\
URIs: https://qgis.org/debian\n\
Suites: noble\n\
Architectures: amd64\n\
Components: main\n\
Signed-By: /etc/apt/keyrings/qgis-archive-keyring.gpg\n" > /etc/apt/sources.list.d/qgis.sources

# Install non-QGIS dependencies
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y \
    python3-pip \
    xvfb \
    iputils-ping \
    glibc-tools \
    git

# Set QGIS version as in the debian repos
# Choose your version from here: https://debian.qgis.org/debian/dists/noble/main/binary-amd64/Packages
ARG QGIS_VERSION=1:3.40.1+40noble

# Install QGIS dependencies
RUN apt-get update \
    && apt-get upgrade -y \
    # NOTE `DEBIAN_FRONTEND=noninteractive` is required to be able to install tzinfo
    && DEBIAN_FRONTEND=noninteractive apt-get install -yf \
        qgis=${QGIS_VERSION} \
        qgis-dbg=${QGIS_VERSION} \
        qgis-common=${QGIS_VERSION} \
        python3-qgis=${QGIS_VERSION} \
        python3-qgis-common=${QGIS_VERSION} \
        qgis-providers=${QGIS_VERSION} \
        qgis-providers-common=${QGIS_VERSION} \
    && apt-get clean

# If debug build, install `gdbserver`
ARG DEBUG_BUILD
RUN if [ "$DEBUG_BUILD" = "1" ]; then apt install -y gdbserver valgrind; fi

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
ENV PYTHONPATH=/qfieldcloud-sdk-python:${PYTHONPATH}

# Install regular dependencies that rarely change
COPY requirements.txt /tmp/
RUN pip3 install --break-system-packages --ignore-installed -r /tmp/requirements.txt

# Install `libqfieldsync` dependecy since it changes more frequently compared to regular dependencies
COPY requirements_libqfieldsync.txt /tmp/
RUN pip3 install --break-system-packages --use-deprecated=legacy-resolver -r /tmp/requirements_libqfieldsync.txt

COPY schemas schemas
COPY qfc_worker qfc_worker
COPY entrypoint.py .

ENTRYPOINT ["/bin/sh", "-c", "/usr/bin/xvfb-run -a \"$@\"", ""]
