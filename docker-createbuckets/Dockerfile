FROM ubuntu:noble

RUN apt-get update \
    && apt-get install -y \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L https://github.com/rustfs/cli/releases/download/v0.1.12/rustfs-cli-linux-amd64-gnu-v0.1.12.tar.gz \
    | tar -xz -C /usr/bin rc
RUN chmod +x /usr/bin/rc

COPY ./createbuckets.py /createbuckets.py
RUN chmod +x /createbuckets.py

ENTRYPOINT ["/createbuckets.py"]
