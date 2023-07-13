from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from qfieldcloud.core import pagination, permissions_utils
from qfieldcloud.core.models import Organization, OrganizationMember
from qfieldcloud.core.serializers import OrganizationMemberSerializer
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.settings import api_settings

User = get_user_model()


class ListCreateMembersViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        organization_name = permissions_utils.get_param_from_request(
            request, "organization"
        )

        try:
            organization = User.objects.get(username=organization_name)
        except ObjectDoesNotExist:
            return False

        if request.method == "GET":
            return permissions_utils.can_read_members(user, organization)
        if request.method == "POST":
            return permissions_utils.can_create_members(user, organization)
        return False


class ListCreateMembersView(generics.ListCreateAPIView):

    permission_classes = [permissions.IsAuthenticated, ListCreateMembersViewPermissions]
    serializer_class = OrganizationMemberSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self):
        organization = self.request.parser_context["kwargs"]["organization"]
        organization_obj = User.objects.get(username=organization)

        return OrganizationMember.objects.filter(organization=organization_obj)

    def post(self, request, organization):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        organization_obj = Organization.objects.get(username=organization)
        member_obj = User.objects.get(username=request.data["member"])
        serializer.save(member=member_obj, organization=organization_obj)

        try:
            headers = {"Location": str(serializer.data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            headers = {}

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class GetUpdateDestroyMemberViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        organization_name = permissions_utils.get_param_from_request(
            request, "organization"
        )

        try:
            organization = Organization.objects.get(username=organization_name)
        except ObjectDoesNotExist:
            return False

        if request.method == "GET":
            return permissions_utils.can_read_members(user, organization)
        if request.method in ["PUT", "PATCH"]:
            return permissions_utils.can_update_members(user, organization)
        if request.method in ["DELETE"]:
            return permissions_utils.can_delete_members(user, organization)
        return False


class GetUpdateDestroyMemberView(generics.RetrieveUpdateDestroyAPIView):

    permission_classes = [
        permissions.IsAuthenticated,
        GetUpdateDestroyMemberViewPermissions,
    ]
    serializer_class = OrganizationMemberSerializer

    def get_object(self):
        organization = self.request.parser_context["kwargs"]["organization"]
        member = self.request.parser_context["kwargs"]["username"]

        organization_obj = Organization.objects.get(username=organization)
        member_obj = User.objects.get(username=member)
        return OrganizationMember.objects.get(
            organization=organization_obj, member=member_obj
        )
