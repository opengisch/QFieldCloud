import csv
import logging
import os
import sys
from typing import Generator

from django.core.management.base import BaseCommand, CommandParser
from qfieldcloud import settings
from qfieldcloud.core import utils

logger = logging.getLogger(__name__)

s3_credentials_envars = [
    "STORAGE_ACCESS_KEY_ID",
    "STORAGE_SECRET_ACCESS_KEY",
    "STORAGE_BUCKET_NAME",
    "STORAGE_REGION_NAME",
    "STORAGE_ENDPOINT_URL",
]


class S3Config:
    config = None

    @classmethod
    def get_or_create(cls, overwrite_settings=False) -> "S3Config":
        if not cls.config:
            cls.config = cls(s3_credentials_envars, overwrite_settings)
        return cls.config

    def __init__(self, keys: list[str], *args, **kwargs):
        values = [os.environ.get(k) for k in keys]
        zipped = zip(keys, values)
        missing = [key for key, value in zipped if value is None]

        if missing:
            logger.error(
                f"These environment variables are missing a value: {','.join(missing)}"
            )
            sys.exit(1)

        for key, value in zipped:
            setattr(self, key, value)

            if kwargs.get("overwrite_settings", False):
                setattr(settings, key, value)


class Command(BaseCommand):
    """Save metadata from S3 storage project files to disk."""

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("-o", "--output", type=str, help="Name of output file")
        parser.add_argument(
            "-f", "--config_file", type=str, help=".env file with your S3 credentials"
        )

    def handle(self, *args, **options):
        if options.get("config_file"):
            S3Config.get_or_create(overwrite_settings=True)

        output_name = options.get("output")

        if output_name:
            name_suffix = output_name.rsplit(".", 1)
            if len(name_suffix) < 2 or name_suffix[1] != "csv":
                logger.error("The name of the output file should end with '.csv'")
                sys.exit(1)
        else:
            output_name = "s3_storage_files.csv"

        bucket = utils.get_s3_bucket()
        interesting_fields = ["id", "key", "e_tag", "size"]

        def get_rows() -> Generator[list[str], None, None]:
            for file in bucket.object_versions.all():
                row = []
                for field in interesting_fields:
                    if hasattr(file, field):
                        item = getattr(file, field)
                        if not isinstance(item, str):
                            item = str(item)
                        row.append(item.strip('"'))
                yield row

        with open(output_name, "w") as fh:
            writer = csv.writer(fh, delimiter=",")
            writer.writerow(interesting_fields)
            writer.writerows(get_rows())

        logger.info(f"Successfully exported data to {output_name}")
