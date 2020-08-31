import os

from django.conf import settings
from django.http import FileResponse

from rest_framework import generics, views, status
from rest_framework.response import Response

from qfieldcloud.apps.api import qgis_utils, file_utils

from qfieldcloud.apps.model.models import (
    Project, File, FileVersion)


class ExportView(views.APIView):

    def get(self, request, projectid):
        # TODO:
        # - If an apply delta job already exists for this project, defer it
        # - Is it possible to see if an export job already exists for this project to avoid duplicating?
        # - Check permissions

        project_obj = None
        try:
            project_obj = Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        project_file = project_obj.get_qgis_project_file()
        if project_file is None:
            return Response(
                'The project does not contain a valid qgis project file',
                status=status.HTTP_400_BAD_REQUEST)

        project_obj.export_to_filesystem()

        job = qgis_utils.export_project(
            str(project_obj.id),
            project_file.original_path)

        return Response({'jobid': job.id})


class ListFilesView(views.APIView):

    def get(self, request, jobid):
        job = qgis_utils.get_job('export', str(jobid))

        job_status = job.get_status()

        projectid = job.kwargs['projectid']

        if job_status == 'finished':
            project_directory = os.path.join(
                settings.PROJECTS_ROOT,
                projectid)

            export_directory = os.path.join(
                project_directory,
                'export')

            files = []
            for filename in os.listdir(export_directory):
                file = os.path.join(export_directory, filename)
                with open(file, 'rb') as f:
                    files.append({
                        'name': filename,
                        'size': os.path.getsize(file),
                        'sha256': file_utils.get_sha256(f),
                    })

            return Response({'status': job_status, 'files': files})

        return Response({'status': job_status})


class DownloadFileView(views.APIView):

    def get(self, request, jobid, filename):
        job = qgis_utils.get_job('export', str(jobid))

        job_status = job.get_status()

        projectid = job.kwargs['projectid']

        if job_status == 'finished':
            project_directory = os.path.join(
                settings.PROJECTS_ROOT,
                projectid)

            export_directory = os.path.join(
                project_directory,
                'export')

            return FileResponse(
                open(os.path.join(export_directory,
                                  filename), 'rb'),
                as_attachment=True,
                filename=filename)

        return Response({'status': job_status})
