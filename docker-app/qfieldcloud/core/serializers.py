from django.contrib.auth import get_user_model

from rest_framework import serializers
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError

from qfieldcloud.core.models import (
    Project, Organization, ProjectCollaborator,
    OrganizationMember)

User = get_user_model()


class UserSerializer():
    class Meta:
        model = User
        fields = ('username',)


class ProjectSerializer(serializers.ModelSerializer):
    owner = serializers.StringRelatedField()

    def to_internal_value(self, data):
        internal_data = super().to_internal_value(data)
        owner_username = data.get('owner')
        try:
            owner = User.objects.get(username=owner_username)
        except User.DoesNotExist:
            raise ValidationError(
                {'owner': ['Invalid owner username']},
                code='invalid',
            )
        internal_data['owner'] = owner
        return internal_data

    class Meta:
        fields = ('id', 'name', 'owner', 'description', 'private',
                  'created_at', 'updated_at')
        model = Project


class CompleteUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ('id', 'password')


class PublicInfoUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('username', 'user_type')


class OrganizationSerializer(serializers.ModelSerializer):
    organization_owner = serializers.StringRelatedField()
    members = serializers.StringRelatedField(many=True)

    class Meta:
        model = Organization
        exclude = ('id', 'password', 'first_name', 'last_name')


class RoleChoiceField(serializers.ChoiceField):
    def to_representation(self, obj):
        return self._choices[obj]

    def to_internal_value(self, data):
        for i in self._choices:
            if self._choices[i] == data:
                return i
        raise serializers.ValidationError(
            "Invalid role. Acceptable values are {0}.".format(
                list(self._choices.values())))


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    collaborator = serializers.StringRelatedField()
    role = RoleChoiceField(
        choices=ProjectCollaborator.ROLE_CHOICES)

    class Meta:
        model = ProjectCollaborator
        fields = ('collaborator', 'role')


class OrganizationMemberSerializer(serializers.ModelSerializer):
    member = serializers.StringRelatedField()
    role = RoleChoiceField(
        choices=OrganizationMember.ROLE_CHOICES)

    class Meta:
        model = OrganizationMember
        fields = ('member', 'role')


class TokenSerializer(serializers.ModelSerializer):
    username = serializers.StringRelatedField(source='user')
    token = serializers.CharField(source='key')

    class Meta:
        model = Token
        fields = ('token', 'username')
