import csv
import io

import yaml
from django.core.management import call_command
from django.test import TestCase
from qfieldcloud.core.management.commands.extractstoragemetadata import Command
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
        cls.credentials_file = "s3_credentials.yaml"
        cls.output_file = "extracted.csv"

        with open(cls.credentials_file, "w") as fh:
            yaml.dump(cls.credentials, fh)

        # User
        setup_subscription_plans()
        user = Person.objects.create(username="u1")
        set_subscription(user, "default_user")

        # Project
        p = Project.objects.create(name="test_project", owner=user)
        file = io.BytesIO(b"Hello world!")
        get_s3_bucket().objects.filter(Prefix="projects/").delete()
        storage.upload_project_file(p, file, "project.qgs")

    def test_config(self):
        config = Command.from_file(self.credentials_file)
        self.assertDictEqual(config._asdict(), self.credentials)

    def test_output_with_user_credentials(self):
        call_command(
            "extractstoragemetadata",
            "-o",
            self.output_file,
            "-f",
            self.credentials_file,
        )

        with open(self.output_file, newline="") as fh:
            reader = csv.reader(fh, delimiter=",")
            entries = list(reader)
            self.assertGreater(len(entries), 1)
