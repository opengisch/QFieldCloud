from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import boto3
from purge_deleted_objects import parse_retention_period

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import (
        DeleteMarkerEntryTypeDef,
        ListObjectVersionsOutputTypeDef,
        ObjectVersionTypeDef,
    )


class TestObjectStorageCleaner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Creates a boto3 s3 client and ensures bucket exists."""
        cls.s3_client = boto3.client("s3")
        cls.bucket_name = f"test-bucket-{uuid.uuid4()}"
        try:
            cls.s3_client.create_bucket(Bucket=cls.bucket_name)
        except cls.s3_client.exceptions.BucketAlreadyOwnedByYou:
            pass
        except cls.s3_client.exceptions.BucketAlreadyExists:
            pass

        # Enable versioning
        cls.s3_client.put_bucket_versioning(
            Bucket=cls.bucket_name, VersioningConfiguration={"Status": "Enabled"}
        )

    @classmethod
    def tearDownClass(cls):
        """Cleans up by emptying and deleting the test bucket."""
        try:
            # Empty the bucket (both versions and delete markers)
            paginator = cls.s3_client.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=cls.bucket_name):
                versions = page.get("Versions", []) + page.get("DeleteMarkers", [])
                if versions:
                    objects_to_delete = []
                    for v in versions:
                        objects_to_delete.append(
                            {"Key": v["Key"], "VersionId": v["VersionId"]}
                        )

                    # Delete in batches of 1000 (S3 limit)
                    for i in range(0, len(objects_to_delete), 1000):
                        cls.s3_client.delete_objects(
                            Bucket=cls.bucket_name,
                            Delete={"Objects": objects_to_delete[i : i + 1000]},
                        )

            # Delete the bucket itself
            cls.s3_client.delete_bucket(Bucket=cls.bucket_name)
        except Exception as e:
            raise Exception(f"Error cleaning up bucket {cls.bucket_name}: {e}") from e

    def setUp(self):
        """Generates a unique prefix for test isolation."""
        self.unique_prefix = f"test-run-{uuid.uuid4()}/"

    def run_script(self, args):
        """Runs the purge_deleted_objects.py script as a subprocess."""
        # Assume script is in the same directory as this test file
        script_path = os.path.join(
            os.path.dirname(__file__), "purge_deleted_objects.py"
        )
        cmd = [sys.executable, script_path, self.bucket_name] + args

        result = subprocess.run(cmd, capture_output=True, text=True)

        self.assertEqual(result.returncode, 0)

        return result

    def create_file(self, key: str, content: str = "test content") -> None:
        # Get number of versions before creating the file
        number_of_versions = len(self.list_versions(key))

        # Create the file
        self.s3_client.put_object(Bucket=self.bucket_name, Key=key, Body=content)

        # Check that the number of versions has increased by 1
        self.assertEqual(len(self.list_versions(key)), number_of_versions + 1)

        # Check that the object exists
        self.assertIsNotNone(
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
        )

        # Check content
        file = (
            self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            .get("Body")
            .read()
            .decode("utf-8")
        )
        self.assertEqual(file, content)

    def delete_file(self, key: str) -> None:
        # Get number of versions before deleting the file
        number_of_versions = len(self.list_versions(key))

        # Delete the file
        self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)

        # Check that the number of versions has increased by 1 (a delete marker is created)
        self.assertEqual(len(self.list_versions(key)), number_of_versions + 1)

        # Check that the object does not exist
        with self.assertRaises(self.s3_client.exceptions.ClientError):
            self.s3_client.get_object(Bucket=self.bucket_name, Key=key)

    def list_versions(
        self, prefix: str | None = None
    ) -> list[DeleteMarkerEntryTypeDef | ObjectVersionTypeDef]:
        versions: ListObjectVersionsOutputTypeDef = self.s3_client.list_object_versions(
            Bucket=self.bucket_name, Prefix=prefix
        )
        all_versions = versions.get("Versions", []) + versions.get("DeleteMarkers", [])
        return all_versions

    def test_no_logically_deleted_files(self):
        """
        test that no logically deleted objects are found if there are no deleted files.
        """
        # 1. Upload a file
        key = f"{self.unique_prefix}file1.txt"
        self.create_file(key)

        time.sleep(1)

        # 2. Run scan
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 3. Verify output
        self.assertIn("Total deleted keys found: 0", result.stdout)
        self.assertIn("Total size wasted: 0 B", result.stdout)
        self.assertIn("Total versions wasted: 0", result.stdout)

        # 4. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 5. Verify file is still there
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 1)

    def test_restored_files_ignored(self):
        """
        test that a file is not found if it is restored after being deleted.
        """
        # 1. Upload file (v1)
        key = f"{self.unique_prefix}file_restored.txt"
        self.create_file(key, "v1")

        # 2. Delete file (v2 - delete marker)
        self.delete_file(key)

        # 3. Restore file (v3 - new version)
        self.create_file(key, "v3")

        time.sleep(1)

        # 4. Run scan
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 5. Verify output - should not find it
        self.assertIn("Total deleted keys found: 0", result.stdout)
        self.assertIn("Total size wasted: 0 B", result.stdout)
        self.assertIn("Total versions wasted: 0", result.stdout)

        # 6. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 7. Verify that no versions are deleted
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 3)

    def test_retention_period_filter(self):
        """
        Test that a file is NOT found if the retention period covers it (recent deletion).
        And that a file IS found if the retention period has passed (old deletion).
        """
        key = f"{self.unique_prefix}file_date_test.txt"
        self.create_file(key, "a" * 100)  # 100 bytes of content
        self.delete_file(key)

        # Wait 2 seconds to ensure clock skew isn't an issue if running locally fast
        # This is to ensure the file is deleted before the scan is run
        time.sleep(2)

        # Retention period is SHORT (1 second).
        # The file was deleted 2 seconds ago. 2s > 1s.
        # So the file is OLDER than the retention period. It should be FOUND (not protected).
        result_short_retention = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        self.assertIn("Total deleted keys found: 1", result_short_retention.stdout)
        self.assertIn("Total size wasted: 100.00 B", result_short_retention.stdout)
        self.assertIn("Total versions wasted: 2", result_short_retention.stdout)

        # Retention period is LONG (5 seconds).
        # The file was deleted 2 seconds ago. 2s < 5s.
        # So the file is NEWER than the retention period. It should be PROTECTED (skipped).
        result_long_retention = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "5 seconds",
            ]
        )

        self.assertIn("Total deleted keys found: 0", result_long_retention.stdout)
        self.assertIn("Total size wasted: 0 B", result_long_retention.stdout)
        self.assertIn("Total versions wasted: 0", result_long_retention.stdout)

        # Run without dry-run
        result_long_retention = self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "5 second",
            ]
        )

        # Verify file is still there (long retention period should keep the file)
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 2)

        # Run without dry-run (short retention period should delete the file)
        result_short_retention = self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # Verify file is completely gone (no versions left)
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 0)

    def test_stray_delete_marker(self):
        """
        test that a key exists only as a Delete Marker is identified and deleted.
        """
        key = f"{self.unique_prefix}stray_marker"

        # 1. Create a file
        self.create_file(key, "a" * 100)  # 100 bytes of content

        # 2. Delete it (creates marker)
        self.delete_file(key)

        # 3. Manually delete the data version, leaving ONLY the marker
        versions = self.list_versions(key)

        # Find the data version
        data_version = None
        for v in versions:
            if not v.get("IsDeleteMarker", False):
                data_version = v
                break

        # Delete the data version
        if data_version:
            self.s3_client.delete_object(
                Bucket=self.bucket_name, Key=key, VersionId=data_version["VersionId"]
            )

        time.sleep(1)

        # 4. Run Scan
        # The script should identify the stray marker and delete it
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        self.assertIn("Total deleted keys found: 1", result.stdout)
        # 0 bytes because it's a delete marker
        self.assertIn("Total size wasted: 0 B", result.stdout)
        self.assertIn("Total versions wasted: 1", result.stdout)

        # 5. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 6. Verify file is completely gone (no versions left)
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 0)

    def test_permanently_deleted(self):
        """
        test that a file is found if it is deleted and then permanently deleted.
        """
        # 1. Upload file
        key = f"{self.unique_prefix}file_deleted.txt"
        self.create_file(key, "a" * 100)

        # 2. Delete file (creates delete marker)
        self.delete_file(key)

        time.sleep(1)

        # 3. Run with dry-run
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )
        self.assertIn("Total deleted keys found: 1", result.stdout)
        self.assertIn("Total size wasted: 100.00 B", result.stdout)
        self.assertIn("Total versions wasted: 2", result.stdout)

        # 4. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 5. Verify file is completely gone (no versions left)
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 0)

    def test_permanently_delete_complex_version_history(self):
        """
        test that all versions (history) are permanently deleted when the key is deleted.
        """
        key = f"{self.unique_prefix}complex_history.txt"

        # 1. v1: Create
        self.create_file(key, "a" * 100)
        # 2. v2: Delete
        self.delete_file(key)
        # 3. v3: Re-create
        self.create_file(key, "a" * 100)
        # 4. v4: Delete again (Final state is deleted)
        self.delete_file(key)

        time.sleep(1)

        # 5. Run with dry-run
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )
        self.assertIn("Total deleted keys found: 1", result.stdout)
        self.assertIn("Total size wasted: 200.00 B", result.stdout)
        self.assertIn("Total versions wasted: 4", result.stdout)

        # 6. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 7. Verify file is completely gone (no versions left)
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 0)

    def test_permanently_delete_versions_large_data_complex_version_history(self):
        """
        test that all versions (history) are permanently deleted when the key is deleted with a large amount of data in an unordered way.
        """
        # Create key1
        key1 = f"{self.unique_prefix}_SHOULD_BE_DELETED"
        self.create_file(key1, "a" * 100)

        # Create 100 files
        for i in range(100):
            self.create_file(
                f"{self.unique_prefix}file_{i}.txt", str(i).ljust(100, "a")
            )

        # Delete key1
        self.delete_file(key1)

        # Create 100 files
        for i in range(100):
            self.create_file(
                f"{self.unique_prefix}file_{i}_a.txt", str(i).ljust(100, "a")
            )

        # Restore key1
        self.create_file(key1, "a" * 100)

        time.sleep(1)

        # 1. Run with dry-run
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )
        self.assertIn("Total deleted keys found: 0", result.stdout)
        self.assertIn("Total size wasted: 0 B", result.stdout)
        self.assertIn("Total versions wasted: 0", result.stdout)

        # 2. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 3. Verify file is completely gone (no versions left)
        versions = self.list_versions(self.unique_prefix)
        # 1 (key1) + 100 (files) + 1 (key1 deleted) + 100 (files) + 1 (key1 restored)
        self.assertEqual(len(versions), 203)

        # 4. delete the key A again
        self.delete_file(key1)

        time.sleep(1)

        # 5. Run with dry-run
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )
        self.assertIn("Total deleted keys found: 1", result.stdout)
        self.assertIn("Total size wasted: 200.00 B", result.stdout)
        self.assertIn("Total versions wasted: 4", result.stdout)

        # 6. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 7. Verify file is completely gone (no versions left)
        versions = self.list_versions(self.unique_prefix)
        # 204 (203 + 1 delete marker version) - 4 (key1 versions)
        self.assertEqual(len(versions), 200)

    def test_permanently_delete_versions_high_frequency_updates(self):
        """
        test that a key with high frequency updates is identified and deleted.
        """
        key = f"{self.unique_prefix}fast_updates.txt"

        # Create 20 versions as fast as possible
        for i in range(20):
            self.create_file(key, str(i).ljust(100, "a"))

        # Delete at the end
        self.delete_file(key)

        time.sleep(1)

        # 1. Run with dry-run
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )
        self.assertIn("Total deleted keys found: 1", result.stdout)
        self.assertIn("Total size wasted: 1.95 KB", result.stdout)
        self.assertIn("Total versions wasted: 21", result.stdout)

        # 2. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "1 second",
            ]
        )

        # 3. Verify file is completely gone (no versions left)
        versions = self.list_versions(key)
        self.assertEqual(len(versions), 0)

    def test_selective_retention_with_multiple_keys(self):
        """
        test that different keys are identified and deleted. With the same prefix but different keys.
        """
        keyA = f"{self.unique_prefix}keyA.txt"
        keyB = f"{self.unique_prefix}keyB.txt"

        self.create_file(keyA, "A" * 100)
        self.delete_file(keyA)

        time.sleep(2)

        self.create_file(keyB, "B" * 100)
        self.delete_file(keyB)

        # 1. Run with dry-run
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "2 second",
            ]
        )
        self.assertIn("Total deleted keys found: 1", result.stdout)
        self.assertIn("Total size wasted: 100.00 B", result.stdout)
        self.assertIn("Total versions wasted: 2", result.stdout)

        # 2. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                self.unique_prefix,
                "--retention-period",
                "2 second",
            ]
        )

        # 3. Verify that only A keys are deleted
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 2)

        # 4. Verify that KeyB is not deleted
        for version in versions:
            self.assertEqual(version["Key"], keyB)

    def test_selective_retention_with_multiple_keys_and_different_prefixes(self):
        """
        test that different keys with different prefixes are not identified and deleted.
        """
        prefixA = f"{self.unique_prefix}A/"
        prefixB = f"{self.unique_prefix}B/"
        keyA = f"{prefixA}keyA.txt"
        keyB = f"{prefixB}keyB.txt"

        self.create_file(keyA, "A" * 100)
        self.delete_file(keyA)

        self.create_file(keyB, "B" * 100)
        self.delete_file(keyB)

        time.sleep(2)

        # 1. Run with dry-run
        result = self.run_script(
            [
                "--dry-run",
                "--prefix",
                prefixA,
                "--retention-period",
                "2 second",
            ]
        )
        self.assertIn("Total deleted keys found: 1", result.stdout)
        self.assertIn("Total size wasted: 100.00 B", result.stdout)
        self.assertIn("Total versions wasted: 2", result.stdout)

        # 2. Run without dry-run
        self.run_script(
            [
                "--force",
                "--prefix",
                prefixA,
                "--retention-period",
                "2 second",
            ]
        )

        # 3. Verify that KeyB still exists
        versions = self.list_versions(prefixB)
        self.assertEqual(len(versions), 2)

        # 4. Verify that KeyB is not deleted
        for version in versions:
            self.assertEqual(version["Key"], keyB)

        # 5. Verify that KeyA is deleted
        versions = self.list_versions(prefixA)
        self.assertEqual(len(versions), 0)

    def test_parse_retention_period_valid_inputs(self):
        """Test that parse_retention_period correctly parses valid duration strings."""
        # Test various valid formats
        test_cases = [
            ("1 second", 1, "seconds"),
            ("10 seconds", 10, "seconds"),
            ("5 minutes", 5, "minutes"),
            ("2 hours", 2, "hours"),
            ("30 days", 30, "days"),
            ("2 weeks", 2, "weeks"),
            ("1 week", 1, "weeks"),
        ]

        for duration_str, amount, unit in test_cases:
            result = parse_retention_period(duration_str)

            # Calculate expected datetime using dictionary unpacking
            expected = datetime.now(timezone.utc) - timedelta(**{unit: amount})

            # Allow 1 second tolerance for test execution time
            self.assertAlmostEqual(
                result.timestamp(),
                expected.timestamp(),
                delta=1,
                msg=f"Failed for input: {duration_str}",
            )

    def test_parse_retention_period_invalid_inputs(self):
        """Test that parse_retention_period raises ArgumentTypeError for invalid inputs."""
        invalid_inputs = [
            "invalid",  # No number
            "10",  # No unit
            "10 months",  # Unsupported unit
            "-5 days",  # Negative number
            "3.5 hours",  # Decimal number
            "ten days",  # Word instead of number
            "",  # Empty string
            "days 10",  # Reversed order
            "5 10 days",  # Multiple numbers
            "5 days weeks",  # Multiple units
            "1 day 2 hours",  # Compound duration
            "9999999999 days",  # Too many days
            "⑤ days",  # Unicode number
            123,  # Int
        ]

        for invalid_input in invalid_inputs:
            with self.assertRaises(
                argparse.ArgumentTypeError,
                msg=f"Should raise error for: {invalid_input}",
            ):
                parse_retention_period(invalid_input)

    def test_parse_retention_period_returns_utc_timezone(self):
        """Test that returned datetime is UTC timezone-aware."""
        result = parse_retention_period("1 day")
        self.assertEqual(result.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
