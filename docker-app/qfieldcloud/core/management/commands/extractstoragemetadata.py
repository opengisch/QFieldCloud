import csv
import logging
import sys
from pathlib import Path
from typing import Generator, NamedTuple

import boto3
import mypy_boto3_s3
import yaml
from django.core.management.base import BaseCommand, CommandParser
from qfieldcloud.core import utils

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Save metadata from S3 storage project files to disk."""

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("-o", "--output", type=str, help="Name of output file")
        parser.add_argument(
            "-f",
            "--config_file",
            type=str,
            help="Path to YAML file with your S3 credentials",
        )

    def handle(self, *args, **options):
        config = None

        if options.get("config_file"):
            path = Path(options["config_file"])

            if not path.is_file():
                logger.error(f"This path does not exist or is not a file: {path}")
                sys.exit(1)

            config = self.from_file(path)
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

        fields = ["id", "key", "e_tag", "size", "create_time"]
        rows = self.read_bucket_files(bucket, fields)

        with open(output_name, "w") as fh:
            writer = csv.writer(fh, delimiter=",")
            writer.writerow(fields)
            writer.writerows(rows)

        logger.info(f"Successfully exported data to {output_name}")

    class S3ConfigObject(NamedTuple):
        STORAGE_ACCESS_KEY_ID: str
        STORAGE_SECRET_ACCESS_KEY: str
        STORAGE_BUCKET_NAME: str
        STORAGE_REGION_NAME: str
        STORAGE_ENDPOINT_URL: str

    @staticmethod
    def from_file(path_to_config: Path) -> S3ConfigObject:
        """Load a YAML file exposing credentials used by S3 storage"""
        with open(path_to_config) as fh:
            contents = yaml.safe_load(fh)

        config = {
            k: v for k, v in contents.items() if k in Command.S3ConfigObject._fields
        }
        return Command.S3ConfigObject(**config)

    @staticmethod
    def get_s3_bucket(config: S3ConfigObject) -> mypy_boto3_s3.service_resource.Bucket:
        """Get a new S3 Bucket instance using S3ConfigObject"""

        bucket_name = config.STORAGE_BUCKET_NAME
        assert bucket_name, "Expected `bucket_name` to be non-empty string!"

        session = boto3.Session(
            aws_access_key_id=config.STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=config.STORAGE_SECRET_ACCESS_KEY,
            region_name=config.STORAGE_REGION_NAME,
        )
        s3 = session.resource("s3", endpoint_url=config.STORAGE_ENDPOINT_URL)

        # Ensure the bucket exists
        s3.meta.client.head_bucket(Bucket=bucket_name)

        # Get the bucket resource
        return s3.Bucket(bucket_name)

    @staticmethod
    def read_bucket_files(
        bucket, fields: list[str]
    ) -> Generator[list[str], None, None]:
        """Generator yielding file metadata 1 by 1"""
        for file in bucket.object_versions.all():
            row = []

            for field in fields:
                item = getattr(file, field)

                if not isinstance(item, str):
                    item = str(item)

                item = item.strip('"')
                row.append(item)

            yield row
