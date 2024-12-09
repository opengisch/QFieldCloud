import csv
import io
import os

from django.core.management import call_command
from django.test import TestCase
from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.core.utils2 import storage


class QfcTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # User
        setup_subscription_plans()
        user = Person.objects.create(username="u1")
        set_subscription(user, "default_user")

        # Project
        p = Project.objects.create(name="test_project", owner=user)
        storage.upload_project_file(p, io.BytesIO(b"Hello world!"), "project.qgs")

    def test_extracts3data_output_to_file(self):
        output_file = "extracted.csv"

        call_command(
            "extracts3data",
            "-o",
            output_file,
            "--storage-name",
            "default",
        )

        with open(output_file, newline="") as fh:
            reader = csv.reader(fh, delimiter=",")
            entries = list(reader)
            self.assertGreater(len(entries), 1)

        os.remove(output_file)

    def test_extracts3data_output_to_sdout(self):
        call_command(
            "extracts3data",
            "--storage-name",
            "default",
        )
