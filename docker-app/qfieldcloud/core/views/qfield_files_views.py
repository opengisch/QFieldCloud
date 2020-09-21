
from pathlib import PurePath

from django.http import FileResponse
from django.core.files.base import ContentFile
from django.utils.decorators import method_decorator

from rest_framework import views, status, permissions
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core import utils, permissions_utils

from qfieldcloud.core.models import (
    Project)


class ExportViewPermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        projectid = permissions_utils.get_param_from_request(
            request, 'projectid')
        # TODO: check if exists
        project = Project.objects.get(id=projectid)
        user = request.user
        return permissions_utils.can_download_files(user, project)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Launch QField export project",
        operation_id="Launch qfield export"))
class ExportView(views.APIView):

    permission_classes = [permissions.IsAuthenticated,
                          ExportViewPermissions]

    def get(self, request, projectid):
        # TODO:
        # - If an apply delta job already exists for this project, defer it
        # - Is it possible to see if an export job already exists for this project to avoid duplicating?

        project_obj = None
        try:
            project_obj = Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        project_file = utils.get_qgis_project_file(projectid)
        if project_file is None:
            return Response(
                'The project does not contain a valid qgis project file',
                status=status.HTTP_400_BAD_REQUEST)

        job = utils.export_project(
            str(project_obj.id),
            project_file)

        return Response({'jobid': job.id})


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List QField project files",
        operation_id="List qfield project files"))
class ListFilesView(views.APIView):

    permission_classes = [permissions.IsAuthenticated,
                          permissions.IsAuthenticated]

    def get(self, request, jobid):
        job = utils.get_job('export', str(jobid))

        if not job:
            return Response(
                'The provided job id does not exist.',
                status=status.HTTP_400_BAD_REQUEST)

        job_status = job.get_status()

        projectid = job.kwargs['projectid']

        if job_status == 'finished':
            exit_code = job.result[0]
            output = job.result[1]

            if not exit_code == 0:
                job_status = 'qgis_error'
                return Response({'status': job_status, 'output': output})

            # Obtain the bucket object
            bucket = utils.get_s3_bucket()

            export_prefix = 'projects/{}/export/'.format(projectid)

            files = []
            for obj in bucket.objects.filter(Prefix=export_prefix):
                path = PurePath(obj.key)
                files.append({
                    # Get the path of the file relative to the export directory
                    'name': str(path.relative_to(*path.parts[:3])),
                    'size': obj.size,
                    'sha256': obj.Object().metadata['Sha256sum'],
                })

            return Response({'status': job_status, 'files': files})

        return Response({'status': job_status})


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Download file for QField",
        operation_id="Download qfield file"))
class DownloadFileView(views.APIView):

    def get(self, request, jobid, filename):
        job = utils.get_job('export', str(jobid))

        job_status = job.get_status()

        projectid = job.kwargs['projectid']

        if job_status == 'finished':
            exit_code = job.result[0]
            output = job.result[1]

            if not exit_code == 0:
                job_status = 'qgis_errors'
                return Response({'status': job_status, 'output': output})

            # Obtain the bucket object
            bucket = utils.get_s3_bucket()

            filekey = utils.safe_join(
                'projects/{}/export/'.format(projectid), filename)

            return_file = ContentFile(b'')
            bucket.download_fileobj(filekey, return_file)

            return FileResponse(
                return_file.open(),
                as_attachment=True,
                filename=filename)

        return Response({'status': job_status})
