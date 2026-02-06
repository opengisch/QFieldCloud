#!/usr/bin/env python3

import logging
import os
from pathlib import Path

from qfc_worker.commands_base import run_command

PGSERVICE_FILE_CONTENTS = os.environ.get("PGSERVICE_FILE_CONTENTS")

logger = logging.getLogger("ENTRYPNT")
logger.setLevel(logging.INFO)


def main() -> None:
    from qfc_worker.memory_profiler import init_memory_profiling
    from qfc_worker.utils import setup_basic_logging_config

    setup_basic_logging_config()

    # Set S3 logging levels
    logging.getLogger("nose").setLevel(logging.CRITICAL)
    logging.getLogger("s3transfer").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)

    # Initialize memory profiling if enabled
    init_memory_profiling()

    if PGSERVICE_FILE_CONTENTS:
        with open(Path.home().joinpath(".pg_service.conf"), "w") as f:
            f.write(PGSERVICE_FILE_CONTENTS)

    run_command()


if __name__ == "__main__":
    main()
