import base64
import os
from abc import ABC

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.http import HttpResponse
from storages.backends.s3boto3 import S3Boto3Storage


class QfcBackendStorageMixin(ABC):
    def check_status(self) -> bool:
        """Checks if the storage is reachable.

        Returns:
            True if reachable, False if not.
        """
        raise NotImplementedError(
            "Subclassing QFC specific storages must implement this method."
        )

    def patch_nginx_download_redirect(self, response: HttpResponse) -> None:
        """Patches a nginx redirect response for usage with the storage backend.
        At the moment, does nothing.

        Arguments:
            response: HTTP redirect response to patch.
        """
        pass


class QfcS3Boto3Storage(QfcBackendStorageMixin, S3Boto3Storage):
    def check_status(self) -> bool:
        """Checks if the S3 bucket is reachable.

        Returns:
            True if reachable, False if not.
        """
        try:
            bucket_name = self.bucket.name
            self.bucket.meta.client.head_bucket(Bucket=bucket_name)
        except Exception:
            return False

        return True

    def patch_nginx_download_redirect(self, response: HttpResponse) -> None:
        """Patches a nginx redirect response for usage with S3.
        At the moment, does nothing.

        Arguments:
            response: HTTP redirect response to patch.
        """
        pass


class QfcWebDavStorage(QfcBackendStorageMixin, Storage):
    """
    Storage backend using WebDAV.
    Adapted and inspired by this repository: https://github.com/marazmiki/django-webdav-storage
    Copyright (c) 2020, Mikhail Porokhovnichenko
    """

    def __init__(self, **options):
        self.requests = self.get_requests_session(**options)

        self.webdav_url = options.get("webdav_url")
        if not self.webdav_url:
            raise ImproperlyConfigured("Please define the `webdav_url` storage option")

        self.public_url = options.get("public_url")
        if not self.public_url:
            raise ImproperlyConfigured("Please define the `public_url` storage option")

        self.basic_auth = options.get("basic_auth")
        if not self.basic_auth:
            raise ImproperlyConfigured("Please define the `basic_auth` storage option")

    def check_status(self) -> bool:
        """Checks if the WebDAV storage is reachable.

        Returns:
            True if reachable, False if not.
        """
        try:
            self.perform_webdav_request("HEAD", "/")
        except requests.exceptions.RequestException:
            return False

        return True

    def get_requests_session(self, **kwargs) -> requests.Session:
        """
        Creates a HTTP session for requesting webdav later.
        """
        return requests.Session()

    def perform_webdav_request(
        self, method: str, name: str, *args, **kwargs
    ) -> requests.Response:
        """Performs a webdav request.

        Arguments:
            method: webdav method, e.g. "HEAD", "GET", "PUT", "DELETE", etc.
            name: relative path of the file on the webdav server.

        Returns:
            HTTP response related to the sent request.
        """
        url = self.get_webdav_url(name)
        method = method.lower()

        response = getattr(self.requests, method)(url, *args, **kwargs)
        response.raise_for_status()

        return response

    def get_webdav_url(self, name: str) -> str:
        """Returns the HTTP url for a webdav file.

        Arguments:
            name: relative path of the file on the webdav server.

        Returns:
            HTTP url for the file.
        """
        return self.webdav_url.rstrip("/") + "/" + name.lstrip("/")

    def get_public_url(self, name: str) -> str:
        """Returns the public HTTP url for a webdav file.

        Arguments:
            name: relative path of the file on the webdav server.

        Returns:
            Public HTTP url for the file.
        """
        return self.public_url.rstrip("/") + "/" + name.lstrip("/")

    def _open(self, name: str, mode: str = "rb") -> ContentFile:
        """Reads the content of a file from the configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.
            mode: opening mode (default: "rb").

        Returns:
            Content of the requested file.
        """
        content = self.perform_webdav_request("GET", name).content
        return ContentFile(content, name)

    def _save(self, name: str, content: ContentFile) -> str:
        """Saves a file on the configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.
            content: content of the file to save.

        Returns:
            relative path of the file on the webdav server.
        """
        self.make_collection(name)

        if hasattr(content, "temporary_file_path"):
            with open(content.temporary_file_path(), "rb") as f:
                self.perform_webdav_request(method="PUT", name=name, data=f)
        else:
            content.file.seek(0)
            self.perform_webdav_request(method="PUT", name=name, data=content.file)

        return name

    def make_collection(self, name: str) -> None:
        """Creates a so-called collection on the configured webdav storage for a file.
        Typically creates parent folders if not existing.

        Arguments:
            name: relative path of the file on the webdav server.
        """
        coll_path = self.webdav_url

        for directory in name.split("/")[:-1]:
            col = os.path.join(coll_path, directory, "")
            resp = self.requests.head(col)

            if not resp.ok:
                resp = self.requests.request("MKCOL", col)
                resp.raise_for_status()

            coll_path = os.path.join(coll_path, directory)

    def delete(self, name: str) -> None:
        """Deletes a file from a configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.
        """
        try:
            self.perform_webdav_request("DELETE", name)
        except requests.HTTPError:
            pass

    def exists(self, name: str) -> bool:
        """Checks if a file exists on a configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.

        Returns:
            True if exists, False if not.
        """
        try:
            self.perform_webdav_request("HEAD", name)
        except requests.exceptions.HTTPError:
            return False

        return True

    def size(self, name: str) -> int:
        """Returns the size of a file on a configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.

        Raises:
            IOError: if something wrong happens during the network request.

        Returns:
            Size in bytes of the requested file.
        """
        try:
            return int(
                self.perform_webdav_request("HEAD", name).headers["content-length"]
            )
        except (ValueError, requests.exceptions.HTTPError):
            raise IOError("Unable get size for %s" % name)

    def url(self, name: str, **kwargs) -> str:  # type: ignore
        """Returns the URL of a file from the configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.

        Returns:
            Public webdav URL of the file.
        """
        return self.get_public_url(name)

    def patch_nginx_download_redirect(self, response: HttpResponse) -> None:
        """Patches a nginx redirect response for usage with WebDAV.
        Adds configured webdav/HTTP basic auth, required for nginx redirect.

        Arguments:
            response: HTTP redirect response to patch.
        """
        b64_auth = base64.b64encode(self.basic_auth.encode()).decode()
        basic_auth = f"Basic {b64_auth}"
        response["webdav_auth"] = basic_auth
