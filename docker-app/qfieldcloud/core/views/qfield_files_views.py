
from pathlib import PurePath

from django.db.models import Q
from django.http import FileResponse
from django.core.files.base import ContentFile
from django.utils.decorators import method_decorator
from django.core.exceptions import ObjectDoesNotExist

from rest_framework import views, permissions
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core import (
    utils, permissions_utils, exceptions, serializers)

from qfieldcloud.core.models import (
    Project, Exportation)


class ExportViewPermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        projectid = permissions_utils.get_param_from_request(
            request, 'projectid')
        try:
            project = Project.objects.get(id=projectid)
        except ObjectDoesNotExist:
            return False
        user = request.user
        return permissions_utils.can_download_files(user, project)


@method_decorator(
    name='post', decorator=swagger_auto_schema(
        operation_description="Launch QField export project",
        operation_id="Launch qfield export"))
@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get QField export status",
        operation_id="Get qfield export status"))
class ExportView(views.APIView):

    permission_classes = [permissions.IsAuthenticated,
                          ExportViewPermissions]

    def post(self, request, projectid):

        project_obj = Project.objects.get(id=projectid)

        project_file = utils.get_qgis_project_file(projectid)
        if project_file is None:
            raise exceptions.NoQGISProjectError()

        # Check if active exportation already exists
        # TODO: cache results for some minutes
        query = (Q(project=project_obj) & (Q(status=Exportation.STATUS_PENDING) | Q(status=Exportation.STATUS_BUSY)))
        if Exportation.objects.filter(query).exists():
            serializer = serializers.ExportationSerializer(
                Exportation.objects.get(query))
            return Response(serializer.data)

        utils.export_project(
            str(project_obj.id),
            project_file)

        exportation = Exportation.objects.create(
            project=project_obj)

        # TODO: check if user is allowed otherwise ERROR 403
        serializer = serializers.ExportationSerializer(
            exportation)
        return Response(serializer.data)

    def get(self, request, projectid):
        project_obj = Project.objects.get(id=projectid)

        exportation = Exportation.objects.filter(
            project=project_obj).order_by('updated_at').last()

        serializer = serializers.ExportationSerializer(exportation)
        return Response(serializer.data)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List QField project files",
        operation_id="List qfield project files"))
class ListFilesView(views.APIView):

    permission_classes = [permissions.IsAuthenticated,
                          ExportViewPermissions]

    def get(self, request, projectid):

        project_obj = Project.objects.get(id=projectid)

        # Check if the project was exported at least once
        if not Exportation.objects.filter(
                project=project_obj, status=Exportation.STATUS_EXPORTED):
            raise exceptions.InvalidJobError(
                'Project files have not been exported for the provided project id')

        exportation = Exportation.objects.filter(
            project=project_obj,
            status=Exportation.STATUS_EXPORTED).order_by('updated_at').last()

        # Obtain the bucket object
        bucket = utils.get_s3_bucket()

        export_prefix = 'projects/{}/export/'.format(projectid)

        files = []
        for obj in bucket.objects.filter(Prefix=export_prefix):
            path = PurePath(obj.key)

            # We cannot be sure of the metadata's first letter case
            # https://github.com/boto/boto3/issues/1709
            metadata = obj.Object().metadata
            if 'sha256sum' in metadata:
                sha256sum = metadata['sha256sum']
            else:
                sha256sum = metadata['Sha256sum']

            files.append({
                # Get the path of the file relative to the export directory
                'name': str(path.relative_to(*path.parts[:3])),
                'size': obj.size,
                'sha256': sha256sum,
            })

        return Response({'files': files,
                         'layers': exportation.exportlog,
                         'exported_at': exportation.updated_at})


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Download file for QField",
        operation_id="Download qfield file"))
class DownloadFileView(views.APIView):

    permission_classes = [permissions.IsAuthenticated,
                          ExportViewPermissions]

    def get(self, request, projectid, filename):

        project_obj = Project.objects.get(id=projectid)

        # Check if the project was exported at least once
        if not Exportation.objects.filter(
                project=project_obj, status=Exportation.STATUS_EXPORTED):
            raise exceptions.InvalidJobError(
                'Project files have not been exported for the provided project id')

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
