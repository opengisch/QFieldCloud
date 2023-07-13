from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from qfieldcloud.core import pagination, permissions_utils, querysets_utils
from qfieldcloud.core.models import Organization, Project
from qfieldcloud.core.serializers import (
    CompleteUserSerializer,
    OrganizationSerializer,
    PublicInfoUserSerializer,
)
from rest_framework import generics, permissions
from rest_framework.response import Response

User = get_user_model()


class ListUsersViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        return permissions_utils.can_list_users_organizations(request.user)


class ListUsersView(generics.ListAPIView):

    serializer_class = PublicInfoUserSerializer
    permission_classes = [permissions.IsAuthenticated, ListUsersViewPermissions]
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self):
        params = self.request.GET
        query = params.get("q", "")

        project = None
        if params.get("project"):
            try:
                project = Project.objects.get(id=params.get("project"))
            except Project.DoesNotExist:
                pass

        organization = None
        if params.get("organization"):
            try:
                organization = Organization.objects.get(
                    username=params.get("organization")
                )
            except Project.DoesNotExist:
                pass

        # TODO : are these GET paremters documented somewhere ? Shouldn't we use something
        # like django_filters.rest_framework.DjangoFilterBackend so they get auto-documented
        # in DRF's views, or is that supposedly done with swagger ?
        exclude_organizations = bool(int(params.get("exclude_organizations") or 0))
        exclude_teams = bool(int(params.get("exclude_teams") or 0))
        invert = bool(int(params.get("invert") or 0))
        return querysets_utils.get_users(
            query,
            project=project,
            organization=organization,
            exclude_organizations=exclude_organizations,
            exclude_teams=exclude_teams,
            invert=invert,
        )


class RetrieveUpdateUserViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):

        username = permissions_utils.get_param_from_request(request, "username")

        try:
            user = User.objects.get(username=username)
        except ObjectDoesNotExist:
            return False

        if request.method == "GET":
            # The queryset is already filtered by what the user can see
            return True
        if request.method in ["PUT", "PATCH"]:
            return permissions_utils.can_update_user(request.user, user)
        return False


class RetrieveUpdateUserView(generics.RetrieveUpdateAPIView):
    """Get or Update the authenticated user"""

    permission_classes = [
        permissions.IsAuthenticated,
        RetrieveUpdateUserViewPermissions,
    ]
    serializer_class = CompleteUserSerializer

    def get_object(self):
        username = self.request.parser_context["kwargs"]["username"]
        return User.objects.get(username=username)

    def get(self, request, username):

        user = User.objects.get(username=username)

        if user.type == User.Type.ORGANIZATION:
            organization = Organization.objects.of_user(request.user).get(
                username=username
            )
            serializer = OrganizationSerializer(organization)
        else:
            if request.user == user:
                serializer = CompleteUserSerializer(user)
            else:
                serializer = PublicInfoUserSerializer(user)

        return Response(serializer.data)


class ListUserOrganizationsViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        username = permissions_utils.get_param_from_request(request, "username")

        if request.user.username != username:
            return False

        if request.method == "GET":
            return True

        return False


class ListUserOrganizationsView(generics.ListAPIView):
    """Get user's organizations"""

    permission_classes = [
        permissions.IsAuthenticated,
        ListUserOrganizationsViewPermissions,
    ]
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.of_user(self.request.user)
