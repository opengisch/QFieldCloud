import logging
from io import StringIO
from typing import IO
from unittest import skip
from uuid import uuid4

from auditlog.models import LogEntry
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.http import FileResponse, HttpResponse
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    User,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    get_named_file_with_size,
    setup_subscription_plans,
)
from qfieldcloud.filestorage.models import File, FileVersion

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

    def assertFileUploaded(
        self, user: User, project: Project, filename: str, content: IO
    ) -> HttpResponse | Response:
        if project.uses_legacy_storage:
            return self._assertFileUploadedLegacy(user, project, filename, content)
        else:
            return self._assertFileUploaded(user, project, filename, content)

    def _assertFileUploadedLegacy(
        self, user: User, project: Project, filename: str, content: IO
    ) -> HttpResponse | Response:
        files_count = len(
            list(filter(lambda f: f.latest.name != filename, project.legacy_files))
        )
        max_versions = user.useraccount.current_subscription.plan.storage_keep_versions

        try:
            file = project.legacy_get_file(filename)

            versions_count = len(file.versions)
            latest_version = file.latest
        except Exception:
            versions_count = 0
            latest_version = None

        response = self._upload_file(user, project, filename, content)

        # clear the cache, as `Project.legacy_files` is `@cached_property`
        del project.legacy_files

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(project.project_files_count, files_count + 1)

        file = project.legacy_get_file(filename)

        self.assertEqual(file.latest.name, filename)
        self.assertEqual(len(file.versions), min((versions_count + 1), max_versions))
        self.assertEqual(file.latest, file.versions[-1])
        self.assertNotEqual(file.latest, latest_version)

        return response

    def _assertFileUploaded(
        self, user: User, project: Project, filename: str, content: IO
    ) -> HttpResponse | Response:
        files_count = project.project_files.exclude(name=filename).count()
        max_versions = user.useraccount.current_subscription.plan.storage_keep_versions

        try:
            file = project.get_file(filename)

            versions_count = file.versions.count()
            latest_version = file.latest_version
        except Exception:
            versions_count = 0
            latest_version = None

        response = self._upload_file(user, project, filename, content)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(project.project_files.count(), files_count + 1)

        file = project.get_file(filename)

        self.assertEqual(file.name, filename)
        self.assertEqual(file.versions.count(), min((versions_count + 1), max_versions))
        self.assertEqual(file.latest_version, file.versions.all()[0])
        self.assertNotEqual(file.latest_version, latest_version)

        return response

    def assertFileDeleted(
        self,
        user: User,
        project: Project,
        filename: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse | Response:
        if params and params.get("version"):
            file_version = FileVersion.objects.get(id=params["version"])
        elif headers and headers.get("x-file-version"):
            file_version = FileVersion.objects.get(id=headers["x-file-version"])
        else:
            file_version = File.objects.get(name=filename).latest_version

            # make typing happy that `file_version` is not `None`
            assert file_version

        storage_filename = file_version.content.name

        self.assertTrue(storages[project.file_storage].exists(storage_filename))

        response = self._delete_file(user, project, filename, params, headers)

        project.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(storages[project.file_storage].exists(storage_filename))

        return response

    def test_upload_file_succeeds(self):
        # 1) first upload of the file
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        # 2) adding a second version
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 2)

    def test_upload_files_with_different_name(self):
        # 1) first upload of the file
        response = self._upload_file(self.u1, self.p1, "file1.name", StringIO("Hello!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file1.name").versions.count(), 1)

        # 2) adding a second version
        response = self._upload_file(
            self.u1, self.p1, "file2.name", StringIO("Hello2!")
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 2)
        self.assertEqual(self.p1.get_file("file2.name").versions.count(), 1)

    def test_upload_files_without_payload_fails(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        response = self.client.post(
            reverse(
                "filestorage_crud_file",
                kwargs={
                    "project_id": self.p1.id,
                    "filename": "file.name",
                },
            ),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.p1.project_files.count(), 0)

    def test_upload_files_with_wrong_file_param_name_fails(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        response = self.client.post(
            reverse(
                "filestorage_crud_file",
                kwargs={
                    "project_id": self.p1.id,
                    "filename": "file.name",
                },
            ),
            {
                "file_content": StringIO("Hello!"),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.p1.project_files.count(), 0)

    def test_upload_file_with_empty_filename_fails(self):
        with self.assertRaises(NoReverseMatch):
            self._upload_file(self.u1, self.p1, "", StringIO("Hello!"))

        self.assertEqual(self.p1.project_files.count(), 0)

    def test_upload_file_with_whitespace_wrapper_filename_fails(self):
        response = self._upload_file(
            self.u1, self.p1, " whitespace around ", StringIO("Hello!")
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        payload = response.json()

        # TODO blocked by QF-4950: check for the message too
        self.assertEqual(payload["code"], "validation_error")
        self.assertEqual(self.p1.project_files.count(), 0)

    def test_upload_file_with_filename_longer_than_max_chars_fails(self):
        """Minio has limit of 255 and Windows o 140 characters"""
        max_chars_len = settings.STORAGE_FILENAME_MAX_CHAR_LENGTH

        filename = "x" * max_chars_len
        response = self._upload_file(self.u1, self.p1, filename, StringIO("Hello!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)

        filename = "x" * (max_chars_len + 1)
        response = self._upload_file(self.u1, self.p1, filename, StringIO("Hello!"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        payload = response.json()

        # TODO blocked by QF-4950: check for the message too
        self.assertEqual(payload["code"], "validation_error")
        self.assertEqual(self.p1.project_files.count(), 1)

    def test_upload_file_name_with_invalid_char_fails(self):
        response = self._upload_file(
            self.u1, self.p1, "NUL/file.name", StringIO("Hello!")
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        payload = response.json()

        # TODO blocked by QF-4950: check for the message too
        self.assertEqual(payload["code"], "validation_error")
        self.assertEqual(self.p1.project_files.count(), 0)

    @skip("It hits the quota error")
    def test_upload_file_bigger_than_max_size_fails(self):
        with get_named_file_with_size(1000) as f:
            response = self._upload_file(self.u1, self.p1, "10gb.file", f)

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_file_sha256sum(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(
            self.p1.get_file("file.name").latest_version.sha256sum.hex(),
            "334d016f755cd6dc58c53a86e183882f8ec14f52fb05345887c8a5edd42c87b7",
        )

    def test_upload_file_etag_single_part(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(
            self.p1.get_file("file.name").latest_version.etag,
            "952d2c56d0485958336747bcdd98590d",
        )

    def test_upload_file_etag_multi_part(self):
        self.assertFileUploaded(
            self.u1, self.p1, "10mb.file", StringIO("x" * (10 * 1000 * 1000))
        )
        self.assertEqual(
            self.p1.get_file("10mb.file").latest_version.etag,
            "1e762c1c6ca960a51ce95942752cf1f6-2",
        )

    def test_upload_file_size(self):
        # the size is going to be 11*2 utf bytes for cyrillic + 3*1 ascii bytes = 25 bytes in total
        self.assertFileUploaded(
            self.u1, self.p1, "file.name", StringIO("Здравей, свят!")
        )
        self.assertEqual(self.p1.get_file("file.name").latest_version.size, 25)

    def test_upload_file_by_unauthorized_user_fails(self):
        response = self.client.post(
            reverse(
                "filestorage_crud_file",
                kwargs={
                    "project_id": self.p1.id,
                    "filename": "file.name",
                },
            ),
            {
                "file": StringIO("Hello!"),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.p1.project_files.count(), 0)

    def test_upload_project_files_sets_the_qgis_file_name(self):
        self.assertIsNone(self.p1.the_qgis_file_name)

        self.assertFileUploaded(self.u1, self.p1, "project1.qgs", StringIO("Hello!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

    def test_upload_multiple_project_files_fails(self):
        self.assertIsNone(self.p1.the_qgis_file_name)

        self.assertFileUploaded(self.u1, self.p1, "project1.qgs", StringIO("Hello!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

        response = self._upload_file(
            self.u1, self.p1, "project2.qgs", StringIO("Hello!")
        )
        self.p1.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

    def test_upload_admin_restricted_files_by_owner_succeeds(self):
        # make sure the project has the flag `has_restricted_projectfiles=True`
        self.p1.has_restricted_projectfiles = True
        self.p1.save(update_fields=["has_restricted_projectfiles"])

        self.assertIsNone(self.p1.the_qgis_file_name)
        self.assertFileUploaded(self.u1, self.p1, "project1.qgs", StringIO("Hello1!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")
        self.assertFileUploaded(self.u1, self.p1, "project1.qgs", StringIO("Hello2!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

    def test_upload_admin_restricted_files_by_admin_or_manager_succeeds(self):
        # make sure the project has the flag `has_restricted_projectfiles=True`
        self.p1.has_restricted_projectfiles = True
        self.p1.save(update_fields=["has_restricted_projectfiles"])

        # create a new user that is has collaborator role ADMIN
        u2 = Person.objects.create_user(username="u2", password="abc123")
        ProjectCollaborator.objects.create(
            project=self.p1, collaborator=u2, role=ProjectCollaborator.Roles.ADMIN
        )

        self.assertFileUploaded(u2, self.p1, "project1.qgs", StringIO("Hello1!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

        # create a new user that is has collaborator role MANAGER
        u3 = Person.objects.create_user(username="u3", password="abc123")
        ProjectCollaborator.objects.create(
            project=self.p1, collaborator=u3, role=ProjectCollaborator.Roles.MANAGER
        )

        self.assertFileUploaded(u3, self.p1, "project1.qgs", StringIO("Hello2!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

    def test_upload_admin_restricted_files_set_to_false_by_editor_succeeds(self):
        # create a new user that is has collaborator role EDITOR
        u2 = Person.objects.create_user(username="u2", password="abc123")
        ProjectCollaborator.objects.create(
            project=self.p1, collaborator=u2, role=ProjectCollaborator.Roles.EDITOR
        )

        self.assertFileUploaded(u2, self.p1, "project1.qgs", StringIO("Hello1!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

    def test_upload_admin_restricted_files_by_non_admin_or_manager_fails(self):
        # make sure the project has the flag `has_restricted_projectfiles=True`
        self.p1.has_restricted_projectfiles = True
        self.p1.save(update_fields=["has_restricted_projectfiles"])

        # create a new user that is has collaborator role EDITOR
        u2 = Person.objects.create_user(username="u2", password="abc123")
        ProjectCollaborator.objects.create(
            project=self.p1, collaborator=u2, role=ProjectCollaborator.Roles.EDITOR
        )

        response = self._upload_file(u2, self.p1, "project1.qgs", StringIO("Hello1!"))

        self.p1.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.p1.project_files.count(), 0)
        self.assertIsNone(self.p1.the_qgis_file_name)

    def test_upload_file_by_non_collaborator_fails(self):
        # create a new independent user that is not a collaborator
        u2 = Person.objects.create_user(username="u2", password="abc123")

        response = self._upload_file(u2, self.p1, "file.name", StringIO("Hello1!"))

        self.p1.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.p1.project_files.count(), 0)
        self.assertIsNone(self.p1.the_qgis_file_name)

    def test_upload_file_by_organization_admin_succeeds(self):
        # create a new organization and a user that has role ADMIN in the organization
        u2 = Person.objects.create_user(username="u2", password="abc123")
        o1 = Organization.objects.create(username="o1", organization_owner=self.u1)
        OrganizationMember.objects.create(
            member=u2, organization=o1, role=OrganizationMember.Roles.ADMIN
        )

        self.p1.owner = o1
        self.p1.save(update_fields=["owner"])

        self.assertFileUploaded(u2, self.p1, "file.name", StringIO("Hello1!"))

    def test_upload_file_by_organization_member_fails(self):
        # create a new organization and a user that has role MEMBER in the organization
        u2 = Person.objects.create_user(username="u2", password="abc123")
        o1 = Organization.objects.create(username="o1", organization_owner=self.u1)
        OrganizationMember.objects.create(
            member=u2, organization=o1, role=OrganizationMember.Roles.MEMBER
        )

        self.p1.owner = o1
        self.p1.save(update_fields=["owner"])

        response = self._upload_file(u2, self.p1, "file.name", StringIO("Hello1!"))

        self.p1.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.p1.project_files.count(), 0)
        self.assertIsNone(self.p1.the_qgis_file_name)

    def test_upload_by_non_organization_member_fails(self):
        # create a new organization and a user that is not a member
        u2 = Person.objects.create_user(username="u2", password="abc123")
        o1 = Organization.objects.create(username="o1", organization_owner=self.u1)

        self.p1.owner = o1
        self.p1.save(update_fields=["owner"])

        response = self._upload_file(u2, self.p1, "file.name", StringIO("Hello1!"))

        self.p1.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.p1.project_files.count(), 0)
        self.assertIsNone(self.p1.the_qgis_file_name)

    def test_upload_file_updates_file_storage_bytes_attribute(self):
        self.assertEqual(self.p1.file_storage_bytes, 0)
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.file_storage_bytes, 7)
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.file_storage_bytes, 14)

    def test_delete_file_updates_file_storage_bytes_attribute(self):
        self.assertEqual(self.p1.file_storage_bytes, 0)
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.file_storage_bytes, 7)
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.file_storage_bytes, 14)

        self.assertFileDeleted(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": self.p1.get_file("file.name").latest_version.id,
            },
        )
        self.assertEqual(self.p1.file_storage_bytes, 7)
        self.assertFileDeleted(self.u1, self.p1, "file.name")
        self.assertEqual(self.p1.file_storage_bytes, 0)

    # def test_upload_non_attachment_file_starts_a_new_job(self):
    # def test_upload_attachment_file_does_not_start_a_new_job(self):

    def test_download_existing_file_succeeds(self):
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        response = self._download_file(self.u1, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(b"".join(response.streaming_content), b"Hello!")

    def test_download_latest_file_version_by_default_succeeds(self):
        # 1) first upload of the file
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello1!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        # 2) adding a second version
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 2)

        # 3) Check the first file version 2
        response = self._download_file(self.u1, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(b"".join(response.streaming_content), b"Hello2!")

    def test_download_non_existing_file_fails(self):
        response = self._download_file(self.u1, self.p1, "not_existing.file")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_existing_file_version_succeeds(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        versions_qs = self.p1.get_file("file.name").versions.all()

        response = self._download_file(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(versions_qs[0].id),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(b"".join(response.streaming_content), b"Hello2!")

        # 4) Check the first file version 2
        response = self._download_file(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(versions_qs[1].id),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(b"".join(response.streaming_content), b"Hello1!")

    def test_download_non_existing_file_version_fails(self):
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello1!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        response = self._download_file(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(uuid4()),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_existing_file_succeeds(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.assertFileDeleted(self.u1, self.p1, "file.name")
        self.assertEqual(self.p1.project_files.count(), 0)

    def test_delete_non_existing_file_fails(self):
        response = self._delete_file(self.u1, self.p1, "not_existing.file")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_existing_file_version_succeeds(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        old_versions_qs = self.p1.get_file("file.name").versions.all()
        old_newer_version = old_versions_qs[0]
        old_older_version = old_versions_qs[1]

        self.assertFileDeleted(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(old_older_version.id),
            },
        )
        self.assertEqual(self.p1.project_files.count(), 1)

        new_versions_qs = self.p1.get_file("file.name").versions.all()
        new_newer_version = new_versions_qs[0]

        self.assertEqual(new_versions_qs.count(), 1)
        self.assertEqual(new_newer_version.id, old_newer_version.id)
        self.assertEqual(new_newer_version.content.read(), b"Hello2!")

    def test_delete_existing_file_version_using_header_succeeds(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        old_versions_qs = self.p1.get_file("file.name").versions.all()
        old_newer_version = old_versions_qs[0]
        old_older_version = old_versions_qs[1]

        self.assertFileDeleted(
            self.u1,
            self.p1,
            "file.name",
            headers={
                "x-file-version": str(old_older_version.id),
            },
        )
        self.assertEqual(self.p1.project_files.count(), 1)

        new_versions_qs = self.p1.get_file("file.name").versions.all()
        new_newer_version = new_versions_qs[0]

        self.assertEqual(new_versions_qs.count(), 1)
        self.assertEqual(new_newer_version.id, old_newer_version.id)
        self.assertEqual(new_newer_version.content.read(), b"Hello2!")

    def test_delete_non_existing_file_version_fails(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        response = self._delete_file(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(uuid4()),
            },
        )

        versions_qs = self.p1.get_file("file.name").versions.all()

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(versions_qs.count(), 2)
        self.assertEqual(versions_qs[0].content.read(), b"Hello2!")
        self.assertEqual(versions_qs[1].content.read(), b"Hello1!")

    def test_delete_qgs_project_file_sets_the_qgis_file_name_to_none(self):
        self.assertIsNone(self.p1.the_qgis_file_name)
        self.assertFileUploaded(self.u1, self.p1, "project1.qgs", StringIO("Hello1!"))

        self.p1.refresh_from_db()

        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

        self.assertFileDeleted(self.u1, self.p1, "project1.qgs")
        self.assertEqual(self.p1.project_files.count(), 0)
        self.assertIsNone(self.p1.the_qgis_file_name)

    def test_delete_all_file_versions_fails(self):
        # new empty project, no `the_qgis_file_name`
        self.assertIsNone(self.p1.the_qgis_file_name)

        # upload the a new `.qgs` file
        self.assertFileUploaded(self.u1, self.p1, "project1.qgs", StringIO("Hello1!"))

        self.p1.refresh_from_db()

        # project file set to the recently uploaded file
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

        # upload the another version of the `.qgs` file
        self.assertFileUploaded(self.u1, self.p1, "project1.qgs", StringIO("Hello2!"))

        self.p1.refresh_from_db()

        # project file still set to the recently uploaded file
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

        versions_qs = self.p1.get_file("project1.qgs").versions.all()

        self.assertFileDeleted(
            self.u1,
            self.p1,
            "project1.qgs",
            params={
                "version": str(versions_qs[0].id),
            },
        )
        self.assertEqual(self.p1.project_files.count(), 1)
        # project file still set to the recently uploaded file as there is one more version
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

        response = self._delete_file(
            self.u1,
            self.p1,
            "project1.qgs",
            params={"version": str(versions_qs[0].id)},
        )

        self.p1.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.p1.project_files.count(), 1)
        # project file still set to the recently uploaded file as there is one more version
        self.assertEqual(self.p1.the_qgis_file_name, "project1.qgs")

    def test_delete_file_by_unauthorized_user_fails(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(self.p1.project_files.count(), 1)

        response = self.client.delete(
            reverse(
                "filestorage_crud_file",
                kwargs={
                    "project_id": self.p1.id,
                    "filename": "file.name",
                },
            ),
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.p1.project_files.count(), 1)

    def test_delete_file_by_non_collaborator_fails(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(self.p1.project_files.count(), 1)

        # create a new user that is has collaborator role ADMIN
        u2 = Person.objects.create_user(username="u2", password="abc123")

        response = self._delete_file(u2, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.p1.project_files.count(), 1)

    def test_delete_file_by_collaborator_with_role_reader_or_reporter_fails(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(self.p1.project_files.count(), 1)

        # create a new user that is has collaborator role ADMIN
        u2 = Person.objects.create_user(username="u2", password="abc123")
        ProjectCollaborator.objects.create(
            project=self.p1, collaborator=u2, role=ProjectCollaborator.Roles.READER
        )

        response = self._delete_file(u2, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.p1.project_files.count(), 1)

        # create a new user that is has collaborator role ADMIN
        u3 = Person.objects.create_user(username="u3", password="abc123")
        ProjectCollaborator.objects.create(
            project=self.p1, collaborator=u3, role=ProjectCollaborator.Roles.REPORTER
        )

        response = self._delete_file(u3, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.p1.project_files.count(), 1)

    def test_delete_file_by_collaborator_with_role_editor_succeeds(self):
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(self.p1.project_files.count(), 1)

        # create a new user that is has collaborator role ADMIN
        u2 = Person.objects.create_user(username="u2", password="abc123")
        ProjectCollaborator.objects.create(
            project=self.p1, collaborator=u2, role=ProjectCollaborator.Roles.EDITOR
        )

        self.assertFileDeleted(u2, self.p1, "file.name")
        self.assertEqual(self.p1.project_files.count(), 0)

    def test_latest_version_attribute_is_updated(self):
        # upload the 1st version
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        version1 = self.p1.get_file("file.name").versions.all()[0]

        self.assertEqual(self.p1.get_file("file.name").latest_version_id, version1.pk)

        # upload the 2nd version
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 2)

        version2 = self.p1.get_file("file.name").versions.all()[0]

        self.assertEqual(self.p1.get_file("file.name").latest_version_id, version2.pk)

        # upload the 3rd version
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello3!"))
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 3)

        version3 = self.p1.get_file("file.name").versions.all()[0]

        self.assertNotEqual(version1.pk, version3.pk)
        self.assertEqual(self.p1.get_file("file.name").latest_version_id, version3.pk)

        # delete the 2nd version
        self.assertFileDeleted(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(version2.id),
            },
        )
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 2)
        self.assertEqual(self.p1.get_file("file.name").latest_version_id, version3.pk)

        # delete the 3rd (latest) version
        self.assertFileDeleted(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(version3.id),
            },
        )
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").latest_version_id, version1.pk)

    def test_user_deletion_sets_uploaded_by_to_null(self):
        u2 = Person.objects.create_user(username="u2", password="abc123")
        ProjectCollaborator.objects.create(
            collaborator=u2, project=self.p1, role=ProjectCollaborator.Roles.EDITOR
        )

        self.assertFileUploaded(u2, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(self.p1.get_file("file.name").uploaded_by, u2)
        self.assertEqual(
            self.p1.get_file("file.name").versions.all()[0].uploaded_by, u2
        )

        u2.delete()

        self.assertIsNone(self.p1.get_file("file.name").uploaded_by)
        self.assertIsNone(self.p1.get_file("file.name").versions.all()[0].uploaded_by)

    def test_upload_file_version_adds_audit(self):
        file_content_type = ContentType.objects.get_for_model(File)
        version_content_type = ContentType.objects.get_for_model(FileVersion)

        file_create_audit_qs = LogEntry.objects.filter(
            action=LogEntry.Action.CREATE,
            content_type_id=file_content_type.id,
        )
        file_update_audit_qs = LogEntry.objects.filter(
            action=LogEntry.Action.UPDATE,
            content_type_id=file_content_type.id,
        )
        version_create_log_qs = LogEntry.objects.filter(
            action=LogEntry.Action.CREATE,
            content_type_id=version_content_type.id,
        )

        self.assertEqual(file_create_audit_qs.count(), 0)
        self.assertEqual(file_update_audit_qs.count(), 0)
        self.assertEqual(version_create_log_qs.count(), 0)
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello!"))
        self.assertEqual(file_create_audit_qs.count(), 1)
        self.assertEqual(file_update_audit_qs.count(), 0)
        self.assertEqual(version_create_log_qs.count(), 1)
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))
        self.assertEqual(file_create_audit_qs.count(), 1)
        self.assertEqual(file_update_audit_qs.count(), 1)
        self.assertEqual(version_create_log_qs.count(), 2)

    def test_delete_file_version_adds_delete_audit(self):
        file_content_type = ContentType.objects.get_for_model(File)
        version_content_type = ContentType.objects.get_for_model(FileVersion)

        file_delete_audit_qs = LogEntry.objects.filter(
            action=LogEntry.Action.DELETE,
            content_type_id=file_content_type.id,
        )
        file_update_audit_qs = LogEntry.objects.filter(
            action=LogEntry.Action.UPDATE,
            content_type_id=file_content_type.id,
        )
        version_delete_log_qs = LogEntry.objects.filter(
            action=LogEntry.Action.DELETE,
            content_type_id=version_content_type.id,
        )

        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello1!"))
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello2!"))
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello3!"))
        self.assertFileUploaded(self.u1, self.p1, "file.name", StringIO("Hello4!"))
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.project_files[0].versions.count(), 4)
        self.assertEqual(file_delete_audit_qs.count(), 0)
        self.assertEqual(file_update_audit_qs.count(), 3)
        self.assertEqual(version_delete_log_qs.count(), 0)

        (v4, v3, v2, v1) = self.p1.project_files[0].versions.all()

        # deleting the oldest version should create only one new `FileVersion` DELETE audit
        self.assertFileDeleted(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(v1.id),
            },
        )
        self.assertEqual(file_delete_audit_qs.count(), 0)
        self.assertEqual(file_update_audit_qs.count(), 3)
        self.assertEqual(version_delete_log_qs.count(), 1)

        # deleting the latest version should create two new audits: `FileVersion` DELETE audit and `File` UPDATE audit
        self.assertFileDeleted(
            self.u1,
            self.p1,
            "file.name",
            params={
                "version": str(v4.id),
            },
        )
        self.assertEqual(file_delete_audit_qs.count(), 0)
        self.assertEqual(file_update_audit_qs.count(), 4)
        self.assertEqual(version_delete_log_qs.count(), 2)

        # deleting the file should create three new audits: two `FileVersion` DELETE audits and `File` DELETE audit
        self.assertFileDeleted(self.u1, self.p1, "file.name")
        self.assertEqual(file_delete_audit_qs.count(), 1)
        self.assertEqual(file_update_audit_qs.count(), 4)
        self.assertEqual(version_delete_log_qs.count(), 4)

    def test_unneeded_file_versions_are_deleted(self):
        s1 = self.u1.useraccount.current_subscription

        self.assertEqual(self.p1.project_files.count(), 0)

        oldest_version_id = None

        for i in range(s1.plan.storage_keep_versions + 1):
            self.assertFileUploaded(
                self.u1, self.p1, "file.name", StringIO(f"Hello{i}!")
            )

            if not oldest_version_id:
                oldest_version_id = self.p1.project_files[0].latest_version_id

        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(
            self.p1.project_files[0].versions.count(), s1.plan.storage_keep_versions
        )
        self.assertFalse(
            self.p1.project_files[0].versions.filter(id=oldest_version_id).exists()
        )

    def test_list_project_files(self):
        # 1) first upload of the file with two versions
        p2 = Project.objects.create(name="p2", owner=self.u1)

        self.assertFileUploaded(self.u1, p2, "file1.name", StringIO("Hello 1!"))
        self.assertFileUploaded(self.u1, p2, "file1.name", StringIO("Hello 2!"))

        # 2) adding a file to another project
        p3 = Project.objects.create(name="p3", owner=self.u1)
        self.assertFileUploaded(self.u1, p3, "file1.name", StringIO("Hello!"))

        response = self._list_files(self.u1, p2)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payload = response.json()

        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 1)
        self.assertIsInstance(payload[0], dict)
        self.assertEqual(payload[0].get("name"), "file1.name")
        self.assertEqual(len(payload[0].get("versions", [])), 2)

    def test_list_project_files_values(self):
        self.assertFileUploaded(
            self.u1, self.p1, "10mb.file", StringIO("x" * (10 * 1000 * 1000))
        )

        response = self._list_files(self.u1, self.p1)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payload = response.json()

        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 1)
        self.assertIsInstance(payload[0], dict)

        self.assertEqual(payload[0].get("name"), "10mb.file")
        self.assertEqual(payload[0].get("md5sum"), "1e762c1c6ca960a51ce95942752cf1f6-2")
        self.assertEqual(
            payload[0].get("sha256"),
            "0c9a42b3d065a64063eca67e98c932fa2e9a077bc7973a421a964a11304c998c",
        )
        self.assertEqual(len(payload[0].get("versions", [])), 1)

    def test_delete_project_deletes_thumbnail_and_all_project_files(self):
        p2 = Project.objects.create(
            owner=self.u1,
            name="p2",
            file_storage="default",
        )

        p2.thumbnail = ContentFile("<svg />", "thumbnail.svg")
        p2.save()

        self.assertFileUploaded(self.u1, p2, "file.name", StringIO("Hello world!"))

        latest_version: FileVersion = p2.project_files.first().latest_version  # type: ignore

        self.assertTrue(storages[p2.file_storage].exists(p2.thumbnail.name))
        self.assertTrue(storages[p2.file_storage].exists(latest_version.content.name))

        p2.delete()

        self.assertFalse(storages[p2.file_storage].exists(p2.thumbnail.name))
        self.assertFalse(storages[p2.file_storage].exists(latest_version.content.name))

    def test_thumbnail_storage_key_is_variable(self):
        self.p1.thumbnail = ContentFile("<svg />", "thumbnail.svg")
        self.p1.save()
        thumbnail_key1 = self.p1.thumbnail.file.name

        self.p1.thumbnail = ContentFile("<svg />", "thumbnail2.svg")
        self.p1.save()
        thumbnail_key2 = self.p1.thumbnail.file.name

        self.assertNotEqual(thumbnail_key1, "thumbnail.svg")
        self.assertNotEqual(thumbnail_key1, "thumbnail.png")
        self.assertNotEqual(thumbnail_key2, "thumbnail2.svg")
        self.assertNotEqual(thumbnail_key1, thumbnail_key2)
