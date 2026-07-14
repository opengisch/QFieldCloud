# from unittest import TestCase
import logging
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from qfieldcloud.core.tests.utils import qgz_from_qgs, testdata_path
from qfieldcloud.filestorage.utils import (
    is_admin_restricted_file,
    is_qgis_project_file,
    is_valid_filename,
    open_qgis_file,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def test_is_valid_filename_rejects_0_char_filename(self):
        self.assertFalse(is_valid_filename(""))

    def test_is_valid_filename_rejects_whitespace_char_at_start_filename(self):
        self.assertFalse(is_valid_filename(" "))

    def test_is_valid_filename_rejects_whitespace_char_at_end_filename(self):
        self.assertFalse(is_valid_filename(" "))

    def test_is_valid_filename_accepts_whitespace_char_at_middle_filename(self):
        self.assertTrue(is_valid_filename("f f"))

    def test_is_valid_filename_rejects_dot_char_at_end_filename(self):
        self.assertFalse(is_valid_filename("f."))

    def test_is_valid_filename_accepts_1_char_filename(self):
        self.assertTrue(is_valid_filename("f"))

    def test_is_valid_filename_accepts_files_without_extensions(self):
        self.assertTrue(is_valid_filename("file"))

    def test_is_valid_filename_accepts_files_with_extensions(self):
        self.assertTrue(is_valid_filename("file.txt"))

    def test_is_valid_filename_accepts_files_within_directories(self):
        self.assertTrue(is_valid_filename("path/to/file.txt"))

    def test_is_valid_filename_fails_with_too_long_name(self):
        base_filename = "this/is/a/very/long/filename/that/is/actually/261/characters/long/and/cannot/be/handled/by/windowsos/so-far/chars/are/122/"
        base_filename_length = len(base_filename)
        max_filename_length = settings.STORAGE_FILENAME_MAX_CHAR_LENGTH

        self.assertTrue(
            is_valid_filename(
                base_filename + ("x" * (max_filename_length - base_filename_length + 0))
            )
        )
        self.assertFalse(
            is_valid_filename(
                base_filename + ("x" * (max_filename_length - base_filename_length + 1))
            )
        )

    def test_is_valid_filename_fails_with_windows_reserved_words(self):
        self.assertFalse(is_valid_filename(r"/path/NUL"))

    def test_is_valid_filename_fails_with_slashes(self):
        self.assertFalse(is_valid_filename(r"/path/file\/name"))

    def test_is_valid_filename_fails_with_null_char(self):
        self.assertFalse(is_valid_filename(r"/path/file\x00name"))

    def test_is_valid_filename_fails_with_carriage_return(self):
        self.assertFalse(is_valid_filename("file\r.txt"))

    def test_is_valid_filename_fails_with_newline(self):
        self.assertFalse(is_valid_filename("file\n.txt"))

    def test_is_valid_filename_fails_with_del_character(self):
        self.assertFalse(is_valid_filename("file\x7f.txt"))

    def test_is_qgis_project_file(self):
        self.assertTrue(is_qgis_project_file("test.qgs"))
        self.assertTrue(is_qgis_project_file("test.qgz"))

    def test_is_qgis_project_file_with_directory(self):
        self.assertTrue(is_qgis_project_file("path/test.qgs"))
        self.assertTrue(is_qgis_project_file("path/test.qgz"))

    def test_is_qgis_project_file_with_capitals(self):
        self.assertTrue(is_qgis_project_file("path/test.QGS"))
        self.assertTrue(is_qgis_project_file("path/test.QGZ"))

    def test_is_qgis_project_file_invalid_when_not_qgis_filename(self):
        self.assertFalse(is_qgis_project_file("test.txt"))
        self.assertFalse(is_qgis_project_file("test.gpkg"))

    def test_is_qgis_project_file_invalid_when_only_file_extension(self):
        self.assertFalse(is_qgis_project_file("qgs"))
        self.assertFalse(is_qgis_project_file("qgz"))

    def test_is_qgis_project_file_invalid_when_only_file_extension_with_dot(self):
        self.assertFalse(is_qgis_project_file(".qgs"))
        self.assertFalse(is_qgis_project_file(".qgz"))

    def test_is_admin_restricted_file_without_projectfile(self):
        self.assertFalse(is_admin_restricted_file("filename.qgs", None))
        self.assertFalse(is_admin_restricted_file("filename_attachments.qgs", None))
        self.assertFalse(is_admin_restricted_file("filename.qml", None))

    def test_is_admin_restricted_file_qgis_file(self):
        self.assertTrue(is_admin_restricted_file("filename.qgs", "filename.qgs"))
        self.assertFalse(is_admin_restricted_file("filename.qgs", "other.qgs"))

    def test_is_admin_restricted_file_qfield_plugin_file(self):
        self.assertTrue(is_admin_restricted_file("filename.qml", "filename.qgs"))
        self.assertFalse(is_admin_restricted_file("filename.qgs", "other.qgs"))

    def test_is_admin_restricted_file_qgis_attachments_file(self):
        self.assertTrue(
            is_admin_restricted_file("filename_attachments.zip", "filename.qgs")
        )
        self.assertFalse(
            is_admin_restricted_file("filename_attachments.zip", "other.qgs")
        )

    def test_calc_etag_on_small_files(self):
        pass

    def test_calc_etag_on_large_files(self):
        pass

    def test_open_qgis_file_with_qgs(self):
        qgs_path = Path(testdata_path("delta/project.qgs"))

        with open(qgs_path, "rb") as fh:
            with open_qgis_file(qgs_path, fh) as text_fh:
                self.assertIsNotNone(text_fh)
                first_line = text_fh.readline()
                self.assertIn("<qgis", first_line)

    def test_open_qgis_file_with_qgz(self):
        qgs_path = Path(testdata_path("delta/project.qgs"))

        with qgz_from_qgs(qgs_path) as qgz_path:
            with open(qgz_path, "rb") as fh:
                with open_qgis_file(qgz_path, fh) as text_fh:
                    self.assertIsNotNone(text_fh)
                    first_line = text_fh.readline()
                    self.assertIn("<qgis", first_line)
