# NOTE if the ubuntu version is changed, also change it in `Suites:` in apt sources, and in `QGIS_VERSION`
FROM ubuntu:noble

# Create the expected /io directory that is usually created via the `worker_wrapper`
RUN mkdir -p /io

# Install dependencies needed to add QGIS repository
RUN apt-get update \
    && apt-get install -y \
    gnupg \
    software-properties-common \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Add QGIS GPG key
RUN wget -O /etc/apt/keyrings/qgis-archive-keyring.gpg https://download.qgis.org/downloads/qgis-archive-keyring.gpg

# Add QGIS repository
RUN echo "Types: deb deb-src\n\
URIs: https://qgis.org/debian\n\
Suites: noble\n\
Architectures: amd64\n\
Components: main\n\
Signed-By: /etc/apt/keyrings/qgis-archive-keyring.gpg\n" > /etc/apt/sources.list.d/qgis.sources

# Disable annoying pip version check, we don't care if pip is slightly older
ARG PIP_DISABLE_PIP_VERSION_CHECK=1

# Do not create and use redundant cache dir in the current user home
ARG PIP_NO_CACHE_DIR=1

# Install non-QGIS dependencies
RUN apt-get update \
    && apt-get install -y \
    python3-pip \
    xvfb \
    iputils-ping \
    glibc-tools \
    git \
    && rm -rf /var/lib/apt/lists/*


# Set QGIS version as in the debian repos
# Choose your version from here: https://debian.qgis.org/debian/dists/noble/main/binary-amd64/Packages
ARG QGIS_VERSION=1:3.44.3+40noble

# Install QGIS dependencies
RUN apt-get update \
    # NOTE `DEBIAN_FRONTEND=noninteractive` is required to be able to install tzinfo
    && DEBIAN_FRONTEND=noninteractive apt-get install -yf \
        qgis=${QGIS_VERSION} \
        qgis-dbg=${QGIS_VERSION} \
        qgis-common=${QGIS_VERSION} \
        python3-qgis=${QGIS_VERSION} \
        python3-qgis-common=${QGIS_VERSION} \
        qgis-providers=${QGIS_VERSION} \
        qgis-providers-common=${QGIS_VERSION} \
    && rm -rf /var/lib/apt/lists/*

# If debug build, install `gdbserver`
ARG DEBUG_BUILD
RUN if [ "$DEBUG_BUILD" = "1" ]; then \
    apt-get update \
    && apt-get install -y \
    gdbserver \
    valgrind \
    && rm -rf /var/lib/apt/lists/* \
    ; fi

WORKDIR /usr/src/app

# crashes to STDERR
ENV LD_PRELOAD="/lib/x86_64-linux-gnu/libSegFault.so"
ENV SEGFAULT_SIGNALS="abrt segv"
ENV LIBC_FATAL_STDERR_=1

# other env
ENV LANG=C.UTF-8
ENV XDG_RUNTIME_DIR=/root
# allow local development for `libqfieldsync`, requires `/libqfieldsync` to be a mounted host directory
ENV PYTHONPATH=/libqfieldsync
ENV PYTHONPATH=/qfieldcloud-sdk-python:${PYTHONPATH}

# Install debugpy for local development and debuggability
ARG DEBUG_BUILD
RUN if [ "$DEBUG_BUILD" = "1" ]; then pip3 install --break-system-packages debugpy; fi

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
