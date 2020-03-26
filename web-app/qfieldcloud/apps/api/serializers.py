from django.contrib.auth import get_user_model

from rest_framework import serializers
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import (
    Project, File, Organization, ProjectCollaborator,
    FileVersion)

User = get_user_model()


class ProjectSerializer(serializers.ModelSerializer):
    owner = serializers.StringRelatedField()

    class Meta:
        fields = ('id', 'name', 'owner', 'description', 'private',
                  'created_at')
        read_only_fields = ('owner',)
        model = Project


class FileSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('project', 'stored_file', 'created_at')
        model = File


class ListFileSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('name', 'size', 'sha256')
        model = File


class FileVersionSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField()

    class Meta:
        fields = ('created_at', 'sha256', 'size', 'uploaded_by')
        model = FileVersion


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


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    collaborator = serializers.StringRelatedField()

    class Meta:
        model = ProjectCollaborator
        fields = ('collaborator', 'role')


class PushFileSerializer(serializers.Serializer):
    file = serializers.FileField()


class TokenSerializer(serializers.ModelSerializer):
    username = serializers.StringRelatedField(source='user')
    token = serializers.CharField(source='key')

    class Meta:
        model = Token
        fields = ('token', 'username')
