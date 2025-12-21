import argparse
import signal
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError


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
        self.scanned_count = 0

        # Initialize client
        self.s3_client = self._create_s3_client(region_name, profile, endpoint_url)

        # Validate bucket immediately
        self._validate_bucket_versioning()

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        """Convert a byte count to a human-readable string."""
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        size = float(num_bytes)
        for unit in units:
            if size < 1024.0 or unit == units[-1]:
                return f"{size:.2f} {unit}"

            size /= 1024.0

        return f"{size:.2f} PB"

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

    def _validate_bucket_versioning(self) -> bool:
        """Ensure the bucket has versioning enabled or suspended."""
        try:
            response = self.s3_client.get_bucket_versioning(Bucket=self.bucket)
            status = response.get("Status")

            if status not in ("Enabled", "Suspended"):
                raise RuntimeError(
                    f"Bucket '{self.bucket}' does not have versioning history (Status: {status}). "
                    "Nothing to clean."
                )
        except ClientError as e:
            raise RuntimeError(
                f"Could not check versioning status for '{self.bucket}': {e}"
            ) from e

        return status == "Enabled"

    def _iter_all_versions(self) -> Iterator[VersionRef]:
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

            # Update scanned count
            self.scanned_count += len(items)

            yield from items

    def _aggregate_versions(
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

        try:
            self.s3_client.delete_objects(
                Bucket=self.bucket, Delete={"Objects": versions, "Quiet": True}
            )

            return len(versions)
        except ClientError as e:
            print(f"Failed to delete batch: {e}")
            return 0

    def get_bucket_info(self):
        """Display bucket and connection information."""

        print("\nBucket Information:")
        print("-" * 80)
        print(f"Bucket:            {self.bucket}")
        print("Versioning Status: Enabled")
        print(f"Region:            {self.s3_client.meta.region_name}")
        print(f"Endpoint URL:      {self.s3_client.meta.endpoint_url}")
        print(f"Prefix Filter:     {self.prefix or 'No prefix specified'}")
        print(
            f"Deleted After:     {self.deleted_after.isoformat() if self.deleted_after else 'No deleted after date specified'}"
        )
        print("-" * 80)
        print("✓ Connection successful.")
        print("✓ Bucket is accessible.")
        print("\nUse --scan to find logically deleted objects.")

    def _find_logically_deleted(
        self,
    ) -> Iterator[tuple[LogicallyDeletedObject, list[VersionRef]]]:
        """Yields logically deleted objects."""
        current_key: str | None = None
        current_versions: list[VersionRef] = []

        for item in self._iter_all_versions():
            # Same key, just accumulate and continue
            if item.key == current_key:
                current_versions.append(item)
                continue

            # Another key, process the previous key.
            if current_key is not None:
                result = self._aggregate_versions(current_key, current_versions)
                if result:
                    yield result

            # Start a new batch for the new key
            current_key = item.key
            current_versions = [item]

        # Process the final key
        if current_key is not None:
            result = self._aggregate_versions(current_key, current_versions)
            if result:
                yield result

    def scan(self) -> tuple[int, int, int]:
        """Scan and print report of logically deleted objects."""
        # Reset metrics
        self.scanned_count = 0

        # Print filters
        print(f"\nScanning bucket: '{self.bucket}'")
        if self.prefix:
            print(f"  Prefix filter: {self.prefix}")

        if self.deleted_after:
            print(
                f"  Date filter:   Objects deleted after {self.deleted_after.isoformat()}"
            )

        print()

        # Print table header
        print("-" * 100)
        print(f"{'Size':>9}  {'Versions':>10}  {'Deleted At':<33}  Key")
        print("-" * 100)

        stats_keys = 0
        stats_versions = 0
        stats_bytes = 0

        # Iterate
        for aggregate, _ in self._find_logically_deleted():
            stats_keys += 1
            stats_versions += aggregate.versions_count + 1
            stats_bytes += aggregate.total_size_bytes

            # Print row if <= 10
            if stats_keys <= 10:
                deleted_at_iso = aggregate.deleted_at.astimezone(
                    timezone.utc
                ).isoformat()
                print(
                    f"{self._format_bytes(aggregate.total_size_bytes):>12}  "
                    f"{aggregate.versions_count:>8}  "
                    f"{deleted_at_iso:<25}  "
                    f"{aggregate.key}"
                )

            elif stats_keys == 11:
                # Clear previous progress line
                print(" " * 100, end="\r")
                # Print aligned continuation markers (matches table columns)
                print(f"{'....':>9}  {'....':>11}  {'....':<32}  ....")
                # Add blank vertical space
                print()

            # Dynamic progress
            print(
                f"Scanned {self.scanned_count} versions | Found {stats_keys} keys | Deletable: {stats_versions} versions ({self._format_bytes(stats_bytes)})"
                + " " * 20,
                end="\r",
            )

        # Clear progress line
        print(" " * 100, end="\r")

        print("-" * 100)
        if stats_keys == 0:
            print("\nNo logically deleted objects found.")
        else:
            print("\nSummary:")
            print(f"  Total logically deleted keys: {stats_keys}")
            print(f"  Total versions to delete: {stats_versions}")
            print(f"  Total storage to free: {self._format_bytes(stats_bytes)}")

        return stats_keys, stats_versions, stats_bytes

    def clean(self) -> tuple[int, int, int]:
        """Scan and delete logically deleted objects."""
        # Reset metrics
        self.scanned_count = 0

        # Print filters
        print(f"\nScanning bucket: '{self.bucket}'")
        if self.prefix:
            print(f"  Prefix filter: {self.prefix}")

        if self.deleted_after:
            print(
                f"  Date filter:   Objects deleted after {self.deleted_after.isoformat()}"
            )

        print()

        batch: list[dict[str, str]] = []

        stats_keys = 0
        stats_deleted_versions = 0
        stats_bytes = 0

        # Iterate
        for aggregate, versions in self._find_logically_deleted():
            stats_keys += 1
            stats_bytes += aggregate.total_size_bytes

            for v in versions:
                batch.append({"Key": v.key, "VersionId": v.version_id})
                if len(batch) >= self.BATCH_SIZE:
                    stats_deleted_versions += self._delete_batch(batch)
                    batch.clear()

            # Dynamic progress
            print(
                f"Scanned {self.scanned_count} versions | Found {stats_keys} keys | Deleted {stats_deleted_versions} versions ({self._format_bytes(stats_bytes)})"
                + " " * 20,
                end="\r",
            )

        # Flush remaining
        if batch:
            stats_deleted_versions += self._delete_batch(batch)

        # Clear progress line
        print(" " * 100, end="\r")

        if stats_keys == 0:
            print("No logically deleted objects found.")
        else:
            print(
                f"\nDone. Deleted {stats_deleted_versions} versions from {stats_keys} keys."
            )
            print(f"Freed {self._format_bytes(stats_bytes)}.")

        return stats_keys, stats_deleted_versions, stats_bytes


def signal_handler(sig, frame):
    print("\n\nScan interrupted by user. Cleaning up...")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan and clean logically deleted objects in S3.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
        # Scan only (default)
        %(prog)s my-bucket

        # Scan with filters
        %(prog)s my-bucket --prefix logs/ --deleted-after 2024-12-01

        # Delete with confirmation prompt
        %(prog)s my-bucket --purge

        # Delete without confirmation (automation)
        %(prog)s my-bucket --purge --noinput
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

    # Action flags
    parser.add_argument(
        "--info", action="store_true", help="Show bucket information (default behavior)"
    )
    parser.add_argument("--scan", action="store_true", help="Scan only")

    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete found objects (requires confirmation unless --noinput)",
    )

    parser.add_argument(
        "--noinput",
        action="store_true",
        help="Skip confirmation prompt (use with --purge for automation)",
    )

    args = parser.parse_args()

    if args.deleted_after:
        args.deleted_after = args.deleted_after.replace(tzinfo=timezone.utc)

    # Create scanner
    try:
        cleaner = ObjectStorageScanner(
            bucket=args.bucket,
            region_name=args.region,
            profile=args.profile,
            endpoint_url=args.endpoint_url,
            prefix=args.prefix,
            deleted_after=args.deleted_after,
        )
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1

    if args.info:
        cleaner.get_bucket_info()
        return 0

    # Mode: Scan only
    elif args.scan:
        cleaner.scan()
        return 0

    # Mode: Purge (with or without confirmation)
    elif args.purge:
        if not args.noinput:
            print(f"\nTarget Bucket: {args.bucket}")
            if args.prefix:
                print(f"Prefix: {args.prefix}")

            print(
                "WARNING: You are about to permanently delete logically deleted objects. This action cannot be undone!"
            )
            confirm = input("Type 'yes' to confirm deletion: ").strip().lower()

            if confirm != "yes":
                print("Operation cancelled.")
                return 0

        # Execute deletion
        if args.noinput:
            print("\nDeleting...")
        else:
            print("\nStarting cleanup...")

        cleaner.clean()

    # Default fallback to info
    else:
        print("No action specified. Use --info, --scan, or --purge.")
        print("Use --help for usage information.")
        print("Defaulting to --info.")
        cleaner.get_bucket_info()
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
