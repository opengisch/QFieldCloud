import csv
import logging
import sys
from typing import Generator, NamedTuple

import boto3
import mypy_boto3_s3
from django.core.management.base import BaseCommand, CommandParser
from qfieldcloud.core import utils

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Save metadata from S3 storage project files to disk."""

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            "-o", "--output", type=str, help="Optional: Name of output file"
        )
        parser.add_argument(
            "-s3",
            "--s3_credentials",
            type=str,
            help="""
            Optional: S3 credentials as comma-separated key=value pairs.
            Example: -s3 STORAGE_ACCESS_KEY_ID=...,STORAGE_SECRET_ACCESS_KEY=...,...
        """,
        )

    def handle(self, *args, **options):
        config = None

        if options.get("s3_credentials"):
            config = self.from_shell(options["s3_credentials"])
            bucket = self.get_s3_bucket(config)

        else:
            bucket = utils.get_s3_bucket()

        output_name = options.get("output")

        if output_name:
            name_suffix = output_name.rsplit(".", 1)

            if len(name_suffix) != 2 or name_suffix[1] != "csv":
                logger.error("The name of the output file should end with '.csv'")
                sys.exit(1)
        else:
            output_name = "s3_storage_files.csv"

        fields = (
            "id",
            "key",
            "e_tag",
            "size",
            "last_modified",
        )
        rows = self.read_bucket_files(bucket, fields)

        with open(output_name, "w") as fh:
            writer = csv.writer(fh, delimiter=",")
            writer.writerow(fields)
            writer.writerows(rows)

        logger.info(f"Successfully exported data to {output_name}")

    class S3ConfigObject(NamedTuple):
        STORAGE_ACCESS_KEY_ID: str
        STORAGE_BUCKET_NAME: str
        STORAGE_ENDPOINT_URL: str
        STORAGE_REGION_NAME: str
        STORAGE_SECRET_ACCESS_KEY: str

    @staticmethod
    def from_shell(user_input: str) -> S3ConfigObject:
        try:
            keys_vals = user_input.split(",")
            builder = {}

            for key_val in keys_vals:
                key, val = key_val.split("=", 1)
                if val is None or val.strip() == "":
                    logger.warning(f"Blank or None value at key {key}")
                builder[key] = val.strip()

            config = Command.S3ConfigObject(**builder)
        except Exception:
            logger.error(
                f"Unable to extract valid S3 storage credentials from your input: {user_input}"
            )
            sys.exit(1)
        return config

    @staticmethod
    def get_s3_bucket(config: S3ConfigObject) -> mypy_boto3_s3.service_resource.Bucket:
        """Get a new S3 Bucket instance using S3ConfigObject"""
        bucket_name = config.STORAGE_BUCKET_NAME
        session = boto3.Session(
            aws_access_key_id=config.STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=config.STORAGE_SECRET_ACCESS_KEY,
            region_name=config.STORAGE_REGION_NAME,
        )
        s3 = session.resource("s3", endpoint_url=config.STORAGE_ENDPOINT_URL)
        return s3.Bucket(bucket_name)

    @staticmethod
    def read_bucket_files(
        bucket, fields: tuple[str], prefix: str = ""
    ) -> Generator[list[str], None, None]:
        """Yield file metadata 1 by 1. `...object_versions.filter(prefix="")` == `...object_versions.all()`"""

        for file in bucket.object_versions.filter(Prefix=prefix):
            row = []

            for field in fields:

                try:
                    item = getattr(file, field)
                except AttributeError:
                    logger.error(
                        f"Unable to find attribute '{field}', perhaps you were trying to get one of these instead {vars(file)}?"
                    )
                    sys.exit(1)

                if not isinstance(item, str):
                    item = str(item)

                # some fields (e.g. `e_tag`) have unnecessary `"` (double quotes) in their value.
                item = item.strip('"')
                row.append(item)

            yield row
