import csv
import logging
import sys
from collections import namedtuple
from functools import reduce
from pathlib import Path
from typing import Any, Generator

import yaml
from django.core.management.base import BaseCommand, CommandParser
from qfieldcloud import settings
from qfieldcloud.core import utils

logger = logging.getLogger(__name__)

s3_credentials_keys = [
    "STORAGE_ACCESS_KEY_ID",
    "STORAGE_SECRET_ACCESS_KEY",
    "STORAGE_BUCKET_NAME",
    "STORAGE_REGION_NAME",
    "STORAGE_ENDPOINT_URL",
]


class S3Config:
    _config = None

    @staticmethod
    def from_file(path_to_config: Path) -> dict[str, Any]:
        """Load a YAML file exposing credentials used by S3 storage"""
        with open(path_to_config) as fh:
            contents = yaml.safe_load(fh)
        return contents

    @staticmethod
    def validate(contents: dict[str, Any]) -> dict[str, Any]:
        """Validate key/values used by S3 storage"""
        reporter = {"missing_value": [], "extra_key": []}

        def reducer(acc, item):
            key, val = item
            if key not in s3_credentials_keys:
                acc["extra_key"].append(key)
            if val in ("", None):
                acc["missing_value"].append(key)
            return acc

        reported = reduce(reducer, contents.items(), reporter)
        reported["missing_key"] = [
            key for key in s3_credentials_keys if key not in contents.keys()
        ]

        if any(reported.values()):
            logger.error(f"Invalid config!: {reported}")
            sys.exit(1)

        return contents

    @classmethod
    def get_or_create_from(cls, path_to_file: str | None) -> "S3Config":
        """Get or create configuation for S3 storage."""
        if not cls._config:
            if not path_to_file:
                logger.error(
                    "You need to pass a valid path to your YAML configuration file"
                )
                sys.exit(1)
            maybe_valid_config = cls.from_file(path_to_file)
            valid_config = cls.validate(maybe_valid_config)
            config_container = namedtuple("S3ConfigObject", s3_credentials_keys)
            cls._config = config_container(**valid_config)

        return cls._config

    @classmethod
    def inject_to_settings(cls):
        """To avoid passing s3 config as parameters"""
        for key, value in cls._config._asdict().items():
            setattr(settings, key, value)


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
        if options.get("config_file"):
            path = Path(options["config_file"])

            if not (path.exists() and path.is_file()):
                logger.error(f"This path does not exist or is not a file: {path}")
                sys.exit(1)

            config = S3Config.get_or_create_from(path)
            config.inject_to_settings()

        output_name = options.get("output")

        if output_name:
            name_suffix = output_name.rsplit(".", 1)

            if len(name_suffix) != 2 or name_suffix[1] != "csv":
                logger.error("The name of the output file should end with '.csv'")
                sys.exit(1)
        else:
            output_name = "s3_storage_files.csv"

        interesting_fields = ["id", "key", "e_tag", "size", "create_time"]
        bucket = utils.get_s3_bucket()

        def gen_rows() -> Generator[list[str], None, None]:
            for file in bucket.object_versions.all():
                row = []

                for field in interesting_fields:
                    if hasattr(file, field):
                        item = getattr(file, field)

                        if not isinstance(item, str):
                            item = str(item)

                        item = item.strip('"')
                        row.append(item)

                yield row

        with open(output_name, "w") as fh:
            writer = csv.writer(fh, delimiter=",")
            writer.writerow(interesting_fields)
            writer.writerows(gen_rows())

        logger.info(f"Successfully exported data to {output_name}")
