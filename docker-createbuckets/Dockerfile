FROM ubuntu:noble

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y \
    curl \
    python3

RUN curl https://dl.min.io/client/mc/release/linux-amd64/archive/mc.RELEASE.2025-03-12T17-29-24Z -o /usr/bin/mc
RUN chmod +x /usr/bin/mc

COPY ./createbuckets.py /createbuckets.py
RUN chmod +x /createbuckets.py

ENTRYPOINT /createbuckets.py
