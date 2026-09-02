"""
Object Storage Logically Deleted Object Cleaner

This script scans an object storage bucket for "logically deleted" objects (objects where the
latest version is a Delete Marker) and optionally permanently deletes all versions
of those objects to reclaim storage space.

Usage:
    python purge_deleted_objects.py <bucket> --retention-period "30 days" [options]
"""

from __future__ import annotations

import argparse
import logging
import re
import signal
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# AWS S3 limit for delete objects batch up to 1000 keys (https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/delete_objects.html)
DELETE_BATCH_SIZE = 1000

# AWS S3 limit for list object versions max keys up to 1000 (https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/list_object_versions.html)
LIST_OBJECT_VERSIONS_MAX_KEYS = 1000

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import (
        DeleteObjectsOutputTypeDef,
        ListObjectVersionsOutputTypeDef,
        ObjectVersionTypeDef,
    )

    class QfcObjectVersionTypeDef(ObjectVersionTypeDef):
        IsDeleteMarker: Literal[False]

    class QfcDeleteMarkerEntryTypeDef(ObjectVersionTypeDef):
        IsDeleteMarker: Literal[True]

    ObjectVersionOrDeleteMarker = QfcObjectVersionTypeDef | QfcDeleteMarkerEntryTypeDef


@dataclass
class LogicallyDeletedObject:
    key: str
    deleted_at: datetime
    total_size_bytes: int
    versions_count: int
    versions: list[dict[str, Any]]


def format_bytes(num_bytes: int) -> str:
    """Convert a byte count to a human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]

    if num_bytes == 0:
        return "0 B"

    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.2f} {unit}"

        size /= 1024.0

    return f"{size:.2f} PB"


def iter_all_versions(
    s3_client: BaseClient, bucket: str, prefix: str | None = None
) -> Iterator[ObjectVersionOrDeleteMarker]:
    """
    Iterate over all object versions and delete markers from object storage, paginated.

    Object storage's `list_object_versions` returns `Versions` and `DeleteMarkers` as separate
    lists within each page. This function merges and sorts them by Key locally
    to ensure that all history (versions + markers) for a specific Key is yielded
    contiguously before the iterator moves to the next Key.

    Args:
        s3_client: The configured boto3 object storage client.
        bucket: The bucket name.
        prefix: Optional key prefix to limit the scan.

    Yields:
        ObjectVersionOrDeleteMarker: A dictionary representing either a Version or a Delete Marker.
    """
    paginator = s3_client.get_paginator("list_object_versions")
    paginate_kwargs = {
        "Bucket": bucket,
        "MaxKeys": LIST_OBJECT_VERSIONS_MAX_KEYS,
    }
    if prefix:
        paginate_kwargs["Prefix"] = prefix

    for page in paginator.paginate(**paginate_kwargs):
        # Type from mypy_boto3_s3.type_defs
        page: ListObjectVersionsOutputTypeDef
        versions: list[ObjectVersionOrDeleteMarker] = []

        # Yield Versions
        for version in page.get("Versions", []):
            version: QfcObjectVersionTypeDef
            version["IsDeleteMarker"] = False
            versions.append(version)

        # Yield Delete Markers
        for delete_marker in page.get("DeleteMarkers", []):
            delete_marker: QfcDeleteMarkerEntryTypeDef
            delete_marker["IsDeleteMarker"] = True
            versions.append(delete_marker)

        # Sort by Key to keep versions of the same object together
        versions.sort(key=lambda v: (v["Key"], v["LastModified"]), reverse=True)

        yield from versions


def analyze_key_history(
    key: str,
    versions: list[ObjectVersionOrDeleteMarker],
    retention_cutoff_ts: datetime | None,
) -> LogicallyDeletedObject | None:
    """
    Analyze a list of versions for a single key to see if it's logically deleted
    and return a LogicallyDeletedObject if it is, otherwise None.

    Args:
        key: The key of the object.
        versions: The list of versions.
        retention_cutoff_ts: Optional cutoff timestamp. If provided, the object is only returned if it was deleted *before* this timestamp. Recent deletions are ignored.

    Returns:
        A LogicallyDeletedObject if the key is logically deleted, None otherwise.
    """
    if not versions:
        return None

    latest_version = versions[0]

    # Criteria: Latest version must be a delete marker
    if not latest_version["IsDeleteMarker"]:
        return None

    # Filter by time
    # If the delete marker is NEWER than the retention cutoff, skip it (retain it)
    if retention_cutoff_ts and latest_version["LastModified"] > retention_cutoff_ts:
        return None

    # Calculate stats efficiently
    # Note: latest is size 0 (delete marker), so we can just sum all
    total_size = 0

    for v in versions:
        if v["IsDeleteMarker"]:
            # Delete markers have no size
            continue
        # Versions have a size
        total_size += v["Size"]

    return LogicallyDeletedObject(
        key=key,
        deleted_at=latest_version["LastModified"],
        total_size_bytes=total_size,
        versions_count=len(versions),
        versions=versions,
    )


def delete_versions_batch(
    s3_client: BaseClient, bucket: str, versions: list[ObjectVersionOrDeleteMarker]
) -> None:
    """
    Delete a batch of versions, up to 1000 versions per batch.

    Args:
        s3_client: The configured S3 client.
        bucket: The bucket name.
        versions: The list of versions to delete.
    """
    if not versions:
        return

    assert len(versions) <= DELETE_BATCH_SIZE

    # Transform to boto3 format
    objects: list[ObjectVersionOrDeleteMarker] = []
    for v in versions:
        objects.append(
            {
                "Key": v["Key"],
                "VersionId": v["VersionId"],
            }
        )

    try:
        # Quiet=False returns success details and errors for logging
        response: DeleteObjectsOutputTypeDef = s3_client.delete_objects(
            Bucket=bucket,
            Delete={
                "Objects": objects,
                "Quiet": False,
            },
        )

        # Log successes
        for success in response.get("Deleted", []):
            logger.info(
                f"Permanently deleted: {success['Key']} (VersionId: {success.get('VersionId')})"
            )

        # Log errors
        for error in response.get("Errors", []):
            logger.error(
                f"Failed to delete: {error['Key']} (VersionId: {error.get('VersionId')}) | "
                f"Code: {error.get('Code')} | Message: {error.get('Message')}"
            )

    except ClientError as err:
        logger.error(f"Failed to delete versions batch: {err}")


def iter_logically_deleted(
    version_iterator: Iterator[ObjectVersionOrDeleteMarker],
    retention_cutoff_ts: datetime | None = None,
) -> Iterator[LogicallyDeletedObject]:
    """
    Consumes an iterator of all object versions and yields ONLY the objects that are logically deleted.

    This function relies on the input iterator being pre-sorted by `key`. It groups all versions
    belonging to the same key into a list, and then passes that complete history to
    `analyze_key_history` to determine if the object is currently in a deleted state.

    Args:
        version_iterator: An iterator of version dictionaries, MUST be sorted by `key`.
        retention_cutoff_ts: Optional cutoff timestamp. If provided, the object is only returned if it was deleted *before* this timestamp. Recent deletions are ignored.

    Yields:
        LogicallyDeletedObject: A summary object for every key that is currently deleted.
    """
    # We maintain a buffer of versions for the "current" key we are processing.
    # Since the input iterator is sorted, all versions for "Key A" will arrive sequentially
    # before any version for "Key B" appears, so we can group them together.
    current_key: str | None = None
    current_versions: list[ObjectVersionOrDeleteMarker] = []

    for version in version_iterator:
        # Case 1: First item in the entire iterator
        if current_key is None:
            current_key = version["Key"]
            current_versions.append(version)
            continue

        # Case 2: Same key as before -> Add to buffer
        if version["Key"] == current_key:
            current_versions.append(version)

        # Case 3: New key detected -> Process the previous buffer
        else:
            # We have collected all versions for 'current_key'. Now analyze it.
            result = analyze_key_history(
                current_key, current_versions, retention_cutoff_ts
            )
            if result:
                yield result

            # Reset buffer for the new key
            current_key = version["Key"]
            current_versions = [version]

    # Case 4: End of iterator -> Process the final buffer remaining in memory
    if current_key and current_versions:
        result = analyze_key_history(current_key, current_versions, retention_cutoff_ts)
        if result:
            yield result


def action_scan(objects_iterator: Iterable[LogicallyDeletedObject]) -> None:
    """
    Consume an iterator of logically deleted objects and log the details.

    Args:
        objects_iterator: The iterator of logically deleted objects.
    """
    logger.info("Scanning for logically deleted objects...")

    # Counters for summary logging
    key_count = 0
    total_size_bytes = 0
    total_versions_count = 0

    for obj in objects_iterator:
        # Update counters
        key_count += 1
        total_size_bytes += obj.total_size_bytes
        total_versions_count += obj.versions_count

        # Log details for each key
        logger.info(
            f"Found: {obj.key} | Deleted At: {obj.deleted_at} | "
            f"Wasted Size: {format_bytes(obj.total_size_bytes)} | {obj.versions_count} versions"
        )

    # Log summary
    logger.info(f"Total deleted keys found: {key_count}")
    logger.info(f"Total size wasted: {format_bytes(total_size_bytes)}")
    logger.info(f"Total versions wasted: {total_versions_count}")


def action_permanently_delete_versions(
    s3_client: BaseClient,
    bucket: str,
    objects_iterator: Iterable[LogicallyDeletedObject],
) -> None:
    """
    Consume an iterator of logically deleted objects and delete the versions in batches.

    Args:
        s3_client: The configured S3 client.
        bucket: The bucket name.
        objects_iterator: The iterator of logically deleted objects.
    """
    batch: list[ObjectVersionOrDeleteMarker] = []

    for obj in objects_iterator:
        for version in obj.versions:
            batch.append(version)

            # Flush batch if full
            if len(batch) == DELETE_BATCH_SIZE:
                delete_versions_batch(s3_client, bucket, batch)
                batch.clear()

    # Flush remaining
    if batch:
        delete_versions_batch(s3_client, bucket, batch)


def get_s3_client(bucket: str, profile: str | None) -> BaseClient:
    """
    Create an object storage client and validate that the bucket has versioning enabled.

    Args:
        bucket: The name of the object storage bucket.
        profile: Optional AWS profile name.

    Returns:
        A configured boto3 object storage client.
    """

    session_kwargs = {}
    if profile:
        session_kwargs["profile_name"] = profile

    client = boto3.Session(**session_kwargs).client("s3")

    # Validate bucket versioning is enabled
    try:
        response = client.get_bucket_versioning(Bucket=bucket)
        status = response.get("Status")
        if status != "Enabled":
            raise RuntimeError(
                f"Bucket '{bucket}' versioning is not Enabled (Status: {status})."
            )
    except ClientError as err:
        raise RuntimeError(
            f"Could not check versioning status for '{bucket}': {err}"
        ) from err

    return client


def parse_retention_period(value: str) -> datetime:
    """
    Parse a duration string (e.g., '3 seconds', '30 days', '2 weeks') and return a datetime object.

    Args:
        value: The duration string to parse. Supports `seconds`, `minutes`, `hours`, `days`, and `weeks`.

    Returns:
        A UTC datetime equal to now minus the parsed duration.
    """
    # Handle None and non-string inputs
    if value is None:
        raise argparse.ArgumentTypeError("Duration cannot be None")

    if not isinstance(value, str):
        raise argparse.ArgumentTypeError(
            f"Duration must be a string, got {type(value).__name__}"
        )

    value = value.strip().lower()

    # Handle empty string after stripping
    if not value:
        raise argparse.ArgumentTypeError("Duration cannot be empty")

    pattern = (
        r"^(\d+)\s*(second|seconds|minute|minutes|hour|hours|day|days|week|weeks)$"
    )
    match = re.match(pattern, value)
    if not match:
        raise argparse.ArgumentTypeError(
            "Invalid duration. Use: '3 seconds', '10 hours', '15 minutes', '30 days', '2 weeks'"
        )

    amount = int(match.group(1))
    unit = match.group(2)

    try:
        if unit in ("second", "seconds"):
            delta = timedelta(seconds=amount)
        elif unit in ("minute", "minutes"):
            delta = timedelta(minutes=amount)
        elif unit in ("hour", "hours"):
            delta = timedelta(hours=amount)
        elif unit in ("day", "days"):
            delta = timedelta(days=amount)
        elif unit in ("week", "weeks"):
            delta = timedelta(weeks=amount)
        else:
            raise argparse.ArgumentTypeError(f"Unsupported time unit: {unit}")
    except OverflowError:
        raise argparse.ArgumentTypeError("Duration is too large")

    return datetime.now(timezone.utc) - delta


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan and clean logically deleted objects in object storage like S3."
    )
    parser.add_argument("bucket", help="Target Object Storage bucket")
    parser.add_argument("--prefix", help="Filter by prefix")
    parser.add_argument("--profile", help="Optional AWS Profile")
    parser.add_argument(
        "--retention-period",
        type=parse_retention_period,
        dest="retention_cutoff_ts",
        required=True,
        help="Only process objects deleted BEFORE this time interval (e.g. '30 days'). Recent deletions are preserved.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan for logically deleted objects without deleting them",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip permanently delete confirmation prompt",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    try:
        # 1. Setup Connection
        client = get_s3_client(args.bucket, args.profile)

        # 2. Build Pipeline
        raw_iterator = iter_all_versions(client, args.bucket, args.prefix)

        # Transform
        clean_iterator = iter_logically_deleted(raw_iterator, args.retention_cutoff_ts)

        # 3. Execute
        if args.dry_run:
            action_scan(clean_iterator)
            return 0

        else:
            if not args.force:
                confirmation_input = input(
                    f"Permanently delete from '{args.bucket}'? (yes/no): "
                ).lower()

                if confirmation_input != "yes":
                    return 0

            action_permanently_delete_versions(client, args.bucket, clean_iterator)

    except Exception as e:
        logger.error(f"Error: {e}")

        raise e

    return 0


def handle_sigint(sig: int, frame: object) -> None:
    logger.info("\n\nScan interrupted by user.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_sigint)
    raise SystemExit(main())
