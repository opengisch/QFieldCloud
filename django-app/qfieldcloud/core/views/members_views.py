from django.contrib.auth import get_user_model
from django.utils.decorators import method_decorator

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.permissions import IsAuthenticated

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core.models import (
    OrganizationMember, Organization)
from qfieldcloud.core.serializers import (
    OrganizationMemberSerializer)
from qfieldcloud.core.permissions import (
    OrganizationPermission)

User = get_user_model()


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List members of an organization",
        operation_id="List memebers",))
@method_decorator(
    name='post', decorator=swagger_auto_schema(
        operation_description="Add a user as member of an organization",
        operation_id="Create member",))
class ListCreateMembersView(generics.ListCreateAPIView):

    permission_classes = [IsAuthenticated, OrganizationPermission]
    serializer_class = OrganizationMemberSerializer

    def get_queryset(self):
        organization = self.request.parser_context['kwargs']['organization']
        organization_obj = User.objects.get(username=organization)

        return OrganizationMember.objects.filter(organization=organization_obj)

    def post(self, request, organization):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        organization_obj = Organization.objects.get(username=organization)
        member_obj = User.objects.get(username=request.data['member'])
        serializer.save(member=member_obj, organization=organization_obj)

        try:
            headers = {
                'Location': str(serializer.data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            headers = {}

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get the role of a member of an organization",
        operation_id="Get memeber",))
@method_decorator(
    name='put', decorator=swagger_auto_schema(
        operation_description="Update a memeber of an organization",
        operation_id="Update member",))
@method_decorator(
    name='patch', decorator=swagger_auto_schema(
        operation_description="Partial update a member of an organization",
        operation_id="Patch member",))
@method_decorator(
    name='delete', decorator=swagger_auto_schema(
        operation_description="Remove a member from an organization",
        operation_id="Delete member",))
class GetUpdateDestroyMemberView(generics.RetrieveUpdateDestroyAPIView):

    permission_classes = [IsAuthenticated, OrganizationPermission]
    serializer_class = OrganizationMemberSerializer

    def get_object(self):
        organization = self.request.parser_context['kwargs']['organization']
        member = self.request.parser_context['kwargs']['username']

        organization_obj = Organization.objects.get(username=organization)
        member_obj = User.objects.get(username=member)
        return OrganizationMember.objects.get(
            organization=organization_obj,
            member=member_obj)
