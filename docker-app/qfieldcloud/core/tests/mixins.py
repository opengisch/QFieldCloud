import urllib
from typing import IO

from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.http import FileResponse, HttpResponse
from django.urls import reverse
from rest_framework.response import Response

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Project, User


class QfcFilesTestCaseMixin:
    """
    Generic Test case class that is able to perform file operations.
    E.g. upload, download, delete, list.
    """

    def _get_token_for_user(self, user: User) -> AuthToken:
        try:
            return AuthToken.objects.get(user=user)
        except ObjectDoesNotExist:
            return AuthToken.objects.create(user=user)
        except MultipleObjectsReturned:
            return AuthToken.objects.filter(user=user).first()

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
        self, user: User, project: Project, files: list[tuple[str, IO]]
    ) -> list[HttpResponse | Response]:
        """
        Uploads several files to the API.
        Note that the `files` argument is a list of tuple:
            - first element is the remote filename
            - second element is the file content
        """

        responses = []
        for remote_filename, content in files:
            response = self._upload_file(user, project, remote_filename, content)
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
        token = AuthToken.objects.get_or_create(user=user)[0]

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
        token = AuthToken.objects.get_or_create(user=user)[0]

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
        token = AuthToken.objects.get_or_create(user=user)[0]

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
