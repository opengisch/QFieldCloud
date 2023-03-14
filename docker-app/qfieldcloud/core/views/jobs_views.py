from django.core.exceptions import ObjectDoesNotExist
from qfieldcloud.core import permissions_utils, serializers
from qfieldcloud.core.models import Job, Project
from rest_framework import generics, permissions, viewsets
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED


class JobPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        project_id = permissions_utils.get_param_from_request(request, "project_id")

        try:
            project = Project.objects.get(id=project_id)
        except ObjectDoesNotExist:
            return False

        return permissions_utils.can_read_jobs(request.user, project)


class JobViewSet(viewsets.ReadOnlyModelViewSet):

    serializer_class = serializers.JobSerializer
    lookup_url_kwarg = "job_id"
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_by_job_type(self, job_type, *args, **kwargs):
        if job_type == Job.Type.DELTA_APPLY:
            return serializers.ApplyJobSerializer(*args, **kwargs)
        elif job_type == Job.Type.PACKAGE:
            return serializers.PackageJobSerializer(*args, **kwargs)
        elif job_type == Job.Type.PROCESS_PROJECTFILE:
            return serializers.ProcessProjectfileJobSerializer(*args, **kwargs)
        else:
            raise NotImplementedError(f'Unknown job type "{job_type}"')

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", self.get_serializer_context())

        if self.action in ("create"):
            if "data" in kwargs:
                job_type = kwargs["data"]["type"]
            else:
                job_type = args[0].type

            return self.get_serializer_by_job_type(job_type, *args, **kwargs)

        if self.action in ("retrieve",):
            job_type = args[0].type

            return self.get_serializer_by_job_type(job_type, *args, **kwargs)

        return serializers.JobSerializer(*args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if bool(int(request.data.get("force", 0))):
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            serializer.is_valid(raise_exception=True)
            if not serializer.Meta.allow_parallel_jobs:
                job = serializer.get_lastest_not_finished_job()
                if job:
                    return Response(self.get_serializer(job).data)
            serializer.save()

        return Response(serializer.data, status=HTTP_201_CREATED)

    def get_queryset(self):
        qs = Job.objects.select_subclasses()

        if self.action == "list":
            project_id = self.request.data.get("project_id")
            project = generics.get_object_or_404(Project, pk=project_id)
            qs = qs.filter(project=project)

        return qs
