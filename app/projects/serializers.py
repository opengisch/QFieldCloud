from rest_framework import serializers

from .models import Project, GenericFile


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('id', 'name', 'created_at', 'is_public')
        model = Project


class GenericFileSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('id', 'filename', 'created_at', 'project')
        model = GenericFile
