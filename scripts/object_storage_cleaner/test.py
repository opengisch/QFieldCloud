import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import boto3
import pytest

# --- Configuration ---
CONNECTION_CONFIG = {
    "endpoint_url": "http://localhost:8009",
    "region_name": "us-east-1",
}
BUCKET_NAME = "test-bucket"

# --- Fixtures ---


@pytest.fixture(scope="session")
def s3_client():
    """Creates a boto3 s3 client."""
    return boto3.client("s3", **CONNECTION_CONFIG)


@pytest.fixture(scope="session")
def ensure_bucket(s3_client):
    """Ensures the test bucket exists and has versioning enabled."""
    try:
        s3_client.create_bucket(Bucket=BUCKET_NAME)
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except s3_client.exceptions.BucketAlreadyExists:
        pass

    # Enable versioning
    s3_client.put_bucket_versioning(
        Bucket=BUCKET_NAME, VersioningConfiguration={"Status": "Enabled"}
    )
    return BUCKET_NAME


@pytest.fixture
def unique_prefix(ensure_bucket):
    """Generates a unique prefix for test isolation."""
    return f"test-run-{uuid.uuid4()}/"


# --- Helper Functions ---


def run_script(args):
    """Runs the storage_cleaner.py script as a subprocess."""
    cmd = [sys.executable, "storage_cleaner.py", BUCKET_NAME] + args

    # Add connection args
    if "endpoint_url" in CONNECTION_CONFIG:
        cmd.extend(["--endpoint-url", CONNECTION_CONFIG["endpoint_url"]])

    if "aws_access_key_id" in CONNECTION_CONFIG:
        cmd.extend(["--access-key-id", CONNECTION_CONFIG["aws_access_key_id"]])

    if "aws_secret_access_key" in CONNECTION_CONFIG:
        cmd.extend(["--secret-access-key", CONNECTION_CONFIG["aws_secret_access_key"]])

    if "region_name" in CONNECTION_CONFIG:
        cmd.extend(["--region", CONNECTION_CONFIG["region_name"]])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def create_file(s3_client, bucket, key, content="test content"):
    s3_client.put_object(Bucket=bucket, Key=key, Body=content)


def delete_file(s3_client, bucket, key):
    s3_client.delete_object(Bucket=bucket, Key=key)


def list_versions(s3_client, bucket, prefix):
    versions = s3_client.list_object_versions(Bucket=bucket, Prefix=prefix)
    all_versions = versions.get("Versions", []) + versions.get("DeleteMarkers", [])
    return all_versions


# --- Tests ---


def test_no_logically_deleted_files(s3_client, unique_prefix):
    """
    Upload files to object storage - no deleted files
    (shouldn't find any logically deleted objects) -> Nothing deleted
    """
    # 1. Upload files
    key = f"{unique_prefix}file1.txt"
    create_file(s3_client, BUCKET_NAME, key)

    # 2. Run scan
    result = run_script(["--scan", "--prefix", unique_prefix])

    # 3. Verify output
    assert result.returncode == 0
    assert "No logically deleted objects found" in result.stdout


def test_logically_deleted_files_cleanup(s3_client, unique_prefix):
    """
    Upload files to object storage - delete some files
    (should find logically deleted objects) -> Deleted files
    """
    # 1. Upload file
    key = f"{unique_prefix}file_deleted.txt"
    create_file(s3_client, BUCKET_NAME, key)

    # 2. Delete file (creates delete marker)
    delete_file(s3_client, BUCKET_NAME, key)

    # 3. Run purge
    result = run_script(["--purge", "--noinput", "--prefix", unique_prefix])

    # 4. Verify output and state
    assert result.returncode == 0
    assert "Deleted 2 versions from 1 keys" in result.stdout

    # Verify file is completely gone (no versions left)
    versions = list_versions(s3_client, BUCKET_NAME, unique_prefix)
    assert len(versions) == 0


def test_restored_files_ignored(s3_client, unique_prefix):
    """
    Upload files to object storage - delete some files - restore
    (shouldn't find any logically deleted objects) -> Nothing deleted
    """
    # 1. Upload file (v1)
    key = f"{unique_prefix}file_restored.txt"
    create_file(s3_client, BUCKET_NAME, key, "v1")

    # 2. Delete file (v2 - delete marker)
    delete_file(s3_client, BUCKET_NAME, key)

    # 3. Restore file (v3 - new version)
    create_file(s3_client, BUCKET_NAME, key, "v3")

    # 4. Run scan
    result = run_script(["--scan", "--prefix", unique_prefix])

    # 5. Verify output - should not find it
    assert result.returncode == 0
    assert "No logically deleted objects found" in result.stdout


def test_deleted_after_filter(s3_client, unique_prefix):
    """
    Upload files, delete some, test deleted-after filter.
    """
    key = f"{unique_prefix}file_date_test.txt"
    create_file(s3_client, BUCKET_NAME, key)
    delete_file(s3_client, BUCKET_NAME, key)

    # Wait a moment to ensure clock skew isn't an issue if running locally fast
    time.sleep(1)

    now = datetime.now(timezone.utc)
    future_date = now + timedelta(days=30)
    past_date = now - timedelta(days=30)

    # Filter is in the FUTURE.

    result_future = run_script(
        [
            "--scan",
            "--prefix",
            unique_prefix,
            "--deleted-after",
            future_date.isoformat(),
        ]
    )
    assert "No logically deleted objects found" in result_future.stdout

    # Filter is in the PAST.

    result_past = run_script(
        ["--scan", "--prefix", unique_prefix, "--deleted-after", past_date.isoformat()]
    )
    assert "No logically deleted objects found" not in result_past.stdout
    assert "Total logically deleted keys: 1" in result_past.stdout


def test_complex_version_history(s3_client, unique_prefix):
    """
    File created, deleted, created again, deleted again.
    Ensure ALL versions (history) are cleaned up.
    """
    key = f"{unique_prefix}complex_history.txt"

    # 1. v1: Create
    create_file(s3_client, BUCKET_NAME, key, "v1")
    # 2. v2: Delete
    delete_file(s3_client, BUCKET_NAME, key)
    # 3. v3: Re-create
    create_file(s3_client, BUCKET_NAME, key, "v3")
    # 4. v4: Delete again (Final state is deleted)
    delete_file(s3_client, BUCKET_NAME, key)

    # Run purge
    result = run_script(["--purge", "--noinput", "--prefix", unique_prefix])

    assert result.returncode == 0
    assert "Deleted 4 versions from 1 keys" in result.stdout

    # Verify completely empty
    versions = list_versions(s3_client, BUCKET_NAME, unique_prefix)
    assert len(versions) == 0


def test_large_data_complex_version_history(s3_client, unique_prefix):
    """
    Upload a large amount of data, delete some, test deleted-after filter.
    """
    # Create key1
    key1 = f"{unique_prefix}_SHOULD_BE_DELETED"
    create_file(s3_client, BUCKET_NAME, key1, "a" * 1000000)

    # Create 100 files
    for i in range(100):
        create_file(
            s3_client, BUCKET_NAME, f"{unique_prefix}file_{i}.txt", "a" * 1000000
        )

    # Delete key1
    delete_file(s3_client, BUCKET_NAME, key1)

    # Create 100 files
    for i in range(100):
        create_file(
            s3_client, BUCKET_NAME, f"{unique_prefix}file_{i}_a.txt", "a" * 1000000
        )

    # Restore key1
    create_file(s3_client, BUCKET_NAME, key1, "a" * 1000000)

    # Run purge
    result = run_script(["--purge", "--noinput", "--prefix", unique_prefix])

    # Verify output (should not find any logically deleted objects)
    assert result.returncode == 0
    assert "No logically deleted objects found" in result.stdout

    # delete the key A again
    delete_file(s3_client, BUCKET_NAME, key1)

    # Run purge
    result = run_script(["--purge", "--noinput", "--prefix", unique_prefix])

    # Verify output (should find logically deleted objects)
    assert result.returncode == 0
    assert "Deleted 4 versions from 1 keys" in result.stdout
