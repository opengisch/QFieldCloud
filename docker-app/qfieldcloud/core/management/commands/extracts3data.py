import csv
import logging
from sys import stdout
from typing import Generator, NamedTuple

import boto3
import mypy_boto3_s3
from django.core.management.base import BaseCommand, CommandParser

logger = logging.getLogger(__name__)


class S3ConfigObject(NamedTuple):
    storage_access_key_id: str
    storage_secret_access_key: str
    storage_bucket_name: str
    storage_endpoint_url: str
    storage_region_name: str


class Command(BaseCommand):
    """
    Save metadata from S3 storage project files to disk.
    Example usage:
    ```
    docker compose exec app python manage.py extracts3data \
        --output results.csv \
        --storage_access_key_id ... \
        --storage_secret_access_key ... \
        --storage_bucket_name ... \
        --storage_endpoint_url ... \
        --storage_region_name ...
    ```
    """

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            "-o", "--output", type=str, help="Optional: Name of output file"
        )
        parser.add_argument(
            "--storage_access_key_id",
            type=str,
            help="S3 access key ID",
        )
        parser.add_argument(
            "--storage_secret_access_key",
            type=str,
            help="S3 access key secret",
        )
        parser.add_argument(
            "--storage_bucket_name",
            type=str,
            help="S3 bucket name",
        )
        parser.add_argument(
            "--storage_endpoint_url",
            type=str,
            help="S3 endpoint url",
        )
        parser.add_argument(
            "--storage_region_name",
            type=str,
            help="S3 region name",
        )

    def handle(self, **options):
        build_config = {}
        for key, value in options.items():
            if key in S3ConfigObject._fields:
                build_config[key] = value

        config = S3ConfigObject(**build_config)
        bucket = self.get_s3_bucket(config)
        output_name = options.get("output")
        fields = (
            "id",
            "key",
            "e_tag",
            "size",
            "last_modified",
        )
        rows = self.read_bucket_files(bucket, fields)

        if output_name:
            handle = open(output_name, "w")
        else:
            handle = stdout

        writer = csv.writer(handle, delimiter=",")
        writer.writerow(fields)
        writer.writerows(rows)

        if output_name:
            handle.close()

        logger.info(f"Successfully exported data to {output_name}")

    @staticmethod
    def get_s3_bucket(config: S3ConfigObject) -> mypy_boto3_s3.service_resource.Bucket:
        """Get a new S3 Bucket instance using S3ConfigObject"""
        bucket_name = config.storage_bucket_name
        session = boto3.Session(
            aws_access_key_id=config.storage_access_key_id,
            aws_secret_access_key=config.storage_secret_access_key,
            region_name=config.storage_region_name,
        )
        s3 = session.resource("s3", endpoint_url=config.storage_endpoint_url)
        return s3.Bucket(bucket_name)

    @staticmethod
    def read_bucket_files(
        bucket, fields: tuple[str], prefix: str = ""
    ) -> Generator[list[str], None, None]:
        """Yield file metadata 1 by 1. Passing `prefix=""` will list all bucket objects."""

        for file in bucket.object_versions.filter(Prefix=prefix):
            row = []

            for field in fields:
                item = getattr(file, field)

                if not isinstance(item, str):
                    item = str(item)

                # some fields (e.g. `e_tag`) have unnecessary `"` (double quotes) in their value.
                item = item.strip('"')
                row.append(item)

            yield row
