import argparse
import logging
import re
import signal
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


# Data classes
@dataclass
class VersionRef:
    """Represents a single object version or delete marker.

    Attributes:
        key: Object key.
        version_id: Version ID of this entry.
        is_delete_marker: True if this entry is a delete marker.
        size: Size in bytes for a normal version. For delete markers, this is 0.
        last_modified: Timestamp when this version was created/modified.
    """

    key: str
    version_id: str
    is_delete_marker: bool
    size: int
    last_modified: datetime


@dataclass
class LogicallyDeletedObject:
    """Aggregated info about a logically deleted object.

    A logically deleted object is one whose latest version is a delete marker,
    even though older versions still exist and consume storage.

    Attributes:
        key: Object key.
        deleted_at: Timestamp of the delete marker (latest version).
        total_size_bytes: Sum of sizes of all non-delete-marker versions.
        versions_count: Number of non-delete-marker versions.
    """

    key: str
    deleted_at: datetime
    total_size_bytes: int
    versions_count: int


# Utility functions
def format_bytes(num_bytes: int) -> str:
    """Convert a byte count to a human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}"

        size /= 1024.0

    return f"{size:.2f} PB"


# Main class
class ObjectStorageScanner:
    BATCH_SIZE = 1000

    def __init__(
        self,
        bucket: str,
        region_name: str | None = None,
        profile: str | None = None,
        endpoint_url: str | None = None,
        prefix: str | None = None,
        deleted_after: datetime | None = None,
    ):
        self.bucket = bucket
        self.prefix = prefix
        self.deleted_after = deleted_after
        self.region_name = region_name
        self.profile = profile
        self.endpoint_url = endpoint_url

        # Metrics
        self._scanned_count = 0
        self._stats_keys = 0
        self._stats_versions = 0
        self._stats_bytes = 0

        # Initialize client
        self.s3_client = self._create_s3_client(region_name, profile, endpoint_url)

        # Validate bucket immediately
        self._validate_bucket_versioning()

    def _create_s3_client(
        self,
        region: str | None,
        profile: str | None,
        endpoint: str | None,
    ) -> BaseClient:
        """Create the Boto3 S3 client."""
        session_kwargs = {}
        client_kwargs = {}

        if profile:
            session_kwargs.update({"profile_name": profile})

        if region:
            session_kwargs.update({"region_name": region})

        if endpoint:
            client_kwargs.update({"endpoint_url": endpoint})

        try:
            session = boto3.Session(**session_kwargs)

            return session.client("s3", **client_kwargs)
        except (BotoCoreError, ClientError) as e:
            raise RuntimeError(f"Failed to initialize S3 client: {e}") from e

    def _validate_bucket_versioning(self) -> None:
        """Ensure the bucket has versioning enabled or suspended."""
        try:
            response = self.s3_client.get_bucket_versioning(Bucket=self.bucket)
            status = response.get("Status")

            if status not in ("Enabled"):
                raise RuntimeError(
                    f"Bucket '{self.bucket}' does not have versioning history (Status: {status}). "
                    "Nothing to scan."
                )
        except ClientError as e:
            raise RuntimeError(
                f"Could not check versioning status for '{self.bucket}': {e}"
            ) from e

        logger.debug(
            "\nBucket: '%s'\nVersioning: %s\nRegion: %s\nEndpoint: %s\nPrefix: %s \nDeleted After: %s",
            self.bucket,
            status,
            self.s3_client.meta.region_name,
            self.s3_client.meta.endpoint_url,
            self.prefix or "No prefix specified",
            self.deleted_after.isoformat()
            if self.deleted_after
            else "No deleted after date specified",
        )

    def _print_progress(self, delta: int, label: str = "Deletable") -> None:
        self._scanned_count += delta
        if sys.stdout.isatty():
            sys.stdout.write(
                f"Scanned {self._scanned_count} versions | Found {self._stats_keys} keys | "
                f"{label}: {self._stats_versions} versions ({format_bytes(self._stats_bytes)})"
                + " " * 20
                + "\r",
            )
            sys.stdout.flush()

    def _print_filters(self) -> None:
        msg = [f"Scanning bucket: '{self.bucket}'"]
        if self.prefix:
            msg.append(f"Prefix filter: {self.prefix}")

        if self.deleted_after:
            msg.append(
                f"Date filter: Objects deleted after {self.deleted_after.isoformat()}"
            )

        logger.info("\n".join(msg) + "\n")

    def _print_summary(self, prune: bool = False) -> None:
        versions_action = "deleted" if prune else "to delete"
        storage_action = "freed" if prune else "to free"

        logger.info("-" * 100)
        logger.info(f"  Total logically deleted keys: {self._stats_keys}")
        logger.info(f"  Total versions {versions_action}: {self._stats_versions}")
        logger.info(
            f"  Total storage {storage_action}: {format_bytes(self._stats_bytes)}"
        )
        logger.info("-" * 100)

    def _iter_all_versions(
        self, progress: Callable[[int], None] | None = None
    ) -> Iterator[VersionRef]:
        """Low-level generator that yields all versions and delete markers, sorted by Key."""
        paginator = self.s3_client.get_paginator("list_object_versions")
        kwargs = {"Bucket": self.bucket, "MaxKeys": 10000}
        if self.prefix:
            kwargs["Prefix"] = self.prefix

        for page in paginator.paginate(**kwargs):
            items: list[VersionRef] = []

            for v in page.get("Versions", []):
                items.append(
                    VersionRef(
                        key=v["Key"],
                        version_id=v["VersionId"],
                        is_delete_marker=False,
                        size=v["Size"],
                        last_modified=v["LastModified"],
                    )
                )

            for dm in page.get("DeleteMarkers", []):
                items.append(
                    VersionRef(
                        key=dm["Key"],
                        version_id=dm["VersionId"],
                        is_delete_marker=True,
                        size=0,
                        last_modified=dm["LastModified"],
                    )
                )

            # Sort by Key to keep versions of the same object together
            items.sort(key=lambda x: x.key)

            if progress:
                progress(len(items))

            yield from items

    def _aggregate_if_logically_deleted(
        self, key: str, versions: list[VersionRef]
    ) -> tuple[LogicallyDeletedObject, list[VersionRef]] | None:
        """Determine if a key is logically deleted and aggregate its stats."""
        if not versions:
            return None

        # Sort by time descending (latest first)
        versions.sort(key=lambda x: x.last_modified, reverse=True)
        latest = versions[0]

        # Criteria: Latest version must be a delete marker
        if not latest.is_delete_marker:
            return None

        # Filter by deleted_after date if set
        if self.deleted_after and latest.last_modified < self.deleted_after:
            return None

        total_size = sum(v.size for v in versions)

        actual_versions_count = len(
            list(filter(lambda v: not v.is_delete_marker, versions))
        )

        aggregate = LogicallyDeletedObject(
            key=key,
            deleted_at=latest.last_modified,
            total_size_bytes=total_size,
            versions_count=actual_versions_count,
        )

        return aggregate, versions

    def _delete_batch(self, versions: list[dict[str, str]]) -> int:
        """Helper to delete a batch of objects."""
        if not versions:
            return 0

        if logger.isEnabledFor(TRACE_LEVEL):
            for v in versions:
                logger.log(
                    TRACE_LEVEL,
                    "Deleting object: Key=%s Version=%s",
                    v["Key"],
                    v["VersionId"],
                )

        try:
            self.s3_client.delete_objects(
                Bucket=self.bucket, Delete={"Objects": versions, "Quiet": True}
            )

            return len(versions)
        except ClientError as e:
            logger.error(f"Failed to delete batch: {e}")
            return 0

    def print_bucket_info(self) -> None:
        """Display bucket and connection information."""

        logger.info("\nBucket Information:")
        logger.info("-" * 80)
        logger.info(f"Bucket:            {self.bucket}")
        logger.info("Versioning Status: Enabled")
        logger.info(f"Region:            {self.s3_client.meta.region_name}")
        logger.info(f"Endpoint URL:      {self.s3_client.meta.endpoint_url}")
        logger.info(f"Prefix Filter:     {self.prefix or 'No prefix specified'}")
        logger.info(
            f"Deleted After:     {self.deleted_after.isoformat() if self.deleted_after else 'No deleted after date specified'}"
        )
        logger.info("-" * 80)
        logger.info("✓ Connection successful.")
        logger.info("✓ Bucket is accessible.")
        logger.info("\nUse --scan to find logically deleted objects.")

    def _iter_logically_deleted(
        self,
        progress: Callable[[int], None] | None = None,
    ) -> Iterator[tuple[LogicallyDeletedObject, list[VersionRef]]]:
        """Yields logically deleted objects."""
        current_key: str | None = None
        current_versions: list[VersionRef] = []

        for item in self._iter_all_versions(progress=progress):
            # Same key, just accumulate and continue
            if item.key == current_key:
                current_versions.append(item)
                continue

            # Another key, process the previous key.
            if current_key is not None:
                result = self._aggregate_if_logically_deleted(
                    current_key, current_versions
                )
                if result:
                    yield result

            # Start a new batch for the new key
            current_key = item.key
            current_versions = [item]

        # Process the final key
        if current_key is not None:
            result = self._aggregate_if_logically_deleted(current_key, current_versions)
            if result:
                yield result

    def scan(self) -> None:
        """Scan and print report of logically deleted objects."""

        self._print_filters()

        def progress(delta: int) -> None:
            self._print_progress(delta)

        for aggregate, versions in self._iter_logically_deleted(progress=progress):
            self._stats_keys += 1
            self._stats_versions += aggregate.versions_count + 1
            self._stats_bytes += aggregate.total_size_bytes

            if logger.isEnabledFor(TRACE_LEVEL):
                for v in versions:
                    logger.log(
                        TRACE_LEVEL,
                        "Version: Key=%s VersionId=%s Size=%s LastModified=%s",
                        v.key,
                        v.version_id,
                        v.size,
                        v.last_modified,
                    )

        self._print_summary(prune=False)

    def prune(self) -> None:
        """Scan and delete logically deleted objects."""

        self._print_filters()

        batch: list[dict[str, str]] = []

        def progress(delta: int) -> None:
            self._print_progress(delta, label="Deleted")

        logger.debug("Starting to delete logically deleted objects...")

        # Iterate
        for aggregate, versions in self._iter_logically_deleted(progress=progress):
            self._stats_keys += 1
            self._stats_bytes += aggregate.total_size_bytes

            for v in versions:
                batch.append({"Key": v.key, "VersionId": v.version_id})
                if len(batch) >= self.BATCH_SIZE:
                    self._stats_versions += self._delete_batch(batch)
                    batch.clear()
                    self._print_progress(0, label="Deleted")

        # Flush remaining
        if batch:
            self._stats_versions += self._delete_batch(batch)

        self._print_summary(prune=True)


def _handle_sigint(sig: int, frame: object) -> None:
    logger.info("\n\nScan interrupted by user.")
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_sigint)


def setup_logging(debug: bool = False, log_file: str | None = None) -> None:
    """Setup logging for the script."""
    level = TRACE_LEVEL if log_file else (logging.DEBUG if debug else logging.INFO)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    # 2. Console Handler (The User UI)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    # Filter out errors (they go to stderr)
    console_handler.addFilter(lambda record: record.levelno <= logging.INFO)
    logger.addHandler(console_handler)

    # 3. Stderr Handler (Errors)
    error_handler = logging.StreamHandler(sys.stderr)
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(error_handler)

    # 4. File Handler (The Audit Log)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=1000 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(TRACE_LEVEL)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(file_handler)


def parse_since_cutoff(value: str) -> datetime:
    """
    Parse a duration like '3s', '30d', '2w', '3 days' and return a datetime object.

    Args:
        value: The duration string to parse.

    Returns:
        A UTC datetime equal to now minus the parsed duration.
    """
    value = value.strip().lower()

    pattern = r"^(\d+)\s*(s|sec|secs|seconds|min|minute|minutes|h|hour|hours|d|day|days|w|week|weeks)$"
    match = re.match(pattern, value)
    if not match:
        raise argparse.ArgumentTypeError(
            "Invalid duration. Use: '3s', '10h', '15min', '30d', '2w' (or words like '3 days')"
        )

    amount = int(match.group(1))
    unit = match.group(2)

    if unit in ("s", "sec", "secs", "seconds"):
        delta = timedelta(seconds=amount)
    elif unit in ("min", "minute", "minutes"):
        delta = timedelta(minutes=amount)
    elif unit in ("h", "hour", "hours"):
        delta = timedelta(hours=amount)
    elif unit in ("d", "day", "days"):
        delta = timedelta(days=amount)
    elif unit in ("w", "week", "weeks"):
        delta = timedelta(weeks=amount)
    else:
        raise argparse.ArgumentTypeError(f"Unsupported time unit: {unit}")

    return datetime.now(timezone.utc) - delta


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan and clean logically deleted objects in object storage like S3.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
        # Scan only (default)
        %(prog)s my-bucket

        # Scan with filters
        %(prog)s my-bucket --prefix logs/ --deleted-after 2024-12-01

        # Delete with confirmation prompt
        %(prog)s my-bucket --prune

        # Delete without confirmation (automation)
        %(prog)s my-bucket --prune --noinput
        """,
    )

    # Required
    parser.add_argument("bucket", help="Target S3 bucket")

    # Connection options
    parser.add_argument("--prefix", help="Key prefix to scan")
    parser.add_argument("--region", help="Region")
    parser.add_argument("--profile", help="Profile")
    parser.add_argument("--endpoint-url", help="Custom S3 endpoint URL")

    # Filter options
    parser.add_argument(
        "--deleted-after",
        type=datetime.fromisoformat,
        help="Only process objects deleted after this date (ISO 8601 format, e.g. 2024-12-01:00:00:00)",
    )

    parser.add_argument(
        "--since",
        type=parse_since_cutoff,
        metavar="DAYS",
        help="Number of days ago (e.g. 3, 3d, '7 days')",
    )

    # Action flags
    parser.add_argument(
        "--info", action="store_true", help="Show bucket information (default behavior)"
    )
    parser.add_argument("--scan", action="store_true", help="Scan only")

    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete found logically deleted objects (requires confirmation unless --noinput)",
    )

    parser.add_argument(
        "--noinput",
        action="store_true",
        help="Skip confirmation prompt (use with --prune for automation)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )

    parser.add_argument(
        "--log-file",
        default=None,
        help="Write a rotating logbook file (e.g. /tmp/s3-cleaner.log)",
    )

    args = parser.parse_args()

    setup_logging(debug=args.debug, log_file=args.log_file)

    deleted_after = None

    if args.since and args.deleted_after:
        raise argparse.ArgumentTypeError(
            "Cannot use --since and --deleted-after together"
        )
    elif args.since:
        deleted_after = args.since
    elif args.deleted_after:
        deleted_after = args.deleted_after.replace(tzinfo=timezone.utc)

    # Create scanner
    try:
        scanner = ObjectStorageScanner(
            bucket=args.bucket,
            region_name=args.region,
            profile=args.profile,
            endpoint_url=args.endpoint_url,
            prefix=args.prefix,
            deleted_after=deleted_after,
        )
    except RuntimeError as e:
        logger.error(e)
        return 1

    if args.info:
        scanner.print_bucket_info()
        return 0

    # Mode: Scan only
    elif args.scan:
        scanner.scan()
        return 0

    # Mode: Prune (with or without confirmation)
    elif args.prune:
        if not args.noinput:
            logger.info(f"\nTarget Bucket: {args.bucket}")
            if args.prefix:
                logger.info(f"Prefix: {args.prefix}")

            logger.warning(
                "You are about to permanently delete logically deleted objects. This action cannot be undone!"
            )
            confirm = input("Type 'yes' to confirm deletion: ").strip().lower()

            if confirm != "yes":
                logger.info("Operation cancelled.")
                return 0

        scanner.prune()

    # Default fallback to info
    else:
        logger.info("No action specified. Defaulting to --info.")
        scanner.print_bucket_info()
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
