from rest_framework import serializers

from .models import Project


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('id', 'name', 'description', 'homepage', 'private',
                  'created_at')
        model = Project


class FileSerializer(serializers.Serializer):
    file_content = serializers.FileField()
