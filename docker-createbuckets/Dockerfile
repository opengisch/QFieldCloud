FROM ubuntu:noble

RUN apt-get update \
    && apt-get install -y \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Download MinIO client for the correct architecture
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        curl https://dl.min.io/client/mc/release/linux-amd64/archive/mc.RELEASE.2025-03-12T17-29-24Z -o /usr/bin/mc; \
    elif [ "$ARCH" = "aarch64" ]; then \
        curl https://dl.min.io/client/mc/release/linux-arm64/archive/mc.RELEASE.2025-03-12T17-29-24Z -o /usr/bin/mc; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    chmod +x /usr/bin/mc

COPY ./createbuckets.py /createbuckets.py
RUN chmod +x /createbuckets.py

ENTRYPOINT ["/createbuckets.py"]
