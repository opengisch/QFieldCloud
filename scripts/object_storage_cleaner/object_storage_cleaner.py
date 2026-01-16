"""
Object Storage Logically Deleted Object Cleaner

This script scans an object storage bucket for "logically deleted" objects (objects where the
latest version is a Delete Marker) and optionally permanently deletes all versions
of those objects to reclaim storage space.

Usage:
    python object_storage_cleaner.py <bucket> [options]
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
from typing import TYPE_CHECKING, Any

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import (
        DeleteMarkerEntryTypeDef,
        DeleteObjectsOutputTypeDef,
        ListObjectVersionsOutputTypeDef,
        ObjectVersionTypeDef,
    )


@dataclass
class LogicallyDeletedObject:
    key: str
    deleted_at: datetime
    total_size_bytes: int
    versions_count: int
    versions: list[dict[str, Any]]


def iter_all_versions(
    s3_client: BaseClient, bucket: str, prefix: str | None = None
) -> Iterator[dict[str, Any]]:
    """
    Stream all object versions and delete markers from object storage, paginated.

    Object storage's `list_object_versions` returns `Versions` and `DeleteMarkers` as separate
    lists within each page. This function merges and sorts them by Key locally
    to ensure that all history (versions + markers) for a specific Key is yielded
    contiguously before the stream moves to the next Key.

    Args:
        s3_client: The configured boto3 object storage client.
        bucket: The bucket name.
        prefix: Optional key prefix to limit the scan.

    Yields:
        dict: A dictionary representing either a Version or a Delete Marker.
    """
    paginator = s3_client.get_paginator("list_object_versions")
    paginate_kwargs = {
        "Bucket": bucket,
        "MaxKeys": 1000,
    }
    if prefix:
        paginate_kwargs["Prefix"] = prefix

    for page in paginator.paginate(**paginate_kwargs):
        page: ListObjectVersionsOutputTypeDef  # Type from mypy_boto3_s3.type_defs
        versions: list[dict[str, Any]] = []

        # Yield Versions
        for version in page.get("Versions", []):
            version: ObjectVersionTypeDef  # Type from mypy_boto3_s3.type_defs
            version["IsDeleteMarker"] = False
            versions.append(version)

        # Yield Delete Markers
        for delete_marker in page.get("DeleteMarkers", []):
            delete_marker: DeleteMarkerEntryTypeDef  # Type from mypy_boto3_s3.type_defs
            delete_marker["IsDeleteMarker"] = True
            versions.append(delete_marker)

        # Sort by Key to keep versions of the same object together
        versions.sort(key=lambda x: (x["Key"], x["LastModified"]), reverse=True)

        yield from versions


def analyze_key_history(
    key: str, versions: list[dict[str, Any]], retention_cutoff: datetime | None
) -> LogicallyDeletedObject | None:
    """
    Analyze a list of versions for a single key to see if it's logically deleted
    and return a LogicallyDeletedObject if it is, otherwise None.

    Args:
        key: The key of the object.
        versions: The list of versions.
        retention_cutoff: Optional cutoff timestamp. If provided, the object is only returned if it was deleted *before* this timestamp. Recent deletions are ignored.

    Returns:
        A LogicallyDeletedObject if the key is logically deleted, None otherwise.
    """
    if not versions:
        return None

    latest_version = versions[0]

    # Criteria: Latest version must be a delete marker
    if not latest_version.get("IsDeleteMarker", False):
        return None

    # Filter by time
    # If the delete marker is NEWER than the retention cutoff, skip it (retain it)
    if retention_cutoff and latest_version["LastModified"] > retention_cutoff:
        return None

    # Calculate stats efficiently
    # Note: latest is size 0 (delete marker), so we can just sum all
    total_size = 0

    for v in versions:
        total_size += v.get("Size", 0)

    return LogicallyDeletedObject(
        key=key,
        deleted_at=latest_version["LastModified"],
        total_size_bytes=total_size,
        versions_count=len(versions),
        versions=versions,
    )


def delete_versions_batch(
    s3_client: BaseClient, bucket: str, versions: list[dict[str, Any]]
) -> None:
    """
    Delete a batch of versions.

    Args:
        s3_client: The configured S3 client.
        bucket: The bucket name.
        versions: The list of versions to delete.
    """
    if not versions:
        return

    # Transform to boto3 format
    objects: list[dict[str, str]] = []
    for v in versions:
        objects.append({"Key": v["Key"], "VersionId": v["VersionId"]})

    try:
        # Quiet=False returns success details and errors for logging
        response: DeleteObjectsOutputTypeDef = s3_client.delete_objects(
            Bucket=bucket, Delete={"Objects": objects, "Quiet": False}
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

    except ClientError as e:
        logger.error(f"Failed to delete versions batch: {e}")


def iter_logically_deleted(
    version_chunks: Iterator[dict[str, Any]],
    retention_cutoff: datetime | None = None,
) -> Iterator[LogicallyDeletedObject]:
    """
    Consumes a stream of all object versions and yields ONLY the objects that are logically deleted.

    This function relies on the input stream being pre-sorted by `key`. It groups all versions
    belonging to the same key into a list, and then passes that complete history to
    `analyze_key_history` to determine if the object is currently in a deleted state.

    Args:
        version_chunks: An iterator of version dictionaries, MUST be sorted by `key`.
        retention_cutoff: Optional cutoff timestamp. If provided, the object is only returned if it was deleted *before* this timestamp. Recent deletions are ignored.

    Yields:
        LogicallyDeletedObject: A summary object for every key that is currently deleted.
    """
    # We maintain a buffer of versions for the "current" key we are processing.
    # Since the input stream is sorted, all versions for "Key A" will arrive sequentially
    # before any version for "Key B" appears, so we can group them together.
    current_key: str | None = None
    current_versions: list[dict[str, Any]] = []

    for version in version_chunks:
        # Case 1: First item in the entire stream
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
                current_key, current_versions, retention_cutoff
            )
            if result:
                yield result

            # Reset buffer for the new key
            current_key = version["Key"]
            current_versions = [version]

    # Case 4: End of stream -> Process the final buffer remaining in memory
    if current_key and current_versions:
        result = analyze_key_history(current_key, current_versions, retention_cutoff)
        if result:
            yield result


def action_scan(objects_stream: Iterable[LogicallyDeletedObject]) -> None:
    """
    Consume a stream of logically deleted objects and log the details.

    Args:
        objects_stream: The stream of logically deleted objects.
    """
    logger.info("Scanning for logically deleted objects...")

    # Counters for summary logging
    key_count = 0
    total_size_bytes = 0
    total_versions_count = 0

    for obj in objects_stream:
        # Update counters
        key_count += 1
        total_size_bytes += obj.total_size_bytes
        total_versions_count += obj.versions_count

        # Log details for each key
        logger.info(
            f"Found: {obj.key} | Deleted At: {obj.deleted_at} | "
            f"Wasted Size: {obj.total_size_bytes} bytes ({obj.versions_count} versions)"
        )

    # Log summary
    logger.info(f"Total keys found: {key_count}")
    logger.info(f"Total size wasted: {total_size_bytes} bytes")
    logger.info(f"Total versions wasted: {total_versions_count}")


def action_permanently_delete_versions(
    s3_client: BaseClient, bucket: str, objects_stream: Iterable[LogicallyDeletedObject]
) -> None:
    """
    Consume a stream of logically deleted objects and delete the versions in batches.

    Args:
        s3_client: The configured S3 client.
        bucket: The bucket name.
        objects_stream: The stream of logically deleted objects.
    """
    batch: list[dict[str, Any]] = []
    batch_size = 1000

    for obj in objects_stream:
        for v in obj.versions:
            batch.append(v)

            # Flush batch if full
            if len(batch) == batch_size:
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
    except ClientError as e:
        raise RuntimeError(
            f"Could not check versioning status for '{bucket}': {e}"
        ) from e

    return client


def parse_retention_period(value: str) -> datetime:
    """
    Parse a duration string (e.g., '3 seconds', '30 days', '2 weeks') and return a datetime object.

    Args:
        value: The duration string to parse. Supports `seconds`, `minutes`, `hours`, `days`, and `weeks`.

    Returns:
        A UTC datetime equal to now minus the parsed duration.
    """
    value = value.strip().lower()

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
        dest="retention_cutoff",
        help="Only process objects deleted BEFORE this duration (e.g. '30 days'). Recent deletions are preserved.",
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
        raw_stream = iter_all_versions(client, args.bucket, args.prefix)

        # Transform
        clean_stream = iter_logically_deleted(raw_stream, args.retention_cutoff)

        # 3. Execute
        if args.dry_run:
            action_scan(clean_stream)
            return 0

        else:
            if not args.force:
                confirmation_input = input(
                    f"Permanently delete from '{args.bucket}'? (yes/no): "
                ).lower()

                if confirmation_input != "yes":
                    return 0

            action_permanently_delete_versions(client, args.bucket, clean_stream)

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
