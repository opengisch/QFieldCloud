import logging
from io import StringIO
from unittest import mock

import requests
from django.http import FileResponse
from django.test import SimpleTestCase
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
from qfieldcloud.filestorage.backend import QfcWebDavStorage

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
            file_storage="webdav",
        )

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

    def test_upload_then_download_file_succeeds(self):
        # 1) first upload of the file
        self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        # 2) download file
        response = self._download_file(self.u1, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(b"".join(response.streaming_content), b"Hello!")

    def test_upload_then_delete_file_succeeds(self):
        # 1) first upload of the file
        self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        # 2) delete file
        response = self._delete_file(self.u1, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_old_version_is_downloadable_after_new_upload(self):
        # Uploads two versions and verifies the latest is served by default
        # while the older one is still retrievable via ?version=<uuid>.
        self._upload_file(self.u1, self.p1, "file.name", StringIO("v1"))
        first_version_id = str(self.p1.get_file("file.name").latest_version.id)

        self._upload_file(self.u1, self.p1, "file.name", StringIO("v2"))

        # Default download → latest version
        response = self._download_file(self.u1, self.p1, "file.name")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), b"v2")

        # Explicit version download → first version still retrievable
        response = self._download_file(
            self.u1,
            self.p1,
            "file.name",
            params={"version": first_version_id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), b"v1")

    def test_delete_specific_version_keeps_other_versions(self):
        # Uploads three versions, deletes the middle one by id,
        # verifies the remaining two are intact and the latest is unchanged.
        self._upload_file(self.u1, self.p1, "file.name", StringIO("v1"))
        self._upload_file(self.u1, self.p1, "file.name", StringIO("v2"))
        middle_version_id = str(self.p1.get_file("file.name").latest_version.id)
        self._upload_file(self.u1, self.p1, "file.name", StringIO("v3"))

        file = self.p1.get_file("file.name")
        self.assertEqual(file.versions.count(), 3)
        latest_before_delete = file.latest_version.id

        response = self._delete_file(
            self.u1,
            self.p1,
            "file.name",
            params={"version": middle_version_id},
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        file = self.p1.get_file("file.name")
        self.assertEqual(file.versions.count(), 2)
        self.assertEqual(file.latest_version.id, latest_before_delete)

        # Latest download still returns v3
        response = self._download_file(self.u1, self.p1, "file.name")
        self.assertEqual(b"".join(response.streaming_content), b"v3")

    def test_delete_then_reupload_same_path_succeeds(self):
        # Regression guard for the "create → delete → create" lifecycle.
        # Verifies WebDAV does not leave the path in a state that blocks
        # re-creation (e.g. a Nextcloud trash entry holding the name).
        self._upload_file(self.u1, self.p1, "file.name", StringIO("v1"))

        response = self._delete_file(self.u1, self.p1, "file.name")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.p1.project_files.count(), 0)

        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("v2"))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        response = self._download_file(self.u1, self.p1, "file.name")
        self.assertEqual(b"".join(response.streaming_content), b"v2")


def _make_storage() -> QfcWebDavStorage:
    return QfcWebDavStorage(
        webdav_url="http://webdav.example/",
        public_url="http://webdav.example/",
        basic_auth="user:pwd",
    )


class WebDavSessionConfigTests(SimpleTestCase):
    def test_session_has_retry_adapter_with_webdav_methods(self):
        storage = _make_storage()
        adapter = storage.requests.get_adapter("https://webdav.example/")
        retry = adapter.max_retries

        self.assertEqual(retry.total, storage.RETRY_TOTAL)
        for method in ("PUT", "DELETE", "MKCOL", "PROPFIND"):
            self.assertIn(method, retry.allowed_methods)

        for status_code in (429, 502, 503, 504):
            self.assertIn(status_code, retry.status_forcelist)

    def test_perform_webdav_request_sets_default_timeout(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.return_value = mock.Mock(status_code=200, headers={})
            head.return_value.raise_for_status = mock.Mock()
            storage.perform_webdav_request("HEAD", "/foo")
            self.assertEqual(head.call_args.kwargs["timeout"], storage.DEFAULT_TIMEOUT)

    def test_perform_webdav_request_uses_longer_timeout_for_put(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "put") as put:
            put.return_value = mock.Mock(status_code=201, headers={})
            put.return_value.raise_for_status = mock.Mock()
            storage.perform_webdav_request("PUT", "/foo", data=b"x")
            self.assertEqual(put.call_args.kwargs["timeout"], storage.UPLOAD_TIMEOUT)

    def test_perform_webdav_request_respects_caller_timeout_override(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "put") as put:
            put.return_value = mock.Mock(status_code=201, headers={})
            put.return_value.raise_for_status = mock.Mock()
            storage.perform_webdav_request("PUT", "/foo", data=b"x", timeout=42)
            self.assertEqual(put.call_args.kwargs["timeout"], 42)


class WebDavExistsTests(SimpleTestCase):
    def test_exists_returns_true_on_200(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.return_value = mock.Mock(status_code=200)
            self.assertTrue(storage.exists("/foo"))

    def test_exists_returns_false_on_404(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.return_value = mock.Mock(status_code=404)
            self.assertFalse(storage.exists("/foo"))

    def test_exists_returns_false_on_410(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.return_value = mock.Mock(status_code=410)
            self.assertFalse(storage.exists("/foo"))

    def test_exists_raises_ioerror_on_500(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.return_value = mock.Mock(status_code=500)
            with self.assertRaises(IOError):
                storage.exists("/foo")

    def test_exists_raises_ioerror_on_401(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.return_value = mock.Mock(status_code=401)
            with self.assertRaises(IOError):
                storage.exists("/foo")

    def test_exists_raises_ioerror_on_network_error(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.side_effect = requests.exceptions.ConnectionError("boom")
            with self.assertRaises(IOError):
                storage.exists("/foo")

    def test_exists_uses_default_timeout(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "head") as head:
            head.return_value = mock.Mock(status_code=200)
            storage.exists("/foo")
            self.assertEqual(head.call_args.kwargs["timeout"], storage.DEFAULT_TIMEOUT)


class WebDavDeleteTests(SimpleTestCase):
    def test_delete_swallows_404(self):
        storage = _make_storage()
        err = requests.HTTPError(response=mock.Mock(status_code=404))
        with mock.patch.object(storage, "perform_webdav_request", side_effect=err):
            storage.delete("/foo")

    def test_delete_swallows_410(self):
        storage = _make_storage()
        err = requests.HTTPError(response=mock.Mock(status_code=410))
        with mock.patch.object(storage, "perform_webdav_request", side_effect=err):
            storage.delete("/foo")

    def test_delete_propagates_500(self):
        storage = _make_storage()
        err = requests.HTTPError(response=mock.Mock(status_code=500))
        with mock.patch.object(storage, "perform_webdav_request", side_effect=err):
            with self.assertRaises(requests.HTTPError):
                storage.delete("/foo")

    def test_delete_propagates_403(self):
        storage = _make_storage()
        err = requests.HTTPError(response=mock.Mock(status_code=403))
        with mock.patch.object(storage, "perform_webdav_request", side_effect=err):
            with self.assertRaises(requests.HTTPError):
                storage.delete("/foo")


class WebDavMakeCollectionTests(SimpleTestCase):
    def test_make_collection_treats_201_as_success(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "request") as req:
            req.return_value = mock.Mock(status_code=201)
            req.return_value.raise_for_status = mock.Mock()
            storage.make_collection("a/b/file.txt")
            self.assertEqual(req.call_count, 2)
            for call in req.call_args_list:
                self.assertEqual(call.args[0], "MKCOL")

    def test_make_collection_treats_405_as_already_exists(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "request") as req:
            req.return_value = mock.Mock(status_code=405)
            storage.make_collection("a/b/file.txt")
            req.return_value.raise_for_status.assert_not_called()

    def test_make_collection_accepts_409_defensively(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "request") as req:
            req.return_value = mock.Mock(status_code=409)
            storage.make_collection("a/b/file.txt")
            req.return_value.raise_for_status.assert_not_called()

    def test_make_collection_propagates_500(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "request") as req:
            resp = mock.Mock(status_code=500)
            resp.raise_for_status = mock.Mock(
                side_effect=requests.HTTPError(response=resp)
            )
            req.return_value = resp
            with self.assertRaises(requests.HTTPError):
                storage.make_collection("a/b/file.txt")

    def test_make_collection_propagates_401(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "request") as req:
            resp = mock.Mock(status_code=401)
            resp.raise_for_status = mock.Mock(
                side_effect=requests.HTTPError(response=resp)
            )
            req.return_value = resp
            with self.assertRaises(requests.HTTPError):
                storage.make_collection("a/b/file.txt")

    def test_make_collection_uses_default_timeout(self):
        storage = _make_storage()
        with mock.patch.object(storage.requests, "request") as req:
            req.return_value = mock.Mock(status_code=201)
            storage.make_collection("a/file.txt")
            self.assertEqual(req.call_args.kwargs["timeout"], storage.DEFAULT_TIMEOUT)
