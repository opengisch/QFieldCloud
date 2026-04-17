import base64
import os
from abc import ABC

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.http import HttpResponse
from requests.adapters import HTTPAdapter
from storages.backends.s3 import S3Storage
from urllib3.util.retry import Retry


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


class QfcS3Boto3Storage(QfcBackendStorageMixin, S3Storage):
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

    # Should this go into .env?
    DEFAULT_TIMEOUT = (10, 60)
    UPLOAD_TIMEOUT = (10, 600)
    RETRY_TOTAL = 5
    RETRY_BACKOFF_FACTOR = 1
    RETRY_STATUS_FORCELIST = (429, 502, 503, 504)
    RETRY_ALLOWED_METHODS = frozenset(
        ["HEAD", "GET", "PUT", "DELETE", "MKCOL", "PROPFIND"]
    )

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

    def get_requests_session(self, **_kwargs) -> requests.Session:
        """
        Creates an HTTP session with retry and connection pooling.
        """
        session = requests.Session()
        retries = Retry(
            total=self.RETRY_TOTAL,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=self.RETRY_STATUS_FORCELIST,
            allowed_methods=self.RETRY_ALLOWED_METHODS,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _timeout_for(self, method: str) -> tuple[int, int]:
        """Returns the (connect, read) timeout to use for a given HTTP method."""
        if method.lower() == "put":
            return self.UPLOAD_TIMEOUT

        return self.DEFAULT_TIMEOUT

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
        kwargs.setdefault("timeout", self._timeout_for(method))

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

    def _open(self, name: str, mode: str = "rb") -> ContentFile:  # pylint: disable=unused-argument
        """Reads the content of a file from the configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.
            mode: opening mode (default: "rb").

        Returns:
            Content of the requested file.
        """
        response = self.perform_webdav_request("GET", name, stream=True)
        return ContentFile(
            b"".join(response.iter_content(chunk_size=8 * 1024 * 1024)),
            name,
        )

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
        """Creates parent collections (folders) for a file on the webdav server.

        Sends MKCOL for each parent. Treats 405 (URL already mapped) and 409
        as success, so the loop is idempotent and tolerant of servers that
        use 409 loosely for "already exists".

        Arguments:
            name: relative path of the file on the webdav server.
        """
        coll_path = self.webdav_url

        for directory in name.split("/")[:-1]:
            col = os.path.join(coll_path, directory, "")
            resp = self.requests.request(
                "MKCOL", col, timeout=self._timeout_for("MKCOL")
            )

            if resp.status_code not in (201, 405, 409):
                resp.raise_for_status()

            coll_path = os.path.join(coll_path, directory)

    def delete(self, name: str) -> None:
        """Deletes a file from a configured webdav storage.

        Idempotent for 404/410, raises for other errors.

        Arguments:
            name: relative path of the file on the webdav server.
        """
        try:
            self.perform_webdav_request("DELETE", name)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                return

            raise

    def exists(self, name: str) -> bool:
        """Checks if a file exists on a configured webdav storage.

        Arguments:
            name: relative path of the file on the webdav server.

        Raises:
            IOError: when the server is unreachable or returns a status that
                is neither a clear hit (2xx) nor a clear miss (404/410).

        Returns:
            True if the file exists, False if not.
        """
        url = self.get_webdav_url(name)
        try:
            resp = self.requests.head(url, timeout=self._timeout_for("HEAD"))
        except requests.exceptions.RequestException as exc:
            raise IOError(f"WebDAV exists() network error for {name!r}: {exc}") from exc

        if 200 <= resp.status_code < 300:
            return True

        if resp.status_code in (404, 410):
            return False

        raise IOError(
            f"WebDAV exists() got unexpected status {resp.status_code} for {name!r}"
        )

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
        except (ValueError, requests.exceptions.HTTPError) as exc:
            raise IOError(f"Unable to get size for {name}") from exc

    def url(self, name: str, **_kwargs) -> str:  # type: ignore
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

    def get_available_name(self, name: str, max_length: int | None = None) -> str:
        """Returns a filename that is available on the configured webdav storage.

        Arguments:
            name: desired relative path of the file on the webdav server.
            max_length: maximum length of the filename (not used)."""

        if self.is_name_available(name, max_length):
            return super().get_available_name(name, max_length)

        return name
