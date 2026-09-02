FROM python:3.14-slim-trixie
WORKDIR /app
RUN pip install --no-cache-dir boto3
COPY purge_deleted_objects.py .
# Keep container running to allow ofelia to exec into it.
CMD ["tail", "-f", "/dev/null"]
