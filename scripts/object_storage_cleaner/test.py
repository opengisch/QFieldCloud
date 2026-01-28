import os
import subprocess
import sys
import time
import unittest
import uuid

import boto3


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
        """Runs the object_storage_cleaner.py script as a subprocess."""
        # Assume script is in the same directory as this test file
        script_path = os.path.join(
            os.path.dirname(__file__), "object_storage_cleaner.py"
        )
        cmd = [sys.executable, script_path, self.bucket_name] + args

        result = subprocess.run(cmd, capture_output=True, text=True)
        return result

    def create_file(self, key, content="test content"):
        self.s3_client.put_object(Bucket=self.bucket_name, Key=key, Body=content)

    def delete_file(self, key):
        self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)

    def list_versions(self, prefix):
        versions = self.s3_client.list_object_versions(
            Bucket=self.bucket_name, Prefix=prefix
        )
        all_versions = versions.get("Versions", []) + versions.get("DeleteMarkers", [])
        return all_versions

    def test_scan_no_logically_deleted_files(self):
        """
        test that no logically deleted objects are found if there are no deleted files.
        """
        # 1. Upload a file
        key = f"{self.unique_prefix}file1.txt"
        self.create_file(key)

        # 2. Run scan
        result = self.run_script(["--dry-run", "--prefix", self.unique_prefix])

        # 3. Verify output
        self.assertIn("Total keys found: 0", result.stdout)
        self.assertIn("Total size wasted: 0 bytes", result.stdout)
        self.assertIn("Total versions wasted: 0", result.stdout)

    def test_scan_restored_files_ignored(self):
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

        # 4. Run scan
        result = self.run_script(["--dry-run", "--prefix", self.unique_prefix])

        # 5. Verify output - should not find it
        self.assertIn("Total keys found: 0", result.stdout)
        self.assertIn("Total size wasted: 0 bytes", result.stdout)
        self.assertIn("Total versions wasted: 0", result.stdout)

    def test_scan_retention_period_filter(self):
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

        self.assertIn("Total keys found: 1", result_short_retention.stdout)
        self.assertIn("Total size wasted: 100 bytes", result_short_retention.stdout)
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

        self.assertIn("Total keys found: 0", result_long_retention.stdout)
        self.assertIn("Total size wasted: 0 bytes", result_long_retention.stdout)
        self.assertIn("Total versions wasted: 0", result_long_retention.stdout)

    def test_scan_stray_delete_marker(self):
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

        # 4. Run Scan
        # The script should identify the stray marker and delete it
        result = self.run_script(["--dry-run", "--prefix", self.unique_prefix])

        self.assertIn("Total keys found: 1", result.stdout)
        # 0 bytes because it's a delete marker
        self.assertIn("Total size wasted: 0 bytes", result.stdout)
        self.assertIn("Total versions wasted: 1", result.stdout)

    def test_permanently_deleted(self):
        """
        test that a file is found if it is deleted and then permanently deleted.
        """
        # 1. Upload file
        key = f"{self.unique_prefix}file_deleted.txt"
        self.create_file(key)

        # 2. Delete file (creates delete marker)
        self.delete_file(key)

        # 3. Run prune
        self.run_script(["--force", "--prefix", self.unique_prefix])

        # Verify file is completely gone (no versions left)
        versions = self.list_versions(self.unique_prefix)
        self.assertEqual(len(versions), 0)

    def test_permanently_delete_complex_version_history(self):
        """
        test that all versions (history) are permanently deleted when the key is deleted.
        """
        key = f"{self.unique_prefix}complex_history.txt"

        # 1. v1: Create
        self.create_file(key, "v1")
        # 2. v2: Delete
        self.delete_file(key)
        # 3. v3: Re-create
        self.create_file(key, "v3")
        # 4. v4: Delete again (Final state is deleted)
        self.delete_file(key)

        # Run prune
        self.run_script(["--force", "--prefix", self.unique_prefix])

        # Verify completely empty
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
            self.create_file(f"{self.unique_prefix}file_{i}.txt", "a" * 100)

        # Delete key1
        self.delete_file(key1)

        # Create 100 files
        for i in range(100):
            self.create_file(f"{self.unique_prefix}file_{i}_a.txt", "a" * 100)

        # Restore key1
        self.create_file(key1, "a" * 100)

        # Run permanently delete versions
        self.run_script(["--force", "--prefix", self.unique_prefix])

        # Verify completely empty
        versions = self.list_versions(self.unique_prefix)
        # 1 (key1) + 100 (files) + 1 (key1 deleted) + 100 (files) + 1 (key1 restored)
        self.assertEqual(len(versions), 203)

        # delete the key A again
        self.delete_file(key1)

        # Run permanently delete versions
        self.run_script(["--force", "--prefix", self.unique_prefix])

        # Verify completely empty
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
            self.create_file(key, "a" * 100)

        # Delete at the end
        self.delete_file(key)

        # Run permanently delete versions
        self.run_script(["--force", "--prefix", self.unique_prefix])

        # Verify everything is gone
        versions = self.list_versions(key)
        self.assertEqual(len(versions), 0)


if __name__ == "__main__":
    unittest.main()
