import csv
import io
import os

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase

from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.core.utils2 import storage
from qfieldcloud.filestorage.models import File, FileVersion


class QfcTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # User
        setup_subscription_plans()
        user = Person.objects.create(username="u1")
        set_subscription(user, "default_user")

        # Project
        cls.p1 = Project.objects.create(name="test_project", owner=user)

        # TODO Delete with QF-4963 Drop support for legacy storage
        if cls.p1.uses_legacy_storage:
            storage.upload_project_file(
                cls.p1, io.BytesIO(b"Hello world!"), "project.qgs"
            )
        else:
            FileVersion.objects.add_version(
                project=cls.p1,
                filename="file.name",
                # NOTE the dummy name is required when running tests on GitHub CI, but not locally. Spent few hours before I isolated this...
                content=ContentFile(b"Hello world!", "dummy.name"),
                file_type=File.FileType.PROJECT_FILE,
                uploaded_by=user,
            )

    def test_extracts3data_output_to_file(self):
        output_file = "extracted.csv"

        call_command(
            "extracts3data",
            "-o",
            output_file,
            "--storage-name",
            self.p1.file_storage,
        )

        with open(output_file, newline="") as fh:
            reader = csv.reader(fh, delimiter=",")
            entries = list(reader)
            self.assertGreaterEqual(len(entries), 2)

        os.remove(output_file)

    def test_extracts3data_output_to_sdout(self):
        call_command(
            "extracts3data",
            "--storage-name",
            self.p1.file_storage,
        )
