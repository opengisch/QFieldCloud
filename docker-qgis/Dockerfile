# NOTE if the ubuntu version is changed, also change it in `Suites:` in apt sources, and in `QGIS_VERSION`
FROM ubuntu:jammy

# Install dependencies needed to add QGIS repository
RUN apt update \
    && apt upgrade -y \
    && apt install -y gnupg software-properties-common wget

# Add QGIS GPG key
RUN wget -O /etc/apt/keyrings/qgis-archive-keyring.gpg https://download.qgis.org/downloads/qgis-archive-keyring.gpg

# Add QGIS repository
COPY <<EOF /etc/apt/sources.list.d/qgis.sources
Types: deb deb-src
URIs: https://qgis.org/debian
Suites: jammy
Architectures: amd64
Components: main
Signed-By: /etc/apt/keyrings/qgis-archive-keyring.gpg
EOF

# Install non-QGIS dependencies
RUN apt update \
    && apt upgrade -y \
    && apt install -y \
    python3-pip \
    xvfb \
    iputils-ping \
    glibc-tools \
    git

# Set QGIS version as in the debian repos
ARG QGIS_VERSION=1:3.34.2+36jammy

# Install QGIS dependencies
RUN apt update \
    && apt upgrade -y \
    # NOTE `DEBIAN_FRONTEND=noninteractive` is required to be able to install tzinfo
    && DEBIAN_FRONTEND=noninteractive apt install -yf \
        qgis=${QGIS_VERSION} \
        qgis-dbg=${QGIS_VERSION} \
        qgis-common=${QGIS_VERSION} \
        python3-qgis=${QGIS_VERSION} \
        python3-qgis-common=${QGIS_VERSION} \
        qgis-providers=${QGIS_VERSION} \
        qgis-providers-common=${QGIS_VERSION} \
    && apt clean

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
