
import json
from pathlib import PurePath

from django.contrib.auth import get_user_model
from django.utils.decorators import method_decorator

from rest_framework import status, views, permissions
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core.models import (
    Project)
from qfieldcloud.core import utils, permissions_utils

User = get_user_model()


class DeltaFilePermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        projectid = permissions_utils.get_param_from_request(
            request, 'projectid')
        # TODO: check if exists
        project = Project.objects.get(id=projectid)
        user = request.user

        if request.method == 'GET':
            return permissions_utils.can_list_deltas(user, project)
        if request.method == 'POST':
            return permissions_utils.can_upload_deltas(user, project)
        return False


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List deltafiles of a project",
        operation_id="List deltafiles",))
@method_decorator(
    name='post', decorator=swagger_auto_schema(
        operation_description="Add a deltafile to a project",
        operation_id="Add deltafile",))
class ListCreateDeltaFileView(views.APIView):

    permission_classes = [DeltaFilePermissions]

    def post(self, request, projectid):

        try:
            project_obj = Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        if 'file' not in request.data:
            return Response(
                'Empty content', status=status.HTTP_400_BAD_REQUEST)

        request_file = request.data['file']

        try:
            delta_json = json.load(request_file)
        except ValueError:
            return Response(
                'DeltaFile is not a valid json file',
                status=status.HTTP_400_BAD_REQUEST)

        deltafileid = delta_json['id']
        sha256sum = utils.get_sha256(request_file)
        key = utils.safe_join(
            'projects/{}/deltas/'.format(projectid), deltafileid)

        # Check if deltafile is already present
        on_storage_sha = utils.check_s3_key(key)
        if on_storage_sha:
            if on_storage_sha == sha256sum:
                # TODO: Return status of the already applied deltafile
                return Response(status=status.HTTP_200_OK)
            else:
                return Response(
                    'A DeltaFile with the same id but different content already exists',
                    status=status.HTTP_400_BAD_REQUEST)

        bucket = utils.get_s3_bucket()
        metadata = {'Sha256sum': sha256sum}

        bucket.upload_fileobj(
            request_file.open(), key, ExtraArgs={"Metadata": metadata})

        project_file = utils.get_qgis_project_file(projectid)

        job = utils.apply_delta(
            str(project_obj.id),
            project_file,
            deltafileid,
            delta_json['id'])

        return Response({'jobid': job.id})

    def get(self, request, projectid):

        try:
            Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        bucket = utils.get_s3_bucket()

        prefix = 'projects/{}/deltas/'.format(projectid)

        deltas = []
        for delta in bucket.objects.filter(Prefix=prefix):
            path = PurePath(delta.key)
            filename = str(path.relative_to(*path.parts[:3]))
            last_modified = delta.last_modified.strftime(
                '%d.%m.%Y %H:%M:%S %Z')
            sha256sum = delta.Object().metadata['Sha256sum']

            deltas.append({
                'id': filename,
                'last_modified': last_modified,
                'size': delta.size,
                'sha256': sha256sum,
            })

        return Response(deltas)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get delta status",
        operation_id="Get delta status",))
class GetDeltaView(views.APIView):

    permission_classes = [DeltaFilePermissions]

    def get(self, request, projectid, deltafileid):

        bucket = utils.get_s3_bucket()
        key = utils.safe_join(
            'projects/{}/deltas/'.format(projectid), str(deltafileid))

        obj = bucket.Object(key)
        status = obj.metadata.get('Status', None)

        path = PurePath(obj.key)
        filename = str(path.relative_to(*path.parts[:3]))
        last_modified = obj.last_modified.strftime('%d.%m.%Y %H:%M:%S %Z')
        sha256sum = obj.metadata['Sha256sum']

        output = None
        # If the status is not stored as file's metadata, means that
        # the deltafile has not been applied yet, so we look at the
        # job queue for the status
        if status is None:
            job = utils.get_job('delta', str(deltafileid))
            if job is not None:
                job_status = job.get_status()
                if job_status == 'started':
                    status = 'STATUS_BUSY'
                elif job_status in ['queued', 'deferred']:
                    status = 'STATUS_PENDING'
                else:
                    status = 'STATUS_ERROR'
                    output = job.result[1]

        result = {
            'id': filename,
            'last_modified': last_modified,
            'size': obj.content_length,
            'sha256': sha256sum,
            'status': status,
        }

        if output:
            result['output'] = output

        return Response(result)
