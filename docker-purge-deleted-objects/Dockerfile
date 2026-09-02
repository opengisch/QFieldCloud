FROM python:3.14-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# install Python dependencies
COPY ./requirements.txt /requirements.txt
RUN uv pip install --system --no-cache -r /requirements.txt \
    && rm /requirements.txt

COPY ./purge_deleted_objects.py /purge_deleted_objects.py

# Keep container running to allow ofelia to exec into it.
CMD ["tail", "-f", "/dev/null"]
