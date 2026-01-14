import subprocess
import sys
import time
import uuid

import boto3
import pytest

BUCKET_NAME = "test-bucket"


@pytest.fixture(scope="session")
def s3_client():
    """Creates a boto3 s3 client."""
    return boto3.client("s3")


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


def run_script(args):
    """Runs the object_storage_cleaner.py script as a subprocess."""
    cmd = [sys.executable, "object_storage_cleaner.py", BUCKET_NAME] + args

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


def test_scan_no_logically_deleted_files(s3_client, unique_prefix):
    """
    test that no logically deleted objects are found if there are no deleted files.
    """
    # 1. Upload a file
    key = f"{unique_prefix}file1.txt"
    create_file(s3_client, BUCKET_NAME, key)

    # 2. Run scan
    result = run_script(["--scan", "--prefix", unique_prefix])

    # 3. Verify output
    assert "Total keys found: 0" in result.stdout
    assert "Total size wasted: 0 bytes" in result.stdout
    assert "Total versions wasted: 0" in result.stdout


def test_scan_restored_files_ignored(s3_client, unique_prefix):
    """
    test that a file is not found if it is restored after being deleted.
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
    assert "Total keys found: 0" in result.stdout
    assert "Total size wasted: 0 bytes" in result.stdout
    assert "Total versions wasted: 0" in result.stdout


def test_scan_retention_period_filter(s3_client, unique_prefix):
    """
    Test that a file is NOT found if the retention period covers it (recent deletion).
    And that a file IS found if the retention period has passed (old deletion).
    """
    key = f"{unique_prefix}file_date_test.txt"
    create_file(s3_client, BUCKET_NAME, key, "a" * 100)  # 100 bytes of content
    delete_file(s3_client, BUCKET_NAME, key)

    # Wait 2 seconds to ensure clock skew isn't an issue if running locally fast
    # This is to ensure the file is deleted before the scan is run
    time.sleep(2)

    # Retention period is SHORT (1 second).
    # The file was deleted 2 seconds ago. 2s > 1s.
    # So the file is OLDER than the retention period. It should be FOUND (not protected).
    result_short_retention = run_script(
        [
            "--scan",
            "--prefix",
            unique_prefix,
            "--retention-period",
            "1 second",
        ]
    )

    assert "Total keys found: 1" in result_short_retention.stdout
    assert "Total size wasted: 100 bytes" in result_short_retention.stdout
    assert "Total versions wasted: 2" in result_short_retention.stdout

    # Retention period is LONG (5 seconds).
    # The file was deleted 2 seconds ago. 2s < 5s.
    # So the file is NEWER than the retention period. It should be PROTECTED (skipped).
    result_long_retention = run_script(
        ["--scan", "--prefix", unique_prefix, "--retention-period", "5 seconds"]
    )

    assert "Total keys found: 0" in result_long_retention.stdout
    assert "Total size wasted: 0 bytes" in result_long_retention.stdout
    assert "Total versions wasted: 0" in result_long_retention.stdout


def test_scan_stray_delete_marker(s3_client, unique_prefix):
    """
    test that a key exists only as a Delete Marker is identified and deleted.
    """
    key = f"{unique_prefix}stray_marker"

    # 1. Create a file
    create_file(s3_client, BUCKET_NAME, key, "a" * 100)  # 100 bytes of content

    # 2. Delete it (creates marker)
    delete_file(s3_client, BUCKET_NAME, key)

    # 3. Manually delete the data version, leaving ONLY the marker
    versions = list_versions(s3_client, BUCKET_NAME, key)

    # Find the data version
    data_version = None
    for v in versions:
        if not v.get("IsDeleteMarker", False):
            data_version = v
            break

    # Delete the data version
    if data_version:
        s3_client.delete_object(
            Bucket=BUCKET_NAME, Key=key, VersionId=data_version["VersionId"]
        )

    # 4. Run Scan
    # The script should identify the stray marker and delete it
    result = run_script(["--scan", "--prefix", unique_prefix])

    assert "Total keys found: 1" in result.stdout
    assert (
        "Total size wasted: 0 bytes" in result.stdout
    )  # 0 bytes because it's a delete marker
    assert "Total versions wasted: 1" in result.stdout


def test_permanently_deleted(s3_client, unique_prefix):
    """
    test that a file is found if it is deleted and then permanently deleted.
    """
    # 1. Upload file
    key = f"{unique_prefix}file_deleted.txt"
    create_file(s3_client, BUCKET_NAME, key)

    # 2. Delete file (creates delete marker)
    delete_file(s3_client, BUCKET_NAME, key)

    # 3. Run prune
    run_script(
        ["--permanently-delete-versions", "--noinput", "--prefix", unique_prefix]
    )

    # Verify file is completely gone (no versions left)
    versions = list_versions(s3_client, BUCKET_NAME, unique_prefix)
    assert len(versions) == 0


def test_permanently_delete_complex_version_history(s3_client, unique_prefix):
    """
    test that all versions (history) are permanently deleted when the key is deleted.
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

    # Run prune
    run_script(
        ["--permanently-delete-versions", "--noinput", "--prefix", unique_prefix]
    )

    # Verify completely empty
    versions = list_versions(s3_client, BUCKET_NAME, unique_prefix)
    assert len(versions) == 0


def test_permanently_delete_versions_large_data_complex_version_history(
    s3_client, unique_prefix
):
    """
    test that all versions (history) are permanently deleted when the key is deleted with a large amount of data in an unordered way.
    """
    # Create key1
    key1 = f"{unique_prefix}_SHOULD_BE_DELETED"
    create_file(s3_client, BUCKET_NAME, key1, "a" * 100)

    # Create 100 files
    for i in range(100):
        create_file(s3_client, BUCKET_NAME, f"{unique_prefix}file_{i}.txt", "a" * 100)

    # Delete key1
    delete_file(s3_client, BUCKET_NAME, key1)

    # Create 100 files
    for i in range(100):
        create_file(s3_client, BUCKET_NAME, f"{unique_prefix}file_{i}_a.txt", "a" * 100)

    # Restore key1
    create_file(s3_client, BUCKET_NAME, key1, "a" * 100)

    # Run permanently delete versions
    run_script(
        ["--permanently-delete-versions", "--noinput", "--prefix", unique_prefix]
    )

    # Verify completely empty
    versions = list_versions(s3_client, BUCKET_NAME, unique_prefix)
    assert (
        len(versions) == 203
    )  # 1 (key1) + 100 (files) + 1 (key1 deleted) + 100 (files) + 1 (key1 restored)

    # delete the key A again
    delete_file(s3_client, BUCKET_NAME, key1)

    # Run permanently delete versions
    run_script(
        ["--permanently-delete-versions", "--noinput", "--prefix", unique_prefix]
    )

    # Verify completely empty
    versions = list_versions(s3_client, BUCKET_NAME, unique_prefix)
    assert (
        len(versions) == 200
    )  # 204 (203 + 1 delete marker version) - 4 (key1 versions)


def test_permanently_delete_versions_high_frequency_updates(s3_client, unique_prefix):
    """
    test that a key with high frequency updates is identified and deleted.
    """
    key = f"{unique_prefix}fast_updates.txt"

    # Create 20 versions as fast as possible
    for i in range(20):
        create_file(s3_client, BUCKET_NAME, key, "a" * 100)

    # Delete at the end
    delete_file(s3_client, BUCKET_NAME, key)

    # Run permanently delete versions
    run_script(
        ["--permanently-delete-versions", "--noinput", "--prefix", unique_prefix]
    )

    # Verify everything is gone
    versions = list_versions(s3_client, BUCKET_NAME, key)
    assert len(versions) == 0
