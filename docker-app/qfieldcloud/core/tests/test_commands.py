import csv
import io
import os

from django.core.management import call_command
from django.test import TestCase
from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.core.utils import get_s3_bucket
from qfieldcloud.core.utils2 import storage


class QfcTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from qfieldcloud import settings

        # Credentials
        cls.credentials = {
            "STORAGE_ACCESS_KEY_ID": settings.STORAGE_ACCESS_KEY_ID,
            "STORAGE_ENDPOINT_URL": settings.STORAGE_ENDPOINT_URL,
            "STORAGE_BUCKET_NAME": settings.STORAGE_BUCKET_NAME,
            "STORAGE_REGION_NAME": settings.STORAGE_REGION_NAME,
            "STORAGE_SECRET_ACCESS_KEY": settings.STORAGE_SECRET_ACCESS_KEY,
        }
        cls.user_input = ",".join(f"{key}={val}" for key, val in cls.credentials.items())
        cls.output_file = "extracted.csv"

        # User
        setup_subscription_plans()
        user = Person.objects.create(username="u1")
        set_subscription(user, "default_user")

        # Project
        p = Project.objects.create(name="test_project", owner=user)
        file = io.BytesIO(b"Hello world!")
        get_s3_bucket().objects.filter(Prefix="projects/").delete()
        storage.upload_project_file(p, file, "project.qgs")

    def tearDown(self):
        super().tearDown()
        os.remove(self.output_file)

    def test_output_without_user_credentials(self):
        call_command(
            "extractstoragemetadata",
            "-o",
            self.output_file,
        )

        with open(self.output_file, newline="") as fh:
            reader = csv.reader(fh, delimiter=",")
            entries = list(reader)
            print(entries)
            self.assertGreater(len(entries), 1)

    def test_output_with_user_credentials(self):
        call_command(
            "extractstoragemetadata",
            "-o",
            self.output_file,
            "-s3",
            self.user_input
        )

        with open(self.output_file, newline="") as fh:
            reader = csv.reader(fh, delimiter=",")
            entries = list(reader)
            print(entries)
            self.assertGreater(len(entries), 1)
