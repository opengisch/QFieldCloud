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

        storage_name = os.environ["TEST_SUITE_PROJECT_DEFAULT_STORAGE"]
        storage_config = settings.STORAGES[storage_name]["OPTIONS"]

        # Credentials
        cls.credentials = {
            "storage_access_key_id": storage_config["access_key"],
            "storage_endpoint_url": storage_config["endpoint_url"],
            "storage_bucket_name": storage_config["bucket_name"],
            "storage_region_name": storage_config["region_name"],
            "storage_secret_access_key": storage_config["secret_key"],
        }
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

    def test_extracts3data_output_to_file(self):
        call_command(
            "extracts3data",
            "-o",
            self.output_file,
            "--storage_access_key_id",
            self.credentials["storage_access_key_id"],
            "--storage_bucket_name",
            self.credentials["storage_bucket_name"],
            "--storage_endpoint_url",
            self.credentials["storage_endpoint_url"],
            "--storage_region_name",
            self.credentials["storage_region_name"],
            "--storage_secret_access_key",
            self.credentials["storage_secret_access_key"],
        )

        with open(self.output_file, newline="") as fh:
            reader = csv.reader(fh, delimiter=",")
            entries = list(reader)
            self.assertGreater(len(entries), 1)

        os.remove(self.output_file)

    def test_extracts3data_output_to_sdout(self):
        call_command(
            "extracts3data",
            "--storage_access_key_id",
            self.credentials["storage_access_key_id"],
            "--storage_bucket_name",
            self.credentials["storage_bucket_name"],
            "--storage_endpoint_url",
            self.credentials["storage_endpoint_url"],
            "--storage_region_name",
            self.credentials["storage_region_name"],
            "--storage_secret_access_key",
            self.credentials["storage_secret_access_key"],
        )
