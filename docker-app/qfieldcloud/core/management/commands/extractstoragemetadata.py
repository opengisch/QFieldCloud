import csv
import logging
import sys
from pathlib import Path
from typing import Generator

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

            config = utils.S3Config.get_or_load(path)

        output_name = options.get("output")

        if output_name:
            name_suffix = output_name.rsplit(".", 1)

            if len(name_suffix) != 2 or name_suffix[1] != "csv":
                logger.error("The name of the output file should end with '.csv'")
                sys.exit(1)
        else:
            output_name = "s3_storage_files.csv"

        interesting_fields = ["id", "key", "e_tag", "size", "create_time"]
        bucket = utils.get_s3_bucket(config)

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
