
from pathlib import PurePath
from django.core.files.base import ContentFile
from django.http import FileResponse

from rest_framework import views, status, permissions
from rest_framework.response import Response

from qfieldcloud.core.models import Project
from qfieldcloud.core import utils
from qfieldcloud.core import permissions_utils


class ListFilesViewPermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'projectid' not in request.parser_context['kwargs']:
            return False

        projectid = request.parser_context['kwargs']['projectid']
        project = Project.objects.get(id=projectid)

        return permissions_utils.can_list_files(request.user, project)


class ListFilesView(views.APIView):
    # TODO: swagger doc
    # TODO: docstring

    permission_classes = [ListFilesViewPermissions]

    def get(self, request, projectid):
        try:
            Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        bucket = utils.get_s3_bucket()

        prefix = 'projects/{}/files/'.format(projectid)

        files = {}
        for version in bucket.object_versions.filter(Prefix=prefix):
            # Created the dict entry if doesn't exist
            if version.key not in files:
                files[version.key] = {'versions': []}

            head = version.head()
            path = PurePath(version.key)
            filename = str(path.relative_to(*path.parts[:3]))
            last_modified = version.last_modified.strftime(
                '%d.%m.%Y %H:%M:%S %Z')

            if version.is_latest:
                files[version.key]['name'] = filename
                files[version.key]['size'] = version.size
                files[version.key]['sha256'] = head['Metadata']['Sha256sum']
                files[version.key]['last_modified'] = last_modified

            files[version.key]['versions'].append(
                {'size': version.size,
                 'sha256': head['Metadata']['Sha256sum'],
                 'version_id': version.version_id,
                 'last_modified': last_modified,
                 'is_latest': version.is_latest,
                 })

        result_list = [files[key] for key in files]
        return Response(result_list)


class DownloadPushDeleteFileViewPermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'projectid' not in request.parser_context['kwargs']:
            return False

        projectid = request.parser_context['kwargs']['projectid']
        # TODO: check if exists or catch exception
        project = Project.objects.get(id=projectid)
        user = request.user

        if request.method == 'GET':
            return permissions_utils.can_download_files(user, project)
        if request.method == 'DELETE':
            return permissions_utils.can_delete_files(user, project)
        if request.method == 'POST':
            return permissions_utils.can_upload_files(user, project)
        return False


class DownloadPushDeleteFileView(views.APIView):
    # TODO: swagger doc
    # TODO: docstring
    permission_classes = [DownloadPushDeleteFileViewPermissions]

    def get(self, request, projectid, filename):
        try:
            Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        extra_args = {}
        if 'version' in self.request.query_params:
            version = self.request.query_params['version']
            extra_args['VersionId'] = version

        bucket = utils.get_s3_bucket()

        filekey = utils.safe_join(
            'projects/{}/files/'.format(projectid), filename)
        return_file = ContentFile(b'')
        bucket.download_fileobj(filekey, return_file, extra_args)

        return FileResponse(
            return_file.open(),
            as_attachment=True,
            filename=filename)

    def post(self, request, projectid, filename, format=None):
        # TODO: why the format parameter?

        try:
            Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        if 'file' not in request.data:
            return Response(
                'Empty content', status=status.HTTP_400_BAD_REQUEST)

        # check only one qgs/qgz file per project
        if filename.lower().endswith('.qgs') or filename.lower().endswith('.qgz'):
            current_project_file = utils.get_qgis_project_file(projectid)
            if current_project_file is not None:
                # Allowed only to push the a new version of the same file
                if not PurePath(filename) == PurePath(current_project_file):
                    return Response(
                        'Only one QGIS project per project allowed',
                        status=status.HTTP_400_BAD_REQUEST)

        request_file = request.data['file']

        sha256sum = utils.get_sha256(request_file)
        bucket = utils.get_s3_bucket()

        key = utils.safe_join('projects/{}/files/'.format(projectid), filename)
        metadata = {'Sha256sum': sha256sum}

        bucket.upload_fileobj(
            request_file.open(), key, ExtraArgs={"Metadata": metadata})

        return Response(status=status.HTTP_201_CREATED)

    def delete(self, request, projectid, filename):

        try:
            Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        key = utils.safe_join('projects/{}/files/'.format(projectid), filename)
        bucket = utils.get_s3_bucket()

        bucket.object_versions.filter(Prefix=key).delete()

        return Response(status=status.HTTP_200_OK)
