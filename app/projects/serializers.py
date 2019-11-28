from django.conf import settings
from rest_framework import serializers

from .models import Project


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('id', 'name', 'description', 'homepage', 'private',
                  'created_at')
        model = Project


class FileSerializer(serializers.Serializer):
    file_content = serializers.FileField()


class CollaboratorSerializer(serializers.Serializer):
    role = serializers.CharField(max_length=20)

    def validate_role(self, value):
        if value not in settings.PERMISSION_ROLE:
            raise serializers.ValidationError("Role has a unknown value")
        return value
