# Usually the ARGs are passed via docker-compose.yml, but we set them here as well to have default values and to be able to build the image standalone without passing the args.

# Base Ubuntu image
ARG UBUNTU_VERSION=noble

# QGIS repository to use, either `ubuntu-ltr` or `debian`
ARG QGIS_REPOSITORY=ubuntu-ltr

# Set QGIS version as in the ubuntu/debian repos.
# Choose your version from here: https://debian.qgis.org/ubuntu-ltr/dists/noble/main/binary-amd64/Packages or https://debian.qgis.org/debian/dists/resolute/main/binary-amd64/Packages
ARG QGIS_VERSION=1:3.44.10+40noble

# Start from a basic Ubuntu image
FROM ubuntu:${UBUNTU_VERSION}

# Redeclare within the stage, otherwise the variables will not be available in the `RUN` commands.
ARG UBUNTU_VERSION
ARG QGIS_REPOSITORY
ARG QGIS_VERSION

# Print the values of the build arguments to verify they are correctly passed
RUN echo "UBUNTU_VERSION=${UBUNTU_VERSION}"
RUN echo "QGIS_REPOSITORY=${QGIS_REPOSITORY}"
RUN echo "QGIS_VERSION=${QGIS_VERSION}"

# Create the expected /io directory that is usually created via the `worker_wrapper`
RUN mkdir -p /io

# Install dependencies needed to add QGIS repository
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gnupg \
    software-properties-common \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Add QGIS GPG key
RUN wget -q -O /etc/apt/keyrings/qgis-archive-keyring.gpg https://download.qgis.org/downloads/qgis-archive-keyring.gpg

# Add QGIS repository
RUN cat > /etc/apt/sources.list.d/qgis.sources <<EOF
Types: deb deb-src
URIs: https://qgis.org/${QGIS_REPOSITORY}
Suites: ${UBUNTU_VERSION}
Architectures: amd64
Components: main
Signed-By: /etc/apt/keyrings/qgis-archive-keyring.gpg
EOF

# Disable annoying pip version check, we don't care if pip is slightly older
ARG PIP_DISABLE_PIP_VERSION_CHECK=1

# Do not create and use redundant cache dir in the current user home
ARG PIP_NO_CACHE_DIR=1

# Install non-QGIS dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    python3-pip \
    xvfb \
    iputils-ping \
    glibc-tools \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install QGIS dependencies
RUN apt-get update \
    # NOTE `DEBIAN_FRONTEND=noninteractive` is required to be able to install tzinfo
    && DEBIAN_FRONTEND=noninteractive apt-get install -yf --no-install-recommends \
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
    && apt-get install -y --no-install-recommends \
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
ENV PYTHONPATH=/usr/share/qgis/python:${PYTHONPATH}

# Fix for "error: the configured Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)"
ENV PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

# QFC specific variables
# Controls whether libqfieldsync should log also to the QGIS message log
ENV IS_WITHIN_QFC_WORKER=1

# Install debugpy for local development and debuggability
ARG DEBUG_BUILD
RUN if [ "$DEBUG_BUILD" = "1" ]; then pip3 install --no-cache-dir --break-system-packages debugpy; fi

# Install regular dependencies that rarely change
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages --ignore-installed -r /tmp/requirements.txt

# Install `libqfieldsync` dependency since it changes more frequently compared to regular dependencies
COPY requirements_internal.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages --use-deprecated=legacy-resolver -r /tmp/requirements_internal.txt

COPY schemas schemas
COPY qfc_worker qfc_worker
COPY entrypoint.py .

ENTRYPOINT ["/bin/sh", "-c", "/usr/bin/xvfb-run -a \"$@\"", ""]
