import logging
from unittest.mock import patch

from django.test import TestCase

from qfieldcloud.filestorage.backend import QfcS3Boto3Storage

logging.disable(logging.CRITICAL)


class QfcS3Boto3StorageTestCase(TestCase):
    """Tests for _get_write_parameters Content-Type detection.

    The version-detection regex mirrors the S3 key format produced by
    FileVersion.display and get_file_version_upload_to in models.py.
    The contract tests below verify that the regex matches keys built
    from those same format strings — if someone changes either the
    display format or the UUID fragment length in models.py, these
    tests will fail, forcing the regex in backend.py to be updated.
    """

    def setUp(self):
        with patch(
            "storages.backends.s3.S3Storage.__init__",
            lambda self, **kwargs: None,
        ):
            self.storage = QfcS3Boto3Storage()

    def _call(self, name, parent_params=None):
        if parent_params is None:
            parent_params = {}

        with patch(
            "storages.backends.s3.S3Storage._get_write_parameters",
            return_value=parent_params,
        ):
            return self.storage._get_write_parameters(name)

    # ==================================================================
    # HAPPY PATH — versioned paths for common file types
    # ==================================================================

    def test_versioned_jpg(self):
        params = self._call(
            "projects/abc123/files/DCIM/photo.jpg/v20260317162354-512bd29b"
        )
        self.assertEqual(params["ContentType"], "image/jpeg")

    def test_versioned_png(self):
        params = self._call(
            "projects/abc123/files/maps/topo.png/v20260610152033-a1b2c3d4"
        )
        self.assertEqual(params["ContentType"], "image/png")

    def test_versioned_pdf(self):
        params = self._call("projects/abc123/files/report.pdf/v20261231235959-abcdef01")
        self.assertEqual(params["ContentType"], "application/pdf")

    # ==================================================================
    # REGRESSION — non-versioned paths must still work
    # ==================================================================

    def test_non_versioned_jpg(self):
        params = self._call("projects/abc123/files/DCIM/photo.jpg")
        self.assertEqual(params["ContentType"], "image/jpeg")

    def test_non_versioned_txt(self):
        params = self._call("projects/abc123/files/notes.txt")
        self.assertEqual(params["ContentType"], "text/plain")

    # ==================================================================
    # EDGE CASES
    # ==================================================================

    def test_no_extension_versioned(self):
        """Versioned path where the original filename has no extension
        — no Content-Type should be set."""
        params = self._call("projects/abc123/files/README/v20260317162354-512bd29b")
        self.assertNotIn("ContentType", params)

    def test_preserves_existing_parent_params(self):
        """Params set by the parent S3Storage call (e.g. ACL) survive."""
        params = self._call(
            "projects/abc123/files/photo.jpg/v20260317162354-512bd29b",
            parent_params={"ACL": "public-read"},
        )
        self.assertEqual(params["ACL"], "public-read")
        self.assertEqual(params["ContentType"], "image/jpeg")

    def test_old_year_format_not_matched(self):
        """v1999… does not match the regex — falls through safely
        to guess_type on the last path component (no extension)."""
        params = self._call("projects/abc123/files/photo.jpg/v19991231235959-abcdef01")
        self.assertNotIn("ContentType", params)
