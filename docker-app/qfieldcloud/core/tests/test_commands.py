import csv

import yaml
from django.core.management import call_command
from django.test import TestCase
from qfieldcloud import settings
from qfieldcloud.core.management.commands.extractstoragemetadata import S3Config


class QfcTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.credentials = {
            "STORAGE_ACCESS_KEY_ID": settings.STORAGE_ACCESS_KEY_ID,
            "STORAGE_ENDPOINT_URL": settings.STORAGE_ENDPOINT_URL,
            "STORAGE_BUCKET_NAME": settings.STORAGE_BUCKET_NAME,
            "STORAGE_REGION_NAME": "eu-west-2",  # FIXME: Currently settings doesn't define this,
            "STORAGE_SECRET_ACCESS_KEY": settings.STORAGE_SECRET_ACCESS_KEY,
        }
        cls.credentials_file = "s3_credentials.yaml"
        cls.outputfile = "extracted.csv"

        with open(cls.credentials_file, "w") as fh:
            yaml.dump(cls.credentials, fh)

    def test_output(self):
        call_command("extractstoragemetadata", "-o", self.outputfile)

        with open(self.outputfile, newline="") as fh:
            reader = csv.reader(fh, delimiter=",")
            self.assertGreater(len(list(reader)), 1)

    def test_config(self):
        config = S3Config.get_or_load(self.credentials_file)
        self.assertDictEqual(config._asdict(), self.credentials)
