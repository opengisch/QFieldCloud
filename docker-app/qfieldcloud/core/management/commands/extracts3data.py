import csv
import logging
from sys import stdout
from typing import Generator, Iterable

import mypy_boto3_s3
from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandParser
from storages.backends.s3boto3 import S3Boto3Storage

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Prepare a CSV with the storage files metadata
    Example usage:
    ```
    docker compose exec app python manage.py extracts3data \
        --output results.csv \
        --storage-name
    ```
    """

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            "-o", "--output", type=str, help="Optional: Name of output file"
        )
        parser.add_argument(
            "--storage-name",
            type=str,
            choices=self._get_supported_storage_names(),
            help="Storage name as defined in `STORAGES` envvar",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default="",
            help="File prefix to search for",
        )

    def handle(self, **options):
        bucket = self.get_s3_bucket(options["storage_name"])
        output_filename = options.get("output")
        fields = [
            "key",
            "version_id",
            "e_tag",
            "size",
            "is_latest",
            "last_modified",
        ]
        rows = self.read_bucket_files(bucket, fields, options.get("prefix", ""))

        if output_filename:
            handle = open(output_filename, "w")
        else:
            handle = stdout

        writer = csv.writer(handle, delimiter=",")
        writer.writerow(fields)
        writer.writerows(rows)

        if output_filename:
            handle.close()

        logger.info(f"Successfully exported data to {output_filename or 'STDOUT'}")

    @staticmethod
    def get_s3_bucket(storage_name: str) -> mypy_boto3_s3.service_resource.Bucket:
        storage = storages[storage_name]

        if not isinstance(storage, S3Boto3Storage):
            raise NotImplementedError(
                "Using the `extracts3data` command only supports S3 storages!"
            )

        # Access the bucket name
        bucket_name = storage.bucket_name

        # Access the raw boto3 bucket
        return storage.connection.Bucket(bucket_name)

    @staticmethod
    def read_bucket_files(
        bucket: mypy_boto3_s3.service_resource.Bucket,
        fields: Iterable[str],
        prefix: str = "",
    ) -> Generator[list[str], None, None]:
        """Yield file metadata 1 by 1. Passing `prefix=""` will list all bucket objects."""

        for version in bucket.object_versions.filter(Prefix=prefix):
            row = []

            for field in fields:
                item = getattr(version, field)

                if not isinstance(item, str):
                    item = str(item)

                row.append(item)

            yield row

    def _get_supported_storage_names(self) -> list[str]:
        """Get storage names that are supported by the command"""
        storage_names = []

        for storage_name, storage_config in settings.STORAGES.items():
            storage = storages[storage_name]

            # currently we only support S3 storage
            if not isinstance(storage, S3Boto3Storage):
                continue

            storage_names.append(storage_name)

        return storage_names
