import logging
from io import StringIO

from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Person,
    Project,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    setup_subscription_plans,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.u1 = Person.objects.create_user(username="u1", password="abc123")
        self.t1 = AuthToken.objects.get_or_create(user=self.u1)[0]
        self.p1 = Project.objects.create(
            owner=self.u1,
            name="p1",
            file_storage="default",
        )

    def test_upload_file_succeeds(self):
        self.assertEqual(self.u1.useraccount.storage_used_bytes, 0)

        # 1) first upload of the file
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        self.p1.refresh_from_db()
        self.u1.useraccount.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)
        self.assertEqual(self.p1.file_storage_bytes, 6)
        self.assertEqual(self.u1.useraccount.storage_used_bytes, 6)

        # 2) adding a second version
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        self.p1.refresh_from_db()
        self.u1.useraccount.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 2)
        self.assertEqual(self.p1.file_storage_bytes, 13)
        self.assertEqual(self.u1.useraccount.storage_used_bytes, 13)

        # 3) creating a second project with legacy storage backend
        # TODO: Delete with QF-4963 Drop support for legacy storage
        p2 = Project.objects.create(
            owner=self.u1,
            name="p2",
            file_storage="legacy_storage",
        )

        # 4) adding a file in the legacy storage backend
        response = self._upload_file(self.u1, p2, "file.name", StringIO("Hello3!"))

        self.p1.refresh_from_db()
        p2.refresh_from_db()
        self.u1.useraccount.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # p1 checks
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 2)
        self.assertEqual(self.p1.file_storage_bytes, 13)
        # TODO: Change the number of files with QF-4963 Drop support for legacy storage
        # p2 checks
        # since the project is in the legacy storage, no `File`` object is created.
        self.assertEqual(p2.project_files.count(), 0)
        self.assertEqual(p2.file_storage_bytes, 7)

        self.assertEqual(self.u1.useraccount.storage_used_bytes, 20)
