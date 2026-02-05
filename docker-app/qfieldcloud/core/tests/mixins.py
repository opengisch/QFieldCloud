import urllib
from pathlib import Path
from typing import IO

from django.http import FileResponse, HttpResponse
from django.urls import reverse
from rest_framework.response import Response

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Project, User
from qfieldcloud.core.tests.utils import testdata_path


class QfcFilesTestCaseMixin:
    """
    Generic Test case class that is able to perform file operations.
    E.g. upload, download, delete, list.
    """

    def _get_token_for_user(self, user: User) -> AuthToken:
        # We pass the client_type to prevent get_or_create() from failing with
        # MultipleObjectsReturned if a worker token for the same user happens
        # to be created during the test.
        token = AuthToken.objects.get_or_create(
            user=user,
            client_type=AuthToken.ClientType.UNKNOWN,
        )[0]
        return token

    def _upload_file(
        self, user: User, project: Project, filename: str, content: IO
    ) -> HttpResponse | Response:
        """Uploads a file to the API.

        Arguments:
            user: User that uploads the file.
            project: Project to which the file belongs.
            filename: Name of the file to upload.
            content: Content of the file to upload.

        Returns:
            Response answered by the API.
        """

        token = self._get_token_for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

        response = self.client.post(
            reverse(
                "filestorage_crud_file",
                kwargs={
                    "project_id": project.id,
                    "filename": filename,
                },
            ),
            {
                "file": content,
            },
        )

        self.client.credentials(HTTP_AUTHORIZATION="")

        return response

    def _upload_files(
        self, user: User, project: Project, files: list[tuple[str, IO | str | Path]]
    ) -> list[HttpResponse | Response]:
        """
        Uploads several files to the API.
        Note that the `files` argument is a list of tuple:
            - first element is the remote filename
            - second element is the file content
        """

        responses = []
        for remote_filename, content in files:
            if isinstance(content, (str, Path)):
                file = open(testdata_path(content), "r")
            else:
                file = content

            response = self._upload_file(user, project, remote_filename, file)
            responses.append(response)

        return responses

    def _download_file(
        self,
        user: User,
        project: Project,
        filename: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse | Response | FileResponse:
        token = self._get_token_for_user(user)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

        response = self.client.get(
            reverse(
                "filestorage_crud_file",
                kwargs={
                    "project_id": project.id,
                    "filename": filename,
                },
            ),
            data=params,
            headers=headers,
        )

        self.client.credentials(HTTP_AUTHORIZATION="")

        return response

    def _delete_file(
        self,
        user: User,
        project: Project,
        filename: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse | Response:
        token = self._get_token_for_user(user)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

        url = reverse(
            "filestorage_crud_file",
            kwargs={
                "project_id": project.id,
                "filename": filename,
            },
        )

        if params is not None:
            url += "?"
            url += urllib.parse.urlencode(params)

        response = self.client.delete(
            url,
            headers=headers,
        )

        self.client.credentials(HTTP_AUTHORIZATION="")

        return response

    def _list_files(self, user: User, project: Project) -> HttpResponse | Response:
        token = self._get_token_for_user(user)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

        response = self.client.get(
            reverse(
                "filestorage_list_files",
                kwargs={
                    "project_id": project.id,
                },
            ),
        )

        self.client.credentials(HTTP_AUTHORIZATION="")

        return response

    def _get_file_metadata(
        self,
        user: User,
        project: Project,
        filename: str,
    ) -> HttpResponse | Response:
        token = self._get_token_for_user(user)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

        response = self.client.get(
            reverse(
                "filestorage_file_metadata",
                kwargs={
                    "project_id": project.id,
                    "filename": filename,
                },
            )
        )

        self.client.credentials(HTTP_AUTHORIZATION="")

        return response
