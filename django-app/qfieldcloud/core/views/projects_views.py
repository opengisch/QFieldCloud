import os
import shutil

from django.contrib.auth import get_user_model
from django.utils.decorators import method_decorator
from django.conf import settings

from rest_framework import viewsets, permissions
from rest_framework.permissions import IsAuthenticated

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core import permissions_utils, utils
from qfieldcloud.core.models import (
    Project, ProjectCollaborator)
from qfieldcloud.core.serializers import (
    ProjectSerializer)


User = get_user_model()


class ProjectViewSetPermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        if view.action == 'list':
            # The queryset is already filtered by what the user can see
            return True
        user = request.user
        owner = permissions_utils.get_param_from_request(request, 'owner')
        if owner:
            # TODO: check if exists or catch exception
            owner_obj = User.objects.get(username=owner)
        else:
            # If the owner is not in the request, means that the owner
            # should be the user that made the request
            owner_obj = user

        if view.action == 'create':
            return permissions_utils.can_create_project(user, owner_obj)

        projectid = permissions_utils.get_param_from_request(request, 'projectid')
        project = Project.objects.get(id=projectid)

        if view.action in ['update', 'partial_update', 'destroy']:
            return permissions_utils.can_update_delete_project(user, project)
        if view.action == 'retrieve':
            return permissions_utils.can_get_project(user, project)

        return False


include_public_param = openapi.Parameter(
    'include-public', openapi.IN_QUERY,
    description="Include public projects",
    type=openapi.TYPE_BOOLEAN)


@method_decorator(
    name='retrieve', decorator=swagger_auto_schema(
        operation_description="Get a project", operation_id="Get a project",))
@method_decorator(
    name='update', decorator=swagger_auto_schema(
        operation_description="Update a project",
        operation_id="Update a project",))
@method_decorator(
    name='partial_update', decorator=swagger_auto_schema(
        operation_description="Patch a project",
        operation_id="Patch a project",))
@method_decorator(
    name='destroy', decorator=swagger_auto_schema(
        operation_description="Delete a project",
        operation_id="Delete a project",))
@method_decorator(
    name='list', decorator=swagger_auto_schema(
        operation_description="""List projects owned by the authenticated
        user or that the authenticated user has explicit permission to access
        (i.e. she is a project collaborator)""",
        operation_id="List projects",
        manual_parameters=[include_public_param]))
@method_decorator(
    name='create', decorator=swagger_auto_schema(
        operation_description="""Create a new project owned by the specified
        user or organization""",
        operation_id="Create a project",))
class ProjectViewSet(viewsets.ModelViewSet):

    serializer_class = ProjectSerializer
    lookup_url_kwarg = 'projectid'
    permission_classes = [permissions.IsAuthenticated, ProjectViewSetPermissions]

    def get_queryset(self):
        queryset = Project.objects.filter(owner=self.request.user) | \
            Project.objects.filter(
                collaborators__in=ProjectCollaborator.objects.filter(
                    collaborator=self.request.user))

        include_public = self.request.query_params.get(
            'include-public', default=None)

        if include_public and include_public.lower() == 'true':
            queryset |= Project.objects.filter(private=False)

        return queryset

    def destroy(self, request, projectid):
        # Delete files from storage
        bucket = utils.get_s3_bucket()
        prefix = utils.safe_join('projects/{}/'.format(projectid))
        bucket.objects.filter(Prefix=prefix).delete()

        return super().destroy(request, projectid)
