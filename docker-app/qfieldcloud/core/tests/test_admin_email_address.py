import csv
import io
import logging

from allauth.account.models import EmailAddress
from django.test import TestCase
from django.urls import reverse

from qfieldcloud.core.models import Organization, Person
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        # the primary allauth email address takes precedence over the user's own email
        self.user1 = Person.objects.create_user(
            username="user1", password="abc123", email="user1-old@example.com"
        )
        EmailAddress.objects.create(
            user=self.user1, email="user1@example.com", primary=True, verified=True
        )
        self.user2 = Person.objects.create_user(
            username="user2", password="abc123", email="user2@example.com"
        )
        # users without any email are left out of the export
        Person.objects.create_user(username="user3", password="abc123", email="")
        Organization.objects.create(
            username="org1", organization_owner=self.user1, email="org1@example.com"
        )

        self.url = reverse("admin:account_emailaddress_export_emails_to_csv")

    def test_email_address_admin_changelist_links_to_csv_export(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(reverse("admin:account_emailaddress_changelist"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'href="{self.url}"')

    def test_email_address_admin_export_emails_to_csv_streams_contact_details(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(self.url)
        content = b"".join(resp.streaming_content).decode()
        rows = []

        for row in csv.DictReader(io.StringIO(content)):
            rows.append(
                (
                    row["username"],
                    row["type"],
                    row["email"],
                    row["verified"],
                    row["owner_username"],
                    row["owner_email"],
                )
            )

        with self.subTest("Test the export is a CSV attachment"):
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["Content-Type"], "text/csv")
            # the filename ends with a timestamp of when the export ran
            self.assertTrue(
                resp["Content-Disposition"].startswith(
                    "attachment; filename=qfc_user_email_"
                )
            )
            self.assertTrue(resp["Content-Disposition"].endswith(".csv"))

        with self.subTest("Test the export has a header row with every column"):
            self.assertEqual(
                content.splitlines()[0],
                "id,username,first_name,last_name,type,email,date_joined,last_login,"
                "has_newsletter_subscription,has_accepted_tos,verified,owner_id,"
                "owner_username,owner_email,owner_first_name,owner_last_name,"
                "owner_date_joined,owner_last_login,owner_has_newsletter_subscription,"
                "owner_has_accepted_tos",
            )

        with self.subTest(
            "Test the export lists every user with an email and their owner details"
        ):
            self.assertEqual(
                rows,
                [
                    ("superuser", "1", "super@example.com", "", "", ""),
                    ("user1", "1", "user1@example.com", "True", "", ""),
                    ("user2", "1", "user2@example.com", "", "", ""),
                    ("org1", "2", "org1@example.com", "", "user1", "user1@example.com"),
                ],
            )
