FROM ubuntu:noble

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y \
    curl \
    python3

RUN curl https://dl.minio.io/client/mc/release/linux-amd64/archive/mc.RELEASE.2025-02-18T16-25-55Z.fips -o /usr/bin/mc
RUN chmod +x /usr/bin/mc

COPY ./createbuckets.py /createbuckets.py
RUN chmod +x /createbuckets.py

ENTRYPOINT /createbuckets.py
